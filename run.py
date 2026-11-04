"""Start the PrivaFuse API.

    python run.py

Reads settings from backend/.env (see backend/.env.example). Equivalent to
``cd backend && uvicorn app.main:app``.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv

    # API_HOST / API_PORT may be set in backend/.env; read it before using them.
    load_dotenv(ROOT / "backend" / ".env")
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    print(f"PrivaFuse API on http://{host}:{port}  (interactive docs: /docs)")
    uvicorn.run("app.main:app", host=host, port=port, reload=False, timeout_graceful_shutdown=5)
