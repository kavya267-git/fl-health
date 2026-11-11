"""Where the agent keeps its settings, and how it keeps the node token.

* Settings (server URL, hospital id, data folder, the "take part" switch) go to a small JSON file in the user's
  own settings folder: ``%APPDATA%\\MediFed Agent`` on Windows, ``~/.config/medifed-agent`` elsewhere.
* The node token goes to the operating system's credential store (Windows Credential Manager, macOS Keychain,
  Secret Service) through ``keyring`` when one is available. Otherwise it goes to a file in the same folder that
  only the current user can read. The token is never written to the settings file or to any log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

KEYRING_SERVICE = "MediFed Hospital Agent"


def config_dir() -> Path:
    if sys.platform == "win32" and os.getenv("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "MediFed Agent"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "medifed-agent"
    override = os.getenv("MEDIFED_AGENT_HOME")
    path = Path(override) if override else base
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_file() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> dict:
    path = _settings_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    data.pop("token", None)  # never kept here
    return data


def save_settings(settings: dict) -> None:
    clean = {k: v for k, v in settings.items() if k != "token"}
    _settings_file().write_text(json.dumps(clean, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ token
def _keyring():
    if os.getenv("MEDIFED_AGENT_NO_KEYRING"):
        return None
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _token_file() -> Path:
    return config_dir() / "node-token"


def _restrict_to_user(path: Path) -> None:
    """Make the fallback token file readable by the current user only."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if sys.platform == "win32":
        user = os.getenv("USERNAME")
        if user:
            # Remove inherited permissions and grant only the current user. Best effort; quiet on failure.
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )


def token_storage() -> str:
    return "the system credential store" if _keyring() else "a file only you can read"


def save_token(server: str, token: str) -> str:
    """Store the token; returns where it went (for the log, without the token)."""
    backend = _keyring()
    if backend is not None:
        try:
            backend.set_password(KEYRING_SERVICE, server, token)
            if _token_file().exists():
                _token_file().unlink()
            return "the system credential store"
        except Exception:
            pass
    path = _token_file()
    path.write_text(json.dumps({"server": server, "token": token}), encoding="utf-8")
    _restrict_to_user(path)
    return "a file only you can read"


def load_token(server: str) -> Optional[str]:
    backend = _keyring()
    if backend is not None:
        try:
            value = backend.get_password(KEYRING_SERVICE, server)
            if value:
                return value
        except Exception:
            pass
    path = _token_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("server") == server:
                return data.get("token")
        except (OSError, ValueError):
            return None
    return None


def forget_token(server: str) -> None:
    backend = _keyring()
    if backend is not None:
        try:
            backend.delete_password(KEYRING_SERVICE, server)
        except Exception:
            pass
    if _token_file().exists():
        _token_file().unlink()
