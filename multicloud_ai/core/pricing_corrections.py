"""Deterministic corrections to unsupported AI pricing inputs."""
import json
import math
from copy import deepcopy

# AWS published standard public IPv4 list rate; no credits or BYOIP assumed.
AWS_IPV4_RATE = .005
AWS_IPV4_SOURCE = "https://aws.amazon.com/vpc/pricing/"
AWS_IPV4_CHECKED = "2026-10-02"


def correct_comparison(result, contracts):
    result = deepcopy(result)
    source = result["source"]
    allowances = 0
    for row in result["rows"]:
        contract = contracts.get(row["Resource ID"], {})
        meters = contract.get("meters", [])
        if not any(m.get("name") for m in meters):
            continue
        kind = contract.get("resource_type")
        for cloud in result["totals"]:
            if cloud == source:
                continue
            if contract.get("private_zone_only"):
                row[cloud + " Estimate Basis"] = "Published private-zone base fee; query scope disclosed in assumptions"
                continue
            if contract.get("published_token_rates"):
                row[cloud + " Estimate Basis"] = "Published model token rates; proposed model and source-unit interpretation"
                continue
            reason = ""
            parts = None
            if cloud == "AWS" and kind == "public_ip" and meters and all(
                "ipv4" in str(m.get("name", "")).lower() and str(m.get("unit", "")).lower() == "hours"
                and isinstance(m.get("quantity"), (int, float)) and math.isfinite(m["quantity"]) and m["quantity"] >= 0
                for m in meters
            ):
                parts = [{"quantity": m["quantity"], "unit": "Hours", "rate_unit": "Hours",
                          "unit_price_usd": AWS_IPV4_RATE, "description": "Standard AWS public IPv4 address",
                          "meter_index": i, "rate_basis": "Published list rate; excludes credits and special address arrangements",
                          "rate_source": AWS_IPV4_SOURCE, "rate_checked": AWS_IPV4_CHECKED}
                         for i, m in enumerate(meters)]
                service = "AWS public IPv4 address"
                assumptions = "Same billed/projected address-hours; USD 0.005 per address-hour. No credits assumed."
                status = "Published rate applied to source address-hours"
            else:
                # Preserve the proposed target and its exploratory cost. A source-cost
                # copy is not an independently estimated target price.
                is_allowance = "planning allowance" in row.get(cloud + " Service", "").lower()
                row[cloud + " Estimate Basis"] = (
                    "Source-cost planning allowance" if is_allowance else "AI estimate ? requires review"
                )
                if is_allowance:
                    allowances += 1
                continue
            row[cloud + " Original AI Calculation"] = row.get(cloud + " Calculation", "")
            row[cloud + " Original AI Service"] = row.get(cloud + " Service", "")
            row[cloud + " Original AI Cost"] = row[cloud + " Cost"]
            row[cloud + " Calculation"] = json.dumps(parts)
            row[cloud + " Cost"] = sum(p["quantity"] * p["unit_price_usd"] for p in parts)
            row[cloud + " Service"] = service
            row[cloud + " Assumptions"] = assumptions
            row[cloud + " Pricing Review"] = assumptions
            row[cloud + " Estimate Basis"] = status
        values = {c: row[c + " Cost"] for c in result["totals"]}
        winner = min(values, key=lambda c: (round(values[c], 8), c != source))
        row.update({"Lowest Cost": values[winner], "Lowest Estimated Cost Cloud": winner,
                    "Estimated Savings": values[source] - values[winner]})
    result["totals"] = {c: sum(r[c + " Cost"] for r in result["rows"]) for c in result["totals"]}
    winner = min(result["totals"], key=lambda c: (round(result["totals"][c], 8), c != source))
    result.update(recommended=winner, savings=result["totals"][source]-result["totals"][winner], allowance_entries=allowances)
    if allowances:
        result["recommendation_status"] += f" {allowances} target entries use source-cost planning allowances; those entries assume no savings and do not establish provider equivalence."
    return result
