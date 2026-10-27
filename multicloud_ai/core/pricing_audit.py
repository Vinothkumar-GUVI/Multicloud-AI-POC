"""Check AI pricing evidence without treating arithmetic validity as price validation."""
import json
import math
import re


def unit_key(value):
    value = re.sub(r"\s+", "", str(value).lower()).replace("/", "-")
    return {"hours": "hour", "hrs": "hour", "hr": "hour", "instance-hours": "hour",
            "instance-hour": "hour", "gb-months": "gb-month"}.get(value, value)


def audit_comparison(result, contracts):
    issues = []
    source = result["source"]
    for row in result["rows"]:
        contract = contracts.get(row["Resource ID"], {})
        meters = contract.get("meters", [])
        for cloud in result["totals"]:
            if cloud == source:
                continue
            reasons = []
            if json.loads(row.get(cloud + " Excluded Components", "[]")):
                reasons.append("Unsupported components excluded from subtotal; target workload coverage is incomplete")
            if row.get(cloud + " Runtime Review"):
                reasons.append(row[cloud + " Runtime Review"])
            parts = json.loads(row.get(cloud + " Calculation", "[]"))
            if "planning allowance" in row.get(cloud + " Service", "").lower():
                reasons.append("Source-cost allowance; target service and rate remain unverified")
            covered = set()
            for part in parts:
                if contract.get("private_zone_only") and part.get("fixed_zone_fee"):
                    covered.update(range(len(meters)))
                    continue
                if part.get("usage_review"):
                    reasons.append(part["usage_review"])
                for field in part.get("missing_metadata", []):
                    reasons.append("AI omitted component " + field)
                if unit_key(part.get("rate_unit")) != unit_key(part.get("unit")):
                    reasons.append("Quantity unit and explicit rate unit must match")
                index = part.get("meter_index")
                if type(index) is not int or not 0 <= index < len(meters):
                    reasons.append("Component has no valid source-meter reference")
                    continue
                covered.add(index)
                meter = meters[index]
                if unit_key(part["unit"]) != unit_key(meter["unit"]):
                    reasons.append("Source-to-target unit conversion is not validated")
                elif not math.isclose(part["quantity"], meter["quantity"], rel_tol=1e-6, abs_tol=1e-9):
                    reasons.append("Target quantity differs from projected source-meter quantity")
                if re.match(r"^\d", str(meter.get("raw_unit") or meter.get("unit") or "")):
                    reasons.append("Packed source meter requires confirmed export-unit semantics")
                # A URL or AI assertion is not independent verification of a rate.
                if not part.get("rate_source"):
                    reasons.append("Target rate source is missing")
            missing = sorted(set(range(len(meters))) - covered)
            if missing:
                reasons.append("Source meters omitted from target estimate: " + ", ".join(map(str, missing)))
            if contract.get("resource_type") in {"compute_instance", "block_storage", "relational_database"}:
                reasons.append("Proposed service only: target CPU/RAM, engine, GPU or storage performance equivalence is not validated")
                row[cloud + " Equivalence Status"] = "Proposed mapping ? capacity/performance review required"
            if contract.get("resource_type") == "generative_ai":
                if not row.get(cloud + " Model") or not row.get(cloud + " Inference Mode"):
                    reasons.append("Specific target model and inference mode are required")
            if contract.get("resource_type") == "nosql_database":
                reasons.append("Database API and request-unit equivalence require workload validation")
            reasons = list(dict.fromkeys(reasons))
            row[cloud + " Pricing Review"] = "; ".join(reasons) or "AI rate and service mapping require independent verification"
            issues.extend({"resource_id": row["Resource ID"], "cloud": cloud, "reason": reason} for reason in reasons)
    for row in result["rows"]:
        row["Lowest Estimated Cost Cloud"] = row.pop("Recommended Cloud", "")
    result["pricing_issues"] = issues
    result["recommendation_ready"] = True
    result["recommendation_status"] = (
        "Recommendation uses estimated component subtotals across the current and target clouds; incomplete coverage can affect the ranking. "
        "Rates and service equivalence remain assumptions; review details in the pricing download."
    )
    return result
