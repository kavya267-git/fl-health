#!/usr/bin/env python3
"""Set up and start one hospital node on this machine.

First time, on the hospital's laptop (one console window per hospital):

    python scripts/setup_hospital.py hospital_b --server http://192.168.1.20:8000 --token <token>

This
  1. generates ONLY this hospital's simulated data, in data/hospitals/<id>/
     (SIMULATED: fictional records, labelled as such everywhere), or, with
     --data <folder>, uses data you prepared with scripts/prepare_real_data.py;
  2. saves the server address and token in data/nodes/<id>.json (git-ignored);
  3. starts the node: it checks it matches the coordinator, sends a heartbeat
     every ~10 s and takes part in rounds.

After that, just:

    python scripts/setup_hospital.py hospital_b

Two hospitals can run side by side on one laptop: each has its own config file,
its own data folder and its own console window (titled with the hospital name).

The data never leaves this machine. Only model weights, record counts and
summary metrics are sent to the coordinator. On the server,
`python scripts/print_demo_setup.py` prints the exact command for each hospital.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_SEED = 2024  # same as the server's SEED default, so the data matches in-process mode
CONFIG_DIR = ROOT / "data" / "nodes"
KNOWN_HOSPITALS = ("hospital_a", "hospital_b", "hospital_c", "hospital_d")


def config_path(hospital_id: str, config_dir: Path = CONFIG_DIR) -> Path:
    return Path(config_dir) / f"{hospital_id}.json"


def load_config(hospital_id: str, config_dir: Path = CONFIG_DIR, data_root: Path = ROOT / "data" / "hospitals") -> dict:
    legacy = Path(data_root) / hospital_id / "node_config.json"  # where an earlier version kept it
    for candidate in (config_path(hospital_id, config_dir), legacy):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


def save_config(hospital_id: str, config: dict, config_dir: Path = CONFIG_DIR) -> Path:
    path = config_path(hospital_id, config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def resolve_settings(args: argparse.Namespace) -> dict:
    """Merge the saved config with this run's arguments. Exits with a message if something is missing."""
    config = load_config(args.hospital_id, args.config_dir, args.data_root)
    for key in ("server", "token", "ml_backend"):
        value = getattr(args, key)
        if value:
            config[key] = value
    if args.data:
        config["data_dir"] = str(Path(args.data).resolve())
    config.setdefault("ml_backend", "auto")
    missing = [name for name in ("server", "token") if not config.get(name)]
    if missing:
        sys.exit(
            f"Missing --{' and --'.join(missing)}. The first run needs both, e.g.\n"
            f"  python scripts/setup_hospital.py {args.hospital_id} --server http://<server-ip>:8000 --token <token>\n"
            "On the server, `python scripts/print_demo_setup.py` prints the exact command for every hospital."
        )
    config["server"] = config["server"].rstrip("/")
    return config


def prepare_data(hospital_id: str, config: dict, args: argparse.Namespace, say) -> Path:
    """Simulated data for this hospital only, or the prepared folder given with --data."""
    from ml.common.datasets import local_data_summary
    from ml.simulation.hospitals import generate_hospital_data, get_simulated_hospital

    if config.get("data_dir"):
        data_dir = Path(config["data_dir"])
        summary = local_data_summary(data_dir)
        if not summary:
            sys.exit(
                f"No prepared data in {data_dir}. It should contain ehr/, ecg/ or xray/ folders with a "
                "manifest.json each, as written by scripts/prepare_real_data.py."
            )
        for modality, entry in sorted(summary.items()):
            say(f"{modality.upper():5s} {entry['train_samples']:6d} train / {entry['val_samples']:5d} held-out ({entry['source']})")
        return data_dir

    hospital = get_simulated_hospital(hospital_id)
    manifests = generate_hospital_data(args.data_root, hospital, seed=args.seed, scale=args.scale, overwrite=args.regenerate)
    say(f"{hospital.name} · SIMULATED hospital, fictional records")
    for modality, manifest in manifests.items():
        splits = manifest.get("splits", {})
        label = "simulated" if manifest.get("simulated") else manifest.get("source", "unknown source")
        say(f"{modality.upper():5s} {splits.get('train', 0):6d} train / {splits.get('val', 0):5d} held-out ({label})")
    return Path(args.data_root) / hospital_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hospital_id", help="hospital_a, hospital_b, hospital_c or hospital_d")
    parser.add_argument("--server", help="Coordinator URL, e.g. http://192.168.1.20:8000 (remembered)")
    parser.add_argument("--token", help="This hospital's node token (remembered)")
    parser.add_argument(
        "--ml-backend",
        choices=("auto", "pytorch", "numpy-reference"),
        help="Must match the server's ML_BACKEND (remembered; default auto)",
    )
    parser.add_argument(
        "--data", type=Path, help="Use prepared real data in this folder instead of simulated data (remembered)"
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "hospitals", help=argparse.SUPPRESS)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Seed for the simulated data")
    parser.add_argument("--scale", type=float, default=1.0, help="Multiplier on the simulated dataset size")
    parser.add_argument("--regenerate", action="store_true", help="Replace existing simulated data")
    parser.add_argument("--no-start", action="store_true", help="Prepare data and config, but do not start the node")
    return parser


def main(argv=None) -> None:
    # '·' and '…' must never crash a console with a narrow code page.
    sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    if args.hospital_id not in KNOWN_HOSPITALS:
        sys.exit(f"Unknown hospital '{args.hospital_id}'. Use one of: {', '.join(KNOWN_HOSPITALS)}")

    # Before anything imports the model registry, which reads ML_BACKEND.
    config = resolve_settings(args)
    os.environ["ML_BACKEND"] = config["ml_backend"]

    from ml.training.node_runner import NodeRunner, NodeStartupError, display_name, set_console_title

    name = display_name(args.hospital_id)
    set_console_title(f"{name} · FL hospital node")

    def say(message: str) -> None:
        print(f"{name} · {message}", flush=True)

    data_dir = prepare_data(args.hospital_id, config, args, say)
    say(f"data in {data_dir} · stays on this machine")
    path = save_config(args.hospital_id, config, args.config_dir)
    say(f"server {config['server']} · ML_BACKEND={config['ml_backend']} · settings saved to {path}")
    if args.no_start:
        return

    runner = NodeRunner(args.hospital_id, config["server"], config["token"], data_dir)
    try:
        runner.run()
    except NodeStartupError as exc:
        sys.exit(f"{name} · not starting:\n{exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
