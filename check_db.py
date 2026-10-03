import os
from dotenv import load_dotenv

# Load env from backend directory
load_dotenv(os.path.join(os.path.dirname(__file__), 'backend', '.env'))

from backend.app.supabase_client import get_service_client

service = get_service_client()
hospitals = service.table("hospitals").select("*").execute()
print(f"Hospitals: {len(hospitals.data)}")
print(hospitals.data)
