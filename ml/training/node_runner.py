"""Runs one hospital node on its own machine.

Used by ``scripts/run_hospital_node.py`` and ``scripts/setup_hospital.py``:

1. **Start-up check.** Reach the coordinator, read ``/api/system/config`` and
   refuse to start if this machine would train a different model (backend,
   architecture or layer shapes) than the coordinator expects. Without this a
   mismatch only shows up mid-round, as a rejected update.
2. **Heartbeat.** Every ~10 s, tell the coordinator the node is up: hospital
   id, ML backend, device, software version and record *counts*. The dashboard
   shows the hospital as connected while these arrive.
3. **Round loop.** Wait for rounds this hospital is invited to, train locally,
   send the update, evaluate the aggregated model. Survives the coordinator or
   the network going away and carries on when they come back.

No record ever leaves the machine: only weights, counts and summary metrics.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import requests

from ml import __version__
from ml.common.datasets import local_data_summary
from ml.registry import BackendUnavailableError, configured_backend, get_adapter
from ml.training.hospital_node import HospitalNode
from ml.training.http_transport import CoordinatorError, HttpTransport

HEARTBEAT_SECONDS = 10.0
DECLINE_REASON = "participation is switched off on this hospital's dashboard"


def display_name(hospital_id: str) -> str:
    """'hospital_b' -> 'Hospital B'; any other id is shown as it is (registered hospitals use their own name)."""
    prefix, _, suffix = hospital_id.partition("_")
    return f"Hospital {suffix.upper()}" if prefix == "hospital" and len(suffix) == 1 else hospital_id


def format_bytes(size: int) -> str:
    """Readable size of an update: kilobytes below 0.1 MB, so small models do not show as 0.0 MB."""
    return f"{size / 1e6:.1f} MB" if size >= 100_000 else f"{max(1, round(size / 1e3))} KB"


def round_label(round_id: str) -> str:
    """'ehr-r0004' -> 'round 4 (EHR)' (round ids are '<modality>-r<number>')."""
    modality, _, number = round_id.rpartition("-r")
    return f"round {int(number)} ({modality.upper()})" if number.isdigit() and modality else round_id


def set_console_title(title: str) -> None:
    """Name the terminal window, so two nodes on one laptop are easy to tell apart."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        elif sys.stdout.isatty():
            sys.stdout.write(f"]0;{title}")
            sys.stdout.flush()
    except Exception:  # cosmetic only
        pass
PYTORCH_INSTALL = "pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu"


class NodeStartupError(RuntimeError):
    """The node must not start. The message says what to fix."""


def describe_device(backend: str) -> str:
    if backend != "pytorch":
        return "cpu"
    from ml.common.torch_adapter import resolve_device

    return resolve_device().type


def local_architectures(modalities: Iterable[str]) -> Dict[str, dict]:
    """Which model this machine would train for each modality (or why it cannot)."""
    result: Dict[str, dict] = {}
    for modality in modalities:
        try:
            adapter = get_adapter(modality)
            result[modality] = {
                "backend": adapter.backend,
                "architecture": adapter.architecture,
                "architecture_signature": adapter.signature(),
            }
        except (BackendUnavailableError, ValueError, ImportError) as exc:
            result[modality] = {"error": str(exc)}
    return result


def compatibility_problems(server: dict, local: Dict[str, dict]) -> List[str]:
    """Everything that would make this node's updates unusable to the coordinator."""
    problems = []
    if server.get("hospital_nodes") != "external":
        problems.append(
            "The coordinator runs its hospitals inside the API (HOSPITAL_NODES=in-process), so it will never "
            "invite this node. On the server, set HOSPITAL_NODES=external in backend/.env and restart it."
        )
    server_models = server.get("model_backends") or {}
    for modality, mine in local.items():
        theirs = server_models.get(modality) or {}
        name = modality.upper()
        if theirs.get("error") or not theirs.get("backend"):
            problems.append(f"{name}: the coordinator cannot load its own model ({theirs.get('error', 'not reported')}).")
        elif mine.get("error"):
            problems.append(
                f"{name}: the coordinator trains {theirs['architecture']} ({theirs['backend']}), "
                f"but this machine cannot: {mine['error']}"
            )
        elif (mine["backend"], mine["architecture"]) != (theirs["backend"], theirs["architecture"]):
            problems.append(
                f"{name}: the coordinator trains {theirs['architecture']} ({theirs['backend']}); "
                f"this machine would train {mine['architecture']} ({mine['backend']})."
            )
        elif theirs.get("architecture_signature") and mine["architecture_signature"] != theirs["architecture_signature"]:
            problems.append(
                f"{name}: both sides use {mine['architecture']}, but its layers have different shapes. "
                "Use the same copy of the repository and the same PyTorch / torchvision versions on both machines."
            )
    return problems


class NodeRunner:
    def __init__(
        self,
        hospital_id: str,
        server: str,
        token: str,
        data_dir: Path,
        poll_seconds: float = 3.0,
        log: Callable[[str], None] = print,
        name: Optional[str] = None,
    ):
        self.hospital_id = hospital_id
        self.server = server.rstrip("/")
        self.data_dir = Path(data_dir)
        self.poll_seconds = poll_seconds
        self._log = log
        self.transport = HttpTransport(self.server, token)
        # A second session for the heartbeat thread: requests sessions are not thread-safe.
        self._heartbeat_transport = HttpTransport(self.server, token)
        self.node = HospitalNode(hospital_id, self.data_dir, self.transport)
        self.beat: dict = {}
        self._stop = threading.Event()
        self.name = name or display_name(hospital_id)
        self.participating = True
        #: The operator's local switch (the agent's "Take part in rounds"). Rounds are declined while it is off.
        self.local_participation = True
        #: Per modality: passed / counts / problems, from the local data check (registered hospitals).
        self.data_check: Dict[str, dict] = {}

    def log(self, message: str) -> None:
        """One line per step, always naming the hospital: two nodes may share a laptop."""
        self._log(f"{datetime.now():%H:%M:%S} {self.name} · {message}")

    # ------------------------------------------------------------ start-up
    def preflight(self) -> dict:
        """Check everything that can be checked before the first round. Raises NodeStartupError."""
        summary = local_data_summary(self.data_dir)
        if not summary:
            raise NodeStartupError(
                f"No local data in {self.data_dir}.\n"
                f"Create it first:  python scripts/setup_hospital.py {self.hospital_id} --server {self.server} --token <token>"
            )
        try:
            server = self.transport.system_config()
        except requests.RequestException as exc:
            raise NodeStartupError(
                f"Cannot reach the coordinator at {self.server} ({exc.__class__.__name__}).\n"
                "Check that:\n"
                "  - the API is running on the server, started with API_HOST=0.0.0.0 in backend/.env;\n"
                "  - both machines are on the same network (or on Tailscale), and you used the server's address;\n"
                "  - the server's firewall allows incoming connections on port 8000.\n"
                f"Test from this machine: open {self.server}/api/health in a browser."
            ) from exc
        except CoordinatorError as exc:
            raise NodeStartupError(f"{self.server} answered, but not as a MediFed coordinator: {exc}") from exc

        self._check_and_report(summary)
        local = local_architectures(sorted(summary))
        problems = compatibility_problems(server, local)
        if problems:
            raise NodeStartupError(
                "This node does not match the coordinator, so its updates would be rejected:\n"
                + "\n".join(f"  - {p}" for p in problems)
                + f"\nEvery machine must use the same ML_BACKEND. The coordinator's is '{server.get('ml_backend', '?')}'; "
                f"this machine's is '{configured_backend()}'.\n"
                f"To use the PyTorch models here:  {PYTORCH_INSTALL}"
            )
        if server.get("version") != __version__:
            self.log(
                f"warning: coordinator runs version {server.get('version')}, this node {__version__}. "
                "Update both to the same copy of the repository."
            )

        backend = next(iter(local.values()))["backend"]
        self.beat = {
            "hospital_id": self.hospital_id,
            "hostname": socket.gethostname(),
            "ml_backend": backend,
            "device": describe_device(backend),
            "software_version": __version__,
            "architectures": local,
            "data_summary": summary,  # record counts only
        }
        try:
            self.transport.heartbeat(self.beat)
        except CoordinatorError as exc:
            if exc.status_code == 403:
                raise NodeStartupError(
                    f"The coordinator rejected the token for {self.hospital_id}.\n"
                    "Get the token for this hospital from the server (python scripts/node_token.py) and check that "
                    "NODE_TOKEN_SECRET in the server's backend/.env has not changed since."
                ) from exc
            if exc.status_code == 404:
                raise NodeStartupError(
                    f"The coordinator has no hospital '{self.hospital_id}'. "
                    "Use hospital_a, hospital_b, hospital_c or hospital_d."
                ) from exc
            raise NodeStartupError(str(exc)) from exc
        except requests.RequestException as exc:
            raise NodeStartupError(f"The coordinator stopped answering during start-up: {exc}") from exc
        return server

    def _check_and_report(self, summary: dict) -> None:
        """Registered hospitals: run the LOCAL data check on the declared modalities and report pass/fail and counts.

        Built-in hospitals (hospital_a-d) have no profile to check against and skip this.
        """
        from ml.common.data_check import check_folder

        try:
            profile = self.transport.profile(self.hospital_id)
        except CoordinatorError as exc:
            if exc.status_code == 403:
                raise NodeStartupError(
                    f"The coordinator rejected the token for {self.hospital_id}. Generate a new token on the "
                    "hospital's 'My hospital' page and paste it here."
                ) from exc
            if exc.status_code == 404:
                return  # an older coordinator without registration
            raise NodeStartupError(str(exc)) from exc
        if not profile.get("registered"):
            return
        if profile.get("name"):
            self.name = profile["name"]
        declared = profile.get("declared_modalities") or []
        self.data_check = check_folder(self.data_dir, declared)
        for modality, result in self.data_check.items():
            verdict = "passed" if result["passed"] else "FAILED"
            self.log(
                f"data check {modality.upper()}: {verdict} · {result['train_records']} train / "
                f"{result['val_records']} held-out (checked on this machine)"
            )
            for problem in result["problems"]:
                self.log(f"  - {problem}")
        missing = [m for m in declared if m not in summary]
        if missing:
            self.log(f"no local data for declared {', '.join(m.upper() for m in missing)}")
        reply = self.transport.report_data_check(self.hospital_id, self.data_check)
        invited = reply.get("invited_modalities") or []
        if not any(r["passed"] for r in self.data_check.values()):
            raise NodeStartupError(
                "No declared kind of data passed the local check, so this hospital cannot take part yet. "
                "Fix the problems above and check again."
            )
        self.log(
            "the server will invite this hospital to rounds for: "
            + (", ".join(m.upper() for m in invited) if invited else "(after the first heartbeat)")
        )

    def stop(self) -> None:
        """Stop the heartbeat and the round loop (the agent's Disconnect)."""
        self._stop.set()

    # ----------------------------------------------------------- heartbeat
    def _heartbeat_loop(self) -> None:
        healthy = True
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self._heartbeat_transport.heartbeat(self.beat)
                if not healthy:
                    self.log("connection to the coordinator is back")
                    healthy = True
            except (requests.RequestException, RuntimeError) as exc:
                if healthy:
                    self.log(f"heartbeat failed, retrying every {HEARTBEAT_SECONDS:.0f} s: {exc}")
                    healthy = False

    # --------------------------------------------------------------- rounds
    def handle_round(self, round_id: str) -> None:
        label = round_label(round_id)
        self.log(f"{label} · invited, joining")
        stage = "join"
        try:
            info = self.node.join(round_id)
            stage = "training"
            self.log(f"{label} · training locally…")
            started = time.perf_counter()
            self.node.train_and_submit(round_id, info)
            size = format_bytes(self.node.last_update_bytes or 0)
            self.log(f"{label} · update sent ({size}, trained in {time.perf_counter() - started:.1f} s)")
        except Exception as exc:
            self.transport.report_failure(round_id, self.hospital_id, stage, str(exc))
            self.log(f"{label} · {stage} failed: {exc}")
            return
        try:
            status = self.transport.wait_for_status(round_id, self.hospital_id, ("EVALUATING", "COMPLETED"))
        except Exception as exc:
            self.log(f"{label} · lost track of the round: {exc}")
            return
        if status["status"] != "EVALUATING":
            self.log(f"{label} · round ended as {status['status'].lower()}")
            return
        try:
            self.node.evaluate_and_report(round_id, info)
            self.log(f"{label} · evaluated {self._f1_text(info['modality'])} on local held-out data")
        except Exception as exc:
            self.transport.report_failure(round_id, self.hospital_id, "evaluation", str(exc))
            self.log(f"{label} · evaluation failed: {exc}")

    def _f1_text(self, modality: str) -> str:
        """F1 of the new global model on this hospital's held-out split (as the dashboard defines F1)."""
        from ml.evaluation.metrics import metrics_from_evaluation

        if self.node.last_evaluation is None:
            return "the new global model"
        metrics = metrics_from_evaluation(self.node.last_evaluation, get_adapter(modality).task)
        return f"F1 {metrics['f1']:.2f}"

    def decline(self, round_id: str) -> None:
        """The operator switched participation off: tell the coordinator rather than stay silent."""
        self.transport.report_failure(round_id, self.hospital_id, "declined", DECLINE_REASON)
        self.log(f"{round_label(round_id)} · declined ({DECLINE_REASON})")

    def poll_once(self) -> None:
        pending = self.transport.pending(self.hospital_id)
        participating = bool(pending.get("participating", True)) and self.local_participation
        if participating != self.participating:
            self.participating = participating
            self.log(
                "participation switched on: taking part in rounds again"
                if participating
                else f"{DECLINE_REASON}: rounds will be declined"
            )
        for round_id in pending["round_ids"]:
            if self.participating:
                self.handle_round(round_id)
            else:
                self.decline(round_id)

    def run(self, only_round: Optional[str] = None) -> None:
        set_console_title(f"{self.name} · FL hospital node")
        server = self.preflight()
        counts = ", ".join(
            f"{m.upper()} {s['train_samples'] + s['val_samples']}"
            + (" (simulated)" if s["simulated"] else "")
            for m, s in sorted(self.beat["data_summary"].items())
        )
        self.log(f"connected to {self.server} (coordinator {server.get('version')})")
        self.log(f"machine {self.beat['hostname']} · {self.beat['ml_backend']} on {self.beat['device'].upper()}")
        self.log(f"local records: {counts} · they stay on this machine")
        set_console_title(f"{self.name} · connected to {self.server}")

        heartbeat = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        heartbeat.start()
        try:
            if only_round:
                self.handle_round(only_round)
                return
            self.log("waiting for rounds (Ctrl+C to stop)")
            reachable = True
            while not self._stop.is_set():
                try:
                    self.poll_once()
                    if not reachable:
                        self.log("coordinator reachable again; waiting for rounds")
                        reachable = True
                except (requests.RequestException, RuntimeError) as exc:
                    if reachable:
                        self.log(f"cannot reach the coordinator, will keep trying: {exc}")
                        reachable = False
                self._stop.wait(self.poll_seconds)
        finally:
            self._stop.set()
