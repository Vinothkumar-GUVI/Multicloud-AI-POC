"""Explicit planning fallback quantities; catalog prices are never invented."""
import math
import re
from .pricing import PriceResult
from .workload_pricing import catalog_component

# These are workload assumptions, not measured consumption or equivalent designs.
PROFILES = {
    "object_storage": ("AmazonS3", {"storageClass": "General Purpose", "volumeType": "Standard"}, {"GB-Mo"}, 10, "10 GiB S3 Standard held one month; storage only", None),
    "container_registry": ("AmazonECR", {"productFamily": "Storage"}, {"GB-Mo"}, 1, "1 GiB private registry storage held one month; storage only", None),
    "search": ("AmazonES", {"instanceType": "t3.small.search"}, {"Hrs"}, 730, "One t3.small.search node for 730 hours; storage, transfer and HA excluded", None),
    "data_pipeline": ("AWSGlue", {}, {"DPU-Hour", "DPU-Hours"}, 60, "Spark ETL: 2 DPUs, 1 hour/day for 30 days; orchestration and transfer excluded", r"(?:.*-)?ETL-DPU-Hour"),
    "logging": ("AmazonCloudWatch", {"operation": "PutLogEvents", "version": "Current"}, {"GB"}, 1, "1 GiB standard log ingestion/month; retention and queries excluded", r"(?:.*-)?DataProcessing-Bytes"),
    "secrets_manager": ("AWSSecretsManager", {"group": "AWSSecretsManager-Secret"}, {"Secrets"}, 1, "One secret held one month; API calls, rotation and replication excluded", None),
    "machine_learning": ("AmazonSageMaker", {"instanceType": "ml.t3.medium-Notebook", "component": "Notebook"}, {"Hrs"}, 160, "One ml.t3.medium notebook for 160 hours/month; training, endpoints and storage excluded; workspace inventory unverified", None),
    "nosql_database": ("AmazonDocDB", {"productFamily": "Database Storage"}, {"GB-Mo", "GB-month"}, 10, "10 GiB DocumentDB Standard storage/month; compute, I/O and replicas excluded", r"(?:.*[-:])?StorageUsage"),
}


def aws_default(resource, provider):
    if resource.canonical_type == "generative_ai":
        return bedrock_default(resource, provider)
    if resource.canonical_type in {"app_service", "cdn"}:
        return composite_default(resource, provider)
    profile = PROFILES.get(resource.canonical_type)
    if not profile:
        return PriceResult(None, reason="No default profile for this resource; explicit target design is still required.")
    if resource.canonical_type == "nosql_database" and "mongo" not in str(resource.configuration.get("database", {})).lower():
        return PriceResult(None, reason="Select the database API before applying a DocumentDB storage default.")
    service, filters, units, quantity, assumption, pattern = profile
    region = resource.configuration.get("target_region") or resource.configuration.get("aws_placement", {}).get("region")
    if not region:
        return PriceResult(None, reason="Target region required for default catalog lookup.")
    if not getattr(provider, "enabled", False):
        return PriceResult(None, reason="AWS catalog access unavailable; default quantity does not supply a price.")
    cost, error = catalog_component(provider, service, region, filters, units, quantity, pattern)
    return PriceResult(cost, sku=service, coverage="Default planning component", confidence="Assumed usage/configuration",
        reason="DEFAULT ASSUMPTION: " + assumption + (". " + error if error else ""), source="AWS catalog with default quantity")


def azure_default(resource, components, provider):
    """Use the source's meter identity; only recognized unit dimensions get defaults."""
    total = 0.0
    assumptions = []
    seen = set()
    catalog_errors = []
    for component in components:
        meter = component.get("meter", {})
        mid = meter.get("id", "")
        if mid in seen or not re.fullmatch(r"[0-9a-fA-F-]{36}", mid):
            continue
        seen.add(mid)
        items, error = provider._query(f"meterId eq '{mid}' and priceType eq 'Consumption'")
        if error:
            catalog_errors.append(error)
            continue
        # A first-tier price alone is insufficient for a tiered source meter.
        if any(float(i.get("tierMinimumUnits", 0) or 0) != 0 for i in items if i.get("meterId", "").lower() == mid.lower()):
            continue
        candidates = []
        for item in items:
            if (item.get("currencyCode") != "USD" or item.get("type") != "Consumption"
                or item.get("meterId", "").lower() != mid.lower()
                or item.get("armRegionName", "").lower() != resource.region.lower().replace(" ", "")
                or float(item.get("tierMinimumUnits", 0) or 0) != 0):
                continue
            unit = str(item.get("unitOfMeasure", "")).lower().replace(" ", "")
            qty = source_default_quantity(resource.canonical_type, meter.get("name", ""), unit)
            if qty is None:
                continue
            rate = float(item.get("retailPrice", -1))
            if math.isfinite(rate) and rate >= 0:
                candidates.append((rate * qty, f"{meter.get('name')}: {qty:g} catalog units ({item.get('unitOfMeasure')})"))
        unique = set(candidates)
        if len(unique) == 1:
            cost, note = unique.pop()
            total += cost
            assumptions.append(note)
    if not assumptions and catalog_errors:
        return PriceResult(None, reason=catalog_errors[0])
    if not assumptions:
        return PriceResult(None, reason="Source meter needs an explicit configuration/unit mapping or an available catalog rate.")
    return PriceResult(total, coverage="Default planning components", confidence="Assumed usage/configuration",
        reason="DEFAULT ASSUMPTIONS: " + "; ".join(assumptions) + ". Partial components only; other charges excluded.", source="Azure catalog with default quantities")


def bedrock_default(resource, provider):
    from .catalog_scenarios import flat_rates
    region = resource.configuration.get("target_region") or resource.configuration.get("aws_placement", {}).get("region")
    assumption = "DEFAULT ASSUMPTION: Nova Micro standard on-demand, 1,000,000 input and 200,000 output tokens/month, no caching. Model substitution is unvalidated."
    if not region or not getattr(provider, "enabled", False):
        return PriceResult(None, reason=assumption + " Region/catalog access unavailable.")
    products, error = provider._query("AmazonBedrock", [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}])
    if error:
        return PriceResult(None, reason=assumption + " " + error)
    rates = flat_rates(products)
    total = 0.0
    for direction, tokens in [("input", 1000000), ("output", 200000)]:
        matches = []
        for rate in rates:
            attrs = rate.get("attributes", {})
            if attrs and (attrs.get("regionCode") != region or attrs.get("model") != "Nova Micro"
                          or attrs.get("feature") != "On-demand Inference"
                          or attrs.get("inferenceType", "").lower() != direction + " tokens"):
                continue
            description = rate["description"].lower()
            compact = re.sub(r"[^a-z0-9]", "", description)
            if "novamicro" not in compact or direction not in description:
                continue
            if any(x in description for x in ("cache", "custom", "batch", "priority", "flex", "reserved")):
                continue
            unit = rate["unit"].lower().replace(" ", "")
            scale = {"1ktokens": 1000, "1mtokens": 1000000, "tokens": 1, "token": 1}.get(unit)
            if scale:
                matches.append(rate["rate_usd"] * tokens / scale)
        if len(matches) != 1:
            return PriceResult(None, reason=assumption + f" Unique standard {direction}-token rate not found; review catalog selection.")
        total += matches[0]
    return PriceResult(total, sku="Amazon Nova Micro", coverage="Default token scenario", confidence="Assumed model and usage",
        reason=assumption, source="AWS catalog with default token quantities")


def composite_default(resource, provider):
    region = resource.configuration.get("target_region") or resource.configuration.get("aws_placement", {}).get("region")
    if not region or not getattr(provider, "enabled", False):
        return PriceResult(None, reason="Target region/catalog access unavailable.")
    if resource.canonical_type == "app_service":
        service = "AWSAppRunner"
        assumption = "One 1-vCPU, 2-GB App Runner instance active for 730 hours; no idle interval or scaling; builds, logs and transfer excluded."
        parts = [(region, {"type": "vCPU-hours"}, {"vCPU-hour"}, 730),
                 (region, {"type": "GB-hours"}, {"hours"}, 1460)]
    else:
        service = "AmazonCloudFront"
        assumption = "Pay-as-you-go CloudFront: 10 GB outbound to US viewers and 10,000 HTTPS requests/month; viewer geography is an assumption independent of deployment region. Free allowances, origin, WAF and other features excluded."
        parts = [(None, {"usagetype": "US-DataTransfer-Out-Bytes", "fromLocation": "United States", "toLocation": "External"}, {"GB"}, 10),
                 (None, {"usagetype": "US-Requests-Tier2-HTTPS", "location": "United States"}, {"Requests"}, 10000)]
    total = 0.0
    for location, filters, units, quantity in parts:
        cost, error = catalog_component(provider, service, location, filters, units, quantity)
        if cost is None:
            return PriceResult(None, reason="DEFAULT ASSUMPTION: " + assumption + " " + error)
        total += cost
    return PriceResult(total, sku=service, coverage="Default planning components", confidence="Assumed usage/configuration",
                       reason="DEFAULT ASSUMPTION: " + assumption, source="AWS catalog with default quantities")


def non_workload_status(resource):
    """Classification only: never invent a zero price for an unidentified workload."""
    kind = resource.canonical_type
    raw = str(getattr(resource, "raw_type", "")).lower()
    if kind in {"network_interface", "security_group"}:
        return "No standalone capacity estimate", "Networking configuration object; attached compute, public IP, traffic and network services are priced separately."
    if kind == "app_service_plan":
        return "Included with application estimates", "AWS App Runner capacity is estimated per application; adding another shared-plan estimate would duplicate capacity."
    if raw == "microsoft.sql/servers" or (raw == "microsoft.sql/servers/databases" and resource.name.lower() == "master"):
        return "RDS instance not applicable", "Logical SQL server/system database has no standalone RDS instance equivalent; user databases and security charges require separate assessment."
    if kind == "other":
        return "Resource mapping required", "Identify the source resource type and target service before selecting a default workload; unknown resources are not assigned arbitrary prices."
    return "", ""


def source_default_quantity(kind, meter_name, unit):
    """Default workload quantities expressed in the exact source catalog unit."""
    name = str(meter_name).lower()
    unit = str(unit).lower().replace(" ", "").replace(",", "")
    if "token" in name:
        if "cache" in name:
            return None
        pack = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)(?:tokens)?", unit)
        if not pack:
            return None
        divisor = float(pack[1]) * {"": 1, "k": 1000, "m": 1000000}[pack[2]]
        if divisor <= 0:
            return None
        if "outp" in name:
            return 200000 / divisor
        if "inp" in name:
            return 1000000 / divisor
        return None
    if kind == "cdn":
        if "base" in name:
            return 1.0 if unit in {"1/month", "1month"} else 730.0 if unit in {"1hour", "1hours"} else None
        if "transfer" in name and unit == "1gb":
            return 10.0
        if "request" in name:
            pack = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)(?:requests)?", unit)
            if pack and float(pack[1]) > 0:
                return 10000 / (float(pack[1]) * {"": 1, "k": 1000, "m": 1000000}[pack[2]])
    if kind == "data_pipeline" and "read write operations" in name:
        pack = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)(?:operations)?", unit)
        if pack and float(pack[1]) > 0:
            return 1000 / (float(pack[1]) * {"": 1, "k": 1000, "m": 1000000}[pack[2]])
    if unit in {"1gb", "1gb/month", "1gbmonth"}:
        if kind == "logging" and "ingestion" in name:
            return 1.0
        if kind in {"object_storage", "container_registry", "nosql_database", "machine_learning"} and ("stored" in name or "storage" in name):
            return 1.0 if kind == "container_registry" else 10.0
    return None
