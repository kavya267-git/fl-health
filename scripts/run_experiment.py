#!/usr/bin/env python3
"""Run reproducible federated-learning experiments and write the report.

    python scripts/run_experiment.py experiments/configs/sim_ecg_baselines.yaml
    python scripts/run_experiment.py experiments/configs/*.yaml        # several, in order
    python scripts/run_experiment.py --report                          # only rebuild RESULTS.md

Results go to experiments/results/<name>/ (rounds.csv, partitions.csv,
config.json, figures). A run that is interrupted resumes where it stopped:
finished (variant, seed, method) combinations are skipped. Use --fresh to
start an experiment again from scratch.

After running, experiments/RESULTS.md is rebuilt from every experiment listed
in experiments/configs/ORDER (or all results, alphabetically).
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.harness import RESULTS_DIR, load_config, run_experiment, time_methods  # noqa: E402

RESULTS_MD = ROOT / "experiments" / "RESULTS.md"
HEADER = ROOT / "experiments" / "results_header.md"
DISCUSSION = ROOT / "experiments" / "discussion.md"
KNOWN_ISSUES = ROOT / "experiments" / "known_issues.md"
ORDER = ROOT / "experiments" / "configs" / "ORDER"


def not_run_section(name: str) -> str:
    """Title and description of an experiment whose config is fixed but which has not run."""
    path = ROOT / "experiments" / "configs" / f"{name}.yaml"
    if not path.exists():
        return f"### {name}\n\nNot run yet.\n"
    config = load_config(path)
    return (
        f"### {config.get('title', name)}\n\n{config.get('description', '').strip()}\n\n"
        f"*Config:* `experiments/configs/{path.name}`, fixed before any run. **Not run yet.**\n"
    )


def build_results_md() -> None:
    from experiments.report import section, timing_section

    if ORDER.exists():
        lines = ORDER.read_text(encoding="utf-8").splitlines()
        names = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    else:
        names = sorted(p.name for p in RESULTS_DIR.iterdir() if (p / "rounds.csv").exists())
    parts = [HEADER.read_text(encoding="utf-8")] if HEADER.exists() else ["# Experiment results\n"]
    timing = timing_section()
    if timing:
        parts.append(timing)
    for name in names:
        if name.startswith(">"):  # a line of markdown, e.g. a part heading
            parts.append(name[1:].strip() + "\n")
        elif (RESULTS_DIR / name / "rounds.csv").exists():
            parts.append(section(name))
        else:
            parts.append(not_run_section(name))
    if KNOWN_ISSUES.exists():
        parts.append(KNOWN_ISSUES.read_text(encoding="utf-8"))
    if DISCUSSION.exists():
        parts.append(DISCUSSION.read_text(encoding="utf-8"))
    RESULTS_MD.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {RESULTS_MD}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("configs", nargs="*", type=Path, help="YAML or JSON experiment configs")
    parser.add_argument("--fresh", action="store_true", help="Discard earlier results of these experiments")
    parser.add_argument("--report", action="store_true", help="Only rebuild experiments/RESULTS.md")
    parser.add_argument(
        "--time",
        action="store_true",
        help="Instead of the experiments, time a few rounds of each method in this process alone "
        "(writes experiments/results/timing.csv). Run it with nothing else using the CPU.",
    )
    args = parser.parse_args()

    if args.time:
        import csv

        rows = []
        for path in args.configs:
            config = load_config(path)
            config["config_file"] = path.name
            rows += time_methods(config)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with (RESULTS_DIR / "timing.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    elif not args.report:
        if not args.configs:
            parser.error("give at least one config, or --report")
        for path in args.configs:
            config = load_config(path)
            config["config_file"] = path.name
            if args.fresh:
                shutil.rmtree(RESULTS_DIR / config["name"], ignore_errors=True)
            out = run_experiment(config, resume=not args.fresh)
            print(f"Results in {out}")
    build_results_md()


if __name__ == "__main__":
    main()
