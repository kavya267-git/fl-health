"""
clients/client_template.py
FL-Health Hospital Client SDK
Complete reference implementation for hospital-side integration.

Usage:
    1. Configure SERVER_URL, HOSPITAL_EMAIL, HOSPITAL_PASSWORD below
    2. Run: python client_template.py
    3. Follow the printed prompts

Supports:
    - Login / session management
    - Upload datasets (CSV, NPY, ZIP, images)
    - View upload history
    - View current dataset on server
    - Trigger server-side federated training
    - View training history
    - Trigger aggregation
    - View FL network status
    - Validate credential
"""
import os
import sys
import json
import time
import requests
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
SERVER_URL         = "http://localhost:8000"   # change to your deployed URL
HOSPITAL_EMAIL     = "hospital@example.com"
HOSPITAL_PASSWORD  = "your_password"
DEFAULT_DATA_PATH  = "data/my_dataset.csv"    # default file to upload

# ─────────────────────────────────────────────────────────────────────────────


def login() -> tuple[str, str]:
    """Authenticate and return (access_token, user_id)."""
    r = requests.post(f"{SERVER_URL}/api/auth/login", json={
        "email": HOSPITAL_EMAIL,
        "password": HOSPITAL_PASSWORD,
    })
    r.raise_for_status()
    data = r.json()
    print(f"✅ Logged in as {data['user']['email']}")
    return data["access_token"], data["user"]["id"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_dataset(token: str, file_path: str) -> dict:
    """Upload a dataset file (CSV, NPY, ZIP, PNG, JPG, etc.) to the server."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    print(f"📤 Uploading: {file_path} ({os.path.getsize(file_path):,} bytes)")
    with open(file_path, "rb") as f:
        r = requests.post(
            f"{SERVER_URL}/api/hospital/upload-data",
            headers=auth_headers(token),
            files={"file": (os.path.basename(file_path), f)},
        )
    r.raise_for_status()
    result = r.json()
    print(f"✅ Upload complete: {result.get('message')}")
    print(f"   EHR: {result.get('ehr',0)} | ECG: {result.get('ecg',0)} | X-Ray: {result.get('xray',0)} | Total: {result.get('total',0)}")
    if result.get("upload_id"):
        print(f"   Upload ID: {result['upload_id']}")
    return result


def get_dataset_info(token: str) -> dict:
    """Fetch current on-disk dataset summary from the server."""
    r = requests.get(f"{SERVER_URL}/api/hospital/dataset-info", headers=auth_headers(token))
    r.raise_for_status()
    data = r.json()
    if not data.get("has_data"):
        print("⚠️  No dataset on server. Upload first.")
    else:
        print(f"📂 Dataset on server: {data['total_files']} files | "
              f"EHR:{data['ehr_files']} ECG:{data['ecg_files']} X-Ray:{data['xray_files']} | "
              f"{data['size_bytes']//1024} KB")
    return data


def get_upload_history(token: str) -> list:
    """Fetch the full upload history for this hospital."""
    r = requests.get(f"{SERVER_URL}/api/hospital/uploads", headers=auth_headers(token))
    r.raise_for_status()
    uploads = r.json().get("uploads", [])
    if not uploads:
        print("📋 No upload history yet.")
    else:
        print(f"📋 Upload History ({len(uploads)} records):")
        for u in uploads:
            date = u.get("created_at", "—")[:19].replace("T", " ") if u.get("created_at") else "—"
            print(f"   [{u.get('upload_status','?').upper()}] {u['file_name']} · {u['file_count']} files · {date}")
    return uploads


# ── Training ──────────────────────────────────────────────────────────────────

def get_my_info(token: str) -> dict:
    """Fetch current hospital profile including credential_hash."""
    r = requests.get(f"{SERVER_URL}/api/hospital/me", headers=auth_headers(token))
    r.raise_for_status()
    return r.json().get("hospital", {})


def train(token: str, credential_hash: str, epochs: int = 3, epsilon: float = 1.0) -> dict:
    """
    Trigger federated training on the server.

    Args:
        token:            JWT access token
        credential_hash:  From hospital profile (hospital.credential_hash)
        epochs:           Training epochs (keep 2-3 on free-tier servers)
        epsilon:          Differential privacy budget (default 1.0)
    """
    print(f"🚀 Starting training: epochs={epochs}, ε={epsilon}")
    print("   (This may take 30-120 seconds on free-tier servers…)")

    r = requests.post(
        f"{SERVER_URL}/api/hospital/train",
        headers=auth_headers(token),
        data={
            "credential_hash": credential_hash,
            "epochs": epochs,
            "epsilon": epsilon,
        },
        timeout=180,  # 3-minute timeout for training
    )

    if r.status_code == 403:
        print("❌ Credential invalid or not yet approved. Contact admin.")
        return {}
    if r.status_code == 400:
        print(f"❌ Training error: {r.json().get('detail')}")
        return {}

    r.raise_for_status()
    result = r.json()

    acc = result.get("accuracy", 0) * 100
    ps  = result.get("privacy_score", 0) * 100
    print(f"✅ Training complete!")
    print(f"   Round:         R{result.get('round')}")
    print(f"   Accuracy:      {acc:.1f}% {'🎯 (in target range!)' if 65 <= acc <= 75 else ''}")
    print(f"   Privacy Score: {ps:.0f}%")
    print(f"   Data Type:     {result.get('data_type')}")
    print(f"   Samples:       {result.get('data_size')}")
    print(f"   File Used:     {result.get('file_name')}")
    print(f"   Epsilon Used:  ε={result.get('epsilon_used')}")
    print(f"   Model Hash:    {result.get('model_hash')}")
    return result


def get_training_history(token: str) -> list:
    """Fetch full training history for this hospital."""
    r = requests.get(f"{SERVER_URL}/api/hospital/history", headers=auth_headers(token))
    r.raise_for_status()
    history = r.json().get("history", [])
    if not history:
        print("📈 No training sessions yet.")
    else:
        print(f"📈 Training History ({len(history)} sessions):")
        for s in history:
            acc  = f"{s['accuracy']*100:.1f}%" if s.get("accuracy") is not None else "—"
            ps   = f"{s['privacy_score']*100:.0f}%" if s.get("privacy_score") is not None else "—"
            date = s.get("created_at", "—")[:19].replace("T", " ") if s.get("created_at") else "—"
            print(f"   R{s['round_number']} | {s.get('file_name','—')} | {s.get('data_type','—')} | "
                  f"Acc:{acc} | Privacy:{ps} | ε={s.get('epsilon_used','—')} | {date}")
    return history


# ── Aggregation ───────────────────────────────────────────────────────────────

def trigger_aggregation(token: str) -> dict:
    """Trigger global model aggregation (Byzantine-tolerant FedAvg)."""
    print("🔄 Triggering aggregation…")
    r = requests.post(
        f"{SERVER_URL}/api/hospital/aggregate",
        headers=auth_headers(token),
        timeout=60,
    )
    r.raise_for_status()
    result = r.json()
    print(f"✅ Aggregation complete!")
    print(f"   New Round:          R{result.get('round')}")
    print(f"   Hospitals Included: {result.get('hospitals_aggregated')}")
    print(f"   Byzantine Excluded: {result.get('byzantine_excluded', 0)}")
    print(f"   Dropout Rate:       {result.get('dropout_rate', 0)*100:.0f}%")
    return result


# ── Network Status ─────────────────────────────────────────────────────────────

def get_fl_status() -> dict:
    """Fetch public FL network status (no auth required)."""
    r = requests.get(f"{SERVER_URL}/api/public/fl-status")
    r.raise_for_status()
    s = r.json()
    print(f"🌐 FL Network Status:")
    print(f"   Round:            R{s['current_round']} / {s['max_rounds']} ({s['round_progress_pct']}% done)")
    print(f"   Approved Hosps:   {s['approved_hospitals']}")
    print(f"   Active (24h):     {s['active_last_24h']}")
    print(f"   Avg Accuracy:     {s['avg_accuracy']}%  (target: {s['accuracy_target']})")
    print(f"   Privacy Budget:   ε={s['privacy_budget']}")
    print(f"   Dropout Tol:      {s['dropout_tolerance']}")
    return s


def validate_credential(token: str) -> dict:
    """Validate this hospital's credential without triggering training."""
    profile = get_my_info(token)
    cred_hash = profile.get("credential_hash")
    hospital_id = profile.get("id")
    if not cred_hash:
        print("⚠️  No credential issued yet. Awaiting admin approval.")
        return {"valid": False}

    r = requests.post(
        f"{SERVER_URL}/api/hospital/validate-credential",
        headers=auth_headers(token),
        data={"hospital_id": hospital_id, "credential_hash": cred_hash},
    )
    r.raise_for_status()
    result = r.json()
    if result.get("valid"):
        print(f"✅ Credential is VALID")
    else:
        print(f"❌ Credential INVALID: {result.get('reason')}")
        print(f"   Checks: {result.get('checks')}")
    return result


# ── Full Pipeline ──────────────────────────────────────────────────────────────

def run_full_pipeline(data_path: str = DEFAULT_DATA_PATH, epochs: int = 3, epsilon: float = 1.0):
    """
    Run the complete FL pipeline:
    1. Login
    2. Upload dataset
    3. Validate credential
    4. Train local model
    5. View training history
    6. (Optionally) trigger aggregation
    """
    print("=" * 60)
    print("  FL-Health Hospital Client SDK — Full Pipeline")
    print("=" * 60)
    print()

    # 1. Login
    token, user_id = login()
    print()

    # 2. FL Network Status
    try:
        get_fl_status()
    except Exception as e:
        print(f"⚠️  Could not fetch FL status: {e}")
    print()

    # 3. Upload Dataset
    try:
        upload_dataset(token, data_path)
    except FileNotFoundError as e:
        print(f"⚠️  {e} — skipping upload.")
    print()

    # 4. Validate Credential
    cred_result = validate_credential(token)
    if not cred_result.get("valid"):
        print("🛑 Cannot train — credential not valid. Contact your admin.")
        return
    print()

    # 5. Get credential hash and train
    profile = get_my_info(token)
    cred_hash = profile.get("credential_hash")
    result = train(token, cred_hash, epochs=epochs, epsilon=epsilon)
    print()

    # 6. Training history
    get_training_history(token)
    print()

    # 7. Ask about aggregation
    if result:
        choice = input("Trigger global aggregation now? (y/N): ").strip().lower()
        if choice == "y":
            trigger_aggregation(token)
            print()

    print("Pipeline complete. ✅")


# ── CLI Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FL-Health Hospital Client")
    parser.add_argument("--action", choices=[
        "status", "upload", "train", "history", "uploads",
        "dataset", "aggregate", "validate", "pipeline"
    ], default="pipeline", help="Action to perform")
    parser.add_argument("--file",    default=DEFAULT_DATA_PATH, help="Path to dataset file")
    parser.add_argument("--epochs",  type=int,   default=3,   help="Training epochs (default: 3)")
    parser.add_argument("--epsilon", type=float, default=1.0, help="Privacy budget ε (default: 1.0)")
    args = parser.parse_args()

    if args.action == "status":
        get_fl_status()

    elif args.action == "pipeline":
        run_full_pipeline(data_path=args.file, epochs=args.epochs, epsilon=args.epsilon)

    else:
        token, _ = login()
        if args.action == "upload":
            upload_dataset(token, args.file)
        elif args.action == "train":
            profile = get_my_info(token)
            cred_hash = profile.get("credential_hash")
            if not cred_hash:
                print("❌ No credential. Await admin approval first.")
            else:
                train(token, cred_hash, epochs=args.epochs, epsilon=args.epsilon)
        elif args.action == "history":
            get_training_history(token)
        elif args.action == "uploads":
            get_upload_history(token)
        elif args.action == "dataset":
            get_dataset_info(token)
        elif args.action == "aggregate":
            trigger_aggregation(token)
        elif args.action == "validate":
            validate_credential(token)