# backend/app/main.py
"""
FL-Health Server — FastAPI backend
Handles:
  - Public auth (register / login)
  - Admin routes (approve hospitals, issue credentials)
  - Hospital routes (upload data, train, view dashboard)
  - Dashboard analytics
"""

import os
import shutil
from datetime import datetime

from fastapi import FastAPI, Form, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import pandas as pd

from app.supabase_client import supabase, get_service_client
from app.auth import require_role
from app.credential_manager import issue_credential, validate_credential
from app.fl_engine import FLEngine

# ============================================================
# APP SETUP
# ============================================================
app = FastAPI(title="FL-Health Server", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fl_engine = FLEngine()

# Ensure base directories exist
os.makedirs("data/hospitals", exist_ok=True)
os.makedirs("data/global_model", exist_ok=True)


# ============================================================
# PYDANTIC MODELS
# ============================================================
class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    hospital_name: str
    email: str
    password: str
    license_number: str
    registration_id: str


# ============================================================
# ROOT
# ============================================================
@app.get("/")
async def root():
    """Serve the dashboard (or landing page)."""
    return FileResponse("frontend/dashboard.html")


# ============================================================
# PUBLIC ROUTES
# ============================================================

@app.get("/api/public/hospital-count")
async def public_hospital_count():
    """Used on the landing page."""
    service = get_service_client()
    res = service.table("hospitals").select("id").execute()
    return {"count": len(res.data)}


@app.post("/api/auth/register")
async def register_hospital(req: RegisterRequest):
    """
    Open registration — ANY hospital can register.
    Creates Supabase auth user + hospital row.
    Credential is NOT issued yet — admin must approve.
    """
    service = get_service_client()
    try:
        # Create auth user
        user = service.auth.admin.create_user({
            "email": req.email,
            "password": req.password,
            "email_confirm": True
        })

        # Create hospital record
        service.table("hospitals").insert({
            "id": user.user.id,
            "hospital_name": req.hospital_name,
            "hospital_id": f"HOSP-{user.user.id[:6].upper()}",
            "email": req.email,
            "license_number": req.license_number,
            "registration_id": req.registration_id,
            "is_credential_valid": False,
            "government_approved": False
        }).execute()

        return {
            "success": True,
            "user_id": user.user.id,
            "message": "Registered. Awaiting admin approval."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
            "access_token": resp.session.access_token
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ============================================================
# ADMIN ROUTES
# ============================================================

@app.get("/api/admin/all-hospitals")
async def all_hospitals(admin=Depends(require_role("admin"))):
    """Return every registered hospital (pending + approved)."""
    service = get_service_client()
    res = service.table("hospitals").select("*").order("created_at", desc=True).execute()
    return {"hospitals": res.data}


@app.get("/api/admin/pending-hospitals")
async def pending_hospitals(admin=Depends(require_role("admin"))):
    """Hospitals awaiting approval."""
    service = get_service_client()
    res = service.table("hospitals").select("*").eq("government_approved", False).execute()
    return {"pending": res.data}


@app.post("/api/admin/approve-hospital/{hospital_id}")
async def approve_hospital(hospital_id: str, admin=Depends(require_role("admin"))):
    """
    Admin approves instantly. Credential is issued in the same request.
    """
    result = issue_credential(hospital_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


# ============================================================
# HOSPITAL ROUTES
# ============================================================

@app.get("/api/hospital/me")
async def hospital_me(hospital=Depends(require_role("hospital"))):
    """Return the logged-in hospital's record."""
    return {"hospital": hospital}


@app.post("/api/hospital/upload-data")
async def upload_hospital_data(
    file: UploadFile = File(...),
    hospital=Depends(require_role("hospital"))
):
    """
    Hospital uploads their own CSV. Only CSV allowed.
    File is saved to: data/hospitals/{hospital_id}/data.csv
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files allowed")

    hospital_id = hospital["id"]
    folder = f"data/hospitals/{hospital_id}"
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, "data.csv")

    # Save file
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Count rows
    try:
        row_count = len(pd.read_csv(dest, header=None))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid CSV format")

    # Update hospital metrics
    service = get_service_client()
    service.table("hospitals").update({
        "total_patients": row_count,
        "last_active": datetime.utcnow().isoformat()
    }).eq("id", hospital_id).execute()

    return {
        "success": True,
        "message": f"Uploaded {row_count} patient records",
        "rows": row_count
    }


@app.post("/api/hospital/validate-credential")
async def hospital_validate_credential(
    hospital_id: str = Form(...),
    credential_hash: str = Form(...)
):
    """Hospital presents credential. Server validates."""
    return validate_credential(hospital_id, credential_hash)


@app.post("/api/hospital/train")
async def hospital_train(
    credential_hash: str = Form(...),
    epochs: int = Form(5),
    epsilon: float = Form(1.0),
    hospital=Depends(require_role("hospital"))
):
    """
    Hospital trains locally. Requires:
      - Valid credential
      - Uploaded data
    """
    hospital_id = hospital["id"]

    # 1. Validate credential
    val = validate_credential(hospital_id, credential_hash)
    if not val["valid"]:
        raise HTTPException(status_code=403, detail="Invalid or expired credential")

    # 2. Check uploaded data exists
    data_path = f"data/hospitals/{hospital_id}/data.csv"
    if not os.path.exists(data_path):
        raise HTTPException(status_code=400, detail="Upload your data first")

    # 3. Local training
    global_weights = fl_engine.get_global_model()
    result = fl_engine.train_local(data_path, global_weights, epochs=epochs)

    # 4. Apply Differential Privacy
    _ = fl_engine.add_differential_privacy(result["weights"], epsilon=epsilon)

    # 5. Compute privacy score
    privacy_score = fl_engine.calculate_privacy_score(
        result["data_size"], result["accuracy"], epsilon
    )

    # 6. Log training round + update hospital metrics
    service = get_service_client()
    service.table("training_history").insert({
        "hospital_id": hospital_id,
        "round_number": fl_engine.round + 1,
        "accuracy": result["accuracy"],
        "epsilon_used": epsilon,
        "data_size": result["data_size"]
    }).execute()

    service.table("hospitals").update({
        "local_accuracy": result["accuracy"],
        "privacy_score": privacy_score,
        "epsilon_used": epsilon,
        "total_patients": result["data_size"],
        "rounds_participated": hospital.get("rounds_participated", 0) + 1,
        "last_active": datetime.utcnow().isoformat()
    }).eq("id", hospital_id).execute()

    return {
        "success": True,
        "accuracy": result["accuracy"],
        "privacy_score": privacy_score,
        "data_size": result["data_size"],
        "epsilon_used": epsilon,
        "round": fl_engine.round + 1
    }


@app.get("/api/hospital/history")
async def hospital_history(hospital=Depends(require_role("hospital"))):
    """Return this hospital's training history."""
    service = get_service_client()
    res = service.table("training_history").select("*") \
        .eq("hospital_id", hospital["id"]) \
        .order("round_number").execute()
    return {"history": res.data}


# ============================================================
# DASHBOARD ROUTES (public read for dashboard)
# ============================================================

@app.get("/api/dashboard/convergence")
async def dashboard_convergence():
    """Accuracy per round across all hospitals."""
    service = get_service_client()
    res = service.table("training_history") \
        .select("round_number, accuracy") \
        .order("round_number").execute()
    return {"history": res.data}


@app.get("/api/dashboard/privacy-budget")
async def dashboard_privacy_budget():
    """Total ε used (capped at 1.0)."""
    service = get_service_client()
    res = service.table("hospitals").select("epsilon_used").execute()
    total_eps = sum([h.get("epsilon_used") or 0 for h in res.data])
    return {"epsilon_used": min(total_eps, 1.0), "epsilon_budget": 1.0}


@app.get("/api/dashboard/hospitals")
async def dashboard_hospitals():
    """Hospital status for dashboard."""
    service = get_service_client()
    res = service.table("hospitals").select(
        "hospital_name, local_accuracy, rounds_participated, last_active, government_approved"
    ).execute()
    return {"hospitals": res.data}


# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)