"""FL-Healthcare coordinator API.

The repository root is added to ``sys.path`` so the top-level ``ml`` and
``analytics`` packages import whether the server is started from the
repository root (``python run.py``) or from ``backend/`` (``uvicorn app.main:app``).
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
