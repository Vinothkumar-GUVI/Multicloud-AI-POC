"""Credential-free billing scenario model, matching the supplied V1 methodology."""
import math
from collections import OrderedDict

CLOUDS = ("Azure", "AWS", "GCP")
DEFAULT_FACTORS = {"Azure": 1.0, "AWS": .92, "GCP": .90}


def compare_model(billing, source, factors, days=None):
    if source not in CLOUDS:
        raise ValueError("Unknown source cloud")
    targets = [c for c in CLOUDS if c != source]
    for target in targets:
        if not math.isfinite(float(factors[target])) or float(factors[target]) <= 0:
            raise ValueError("Model factors must be positive and finite")
    scale = 1.0
    if days is not None:
        if not math.isfinite(float(days)) or float(days) <= 0:
            raise ValueError("Billing period must have a positive duration")
        scale = (730 / 24) / float(days)
    grouped = OrderedDict()
    for r in billing:
        if str(r.currency).upper() != "USD":
            raise ValueError("Normalize billing to USD before comparison")
        cost = float(r.cost)
        if not math.isfinite(cost):
            raise ValueError("Invalid billing cost")
        rid = str(r.resource_id).strip().rstrip("/").lower()
        if not rid:
            raise ValueError("Resource ID required for billing aggregation")
        entry = grouped.setdefault(rid, {"Resource": r.name, "Resource ID": rid, "Type": r.canonical_type, "cost": 0.0})
        entry["cost"] += cost
    rows = []
    totals = {cloud: 0.0 for cloud in [source] + targets}
    for entry in grouped.values():
        current = entry.pop("cost") * scale
        values = {source: current, **{t: current * float(factors[t]) for t in targets}}
        winner = min(values, key=lambda c: (round(values[c], 8), c != source))
        rows.append({**entry, **{c + " Cost": v for c, v in values.items()}, "Lowest Cost": values[winner],
                     "Recommended Cloud": winner, "Estimated Savings": current - values[winner]})
        for c, value in values.items():
            totals[c] += value
    winner = min(totals, key=lambda c: (round(totals[c], 8), c != source))
    if not rows or totals[source] <= 0:
        winner = source
    return {"rows": rows, "totals": totals, "recommended": winner, "source": source,
            "savings": totals[source] - totals[winner], "monthly": days is not None,
            "factors": {source: 1.0, **{t: float(factors[t]) for t in targets}}}
