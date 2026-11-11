"""MediFed Hospital Agent: token storage, local data check, sample data, take-part switch, no token in logs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "hospital_agent")]

from medifed_agent import settings  # noqa: E402
from medifed_agent.session import AgentError, AgentSession  # noqa: E402

TOKEN = "secret-node-token-123"


@pytest.fixture(autouse=True)
def agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIFED_AGENT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MEDIFED_AGENT_NO_KEYRING", "1")
    return tmp_path / "home"


def test_settings_never_hold_the_token(agent_home):
    settings.save_settings({"server": "https://x.example", "hospital_id": "h", "token": TOKEN})
    text = (agent_home / "settings.json").read_text(encoding="utf-8")
    assert TOKEN not in text and json.loads(text)["hospital_id"] == "h"
    assert "token" not in settings.load_settings()


def test_token_fallback_file_round_trip(agent_home):
    where = settings.save_token("https://x.example", TOKEN)
    assert where == "a file only you can read"
    assert settings.load_token("https://x.example") == TOKEN
    assert settings.load_token("https://other.example") is None  # bound to its server
    assert TOKEN not in (agent_home / "settings.json").read_text(encoding="utf-8") if (agent_home / "settings.json").exists() else True
    settings.forget_token("https://x.example")
    assert settings.load_token("https://x.example") is None


def test_identify_refuses_bad_input_before_any_request():
    session = AgentSession(log=lambda line: None)
    with pytest.raises(AgentError, match="https://"):
        session.identify("ftp://x", TOKEN)
    with pytest.raises(AgentError, match="token"):
        session.identify("https://x.example", "  ")


def test_sample_data_is_simulated_and_passes_the_local_check(agent_home):
    session = AgentSession(log=lambda line: None)
    session.profile = {"hospital_id": "hospital_test_city_hospital", "name": "Test City Hospital", "declared_modalities": ["ecg"]}
    folder = session.make_sample_data()
    assert folder.is_relative_to(agent_home)
    manifest = json.loads((folder / "ecg" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["simulated"] is True
    results = session.check_data(folder)
    assert list(results) == ["ecg"]  # only what the hospital declared
    assert results["ecg"]["passed"] and results["ecg"]["train_records"] > 0
    assert not (folder / "ehr").exists() and not (folder / "xray").exists()


class FakeTransport:
    def __init__(self, participating=True):
        self.calls = []
        self.participating = participating

    def profile(self, hospital_id):
        return {"hospital_id": hospital_id, "name": "Test City Hospital", "registered": True, "declared_modalities": ["ecg"]}

    def report_data_check(self, hospital_id, modalities):
        self.calls.append(("check", modalities))
        return {"invited_modalities": ["ecg"]}

    def pending(self, hospital_id):
        return {"round_ids": ["ecg-r0001"], "participating": self.participating}

    def report_failure(self, round_id, hospital_id, stage, message):
        self.calls.append(("failure", round_id, stage))


def _runner(tmp_path, lines):
    from ml.simulation.hospitals import generate_hospital_data, sample_hospital
    from ml.training.node_runner import NodeRunner

    hospital = sample_hospital("hospital_test_city_hospital", "Test City Hospital")
    generate_hospital_data(tmp_path / "data", hospital, modalities=["ecg"])
    runner = NodeRunner("hospital_test_city_hospital", "https://x.example", TOKEN, tmp_path / "data" / hospital.hospital_id, log=lines.append)
    runner.transport = FakeTransport()
    return runner


def test_data_check_report_and_logs_never_carry_the_token(tmp_path):
    lines = []
    runner = _runner(tmp_path, lines)
    from ml.common.datasets import local_data_summary

    runner._check_and_report(local_data_summary(runner.data_dir))
    kind, report = runner.transport.calls[0]
    assert kind == "check" and report["ecg"]["passed"] is True
    assert set(report["ecg"]) == {"passed", "train_records", "val_records", "label_counts", "problems"}
    assert runner.name == "Test City Hospital"
    assert lines and not any(TOKEN in line for line in lines)


def test_take_part_switch_off_declines_rounds(tmp_path):
    lines = []
    runner = _runner(tmp_path, lines)
    runner.local_participation = False
    runner.poll_once()
    assert ("failure", "ecg-r0001", "declined") in runner.transport.calls
