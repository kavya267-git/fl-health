#!/usr/bin/env python3
"""Print the token a hospital node must send in the X-Hospital-Token header.

Tokens are derived from NODE_TOKEN_SECRET (backend/.env), so set that variable
to a fixed value before using external nodes; otherwise the server generates a
new secret on every start and old tokens stop working.

    python scripts/node_token.py hospital_a hospital_b
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.utils.hashing import hmac_token  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")
secret = os.getenv("NODE_TOKEN_SECRET", "").strip()
if not secret:
    sys.exit("NODE_TOKEN_SECRET is not set in backend/.env (or the environment).")
for hospital_id in sys.argv[1:] or ["hospital_a", "hospital_b", "hospital_c", "hospital_d"]:
    print(f"{hospital_id}  {hmac_token(secret, f'hospital-node:{hospital_id}')}")
