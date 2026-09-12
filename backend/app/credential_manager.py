# backend/app/credential_manager.py
import hashlib
import json
from datetime import datetime, timedelta
from app.supabase_client import get_service_client

class CredentialManager:
    def __init__(self):
        self.service = get_service_client()
    
    def generate_hash(self, data: dict) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    
    def issue_credential(self, hospital_id: str, admin_id: str):
        result = self.service.table("hospitals").select("*").eq("id", hospital_id).execute()
        if not result.data:
            return {"success": False, "error": "Hospital not found"}
        
        hospital = result.data[0]
        
        credential = {
            "id": f"cred:{hospital_id}",
            "type": ["VerifiableCredential", "HospitalCredential"],
            "issuer": "FL-Health Authority",
            "issuanceDate": datetime.now().isoformat(),
            "expirationDate": (datetime.now() + timedelta(days=365)).isoformat(),
            "credentialSubject": {
                "id": hospital_id,
                "hospital_name": hospital.get("hospital_name"),
                "license_number": hospital.get("license_number"),
                "approved_diseases": ["Heart Disease", "Diabetes", "Breast Cancer"],
                "privacy_level": "ε=1.0"
            }
        }
        
        credential_hash = self.generate_hash(credential)
        
        update_data = {
            "is_credential_valid": True,
            "government_approved": True,
            "credential_issued_at": datetime.now().isoformat(),
            "credential_expires_at": (datetime.now() + timedelta(days=365)).isoformat(),
            "credential_hash": credential_hash,
            "credential_metadata": credential
        }
        
        self.service.table("hospitals").update(update_data).eq("id", hospital_id).execute()
        
        self.service.table("credential_requests").insert({
            "hospital_id": hospital_id,
            "request_status": "approved",
            "reviewed_at": datetime.now().isoformat(),
            "reviewed_by": admin_id,
            "notes": "Credential issued by admin"
        }).execute()
        
        return {
            "success": True,
            "credential_hash": credential_hash,
            "expires_at": update_data["credential_expires_at"],
            "message": "Credential issued successfully"
        }
    
    def verify_credential(self, hospital_id: str, credential_hash: str):
        result = self.service.table("hospitals").select("*").eq("id", hospital_id).execute()
        if not result.data:
            return {"valid": False, "reason": "Hospital not found"}
        
        hospital = result.data[0]
        checks = {
            "credential_valid": hospital.get("is_credential_valid", False),
            "government_approved": hospital.get("government_approved", False),
            "hash_match": hospital.get("credential_hash") == credential_hash,
            "not_expired": self._is_not_expired(hospital.get("credential_expires_at"))
        }
        
        if all(checks.values()):
            return {"valid": True, "message": "Credential verified"}
        return {"valid": False, "reason": "Invalid credential", "checks": checks}
    
    def _is_not_expired(self, expires_at: str) -> bool:
        if not expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return datetime.now(expiry.tzinfo) < expiry
        except:
            return False