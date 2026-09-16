# backend/app/credential_manager.py
"""
FL-Health — Verifiable Credential Manager

Simulates a government authority issuing cryptographic credentials
to hospitals. In production this would use DID + VC standards.
"""

import hashlib
import json
from datetime import datetime, timedelta

from app.supabase_client import supabase, get_service_client


def generate_credential(hospital_id: str, hospital_name: str, license_number: str):
    """Generate a Verifiable Credential JSON object."""
    issued_at = datetime.utcnow()
    expires_at = issued_at + timedelta(days=365)

    credential = {
        "id": f"cred:{hospital_id}",
        "type": ["VerifiableCredential", "HospitalCredential"],
        "issuer": "FL-Health Government Authority (Simulated)",
        "issuanceDate": issued_at.isoformat(),
        "expirationDate": expires_at.isoformat(),
        "credentialSubject": {
            "id": hospital_id,
            "hospital_name": hospital_name,
            "license_number": license_number,
            "approved_training": ["Heart Disease", "Diabetes", "Breast Cancer"],
            "privacy_level": "epsilon=1.0",
        },
        "proof": {
            "type": "Ed25519Signature2020",
            "created": issued_at.isoformat(),
            "verificationMethod": "did:fl-health:gov#keys-1",
            "proofPurpose": "assertionMethod",
        },
    }

    # Hash the credential subject as the "proof value"
    credential["proof"]["proofValue"] = hashlib.sha256(
        json.dumps(credential["credentialSubject"], sort_keys=True).encode()
    ).hexdigest()

    return credential, issued_at, expires_at


def issue_credential(hospital_id: str):
    """
    Admin action — issue a Verifiable Credential to a hospital.
    Called when the admin approves a pending hospital.
    """
    service = get_service_client()

    # Fetch hospital
    result = service.table("hospitals").select("*").eq("id", hospital_id).execute()
    if not result.data:
        return {"success": False, "reason": "Hospital not found"}

    hospital = result.data[0]

    # Generate credential
    credential, issued_at, expires_at = generate_credential(
        hospital_id=hospital_id,
        hospital_name=hospital["hospital_name"],
        license_number=hospital.get("license_number", "N/A"),
    )

    credential_hash = hashlib.sha256(
        json.dumps(credential, sort_keys=True).encode()
    ).hexdigest()

    # Update hospital record
    service.table("hospitals").update({
        "is_credential_valid": True,
        "government_approved": True,
        "credential_issued_at": issued_at.isoformat(),
        "credential_expires_at": expires_at.isoformat(),
        "credential_hash": credential_hash,
        "credential_metadata": credential,
    }).eq("id", hospital_id).execute()

    return {
        "success": True,
        "message": "Credential issued successfully",
        "credential_hash": credential_hash,
        "expires_at": expires_at.isoformat(),
    }


def validate_credential(hospital_id: str, credential_hash: str):
    """
    Server action — validate a hospital's credential before training.
    Returns dict with valid: True/False and a breakdown of checks.
    """
    result = supabase.table("hospitals").select("*").eq("id", hospital_id).execute()
    if not result.data:
        return {"valid": False, "reason": "Hospital not registered"}

    hospital = result.data[0]

    expires = hospital.get("credential_expires_at")

    checks = {
        "hash_match": credential_hash == hospital.get("credential_hash"),
        "not_expired": (
            expires is not None
            and datetime.utcnow().isoformat() < expires
        ),
        "government_approved": hospital.get("government_approved", False),
        "credential_valid": hospital.get("is_credential_valid", False),
    }

    return {"valid": all(checks.values()), "checks": checks}