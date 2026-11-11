"""Start the agent: the window by default, or headless with --server / --token / --data.

    medifed-agent                                   # the window
    medifed-agent --server https://... --token <token> --data <folder>
    medifed-agent --server https://... --token <token> --sample-data   # SIMULATED records
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="medifed-agent", description="MediFed Hospital Agent")
    parser.add_argument("--server", help="The MediFed API address, e.g. https://medifed.example")
    parser.add_argument("--token", help="Your hospital's node token (or set MEDIFED_NODE_TOKEN)")
    parser.add_argument("--data", type=Path, help="Your prepared data folder")
    parser.add_argument("--sample-data", action="store_true", help="Use SIMULATED sample records instead of --data")
    parser.add_argument("--hospital-id", help="Only for the built-in demo hospitals hospital_a-d")
    parser.add_argument("--no-take-part", action="store_true", help="Connect but decline every round")
    parser.add_argument("--check-only", action="store_true", help="Run the local data check and exit")
    return parser


def run_headless(args) -> int:
    from .session import AgentError, AgentSession
    from .settings import save_settings, save_token

    token = args.token or os.getenv("MEDIFED_NODE_TOKEN", "")
    session = AgentSession(log=lambda line: print(line, flush=True))
    try:
        profile = session.identify(args.server, token, args.hospital_id)
    except AgentError as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2
    print(f"Hospital: {profile['name']} ({profile['hospital_id']})", flush=True)
    where = save_token(args.server.rstrip("/"), token)
    print(f"Token kept in {where}.", flush=True)
    if args.sample_data:
        folder = session.make_sample_data()
        print(f"Using SIMULATED sample data (fictional records) in {folder}", flush=True)
    elif args.data:
        folder = args.data.resolve()
    else:
        print("Give --data <folder> or --sample-data.", file=sys.stderr)
        return 2
    save_settings({"server": args.server.rstrip("/"), "hospital_id": profile["hospital_id"],
                   "hospital_name": profile["name"], "data_dir": str(folder), "take_part": not args.no_take_part})
    try:
        results = session.check_data(folder)
    except AgentError as exc:
        print(f"Cannot check the data: {exc}", file=sys.stderr)
        return 2
    for modality, result in results.items():
        verdict = "passed" if result["passed"] else "FAILED"
        print(f"Data check {modality.upper()}: {verdict} ({result['train_records']} train / {result['val_records']} held-out)")
        for problem in result["problems"]:
            print(f"  - {problem}")
    if args.check_only:
        return 0 if all(r["passed"] for r in results.values()) else 1
    session.set_take_part(not args.no_take_part)
    ended = {}
    session.connect(args.server, token, folder, on_end=lambda error: ended.setdefault("error", error))
    try:
        while "error" not in ended:
            time.sleep(0.5)
    except KeyboardInterrupt:
        session.disconnect()
        time.sleep(1)
        return 0
    if ended["error"]:
        print(f"Stopped: {ended['error']}", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    if args.server or args.token or args.data or args.sample_data or args.check_only:
        if not args.server:
            print("--server is required in headless mode.", file=sys.stderr)
            return 2
        return run_headless(args)
    from .defaults import DEFAULT_SERVER
    from .gui import run_window

    run_window(DEFAULT_SERVER)
    return 0
