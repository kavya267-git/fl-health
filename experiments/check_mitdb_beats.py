"""Compare PhysioNet beats extracted by experiments/mitdb.py with the Kaggle MIT-BIH export.

    python -m experiments.check_mitdb_beats

Writes experiments/results/mitdb_beat_check/{check.json, beats.png}: per-class counts, the
length of the non-padded part of each beat, how beats are normalised, and four random
beats per class from each source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments import mitdb  # noqa: E402
from experiments.harness import WORK_DIR, load_mitbih  # noqa: E402

OUT = ROOT / "experiments" / "results" / "mitdb_beat_check"
NAMES = "NSVF"


def describe(X: np.ndarray, y: np.ndarray) -> dict:
    length = np.array([np.max(np.where(row != 0)[0]) + 1 if (row != 0).any() else 0 for row in X])
    beat_min = np.array([X[i, : max(length[i], 1)].min() for i in range(len(X))])
    out = {}
    for k, c in enumerate(NAMES):
        m = y == k
        out[c] = {
            "count": int(m.sum()),
            "length_median": float(np.median(length[m])),
            "length_p10": float(np.percentile(length[m], 10)),
            "length_p90": float(np.percentile(length[m], 90)),
            "share_max_is_1": float(np.mean(np.isclose(X[m].max(1), 1.0))),
            "share_min_is_0": float(np.mean(np.isclose(beat_min[m], 0.0))),
            "share_peak_at_sample_0": float(np.mean(X[m].argmax(1) == 0)),
        }
    return out


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory = ROOT / "data" / "raw" / "mitdb"
    stats = [mitdb.record_beats(directory, r)[2] for r in mitdb.DS1 + mitdb.DS2]
    beats = mitdb.load_all(directory, WORK_DIR / "mitdb-beats.npz")
    records = mitdb.DS1 + mitdb.DS2
    Xm = np.concatenate([beats[r][0] for r in records])
    ym = np.concatenate([beats[r][1] for r in records])
    Xk, yk = load_mitbih([ROOT / "data/raw/mitbih/mitbih_train.csv", ROOT / "data/raw/mitbih/mitbih_test.csv"])

    result = {
        "physionet": describe(Xm, ym),
        "kaggle": describe(Xk, yk),
        "ds_counts": {
            name: {c: int(sum((beats[r][1] == i).sum() for r in recs)) for i, c in enumerate(NAMES)}
            for name, recs in (("DS1", mitdb.DS1), ("DS2", mitdb.DS2))
        },
        "skipped_q": int(sum(s["skipped_q"] for s in stats)),
        "skipped_other": int(sum(s["skipped_edge"] for s in stats)),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "check.json").write_text(json.dumps(result, indent=2))

    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(2, 4, figsize=(13, 5), sharex=True, sharey=True)
    t_ms = np.arange(187) * 8
    for row, (label, X, y) in enumerate((("Kaggle export", Xk, yk), ("PhysioNet, this extraction", Xm, ym))):
        for k, c in enumerate(NAMES):
            ax = axes[row][k]
            for i in rng.choice(np.where(y == k)[0], 4, replace=False):
                ax.plot(t_ms, X[i], linewidth=0.9)
            ax.set_title(f"{label}: {c}", fontsize=9)
            ax.grid(alpha=0.3)
            if row == 1:
                ax.set_xlabel("ms from R-peak (125 Hz)")
        axes[row][0].set_ylabel("normalised amplitude")
    fig.tight_layout()
    fig.savefig(OUT / "beats.png", dpi=120)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
