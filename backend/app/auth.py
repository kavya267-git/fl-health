# backend/app/auth.py
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.supabase_client import supabase

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        user = supabase.auth.get_user(token)
        if user and user.user:
            return {"id": user.user.id, "email": user.user.email}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    raise HTTPException(status_code=401, detail="Authentication required")

async def get_current_hospital(user_data: dict = Depends(verify_token)):
    result = supabase.table("hospitals").select("*").eq("id", user_data["id"]).execute()
    if result.data:
        return result.data[0]
    return None

async def get_current_admin(user_data: dict = Depends(verify_token)):
    result = supabase.table("admins").select("*").eq("id", user_data["id"]).execute()
    if result.data:
        return result.data[0]
    raise HTTPException(status_code=403, detail="Admin access required")

def require_hospital():
    async def dependency(user_data: dict = Depends(verify_token)):
        hospital = await get_current_hospital(user_data)
        if not hospital:
            raise HTTPException(status_code=403, detail="Hospital registration required")
        return hospital
    return dependency

def require_admin():
    async def dependency(user_data: dict = Depends(verify_token)):
        admin = await get_current_admin(user_data)
        if not admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        return admin
    return dependency