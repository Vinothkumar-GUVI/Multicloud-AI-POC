"""Include all target estimates and disclose unresolved component assumptions."""
import json
import math
import re
from copy import deepcopy


def enforce_scope(model, contracts):
    model = deepcopy(model)
    clouds = list(model["totals"])
    source = model["source"]
    review_resources = set()
    for row in model["rows"]:
        for cloud in clouds:
            if cloud == source:
                continue
            parts = json.loads(row.get(cloud + " Calculation", "[]"))
            parts += json.loads(row.get(cloud + " Excluded Components", "[]"))
            reasons = []
            for part in parts:
                raw = str(part.get("usage_conversion", {}).get("source_unit", ""))
                if re.match(r"^\d+\s*(?:gb|tb)[/-]month", raw, re.I):
                    part.setdefault("usage_review", "Packed source storage unit semantics require review")
                if part.get("usage_review"):
                    reasons.append(part["usage_review"])
            if parts:
                cost = sum(p["quantity"] * p["unit_price_usd"] for p in parts)
                if not math.isfinite(cost) or cost < 0:
                    raise ValueError("Target component estimate must be finite and nonnegative")
                row[cloud + " Cost"] = cost
                row[cloud + " Calculation"] = json.dumps(parts)
                row[cloud + " Excluded Components"] = "[]"
                row[cloud + " Component Subtotal"] = cost
            if reasons:
                review_resources.add(row["Resource ID"])
                row[cloud + " Estimate Basis"] = "AI target component estimate - usage assumptions require review"
                row[cloud + " Pricing Review"] = "; ".join(dict.fromkeys([row.get(cloud + " Pricing Review", "")] + reasons)).strip("; ")
        values = {c: row[c + " Cost"] for c in clouds}
        winner = min(clouds, key=lambda c: (round(values[c], 8), c != source))
        row.update({"Lowest Cost": values[winner], "Lowest Estimated Cost Cloud": winner,
                    "Recommended Cloud": winner, "Estimated Savings": values[source] - values[winner]})
        if row["Resource ID"] in review_resources:
            row["Recommended Cloud"] = "Pending usage validation"
    model["totals"] = {c: sum(r[c + " Cost"] for r in model["rows"]) for c in clouds}
    model["observed_source_total"] = model["totals"][source]
    model["comparable_resources"] = len(model["rows"])
    model["excluded_resources"] = 0
    model["allowance_resources"] = 0
    model["review_resources"] = len(review_resources)
    winner = min(clouds, key=lambda c: (round(model["totals"][c], 8), c != source))
    model.update(recommended=winner, savings=model["totals"][source]-model["totals"][winner], recommendation_ready=bool(model["rows"]) and not review_resources)
    model["recommendation_status"] = (f"Estimated comparison includes all {len(model['rows'])} resources using target component estimates. "
        f"{len(review_resources)} resources have usage assumptions requiring review. "
        "Rates and service equivalence require validation; uncertain estimates can affect the ranking.")
    return model
