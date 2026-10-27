"""Billing usage normalization helpers.

Important rule: provider billing exports often include a *pricing unit label* such as
``100 Hours`` or ``1000 Hours`` while the exported ``UsageQuantity`` is already the
consumed base quantity used in the charge calculation.  We therefore normalize the
semantic unit but never multiply elapsed-time quantities by the numeric prefix.
"""
from __future__ import annotations

import math
import re
from typing import Tuple


def _finite_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_usage(quantity, unit) -> Tuple[float, str]:
    """Normalize safe usage dimensions without inferring usage from cost.

    The numeric prefix in Azure EA/Cost exports is treated as meter metadata, not a
    multiplier for ``UsageQuantity``.  For example, an exported quantity of ``24``
    with ``UnitOfMeasure=1000 Hours`` represents 24 consumed hours in the supplied
    export; multiplying it by 1000 would create impossible daily runtimes.

    Storage pricing-unit labels are intentionally preserved because labels such as
    ``100 GB/Month`` and ``1 TB/Month`` are meter-specific and cannot safely be
    converted into target-cloud stored capacity without live capacity evidence.
    """
    number = _finite_number(quantity)
    if number is None:
        return quantity, unit

    original = str(unit or "").strip()
    compact = re.sub(r"\s+", " ", original.lower()).strip()

    # Optional numeric pricing-unit prefix, e.g. "100 Hours", "1000 Hours".
    time_match = re.fullmatch(
        r"(?:\d+(?:\.\d+)?\s*)?(hours?|hrs?|hr|h|minutes?|mins?|min|seconds?|secs?|sec|s)",
        compact,
    )
    if time_match:
        suffix = time_match.group(1)
        if suffix in {"hour", "hours", "hr", "hrs", "h"}:
            return number, "Hours"
        if suffix in {"minute", "minutes", "min", "mins"}:
            return number / 60.0, "Hours"
        return number / 3600.0, "Hours"

    # Explicit single-unit runtime labels such as "1 Hour" are covered above.
    # Do not normalize GB/TB pricing-unit labels here; live/configured capacity is
    # the authoritative input for cross-cloud storage pricing.
    return number, original
