"""Patient-wise ECG beats from the PhysioNet MIT-BIH Arrhythmia Database (``mitdb``).

Records follow the inter-patient convention of de Chazal, O'Dwyer and Reilly
(2004): the four paced records (102, 104, 107, 217) are excluded and the other
44 are split into DS1 (training) and DS2 (held-out). Whole records, i.e. whole
patients, are assigned to hospitals, so no patient appears in two hospitals or
on both sides of a train / held-out split.

Beats are segmented at the database's reference R-peak annotations (no
detector), as in de Chazal et al., and shaped like the beats of the Kaggle
"ECG Heartbeat Categorization" export the platform already reads
(Kachuee et al., 2018): MLII lead resampled to 125 Hz, the signal split into
10 s windows, each beat taken from its R-peak for 1.2 x the median RR interval
of its window, min-max normalised to [0, 1], and zero-padded (or cut) to 187
samples.

Normalisation is per beat. Kachuee et al. describe normalising each 10 s
window, but the export itself has a maximum of exactly 1 in 99.8% of beats and
a minimum of exactly 0 (before padding) in 97%, i.e. each beat was scaled on
its own; matching the data the platform already reads takes precedence.

Annotation symbols are mapped to the AAMI classes N, S, V, F; class Q
(paced, fusion of paced, unclassifiable) is dropped, as for the Kaggle export.

For experiment 1f, ``record_beats_with_rr`` also gives each beat three
RR-interval inputs of the kind de Chazal et al. used, from the reference
annotations: pre-RR, post-RR and the local average RR over the 10 RR intervals
around the beat, each divided by the record's own average RR. Every annotated
beat (class Q included) counts as a beat for the intervals. The first beat of a
record has no pre-RR and takes its post-RR; the last beat takes its pre-RR as
post-RR. The beats themselves are exactly those of ``record_beats``.
"""

from __future__ import annotations

from math import gcd
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from ml.ecg.preprocess import ECG_BEAT_LENGTH

DS1 = (101, 106, 108, 109, 112, 114, 115, 116, 118, 119, 122, 124, 201, 203, 205, 207, 208, 209, 215, 220, 223, 230)
DS2 = (100, 103, 105, 111, 113, 117, 121, 123, 200, 202, 210, 212, 213, 214, 219, 221, 222, 228, 231, 232, 233, 234)
PACED = (102, 104, 107, 217)

TARGET_HZ = 125
WINDOW_SECONDS = 10
CLASS_INDEX = {"N": 0, "S": 1, "V": 2, "F": 3}
AAMI = {
    **{s: "N" for s in "NLRej"},
    **{s: "S" for s in "AaJS"},
    **{s: "V" for s in "VE"},
    "F": "F",
    **{s: "Q" for s in "/fQ"},
}


RR_FEATURES = ("pre_rr", "post_rr", "local_rr")


def rr_features(samples: np.ndarray) -> np.ndarray:
    """[n, 3] pre-RR, post-RR and local average RR (10 intervals around the beat), over the record's mean RR."""
    t = np.asarray(samples, dtype=np.float64)
    rr = np.diff(t)
    n = len(t)
    if n < 2:
        return np.ones((n, 3), dtype=np.float32)
    pre = np.concatenate([[rr[0]], rr])
    post = np.concatenate([rr, [rr[-1]]])
    # Beat i lies between intervals i-1 and i; the 10 intervals i-5 .. i+4 span beats i-5 .. i+5.
    cumulative = np.concatenate([[0.0], np.cumsum(rr)])
    lo = np.clip(np.arange(n) - 5, 0, len(rr))
    hi = np.clip(np.arange(n) + 5, 0, len(rr))
    local = (cumulative[hi] - cumulative[lo]) / np.maximum(hi - lo, 1)
    return (np.stack([pre, post, local], axis=1) / rr.mean()).astype(np.float32)


def record_beats(directory: Path, record: int) -> Tuple[np.ndarray, np.ndarray, dict]:
    """Beats of one record as ([n, 187] float32 in [0, 1], [n] labels), plus extraction statistics."""
    X, y, stats, _ = record_beats_with_rr(directory, record)
    return X, y, stats


def record_beats_with_rr(directory: Path, record: int) -> Tuple[np.ndarray, np.ndarray, dict, np.ndarray]:
    """``record_beats`` plus each kept beat's RR-interval inputs ([n, 3] float32, see ``rr_features``)."""
    import wfdb
    from scipy.signal import resample_poly

    path = str(Path(directory) / str(record))
    header = wfdb.rdheader(path)
    channel = header.sig_name.index("MLII")  # record 114 stores its leads in the other order
    signal = wfdb.rdrecord(path, channels=[channel]).p_signal[:, 0]
    annotation = wfdb.rdann(path, "atr")
    fs = int(header.fs)

    divisor = gcd(TARGET_HZ, fs)
    x = resample_poly(signal, TARGET_HZ // divisor, fs // divisor)
    is_beat = [sym in AAMI for sym in annotation.symbol]
    rr_all = rr_features(np.asarray(annotation.sample)[is_beat])
    beats = [
        (int(round(s * TARGET_HZ / fs)), sym, index)
        for index, (s, sym) in enumerate((s, sym) for s, sym, b in zip(annotation.sample, annotation.symbol, is_beat) if b)
    ]

    window = WINDOW_SECONDS * TARGET_HZ
    X, y, lengths, rr_kept = [], [], [], []
    skipped = {"Q": 0, "edge": 0}
    for start in range(0, len(x), window):
        segment = x[start : start + window]
        if len(segment) < window // 2:
            break
        in_window = [(r, sym, i) for r, sym, i in beats if start <= r < start + window]
        peaks = np.array([r for r, _, _ in in_window])
        if len(peaks) < 2:
            skipped["edge"] += len(in_window)
            continue
        length = min(ECG_BEAT_LENGTH, int(round(1.2 * float(np.median(np.diff(peaks))))))
        for r, sym, index in in_window:
            label = AAMI[sym]
            if label == "Q":
                skipped["Q"] += 1
                continue
            if r + length > len(x):
                skipped["edge"] += 1
                continue
            part = x[r : r + length]
            low, high = float(part.min()), float(part.max())
            if high - low <= 0:
                skipped["edge"] += 1
                continue
            beat = np.zeros(ECG_BEAT_LENGTH, dtype=np.float32)
            beat[:length] = (part - low) / (high - low)
            X.append(beat)
            y.append(CLASS_INDEX[label])
            lengths.append(length)
            rr_kept.append(rr_all[index])
    stats = {"record": record, "beats": len(y), "skipped_q": skipped["Q"], "skipped_edge": skipped["edge"],
             "median_length": float(np.median(lengths)) if lengths else 0.0}
    rr = np.asarray(rr_kept, dtype=np.float32).reshape(-1, len(RR_FEATURES))
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.int64), stats, rr


def load_rr(directory: Path, cache: Path) -> Dict[int, np.ndarray]:
    """RR-interval inputs of every DS1 and DS2 record, aligned with ``load_all``'s beats, cached as one .npz."""
    cache = Path(cache)
    if cache.exists():
        with np.load(cache) as archive:
            return {int(k[3:]): archive[k] for k in archive.files}
    out = {record: record_beats_with_rr(directory, record)[3] for record in DS1 + DS2}
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **{f"rr_{record}": rr for record, rr in out.items()})
    return out


def load_all(directory: Path, cache: Path) -> Dict[int, Tuple[np.ndarray, np.ndarray]]:
    """Beats of every DS1 and DS2 record, cached as one .npz."""
    cache = Path(cache)
    if cache.exists():
        with np.load(cache) as archive:
            return {int(k[2:]): (archive[k], archive["y_" + k[2:]]) for k in archive.files if k.startswith("X_")}
    out, arrays = {}, {}
    for record in DS1 + DS2:
        X, y, _ = record_beats(directory, record)
        out[record] = (X, y)
        arrays[f"X_{record}"], arrays[f"y_{record}"] = X, y
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **arrays)
    return out


def assign_records(seed: int, hospitals: List[str]) -> Dict[str, Dict[str, List[int]]]:
    """Deal DS1 (training) and DS2 (held-out) records to hospitals: whole patients, 5 or 6 each."""
    rng = np.random.default_rng(seed)
    assignment = {h: {"ds1": [], "ds2": []} for h in hospitals}
    for key, records in (("ds1", DS1), ("ds2", DS2)):
        for i, record in enumerate(rng.permutation(records)):
            assignment[hospitals[i % len(hospitals)]][key].append(int(record))
    for h in hospitals:
        assignment[h]["ds1"].sort()
        assignment[h]["ds2"].sort()
    return assignment
