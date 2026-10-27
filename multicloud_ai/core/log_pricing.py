"""Map measured Azure analytics log ingestion to AWS Standard custom logs."""
import math
import re


def price_logs(provider, resource, result_type):
    total=0.0
    found=False
    for component in resource.configuration.get("billing_components", []):
        meter=component.get("meter", {})
        if str(meter.get("name", "")).lower() != "analytics logs data ingestion":
            continue
        unit=re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*)?GB",str(component.get("unit", "")).strip(),re.I)
        qty=float(component.get("quantity", -1))
        if not unit or not math.isfinite(qty) or qty < 0:
            return result_type(None,reason="Log ingestion quantity/unit is invalid or unsupported.")
        multiplier=float(unit.group(1) or 1)
        if multiplier<=0:
            return result_type(None,reason="Log ingestion unit multiplier must be positive.")
        total+=qty*multiplier
        found=True
    if not found:
        return result_type(None,reason="CloudWatch ingestion requires Analytics Logs Data Ingestion GB; retention and queries need separate quantities.")
    region=resource.configuration.get("target_region") or resource.region
    filters=provider._region_filters(region)+[{"Type":"TERM_MATCH","Field":"operation","Value":"PutLogEvents"}]
    products,error=provider._query("AmazonCloudWatch",filters)
    if error:
        return result_type(None,reason=error)
    candidates=[]
    for product in products:
        attrs=product.get("product",{}).get("attributes",{})
        if attrs.get("operation") != "PutLogEvents" or not re.fullmatch(r"(?:[A-Z0-9]+-)?DataProcessing-Bytes",attrs.get("usagetype", "")):
            continue
        if attrs.get("regionCode") != region:
            continue
        for term in product.get("terms",{}).get("OnDemand",{}).values():
            for dim in term.get("priceDimensions",{}).values():
                try:
                    rate=float(dim.get("pricePerUnit",{}).get("USD"))
                    start=float(dim.get("beginRange",0)); end=float(dim.get("endRange","inf"))
                except (TypeError,ValueError):
                    continue
                if dim.get("unit") == "GB" and start==0 and total<=end and not dim.get("appliesTo") and math.isfinite(rate) and rate>=0:
                    candidates.append(rate)
    if len(candidates)!=1:
        return result_type(None,reason="No unique Standard custom-log ingestion rate covers this quantity and mapped region; catalog/tier review required.")
    return result_type(total*candidates[0],sku="CloudWatch Logs Standard ingestion",unit_price=candidates[0],unit="USD/GB",usage=total,
        source="AWS Price List API + Azure billed ingestion",confidence="Live catalog + billed component scenario",coverage="Ingestion only",
        reason="Same billed ingestion GB mapped to Standard custom logs at public list rate; payload/account pricing differences require review. Free tier, storage, retention, queries and transfer excluded.")
