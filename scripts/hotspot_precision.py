"""Hotspot precision from the outcomes health officers recorded on alerts, as a section for RESULTS.md.

    python scripts/hotspot_precision.py
    python scripts/run_experiment.py --report

Reads the API's database (backend/.env) and writes experiments/results/hotspot_precision/section.md, which
the RESULTS.md builder includes. Outcomes on alerts raised from simulated data are reported separately and
labelled as demo outcomes: they were entered during a demo, not established by investigation, so they test
the workflow and the calculation, not the detector.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from app.config import load_settings  # noqa: E402
from app.services.context import build_context  # noqa: E402

OUT = ROOT / "experiments" / "results" / "hotspot_precision"


def fmt(value) -> str:
    return "-" if value is None else f"{value:.2f}"


def section(result: dict) -> str:
    lines = [
        "### Hotspot precision from recorded alert outcomes",
        "",
        "An alert opens when a region becomes a potential hotspot; a health officer acknowledges it and records "
        "whether the rise was confirmed, not confirmed, or a reporting artefact. Precision = confirmed / all "
        "recorded outcomes; the second figure leaves reporting artefacts out (confirmed / (confirmed + not "
        "confirmed)). Alerts without a recorded outcome are not counted.",
        "",
        "| Alerts from | Alerts raised | Outcomes recorded | Confirmed | Not confirmed | Reporting artefact | Precision | Precision without artefacts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, label in (("demo", "**Simulated data (DEMO OUTCOMES)**"), ("real", "Real data")):
        r = result[key]
        lines.append(
            f"| {label} | {result['raised'][key]} | {r['outcomes']} | {r['confirmed']} | {r['not_confirmed']} | "
            f"{r['reporting_artefact']} | {fmt(r['precision'])} | {fmt(r['precision_excluding_artefacts'])} |"
        )
    lines += [
        "",
        "**The simulated-data row uses demo outcomes.** They were entered by hand during a demo walk-through of the "
        "alert workflow, not found by investigating anything, and the rises they refer to were injected by the "
        "simulator. The figures check that outcomes are recorded and counted correctly; they say nothing about "
        "how often the detector is right. Precision on real data needs real alerts with outcomes established by "
        "health officers.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ctx = build_context(load_settings())
    try:
        result = ctx.alerts.precision()
        rows = ctx.db.fetch_all("SELECT is_simulated, COUNT(*) AS n FROM alerts GROUP BY is_simulated")
        result["raised"] = {"demo": 0, "real": 0}
        for row in rows:
            result["raised"]["demo" if row["is_simulated"] else "real"] = int(row["n"])
    finally:
        ctx.close()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "precision.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUT / "section.md").write_text(section(result), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Wrote {OUT / 'section.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
