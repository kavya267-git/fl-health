"""Small-cell suppression for aggregated counts.

A hospital never reports a count between 1 and ``threshold - 1`` for a
region/disease/week cell: such small numbers can single out individuals. The
cell is reported as suppressed instead, and downstream analytics treat the
regional total for that week as incomplete.
"""

from __future__ import annotations

from typing import Optional, Tuple

DEFAULT_SUPPRESSION_THRESHOLD = 5


def suppress_small_count(count: int, threshold: int = DEFAULT_SUPPRESSION_THRESHOLD) -> Tuple[Optional[int], bool]:
    """Return ``(reported_count, suppressed)``. Zero is reported as zero."""
    if count < 0:
        raise ValueError("Counts cannot be negative")
    if 0 < count < threshold:
        return None, True
    return int(count), False


def violates_threshold(count: Optional[int], threshold: int = DEFAULT_SUPPRESSION_THRESHOLD) -> bool:
    return count is not None and 0 < count < threshold
