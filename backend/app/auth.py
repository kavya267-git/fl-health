# backend/app/auth.py
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.supabase_client import supabase, get_service_client

security = HTTPBearer()


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        user = supabase.auth.get_user(token)
        if user and user.user:
            return {"id": user.user.id, "email": user.user.email}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    raise HTTPException(status_code=401, detail="Authentication required")


async def get_current_hospital(user_data: dict = Depends(verify_token)):
    """Use service client to bypass RLS for role lookup."""
    service = get_service_client()
    result = service.table("hospitals").select("*").eq("id", user_data["id"]).execute()
    if result.data:
        return result.data[0]
    return None


async def get_current_admin(user_data: dict = Depends(verify_token)):
    """Use service client to bypass RLS for admin lookup."""
    service = get_service_client()
    result = service.table("admins").select("*").eq("id", user_data["id"]).execute()
    if result.data:
        return result.data[0]
    raise HTTPException(status_code=403, detail="Admin access required")


def require_role(role: str):
    async def dependency(user_data: dict = Depends(verify_token)):
        if role == "hospital":
            hospital = await get_current_hospital(user_data)
            if hospital:
                return hospital
            raise HTTPException(status_code=403, detail="Hospital account required")
        elif role == "admin":
            admin = await get_current_admin(user_data)
            if admin:
                return admin
        raise HTTPException(status_code=403, detail=f"{role} access required")
    return dependency