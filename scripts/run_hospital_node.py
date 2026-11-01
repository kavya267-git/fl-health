#!/usr/bin/env python3
"""Run one hospital node as its own process, talking to the coordinator over HTTP.

Start the API with HOSPITAL_NODES=external, then run one of these per hospital
(on the same machine or another one). The node checks that it matches the
coordinator, sends a heartbeat every ~10 s, waits for rounds it is invited to,
trains on its local data, uploads the update and later evaluates the
aggregated model. Only weights, counts and summary metrics are sent.

    python scripts/run_hospital_node.py --hospital hospital_a \\
        --server http://localhost:8000 --token <token from scripts/node_token.py>

On a hospital machine, scripts/setup_hospital.py prepares the data, remembers
the server and token, and then runs this same node.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.training.node_runner import NodeRunner, NodeStartupError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hospital", required=True, help="Hospital id, e.g. hospital_a")
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="Node token (see scripts/node_token.py)")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "hospitals")
    parser.add_argument("--round", default=None, help="Take part in this round only, then exit")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    args = parser.parse_args()

    runner = NodeRunner(args.hospital, args.server, args.token, args.data_root / args.hospital, args.poll_seconds)
    try:
        runner.run(only_round=args.round)
    except NodeStartupError as exc:
        sys.exit(f"[{args.hospital}] not starting:\n{exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
