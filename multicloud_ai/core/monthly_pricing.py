"""730-hour list-price capacity scenarios, independent of observed billing duration."""
from copy import deepcopy
import math
import re
from .pricing import PriceResult, price_resource, _aggregate_billing
from .recommendations import recommend_aws

HOURS = 730.0


def monthly_resource(resource):
    r = deepcopy(resource)
    r.configuration = {k:v for k,v in (r.configuration or {}).items()
                       if not k.startswith("billing_") and k != "pricing_usage_basis"}
    r.usage_quantity, r.usage_unit = 0.0, ""
    if r.canonical_type in {"compute_instance", "relational_database", "postgresql", "public_ip", "cache", "container_service"}:
        r.usage_quantity, r.usage_unit = HOURS, "Hours"
    r.cost = 0.0
    return r


def azure_monthly(resource, components, provider):
    kind = resource.canonical_type
    cfg = resource.configuration or {}
    candidates = []
    for c in components:
        meter = c["meter"]
        name = str(meter.get("name", "")).lower()
        category = str(meter.get("category", "")).lower()
        sub = str(meter.get("subcategory", "")).lower()
        basis = None
        quantity = None
        if kind == "compute_instance" and category == "virtual machines":
            quantity, basis = HOURS, "730 instance-hours"
        elif kind == "container_registry" and category == "container registry" and name in {"basic registry unit", "standard registry unit", "premium registry unit"}:
            quantity, basis = HOURS / 24, "Current registry tier for 730 hours; excess storage, requests and transfer excluded"
        elif kind == "public_ip" and "public ip" in name:
            quantity, basis = HOURS, "730 address-hours"
        elif kind == "relational_database" and "compute" in sub:
            quantity, basis = HOURS, "730 database compute-hours; storage and I/O excluded"
        elif kind == "app_service" and category == "azure app service":
            quantity, basis = HOURS, "730 hours on source app tier; shared plan not duplicated"
        elif kind == "search" and "unit" in name:
            # Paid replica/partition counts require discovery, not an assumed single unit.
            if "free" in name:
                quantity, basis = HOURS, "Source Free Unit tier; not evidence that AWS is free"
        elif kind == "block_storage" and re.fullmatch(r"[pe]\d+ lrs disk", name):
            quantity, basis = 1.0, "One current disk tier for one month; transactions excluded"
        elif kind == "object_storage" and "block blob" in sub and "data stored" in name and "measured_storage_bytes" in cfg:
            if "hot" in name:
                quantity = float(cfg["measured_storage_bytes"]) / (1024 ** 3)
                basis = "Current measured blob GiB held for one month; requests, transfer and Files/Tables excluded"
        if quantity is None or not math.isfinite(quantity) or quantity < 0 or not meter.get("id"):
            continue
        meter_id = meter["id"]
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", meter_id):
            continue
        items, error = provider._query(f"meterId eq '{meter_id}' and priceType eq 'Consumption'")
        valid = [i for i in items if i.get("meterId", "").lower() == meter_id.lower()
                 and i.get("currencyCode") == "USD" and i.get("type") == "Consumption"
                 and i.get("armRegionName", "").lower() == str(resource.region).lower().replace(" ", "")]
        # Reject tiered/ambiguous meters instead of selecting a cheaper tier.
        if any(float(i.get("tierMinimumUnits", 0) or 0) != 0 for i in valid):
            continue
        matches = []
        for item in valid:
            unit = str(item.get("unitOfMeasure", "")).lower().replace(" ", "")
            expected = {"1/month", "1month"} if kind == "block_storage" else {"1gb/month", "1gbmonth"} if kind == "object_storage" else {"1hour", "1hours"}
            pack = 1.0
            if kind == "container_registry":
                daily = re.fullmatch(r"(\d+(?:\.\d+)?)/?days?", unit)
                if not daily or float(daily.group(1)) <= 0:
                    continue
                pack = float(daily.group(1))
            elif unit not in expected:
                continue
            rate = float(item.get("retailPrice", -1)) / pack
            if math.isfinite(rate) and rate >= 0:
                matches.append((rate, str(item.get("effectiveStartDate", ""))))
        if matches:
            latest = max(date for _,date in matches)
            rates = {rate for rate,date in matches if date == latest}
            if len(rates) == 1:
                candidates.append((next(iter(rates))*quantity, basis, meter["name"]))
        elif error:
            return PriceResult(None, reason=error)
    unique = set(candidates)
    if len(unique) == 1:
        cost, basis, sku = next(iter(unique))
        return PriceResult(cost, sku=sku, reason=basis, coverage="Capacity component", source="Azure Retail Prices API (USD public list rate)")
    return PriceResult(None, reason="Current monthly list-price capacity needs a unique catalog meter and provisioned quantity. Traffic, requests, tokens and storage consumption are not inferred from billed dollars.")


def compare_monthly(billing, live, aws_provider, azure_provider):
    grouped = {r.resource_id.rstrip('/').lower(): r for r in _aggregate_billing(billing)}
    rows = []
    for resource in live:
        b = grouped.get(resource.resource_id.rstrip('/').lower())
        components = b.configuration.get("billing_components", []) if b else []
        r = monthly_resource(resource)
        if r.canonical_type == "other" and b is not None and b.canonical_type == "generative_ai":
            r.canonical_type = "generative_ai"
        current = azure_monthly(r, components, azure_provider) if str(r.cloud).lower() == "azure" else PriceResult(None, reason="Monthly source catalog calculation currently supports Azure.")
        target = price_resource(r, "AWS", aws_provider)
        from .monthly_defaults import aws_default, azure_default, non_workload_status
        current_default = target_default = False
        if not current.available and str(r.cloud).lower() == "azure":
            fallback = azure_default(r, components, azure_provider)
            if fallback.available:
                current, current_default = fallback, True
            elif "Azure Retail Prices API error:" in fallback.reason:
                current = fallback
        if not target.available:
            fallback = aws_default(r, aws_provider)
            if fallback.available:
                target, target_default = fallback, True
            else:
                target.reason += " Default estimate: " + fallback.reason
        status, status_reason = non_workload_status(r)
        if status and not target.available:
            target.reason = status_reason
        recommended, rationale = recommend_aws(r)
        placement = r.configuration.get("aws_placement", {})
        rows.append({"Resource":r.name, "Resource ID":r.resource_id, "Type":r.canonical_type,
            "Source region":r.region, "AWS region":placement.get("region") or "Region selection required",
            "Current monthly component (USD)":current.monthly_cost,
            "AWS monthly component (USD)":target.monthly_cost,
            "Recommended AWS service":recommended or target.sku,
            "Current estimate basis": "Default assumption" if current_default else "Existing evidence" if current.available else "Source catalog unavailable" if "Azure Retail Prices API error:" in current.reason else "Unresolved",
            "AWS estimate basis": "Default assumption" if target_default else "Existing evidence" if target.available else status or "Unresolved",
            "Current basis":current.reason, "AWS basis":"730-hour/full-month capacity scenario. " + target.reason,
            "AWS scope":target.coverage if target.available else status or "Usage/configuration required",
            "Recommendation basis":rationale,
            "Comparison status":"Planning components; scopes may differ; no total savings calculated"})
    return rows


def monthly_summary(rows):
    """Report component subtotals without silently zero-filling missing prices."""
    def numbers(key):
        return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))
                and not isinstance(row[key], bool) and math.isfinite(row[key]) and row[key] >= 0]
    current = numbers("Current monthly component (USD)")
    target = numbers("AWS monthly component (USD)")
    return {"current_subtotal": sum(current) if current else None,
            "target_subtotal": sum(target) if target else None,
            "current_priced": len(current), "target_priced": len(target), "total": len(rows),
            "overall_savings": None}
