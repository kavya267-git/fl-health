"""The hospital node as an operator runs it: console lines, declining rounds, start-up errors, setup script."""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from backend_test_helpers import login
from ml.common.datasets import local_data_summary, save_local_dataset
from ml.simulation.ehr import simulate_ehr
from ml.simulation.hospitals import generate_hospital_data, get_simulated_hospital
from ml.training.http_transport import HttpTransport
from ml.training.node_runner import NodeRunner, NodeStartupError, display_name, format_bytes, round_label

ROOT = Path(__file__).resolve().parents[2]
SERVER = "http://testserver"


@pytest.fixture()
def server(settings):
    with TestClient(create_app(settings.model_copy(update={"hospital_nodes": "external"}))) as client:
        yield client


def _runner(client, hospital_id, tmp_path, token=None, lines=None):
    """A real NodeRunner whose HTTP calls go to the in-memory API instead of the network."""
    data_root = tmp_path / "hospitals"
    generate_hospital_data(data_root, get_simulated_hospital(hospital_id), seed=1, scale=0.2)
    token = token or client.app.state.ctx.hospitals.node_token(hospital_id)
    runner = NodeRunner(hospital_id, SERVER, token, data_root / hospital_id, log=(lines if lines is not None else []).append)
    runner.transport = HttpTransport(SERVER, token, session=client)
    runner._heartbeat_transport = HttpTransport(SERVER, token, session=client)
    runner.node.transport = runner.transport
    return runner


def test_display_names_and_round_labels():
    assert display_name("hospital_b") == "Hospital B" and display_name("clinic-7") == "clinic-7"
    assert round_label("ehr-r0004") == "round 4 (EHR)" and round_label("odd") == "odd"
    assert format_bytes(43_330_000) == "43.3 MB" and format_bytes(8_200) == "8 KB" and format_bytes(10) == "1 KB"


def test_node_runs_a_round_and_names_its_hospital_on_every_line(server, tmp_path):
    lines = []
    runner = _runner(server, "hospital_b", tmp_path, lines=lines)
    runner.preflight()
    admin = login(server, "admin@fl-healthcare.demo")
    started = server.post(
        "/api/federated/rounds/start", json={"modality": "ehr", "min_participants": 1}, headers=admin
    ).json()
    assert [p["hospital_id"] for p in started["participants"]] == ["hospital_b"]

    runner.poll_once()

    assert server.get(f"/api/federated/rounds/{started['id']}", headers=admin).json()["status"] == "COMPLETED"
    assert all(" Hospital B · " in line for line in lines)
    text = "\n".join(lines)
    for step in ("round 1 (EHR) · invited, joining", "round 1 (EHR) · training locally…", "round 1 (EHR) · update sent (",
                 "round 1 (EHR) · evaluated F1 "):
        assert step in text, step
    assert " KB, trained in " in text  # the NumPy test model is a few kilobytes


def test_node_declines_rounds_while_participation_is_off(server, tmp_path):
    lines = []
    runner = _runner(server, "hospital_b", tmp_path, lines=lines)
    runner.preflight()
    admin = login(server, "admin@fl-healthcare.demo")
    started = server.post(
        "/api/federated/rounds/start", json={"modality": "ecg", "min_participants": 1}, headers=admin
    ).json()
    operator = login(server, "hospital_b@fl-healthcare.demo")
    server.post("/api/hospitals/hospital_b/participation", json={"participating": False}, headers=operator)

    runner.poll_once()

    participant = server.get(f"/api/federated/rounds/{started['id']}", headers=admin).json()["participants"][0]
    assert participant["status"] == "FAILED" and "participation is switched off" in participant["error"]
    assert any("rounds will be declined" in line for line in lines)
    assert any("round 1 (ECG) · declined" in line for line in lines)
    declined = server.get("/api/audit", params={"action": "HOSPITAL_DECLINED_ROUND"}, headers=admin).json()["items"]
    assert [(e["hospital_id"], e["round_id"]) for e in declined] == [("hospital_b", started["id"])]


def test_start_up_refuses_a_wrong_token(server, tmp_path):
    runner = _runner(server, "hospital_b", tmp_path, token="not-the-token")
    with pytest.raises(NodeStartupError, match="rejected the token for hospital_b"):
        runner.preflight()


def test_start_up_refuses_an_unknown_hospital(server, tmp_path):
    data_root = tmp_path / "hospitals"
    generate_hospital_data(data_root, get_simulated_hospital("hospital_b"), seed=1, scale=0.2)
    token = server.app.state.ctx.hospitals.node_token("hospital_x")
    runner = NodeRunner("hospital_x", SERVER, token, data_root / "hospital_b", log=lambda _: None)
    runner.transport = HttpTransport(SERVER, token, session=server)
    with pytest.raises(NodeStartupError, match="no hospital 'hospital_x'"):
        runner.preflight()


def test_start_up_explains_an_unreachable_server(tmp_path):
    data_root = tmp_path / "hospitals"
    generate_hospital_data(data_root, get_simulated_hospital("hospital_c"), seed=1, scale=0.2)
    runner = NodeRunner("hospital_c", "http://127.0.0.1:9", "token", data_root / "hospital_c", log=lambda _: None)
    runner.transport.timeout = 2
    with pytest.raises(NodeStartupError) as error:
        runner.preflight()
    message = str(error.value)
    assert "http://127.0.0.1:9" in message and "firewall" in message and "API_HOST=0.0.0.0" in message


# ------------------------------------------------------------ setup script
@pytest.fixture()
def setup_script(monkeypatch):
    monkeypatch.setenv("ML_BACKEND", os.environ.get("ML_BACKEND", "numpy-reference"))  # main() sets it; restore after
    spec = importlib.util.spec_from_file_location("setup_hospital", ROOT / "scripts" / "setup_hospital.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(tmp_path, *extra):
    return [*extra, "--config-dir", str(tmp_path / "nodes"), "--data-root", str(tmp_path / "hospitals"),
            "--scale", "0.1", "--ml-backend", "numpy-reference", "--no-start"]


def test_two_hospitals_on_one_laptop_keep_separate_settings_and_data(setup_script, tmp_path):
    setup_script.main(_args(tmp_path, "hospital_a", "--server", "http://10.0.0.5:8000/", "--token", "token-a"))
    setup_script.main(_args(tmp_path, "hospital_b", "--server", "http://10.0.0.5:8000", "--token", "token-b"))

    configs = {h: json.loads((tmp_path / "nodes" / f"{h}.json").read_text()) for h in ("hospital_a", "hospital_b")}
    assert configs["hospital_a"]["token"] == "token-a" and configs["hospital_b"]["token"] == "token-b"
    assert configs["hospital_a"]["server"] == "http://10.0.0.5:8000"  # trailing slash removed
    assert sorted(p.name for p in (tmp_path / "hospitals").iterdir()) == ["hospital_a", "hospital_b"]
    for hospital_id in ("hospital_a", "hospital_b"):
        assert all(entry["simulated"] for entry in local_data_summary(tmp_path / "hospitals" / hospital_id).values())


def test_only_the_named_hospital_gets_data(setup_script, tmp_path):
    setup_script.main(_args(tmp_path, "hospital_c", "--server", "http://s:8000", "--token", "t"))
    assert [p.name for p in (tmp_path / "hospitals").iterdir()] == ["hospital_c"]


def test_later_runs_need_only_the_hospital_id(setup_script, tmp_path, capsys):
    setup_script.main(_args(tmp_path, "hospital_d", "--server", "http://s:8000", "--token", "t"))
    capsys.readouterr()
    setup_script.main(_args(tmp_path, "hospital_d"))
    out = capsys.readouterr().out
    assert "server http://s:8000" in out and all(line.startswith("Hospital D · ") for line in out.splitlines())


def test_first_run_without_server_or_token_explains_what_is_missing(setup_script, tmp_path):
    with pytest.raises(SystemExit) as error:
        setup_script.main(_args(tmp_path, "hospital_a", "--server", "http://s:8000"))
    assert "--token" in str(error.value) and "print_demo_setup.py" in str(error.value)


def test_unknown_hospital_is_refused(setup_script, tmp_path):
    with pytest.raises(SystemExit, match="Unknown hospital 'hospital_q'"):
        setup_script.main(_args(tmp_path, "hospital_q", "--server", "http://s:8000", "--token", "t"))


def test_prepared_real_data_is_used_instead_of_simulated(setup_script, tmp_path):
    import numpy as np

    prepared = tmp_path / "prepared" / "hospital_b"
    X, y = simulate_ehr(40, np.random.default_rng(0))
    save_local_dataset(prepared, "ehr", train=(X[:30], y[:30]), val=(X[30:], y[30:]), source="mimic-iv", description="test")
    setup_script.main(_args(tmp_path, "hospital_b", "--server", "http://s:8000", "--token", "t", "--data", str(prepared)))

    config = json.loads((tmp_path / "nodes" / "hospital_b.json").read_text())
    assert Path(config["data_dir"]) == prepared.resolve()
    assert not (tmp_path / "hospitals").exists()  # nothing simulated was generated

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit, match="No prepared data"):
        setup_script.main(_args(tmp_path, "hospital_c", "--server", "http://s:8000", "--token", "t", "--data", str(empty)))
