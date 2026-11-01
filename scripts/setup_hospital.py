#!/usr/bin/env python3
"""Set up and start one hospital node on this machine.

First time (on the hospital's laptop):

    python scripts/setup_hospital.py hospital_b --server http://192.168.1.20:8000 --token <token>

This
  1. generates ONLY this hospital's simulated data, under data/hospitals/<id>/
     (SIMULATED: fictional records, labelled as such everywhere);
  2. saves the server address and token in data/hospitals/<id>/node_config.json;
  3. starts the node, which checks it matches the coordinator, sends a
     heartbeat every ~10 s and takes part in rounds.

After that, just:

    python scripts/setup_hospital.py hospital_b

The data never leaves this machine. Only model weights, record counts and
summary metrics are sent to the coordinator.

Get the token on the server with:  python scripts/node_token.py
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_SEED = 2024  # same as the server's SEED default, so the data matches in-process mode


def config_path(data_root: Path, hospital_id: str) -> Path:
    return data_root / hospital_id / "node_config.json"


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hospital_id", help="hospital_a, hospital_b, hospital_c or hospital_d")
    parser.add_argument("--server", help="Coordinator URL, e.g. http://192.168.1.20:8000 (remembered)")
    parser.add_argument("--token", help="This hospital's node token (remembered)")
    parser.add_argument(
        "--ml-backend",
        choices=("auto", "pytorch", "numpy-reference"),
        help="Must match the server's ML_BACKEND (remembered; default auto)",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "hospitals")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Seed for the simulated data")
    parser.add_argument("--scale", type=float, default=1.0, help="Multiplier on the simulated dataset size")
    parser.add_argument("--regenerate", action="store_true", help="Replace existing simulated data")
    parser.add_argument("--no-start", action="store_true", help="Prepare data and config, but do not start the node")
    args = parser.parse_args()

    path = config_path(args.data_root, args.hospital_id)
    config = load_config(path)
    config.update(
        {
            key: value
            for key, value in (("server", args.server), ("token", args.token), ("ml_backend", args.ml_backend))
            if value
        }
    )
    config.setdefault("ml_backend", "auto")
    missing = [name for name in ("server", "token") if not config.get(name)]
    if missing:
        sys.exit(
            f"Missing --{' and --'.join(missing)}. The first run needs both, e.g.\n"
            f"  python scripts/setup_hospital.py {args.hospital_id} --server http://<server-ip>:8000 --token <token>\n"
            "Get the token on the server with:  python scripts/node_token.py"
        )
    config["server"] = config["server"].rstrip("/")

    # Before anything imports the model registry, which reads ML_BACKEND.
    os.environ["ML_BACKEND"] = config["ml_backend"]

    from ml.simulation.hospitals import SIMULATED_HOSPITALS, generate_hospital_data, get_simulated_hospital
    from ml.training.node_runner import NodeRunner, NodeStartupError

    try:
        hospital = get_simulated_hospital(args.hospital_id)
    except KeyError:
        known = ", ".join(h.hospital_id for h in SIMULATED_HOSPITALS)
        sys.exit(f"Unknown hospital '{args.hospital_id}'. Use one of: {known}")

    print(f"[{hospital.hospital_id}] {hospital.name} - SIMULATED hospital, fictional records")
    manifests = generate_hospital_data(
        args.data_root, hospital, seed=args.seed, scale=args.scale, overwrite=args.regenerate
    )
    for modality, manifest in manifests.items():
        splits = manifest.get("splits", {})
        label = "simulated" if manifest.get("simulated") else manifest.get("source", "unknown source")
        print(f"    {modality.upper():5s} {splits.get('train', 0):5d} train / {splits.get('val', 0):4d} held-out  ({label})")
    print(f"    stored in {args.data_root / hospital.hospital_id} - stays on this machine")

    save_config(path, config)
    print(f"    server {config['server']}, ML_BACKEND={config['ml_backend']} (saved to {path})")
    if args.no_start:
        return

    runner = NodeRunner(hospital.hospital_id, config["server"], config["token"], args.data_root / hospital.hospital_id)
    try:
        runner.run()
    except NodeStartupError as exc:
        sys.exit(f"[{hospital.hospital_id}] not starting:\n{exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
