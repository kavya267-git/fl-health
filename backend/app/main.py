# backend/app/main.py
import os
import hashlib
import shutil
import zipfile
from datetime import datetime

# Absolute base path so data/ always resolves correctly regardless of CWD
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

from fastapi import FastAPI, Form, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from pydantic import BaseModel

from app.supabase_client import supabase, get_service_client
from app.auth import require_role
from app.credential_manager import issue_credential, validate_credential
from app.fl_engine import FLEngine
from app.audit import append_audit_entry, verify_chain, get_audit_trail
from app.geospatial import detect_hotspots, forecast_outbreak
from app.encoders import encode_file

app = FastAPI(title="FL-Health Server", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fl_engine = FLEngine()
os.makedirs(os.path.join(DATA_DIR, "hospitals"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "global_model"), exist_ok=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    hospital_name: str
    email: str
    password: str
    license_number: str
    registration_id: str
    city: str = "Unknown"
    state: str = "Unknown"
    latitude: float = 0.0
    longitude: float = 0.0


# ─── helpers ─────────────────────────────────────────────────────────────────

def _count_files_in_folder(folder: str):
    """Walk a folder and tally files by data type."""
    ehr_count = ecg_count = xray_count = other_count = 0
    total_bytes = 0
    for root, _, files in os.walk(folder):
        for fname in files:
            if fname.lower() == "upload.zip":
                continue
            fpath = os.path.join(root, fname)
            try:
                total_bytes += os.path.getsize(fpath)
            except OSError:
                pass
            fl = fname.lower()
            if fl.endswith(".csv"):
                ehr_count += 1
            elif fl.endswith((".npy", ".dat", ".wav", ".npz")):
                ecg_count += 1
            elif fl.endswith((".png", ".jpg", ".jpeg", ".bmp")):
                xray_count += 1
            else:
                other_count += 1
    total = ehr_count + ecg_count + xray_count + other_count
    return {
        "ehr": ehr_count,
        "ecg": ecg_count,
        "xray": xray_count,
        "other": other_count,
        "total": total,
        "size_bytes": total_bytes,
    }


def _get_current_round() -> int:
    """Read persisted round number from DB; fall back to in-memory value."""
    try:
        service = get_service_client()
        res = service.table("fl_round_state").select("round_number").eq("id", 1).execute()
        if res.data:
            return res.data[0]["round_number"]
    except Exception:
        pass
    return fl_engine.round


def _persist_round(round_number: int):
    """Upsert the round number to DB so it survives restarts."""
    try:
        service = get_service_client()
        service.table("fl_round_state").upsert({
            "id": 1,
            "round_number": round_number,
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass  # not fatal — in-memory value still works


# ─── public ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "FL-Health API",
        "version": "1.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "hospital_count": "/api/public/hospital-count",
            "auth_login": "/api/auth/login",
            "admin_hospitals": "/api/admin/all-hospitals",
            "dashboard": "/api/dashboard/hospitals",
            "audit_trail": "/api/audit/trail",
            "hotspots": "/api/geospatial/hotspots",
            "forecast": "/api/geospatial/forecast",
            "upload_history": "/api/hospital/uploads",
            "training_history": "/api/hospital/history",
            "model_versions": "/api/admin/model-versions",
        }
    }


@app.get("/api/public/hospital-count")
async def public_hospital_count():
    service = get_service_client()
    res = service.table("hospitals").select("id").execute()
    return {"count": len(res.data)}


# ─── auth ─────────────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
async def register_hospital(req: RegisterRequest):
    service = get_service_client()
    user_id = None
    try:
        user = service.auth.admin.create_user({
            "email": req.email,
            "password": req.password,
            "email_confirm": True,
        })
        user_id = user.user.id

        service.table("hospitals").insert({
            "id": user_id,
            "hospital_name": req.hospital_name,
            "hospital_id": f"HOSP-{user_id[:6].upper()}",
            "email": req.email,
            "license_number": req.license_number,
            "registration_id": req.registration_id,
            "city": req.city,
            "state": req.state,
            "latitude": req.latitude,
            "longitude": req.longitude,
            "patient_cases": 0,
            "is_credential_valid": False,
            "government_approved": False,
        }).execute()

        return {
            "success": True,
            "user_id": user_id,
            "message": "Registered. Awaiting admin approval.",
        }
    except Exception as e:
        if user_id:
            try:
                service.auth.admin.delete_user(user_id)
            except Exception:
                pass
        error_msg = str(e)
        print(f"[REGISTER ERROR] {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    try:
        resp = supabase.auth.sign_in_with_password({
            "email": req.email,
            "password": req.password
        })
        return {
            "success": True,
            "user": {"id": resp.user.id, "email": resp.user.email},
            "access_token": resp.session.access_token,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ─── admin ───────────────────────────────────────────────────────────────────

@app.get("/api/admin/all-hospitals")
async def all_hospitals(admin=Depends(require_role("admin"))):
    service = get_service_client()
    res = service.table("hospitals").select("*").order("created_at", desc=True).execute()
    return {"hospitals": res.data}


@app.post("/api/admin/revoke-hospital/{hospital_id}")
async def revoke_hospital(hospital_id: str, admin=Depends(require_role("admin"))):
    """Revoke a hospital's credential — blocks them from training until re-approved."""
    service = get_service_client()
    hosp = service.table("hospitals").select("hospital_name").eq("id", hospital_id).execute()
    if not hosp.data:
        raise HTTPException(status_code=404, detail="Hospital not found")
    hname = hosp.data[0]["hospital_name"]

    service.table("hospitals").update({
        "is_credential_valid": False,
        "government_approved": False,
        "credential_hash": None,
    }).eq("id", hospital_id).execute()

    current_round = _get_current_round()
    append_audit_entry(
        round_number=current_round,
        hospital_id=hospital_id,
        hospital_name=hname,
        event_type="CREDENTIAL_REVOKE",
        epsilon_used=0.0,
        model_hash="",
        metadata={"revoked_by": "admin"},
    )
    return {"success": True, "message": f"Credential revoked for {hname}"}


@app.get("/api/admin/pending-hospitals")
async def pending_hospitals(admin=Depends(require_role("admin"))):
    service = get_service_client()
    res = service.table("hospitals").select("*").eq("government_approved", False).execute()
    return {"pending": res.data}


@app.post("/api/admin/approve-hospital/{hospital_id}")
async def approve_hospital(hospital_id: str, admin=Depends(require_role("admin"))):
    result = issue_credential(hospital_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("reason"))

    service = get_service_client()
    hosp = service.table("hospitals").select("hospital_name").eq("id", hospital_id).execute()
    hname = hosp.data[0]["hospital_name"] if hosp.data else "Unknown"

    current_round = _get_current_round()
    append_audit_entry(
        round_number=current_round,
        hospital_id=hospital_id,
        hospital_name=hname,
        event_type="CREDENTIAL_ISSUE",
        epsilon_used=0.0,
        model_hash=result.get("credential_hash", ""),
        metadata={"expires_at": result.get("expires_at")},
    )
    return result


@app.get("/api/admin/model-versions")
async def model_versions(admin=Depends(require_role("admin"))):
    """Return all persisted global model version records."""
    service = get_service_client()
    try:
        res = service.table("model_versions").select("*").order("created_at", desc=True).limit(50).execute()
        return {"versions": res.data}
    except Exception as e:
        return {"versions": [], "error": str(e)}


@app.get("/api/admin/model/download")
async def download_model(admin=Depends(require_role("admin"))):
    """Download the latest aggregated global model (.pth).
    
    Falls back to Supabase Storage if the local file is missing (e.g., after a
    Railway redeploy). The file is served as an application/octet-stream download.
    """
    model_path = os.path.join(DATA_DIR, "global_model", "classifier.pth")

    # If local file is missing, try pulling from Supabase Storage first
    if not os.path.exists(model_path):
        try:
            service = get_service_client()
            data = service.storage.from_("fl-health-data").download("global_model/classifier.pth")
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            with open(model_path, "wb") as f:
                f.write(data)
            print("[DOWNLOAD] Restored model from Supabase Storage.")
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"No trained model available yet. Run at least one aggregation first. ({e})"
            )

    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail="No trained model available yet. Run at least one aggregation first.")

    return FileResponse(
        path=model_path,
        filename="fl_global_model.pth",
        media_type="application/octet-stream",
    )


@app.get("/api/hospital/model/download")
async def download_model_hospital(hospital=Depends(require_role("hospital"))):
    """Hospitals can also download the current global model weights."""
    model_path = os.path.join(DATA_DIR, "global_model", "classifier.pth")

    if not os.path.exists(model_path):
        try:
            service = get_service_client()
            data = service.storage.from_("fl-health-data").download("global_model/classifier.pth")
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            with open(model_path, "wb") as f:
                f.write(data)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"No trained model available yet. ({e})")

    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail="No trained model available yet.")

    return FileResponse(
        path=model_path,
        filename="fl_global_model.pth",
        media_type="application/octet-stream",
    )


@app.get("/api/admin/stats")
async def admin_stats(admin=Depends(require_role("admin"))):
    """Overall platform statistics for admin dashboard."""
    service = get_service_client()
    hospitals = service.table("hospitals").select("*").execute().data or []
    training = service.table("training_history").select("*").execute().data or []
    uploads = []
    try:
        uploads = service.table("uploads").select("*").execute().data or []
    except Exception:
        pass

    approved = [h for h in hospitals if h.get("government_approved")]
    active_24h = [
        h for h in hospitals
        if h.get("last_active") and
        (datetime.utcnow() - datetime.fromisoformat(h["last_active"].replace("Z", ""))).total_seconds() < 86400
    ]
    current_round = _get_current_round()

    return {
        "total_hospitals": len(hospitals),
        "approved_hospitals": len(approved),
        "active_24h": len(active_24h),
        "total_training_sessions": len(training),
        "total_uploads": len(uploads),
        "current_round": current_round,
    }


# ─── hospital ─────────────────────────────────────────────────────────────────

@app.get("/api/hospital/me")
async def hospital_me(hospital=Depends(require_role("hospital"))):
    return {"hospital": hospital}


def background_upload_to_storage(ext, zip_path, dest, hospital_id, file_filename):
    try:
        from app.supabase_client import get_service_client
        service = get_service_client()
        if ext == ".zip":
            with open(zip_path, "rb") as f:
                service.storage.from_("fl-health-data").upload(
                    f"hospitals/{hospital_id}/upload.zip", f.read(), file_options={"upsert": "true"}
                )
        else:
            with open(dest, "rb") as f:
                service.storage.from_("fl-health-data").upload(
                    f"hospitals/{hospital_id}/{file_filename}", f.read(), file_options={"upsert": "true"}
                )
    except Exception as e:
        print(f"[UPLOAD] Storage upload failed: {e}")

@app.post("/api/hospital/upload-data")
async def upload_hospital_data(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    hospital=Depends(require_role("hospital")),
):
    allowed_exts = (".csv", ".npy", ".npz", ".png", ".jpg", ".jpeg",
                    ".bmp", ".wav", ".txt", ".json", ".dat", ".zip")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported format. Allowed: {', '.join(allowed_exts)}")

    hospital_id = hospital["id"]
    folder = os.path.join(DATA_DIR, "hospitals", hospital_id)
    os.makedirs(folder, exist_ok=True)

    original_filename = file.filename
    file_size = 0

    # ── Save the file(s) ──────────────────────────────────────────────────────
    if ext == ".zip":
        zip_path = os.path.join(folder, "upload.zip")
        file_size = 0
        with open(zip_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                file_size += len(chunk)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(folder)
    else:
        file_size = 0
        dest = os.path.join(folder, file.filename)
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                file_size += len(chunk)

    # ── Count all extracted / saved files ─────────────────────────────────────
    counts = _count_files_in_folder(folder)
    ehr_count  = counts["ehr"]
    ecg_count  = counts["ecg"]
    xray_count = counts["xray"]
    total      = counts["total"]
    size_bytes = counts["size_bytes"]

    # ── Upload to Supabase Storage ─────────────────────────────────────────────
    background_tasks.add_task(
        background_upload_to_storage, 
        ext, 
        zip_path if ext == ".zip" else None, 
        dest if ext != ".zip" else None, 
        hospital_id, 
        file.filename
    )

    # Derive a human-readable data type label
    if ehr_count >= ecg_count and ehr_count >= xray_count:
        dominant_type = "ehr"
    elif ecg_count >= xray_count:
        dominant_type = "ecg"
    else:
        dominant_type = "image"

    now_iso = datetime.utcnow().isoformat()

    # ── Write upload record to Supabase ───────────────────────────────────────
    # storage_path permanently records where the file lives in Supabase Storage
    # so we can find it again after a Railway redeploy (local disk is wiped).
    storage_path = (
        f"hospitals/{hospital_id}/upload.zip"
        if ext == ".zip"
        else f"hospitals/{hospital_id}/{original_filename}"
    )

    service = get_service_client()
    upload_id = None
    try:
        upload_res = service.table("uploads").insert({
            "hospital_id": hospital_id,
            "file_name": original_filename,
            "file_type": "zip" if ext == ".zip" else dominant_type,
            "file_size": file_size,
            "file_count": total,
            "ehr_count": ehr_count,
            "ecg_count": ecg_count,
            "xray_count": xray_count,
            "other_count": counts["other"],
            "storage_path": storage_path,
            "upload_status": "completed",
            "created_at": now_iso,
        }).execute()
        if upload_res.data:
            upload_id = upload_res.data[0].get("id")
    except Exception as ex:
        print(f"[UPLOAD] Could not write to uploads table: {ex}")

    # ── Update hospitals row ───────────────────────────────────────────────────
    try:
        service.table("hospitals").update({
            "total_patients": total,
            "patient_cases": total,
            "feature_count": ehr_count,
            "data_type": f"ehr={ehr_count},ecg={ecg_count},xray={xray_count}",
            "data_file_path": folder,
            "ecg_count": ecg_count,
            "xray_count": xray_count,
            "last_active": now_iso,
            "last_upload_id": upload_id,
            "last_upload_at": now_iso,
        }).eq("id", hospital_id).execute()
    except Exception as ex:
        print(f"[UPLOAD] Could not update hospitals table: {ex}")

    # ── Audit entry ───────────────────────────────────────────────────────────
    current_round = _get_current_round()
    append_audit_entry(
        round_number=current_round,
        hospital_id=hospital_id,
        hospital_name=hospital.get("hospital_name", "Unknown"),
        event_type="UPLOAD",
        epsilon_used=0.0,
        model_hash="",
        metadata={
            "file_name": original_filename,
            "ehr": ehr_count,
            "ecg": ecg_count,
            "xray": xray_count,
            "total": total,
            "size_bytes": size_bytes,
            "upload_id": upload_id,
        },
    )

    return {
        "success": True,
        "upload_id": upload_id,
        "message": f"Uploaded {total} files (EHR:{ehr_count}, ECG:{ecg_count}, X-ray:{xray_count})",
        "total": total,
        "ehr": ehr_count,
        "ecg": ecg_count,
        "xray": xray_count,
        "file_name": original_filename,
        "file_size_bytes": file_size,
    }


@app.delete("/api/hospital/clear-data")
async def clear_hospital_data(hospital=Depends(require_role("hospital"))):
    hospital_id = hospital["id"]
    folder = os.path.join(DATA_DIR, "hospitals", hospital_id)
    if os.path.exists(folder):
        shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)

    # Remove files from Supabase Storage
    service = get_service_client()
    try:
        storage_files = service.storage.from_("fl-health-data").list(f"hospitals/{hospital_id}")
        if storage_files:
            paths = [f"hospitals/{hospital_id}/{f['name']}" for f in storage_files if f['name'] != '.emptyFolderPlaceholder']
            if paths:
                service.storage.from_("fl-health-data").remove(paths)
    except Exception as e:
        print(f"[CLEAR] Storage error: {e}")

    # Mark last upload as cleared in uploads table
    try:
        service.table("uploads").update({"upload_status": "cleared"}).eq(
            "hospital_id", hospital_id
        ).eq("upload_status", "completed").execute()
    except Exception:
        pass

    return {"message": "Data cleared successfully"}


@app.post("/api/hospital/validate-credential")
async def hospital_validate_credential(
    hospital_id: str = Form(...),
    credential_hash: str = Form(...),
):
    return validate_credential(hospital_id, credential_hash)


@app.post("/api/hospital/train")
async def hospital_train(
    credential_hash: str = Form(...),
    epochs: int = Form(5),
    epsilon: float = Form(1.0),
    hospital=Depends(require_role("hospital")),
):
    hospital_id = hospital["id"]

    val = validate_credential(hospital_id, credential_hash)
    if not val["valid"]:
        reason = val.get("reason", "Invalid credential")
        raise HTTPException(status_code=403, detail=reason)

    folder = os.path.join(DATA_DIR, "hospitals", hospital_id)
    os.makedirs(folder, exist_ok=True)

    service = get_service_client()
    
    # Download dataset from Supabase Storage if local folder is empty (due to restart)
    if not any(f != "upload.zip" for f in os.listdir(folder)):
        try:
            storage_files = service.storage.from_("fl-health-data").list(f"hospitals/{hospital_id}")
            for sf in storage_files:
                if sf['name'] == '.emptyFolderPlaceholder': continue
                res = service.storage.from_("fl-health-data").download(f"hospitals/{hospital_id}/{sf['name']}")
                local_path = os.path.join(folder, sf['name'])
                with open(local_path, "wb") as out:
                    out.write(res)
                if sf['name'] == "upload.zip":
                    with zipfile.ZipFile(local_path, "r") as z:
                        z.extractall(folder)
        except Exception as e:
            print(f"[TRAIN] Storage download error: {e}")

    if not os.listdir(folder):
        raise HTTPException(status_code=400, detail="Upload your data first")

    # ── Find the best available data file ─────────────────────────────────────
    data_file = None
    priority = (".csv", ".npy", ".dat", ".jpg", ".png")
    for ext in priority:
        for root, _, files in os.walk(folder):
            for fname in files:
                if fname.lower().endswith(ext) and fname.lower() != "upload.zip":
                    data_file = os.path.join(root, fname)
                    break
            if data_file:
                break
        if data_file:
            break

    if not data_file:
        raise HTTPException(status_code=400, detail="No valid data files found. Please upload data first.")

    data_filename = os.path.basename(data_file)

    # ── Run local training ─────────────────────────────────────────────────────
    try:
        result = fl_engine.train_local(data_file, epochs=epochs)
        noisy_weights = fl_engine.add_differential_privacy(result["weights"], epsilon=epsilon)
        fl_engine.store_update(hospital_id, noisy_weights, result["data_size"])

        privacy_score = fl_engine.calculate_privacy_score(
            result["data_size"], result["accuracy"], epsilon
        )
        model_hash = hashlib.sha256(str(noisy_weights).encode()).hexdigest()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Training error: {str(e)}")

    current_round = _get_current_round()
    next_round = current_round + 1
    now_iso = datetime.utcnow().isoformat()

    # ── Fetch the latest upload_id for this hospital ──────────────────────────
    upload_id = hospital.get("last_upload_id")

    service = get_service_client()

    # ── Write to training_history ──────────────────────────────────────────────
    try:
        service.table("training_history").insert({
            "hospital_id": hospital_id,
            "round_number": next_round,
            "accuracy": result["accuracy"],
            "epsilon_used": epsilon,
            "data_size": result["data_size"],
            "data_type": result["data_type"],
            "file_name": data_filename,
            "feature_count": result["feature_count"],
            "privacy_score": privacy_score,
            "model_hash": model_hash,
            "upload_id": upload_id,
            "created_at": now_iso,
        }).execute()
    except Exception as ex:
        # Graceful fallback: insert with only the columns that definitely exist
        print(f"[TRAIN] Full insert failed ({ex}), trying minimal insert")
        try:
            service.table("training_history").insert({
                "hospital_id": hospital_id,
                "round_number": next_round,
                "accuracy": result["accuracy"],
                "epsilon_used": epsilon,
                "data_size": result["data_size"],
            }).execute()
        except Exception as ex2:
            print(f"[TRAIN] Minimal insert also failed: {ex2}")

    # ── Update hospitals row ───────────────────────────────────────────────────
    try:
        service.table("hospitals").update({
            "local_accuracy": result["accuracy"],
            "privacy_score": privacy_score,
            "epsilon_used": epsilon,
            "total_patients": result["data_size"],
            "patient_cases": result["data_size"],
            "rounds_participated": (hospital.get("rounds_participated") or 0) + 1,
            "last_active": now_iso,
            "last_trained_at": now_iso,
            "last_trained_file": data_filename,
        }).eq("id", hospital_id).execute()
    except Exception as ex:
        print(f"[TRAIN] Could not update hospitals table: {ex}")

    # ── Audit ──────────────────────────────────────────────────────────────────
    append_audit_entry(
        round_number=next_round,
        hospital_id=hospital_id,
        hospital_name=hospital.get("hospital_name", "Unknown"),
        event_type="TRAIN",
        epsilon_used=epsilon,
        model_hash=model_hash,
        metadata={
            "accuracy": result["accuracy"],
            "data_type": result["data_type"],
            "features": result["feature_count"],
            "data_size": result["data_size"],
            "file_name": data_filename,
            "privacy_score": privacy_score,
            "upload_id": upload_id,
        },
    )

    return {
        "success": True,
        "accuracy": result["accuracy"],
        "privacy_score": privacy_score,
        "data_size": result["data_size"],
        "data_type": result["data_type"],
        "feature_count": result["feature_count"],
        "epsilon_used": epsilon,
        "round": next_round,
        "file_name": data_filename,
        "model_hash": model_hash[:16] + "...",
    }


@app.post("/api/hospital/aggregate")
async def trigger_aggregation(hospital=Depends(require_role("hospital"))):
    result = fl_engine.aggregate()

    # ── Persist the new round number ──────────────────────────────────────────
    _persist_round(fl_engine.round)

    # ── Save a model version record ───────────────────────────────────────────
    model_path = os.path.join(DATA_DIR, "global_model", "classifier.pth")
    model_hash = ""
    if os.path.exists(model_path):
        with open(model_path, "rb") as f:
            model_hash = hashlib.sha256(f.read()).hexdigest()

    try:
        service = get_service_client()
        service.table("model_versions").insert({
            "round_number": fl_engine.round,
            "hospitals_contributed": result.get("hospitals", 0),
            "byzantine_excluded": result.get("byzantine_excluded", 0),
            "dropout_rate": result.get("dropout_rate", 0.0),
            "model_hash": model_hash,
            "storage_path": "global_model/classifier.pth",  # path in Supabase Storage
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as ex:
        print(f"[AGGREGATE] Could not write model_versions: {ex}")

    # ── Audit ──────────────────────────────────────────────────────────────────
    append_audit_entry(
        round_number=fl_engine.round,
        hospital_id="SERVER",
        hospital_name="FL-Health Server",
        event_type="AGGREGATE",
        epsilon_used=0.0,
        model_hash=model_hash,
        metadata={
            "hospitals": result.get("hospitals", 0),
            "byzantine_excluded": result.get("byzantine_excluded", 0),
            "dropout_rate": result.get("dropout_rate", 0.0),
            "total_submitted": result.get("total_submitted", 0),
        },
    )

    return {
        "success": True,
        "round": fl_engine.round,
        "hospitals_aggregated": result.get("hospitals", 0),
        "byzantine_excluded": result.get("byzantine_excluded", 0),
        "dropout_rate": result.get("dropout_rate", 0.0),
        "total_submitted": result.get("total_submitted", 0),
        "model_hash": model_hash[:16] + "..." if model_hash else "",
    }


@app.get("/api/hospital/history")
async def hospital_history(hospital=Depends(require_role("hospital"))):
    """Training history for the logged-in hospital, newest first."""
    service = get_service_client()
    res = service.table("training_history").select("*").eq(
        "hospital_id", hospital["id"]
    ).order("round_number", desc=True).execute()
    return {"history": res.data}


@app.get("/api/hospital/uploads")
async def hospital_uploads(hospital=Depends(require_role("hospital"))):
    """Upload history for the logged-in hospital, newest first."""
    service = get_service_client()
    try:
        res = service.table("uploads").select("*").eq(
            "hospital_id", hospital["id"]
        ).order("created_at", desc=True).execute()
        return {"uploads": res.data}
    except Exception as e:
        # uploads table may not exist yet — return friendly message
        return {"uploads": [], "warning": f"Uploads table not yet created: {e}"}


@app.get("/api/hospital/dataset-info")
async def hospital_dataset_info(hospital=Depends(require_role("hospital"))):
    """Return dataset summary from Supabase Storage for the logged-in hospital."""
    hospital_id = hospital["id"]
    service = get_service_client()
    
    try:
        storage_files = service.storage.from_("fl-health-data").list(f"hospitals/{hospital_id}")
    except Exception as e:
        return {"has_data": False, "message": f"Storage error: {e}"}

    if not storage_files or len(storage_files) == 0:
        return {"has_data": False, "message": "No data uploaded yet"}

    ehr_count = ecg_count = xray_count = other_count = total_bytes = 0
    files_list = []
    
    for f in storage_files:
        if f['name'] == '.emptyFolderPlaceholder': continue
        fname = f['name']
        size = f.get('metadata', {}).get('size', 0)
        total_bytes += size
        fl = fname.lower()
        if fl.endswith(".csv"): ehr_count += 1
        elif fl.endswith((".npy", ".dat", ".wav", ".npz")): ecg_count += 1
        elif fl.endswith((".png", ".jpg", ".jpeg", ".bmp")): xray_count += 1
        else: other_count += 1
        
        files_list.append({
            "name": fname,
            "size_bytes": size,
            "relative_path": fname,
        })
        
    total = ehr_count + ecg_count + xray_count + other_count
    
    return {
        "has_data": total > 0,
        "total_files": total,
        "ehr_files": ehr_count,
        "ecg_files": ecg_count,
        "xray_files": xray_count,
        "other_files": other_count,
        "size_bytes": total_bytes,
        "files": files_list[:100],  # cap at 100 entries
    }


# ─── dashboard (public reads) ─────────────────────────────────────────────────

@app.get("/api/dashboard/convergence")
async def dashboard_convergence():
    service = get_service_client()
    res = service.table("training_history").select("round_number, accuracy").order("round_number").execute()
    return {"history": res.data}


@app.get("/api/dashboard/privacy-budget")
async def dashboard_privacy_budget():
    service = get_service_client()
    res = service.table("hospitals").select("epsilon_used").execute()
    total_eps = sum([h.get("epsilon_used") or 0 for h in res.data])
    return {"epsilon_used": min(total_eps, 1.0), "epsilon_budget": 1.0}


@app.get("/api/dashboard/hospitals")
async def dashboard_hospitals():
    service = get_service_client()
    res = service.table("hospitals").select(
        "hospital_name, local_accuracy, rounds_participated, last_active, government_approved, data_type, city, state"
    ).execute()
    return {"hospitals": res.data}


@app.get("/api/dashboard/summary")
async def dashboard_summary():
    """Aggregated summary card data for the dashboard."""
    service = get_service_client()
    hospitals = service.table("hospitals").select("*").execute().data or []
    training = service.table("training_history").select("accuracy, round_number").order("round_number").execute().data or []

    approved = [h for h in hospitals if h.get("government_approved")]
    best_acc = max((t["accuracy"] for t in training if t.get("accuracy")), default=0)
    current_round = _get_current_round()

    return {
        "total_hospitals": len(hospitals),
        "approved_hospitals": len(approved),
        "current_round": current_round,
        "best_accuracy": best_acc,
        "training_sessions": len(training),
    }


# ─── audit ───────────────────────────────────────────────────────────────────

@app.get("/api/audit/trail")
async def audit_trail():
    return {"trail": get_audit_trail(limit=100)}


@app.get("/api/audit/verify")
async def audit_verify():
    return verify_chain()


# ─── geospatial ───────────────────────────────────────────────────────────────

@app.get("/api/geospatial/hotspots")
async def geospatial_hotspots():
    return detect_hotspots()


@app.get("/api/geospatial/forecast")
async def geospatial_forecast():
    return forecast_outbreak()


@app.get("/api/geospatial/early-alerts")
async def geospatial_early_alerts():
    """7-21 day early detection alerts — active hospitals with rising cases."""
    result = detect_hotspots()
    forecast = forecast_outbreak()
    return {
        "early_alerts": result.get("early_alerts", []),
        "detection_window": result.get("detection_window", "7-21 days"),
        "early_detection": forecast.get("early_detection", {}),
        "alert_level": forecast.get("alert", "GREEN"),
    }


@app.get("/api/public/fl-status")
async def fl_status():
    """Public FL network status — used by network.html live data panels."""
    service = get_service_client()
    hospitals = service.table("hospitals").select(
        "government_approved, last_active, rounds_participated, local_accuracy"
    ).execute().data or []

    approved = [h for h in hospitals if h.get("government_approved")]
    now = datetime.utcnow()
    active_1h = [
        h for h in approved
        if h.get("last_active") and
        (now - datetime.fromisoformat(h["last_active"].replace("Z", ""))).total_seconds() < 3600
    ]
    active_24h = [
        h for h in approved
        if h.get("last_active") and
        (now - datetime.fromisoformat(h["last_active"].replace("Z", ""))).total_seconds() < 86400
    ]
    avg_acc = 0.0
    accs = [h["local_accuracy"] for h in approved if h.get("local_accuracy")]
    if accs:
        avg_acc = sum(accs) / len(accs)

    current_round = _get_current_round()
    return {
        "current_round":      current_round,
        "max_rounds":         fl_engine.MAX_ROUNDS,
        "round_progress_pct": round(min(current_round / fl_engine.MAX_ROUNDS, 1.0) * 100, 1),
        "total_hospitals":    len(hospitals),
        "approved_hospitals": len(approved),
        "active_last_hour":   len(active_1h),
        "active_last_24h":    len(active_24h),
        "avg_accuracy":       round(avg_acc * 100, 1),
        "accuracy_target":    f"{fl_engine.ACC_TARGET_LOW*100:.0f}-{fl_engine.ACC_TARGET_HIGH*100:.0f}%",
        "privacy_budget":     fl_engine.PRIVACY_BUDGET,
        "dropout_tolerance":  f"{fl_engine.DROPOUT_TOLERANCE*100:.0f}%+",
        "min_hospitals":      fl_engine.MIN_HOSPITALS,
    }


# ─── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)