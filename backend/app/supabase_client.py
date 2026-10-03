# backend/app/supabase_client.py
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Anon client — used for user auth (sign in / get_user)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Service client singleton — bypasses RLS, used for all DB writes/reads
_service_client: Client | None = None


def get_service_client() -> Client:
    """Return a singleton service-role client. Creating one per request was expensive."""
    global _service_client
    if _service_client is None:
        _service_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _service_client