# backend/app/main.py
import os
import hashlib
import shutil
import zipfile
from datetime import datetime

# Absolute base path so data/ always resolves correctly regardless of CWD
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

from fastapi import FastAPI, Form, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

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
            "forecast": "/api/geospatial/forecast"
        }
    }


@app.get("/api/public/hospital-count")
async def public_hospital_count():
    service = get_service_client()
    res = service.table("hospitals").select("id").execute()
    return {"count": len(res.data)}


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


@app.get("/api/admin/all-hospitals")
async def all_hospitals(admin=Depends(require_role("admin"))):
    service = get_service_client()
    res = service.table("hospitals").select("*").order("created_at", desc=True).execute()
    return {"hospitals": res.data}


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

    append_audit_entry(
        round_number=fl_engine.round,
        hospital_id=hospital_id,
        hospital_name=hname,
        event_type="CREDENTIAL_ISSUE",
        epsilon_used=0.0,
        model_hash=result.get("credential_hash", ""),
        metadata={"expires_at": result.get("expires_at")},
    )
    return result


@app.get("/api/hospital/me")
async def hospital_me(hospital=Depends(require_role("hospital"))):
    return {"hospital": hospital}


@app.post("/api/hospital/upload-data")
async def upload_hospital_data(
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

    if ext == ".zip":
        zip_path = os.path.join(folder, "upload.zip")
        with open(zip_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(folder)
    else:
        dest = os.path.join(folder, file.filename)
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

    ehr_count = ecg_count = xray_count = other_count = 0
    for root, _, files in os.walk(folder):
        for fname in files:
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

    service = get_service_client()
    service.table("hospitals").update({
        "total_patients": total,
        "patient_cases": total,
        "feature_count": ehr_count,
        "data_type": f"ehr={ehr_count},ecg={ecg_count},xray={xray_count}",
        "data_file_path": folder,
        "ecg_count": ecg_count,
        "xray_count": xray_count,
        "last_active": datetime.utcnow().isoformat(),
    }).eq("id", hospital_id).execute()

    append_audit_entry(
        round_number=fl_engine.round,
        hospital_id=hospital_id,
        hospital_name=hospital.get("hospital_name", "Unknown"),
        event_type="UPLOAD",
        epsilon_used=0.0,
        model_hash="",
        metadata={"ehr": ehr_count, "ecg": ecg_count, "xray": xray_count, "total": total},
    )

    return {
        "success": True,
        "message": f"Uploaded {total} files (EHR:{ehr_count}, ECG:{ecg_count}, X-ray:{xray_count})",
        "total": total,
        "ehr": ehr_count,
        "ecg": ecg_count,
        "xray": xray_count,
    }


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
    if not os.path.exists(folder):
        raise HTTPException(status_code=400, detail="Upload your data first")

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
        raise HTTPException(status_code=400, detail="No valid data files found")

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

    service = get_service_client()
    service.table("training_history").insert({
        "hospital_id": hospital_id,
        "round_number": fl_engine.round + 1,
        "accuracy": result["accuracy"],
        "epsilon_used": epsilon,
        "data_size": result["data_size"],
    }).execute()

    service.table("hospitals").update({
        "local_accuracy": result["accuracy"],
        "privacy_score": privacy_score,
        "epsilon_used": epsilon,
        "total_patients": result["data_size"],
        "patient_cases": result["data_size"],
        "rounds_participated": (hospital.get("rounds_participated") or 0) + 1,
        "last_active": datetime.utcnow().isoformat(),
    }).eq("id", hospital_id).execute()

    append_audit_entry(
        round_number=fl_engine.round + 1,
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
        "round": fl_engine.round + 1,
    }


@app.post("/api/hospital/aggregate")
async def trigger_aggregation(hospital=Depends(require_role("hospital"))):
    result = fl_engine.aggregate()
    return {"success": True, "round": fl_engine.round, "hospitals": result}


@app.get("/api/hospital/history")
async def hospital_history(hospital=Depends(require_role("hospital"))):
    service = get_service_client()
    res = service.table("training_history").select("*").eq("hospital_id", hospital["id"]).order("round_number").execute()
    return {"history": res.data}


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


@app.get("/api/audit/trail")
async def audit_trail():
    return {"trail": get_audit_trail(limit=100)}


@app.get("/api/audit/verify")
async def audit_verify():
    return verify_chain()


@app.get("/api/geospatial/hotspots")
async def geospatial_hotspots():
    return detect_hotspots()


@app.get("/api/geospatial/forecast")
async def geospatial_forecast():
    return forecast_outbreak()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)