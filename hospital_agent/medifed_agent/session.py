"""What the agent does, independent of the window: identify the hospital, check data, connect, take part.

The data folder is read only on this machine. What reaches the server is what the node has always sent:
model weights, record counts and summary metrics, plus (for a registered hospital) the local data check's
pass / fail and counts per modality.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Every MediFed coordinator in this release trains the PyTorch models; the agent must train the same ones.
os.environ.setdefault("ML_BACKEND", "pytorch")

from ml.common.data_check import check_folder  # noqa: E402
from ml.common.datasets import local_data_summary  # noqa: E402
from ml.common.types import MODALITIES  # noqa: E402
from ml.training.http_transport import CoordinatorError, HttpTransport  # noqa: E402
from ml.training.node_runner import NodeRunner, NodeStartupError  # noqa: E402

from .settings import config_dir  # noqa: E402

BUILT_IN = {f"hospital_{x}" for x in "abcd"}


class AgentError(RuntimeError):
    """Something the operator can fix; the message says what."""


def _friendly(exc: Exception) -> str:
    if isinstance(exc, CoordinatorError):
        if exc.status_code == 403:
            return "The server did not accept this node token. Generate a new one on your hospital's 'My hospital' page."
        return f"The server answered with an error ({exc.status_code}): {exc.detail}"
    import requests

    if isinstance(exc, requests.exceptions.SSLError):
        return (
            "The server's HTTPS certificate could not be verified, so the agent did not connect. Check the address; "
            "if your network inspects HTTPS traffic, ask IT to allow this server."
        )
    if isinstance(exc, requests.RequestException):
        return f"Cannot reach the server ({exc.__class__.__name__}). Check the address and your internet connection."
    return str(exc)


class AgentSession:
    def __init__(self, log: Callable[[str], None]):
        self.log = log
        self.profile: Optional[dict] = None
        self.runner: Optional[NodeRunner] = None
        self._thread: Optional[threading.Thread] = None
        self.take_part = True

    # ---------------------------------------------------------- identity
    def identify(self, server: str, token: str, hospital_id: Optional[str] = None) -> dict:
        """The hospital this token belongs to. Built-in demo hospitals (hospital_a-d) need their id as well."""
        server = server.strip().rstrip("/")
        if not server.startswith(("https://", "http://")):
            raise AgentError("The server address must start with https:// (or http:// on a local network).")
        if not token.strip():
            raise AgentError("Paste your hospital's node token first.")
        transport = HttpTransport(server, token.strip(), timeout=30.0)
        try:
            profile = transport.profile(hospital_id) if hospital_id else transport.whoami()
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            raise AgentError(_friendly(exc)) from exc
        self.profile = profile
        return profile

    # ---------------------------------------------------------- data
    def declared(self) -> List[str]:
        return list((self.profile or {}).get("declared_modalities") or MODALITIES)

    def check_data(self, folder: Path) -> Dict[str, dict]:
        """The local check, on this machine only. Nothing is sent."""
        folder = Path(folder)
        if not folder.is_dir():
            raise AgentError(f"{folder} is not a folder.")
        present = set(local_data_summary(folder))
        modalities = self.declared() if self.profile else sorted(present) or list(MODALITIES)
        return check_folder(folder, modalities)

    def make_sample_data(self) -> Path:
        """SIMULATED records for this hospital in the agent's own folder (fictional, labelled simulated)."""
        from ml.simulation.hospitals import generate_hospital_data, get_simulated_hospital, sample_hospital

        if not self.profile:
            raise AgentError("Check the token first, so the sample data matches your hospital.")
        hospital_id = self.profile["hospital_id"]
        root = config_dir() / "sample-data"
        hospital = (
            get_simulated_hospital(hospital_id)
            if hospital_id in BUILT_IN
            else sample_hospital(hospital_id, self.profile.get("name") or hospital_id)
        )
        generate_hospital_data(root, hospital, modalities=self.declared())
        return root / hospital_id

    # ---------------------------------------------------------- rounds
    @property
    def connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def connect(self, server: str, token: str, folder: Path, on_end: Callable[[Optional[str]], None]) -> None:
        if self.connected:
            return
        if not self.profile:
            raise AgentError("Check the token first.")
        runner = NodeRunner(
            self.profile["hospital_id"],
            server.strip().rstrip("/"),
            token.strip(),
            Path(folder),
            log=self.log,
            name=self.profile.get("name"),
            models_dir=config_dir() / "models",
        )
        runner.local_participation = self.take_part
        self.runner = runner

        def work() -> None:
            error = None
            try:
                runner.run()
            except NodeStartupError as exc:
                error = str(exc)
            except Exception as exc:  # noqa: BLE001
                error = _friendly(exc)
            on_end(error)

        self._thread = threading.Thread(target=work, name="medifed-node", daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        if self.runner is not None:
            self.runner.stop()

    def set_take_part(self, value: bool) -> None:
        self.take_part = value
        if self.runner is not None:
            self.runner.local_participation = value
