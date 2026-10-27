"""Preserve and price explicit billing components without guessing whole workloads."""
from copy import deepcopy
import math
import re

# Azure managed disk capacity tiers (GiB). No provider prices are hardcoded.
DISK_GIB = {"P4": 32, "P6": 64, "P10": 128, "E3": 16, "E4": 32}


def missing_mapping_reason(kind, components):
    reasons = {
        "search": "OpenSearch needs an explicit target deployment (managed domain or Serverless), sizing, storage and runtime. Azure Search Free Unit hours alone do not determine that deployment.",
        "app_service": "App Runner/Beanstalk needs target vCPU, memory, active/provisioned runtime and scaling policy. Azure F1 app hours do not supply those quantities; Azure's free plan is not an AWS free entitlement.",
        "generative_ai": "Bedrock requires a selected supported target model and input/output/cache token units. Azure GPT model names do not identify an equivalent Bedrock model or rate. Select the target model before estimating.",
        "nosql_database": "Cosmos request units cannot be converted directly to DynamoDB read/write units or DocumentDB instance hours. Confirm target engine, read/write split, item sizes and capacity mode.",
        "data_pipeline": "Data Factory control-plane read/write operations are not Glue DPU-hours. Target job runtime, DPU sizing or an explicit workflow/API mapping is required.",
    }
    names = [str(c.get("meter", {}).get("name", "")).lower() for c in components]
    specific = None
    if kind == "data_pipeline" and names and all(n == "cloud read write operations" for n in names):
        specific = ("Data Factory management operations only: The uploaded charge covers control-plane read/write operations, "
                    "not ETL job execution. Glue job compute cannot be priced from this meter. "
                    "Assess the target workflow and supply job type, worker/DPU capacity and execution time; "
                    "any management/API-charge mapping is separate. Absence of execution meters does not prove no jobs ran.")
    elif kind == "generative_ai" and names and all("token" in n for n in names):
        specific = ("AI token usage available; target model unselected: The bill provides source-model token meters, "
                    "but a Bedrock service name does not identify a priced model. Select and validate a specific target model, "
                    "inference mode and regional availability, then map input/output/cache units. "
                    "Token counts can change with the target tokenizer; cached tokens may have different semantics. "
                    "No model or workload needs to be created for this assessment.")
    elif kind == "app_service" and names and all(n == "f1 app" for n in names):
        specific = ("Azure F1 usage only; App Runner capacity unselected: The uploaded bill records Azure F1 app usage. "
                    "Its zero Azure charge is not an AWS price. App Runner needs a compatible application deployment, "
                    "target vCPU/RAM, instance count and active/provisioned runtime. F1 app hours do not specify those quantities. "
                    "Use existing app/plan configuration and workload measurements; no new resource needs to be created for this check.")
    elif kind == "search" and names and all(n == "free unit" for n in names):
        specific = ("Azure Search Free Unit usage only; OpenSearch capacity unselected: The bill records source Free Unit hours, "
                    "not an AWS deployment size. Select managed-domain or Serverless architecture using index size, "
                    "query/indexing load and availability requirements. For a managed domain specify node type/count, "
                    "storage and runtime. Azure's zero charge does not establish a zero AWS charge. "
                    "No new search service needs to be created for this assessment.")
    meters = "; ".join(f"{c['meter'].get('name', 'Unknown')}: {c['quantity']:g} {c['unit']}" for c in components)
    return (specific or ("Target design/usage mapping required, not an AWS permission failure. " + reasons[kind])) + (" Observed billing meters: " + meters if meters else "")


def price_billing_components(provider, resource, price_one, result_type):
    components = resource.configuration.get("billing_components", [])
    details = []
    total = 0.0
    priced = 0
    mapped = 0
    for c in components:
        meter = c["meter"]
        name = meter.get("name", "")
        sub = meter.get("subcategory", "")
        qty = c["quantity"]
        detail = {"Meter ID": meter.get("id", ""), "Meter": name, "Source quantity": qty, "Source unit": c["unit"],
                  "Target component": "Review required", "Target cost (USD)": None}
        proxy = deepcopy(resource)
        proxy.configuration = {"target_region": resource.configuration.get("target_region") or resource.region}
        target_qty = None
        reason = "Meter quantity retained; a validated target usage/unit mapping is required."
        if not math.isfinite(qty) or qty < 0:
            reason = "Invalid or credit usage cannot be treated as target consumption."
        elif "public ip" in name.lower() and c["unit"] == "Hours":
            proxy.canonical_type = "public_ip"
            proxy.usage_quantity, proxy.usage_unit = qty, "Hours"
            target_qty = qty
            detail["Target component"] = "Public IPv4"
            reason = "Billed public IPv4 hours; target assumes the same address lifetime."
        elif (str(meter.get("category", "")).lower() == "storage"
              and "block blob" in sub.lower() and name.lower() == "hot lrs data stored"):
            unit = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*)?GB\s*/\s*Month", str(c["unit"]).strip(), re.I)
            if unit and float(unit.group(1) or 1) > 0:
                target_qty = qty * float(unit.group(1) or 1)
                proxy.canonical_type = "object_storage"
                proxy.usage_quantity, proxy.usage_unit = target_qty, "GB-month"
                detail["Target component"] = "S3 Standard storage"
                reason = "Billed Hot Block Blob GB-month quantity mapped to S3 Standard capacity; requests and other workspace components excluded."
        else:
            disk = re.fullmatch(r"(P\d+|E\d+) LRS Disk", name, re.I)
            if disk and disk.group(1).upper() in DISK_GIB and c["unit"].strip() == "1 /Month" and qty >= 0 and math.isfinite(qty):
                target_qty = qty * DISK_GIB[disk.group(1).upper()]
                proxy.canonical_type = "block_storage"
                proxy.usage_quantity, proxy.usage_unit = target_qty, "GB-month"
                proxy.configuration["target_volume_type"] = "gp3"
                detail["Target component"] = "EBS gp3 capacity scenario"
                reason = "Billed disk-months multiplied by Azure tier capacity; gp3 capacity scenario requires performance/architecture review. This is a capacity component, not a complete workload total."
        if target_qty is not None:
            mapped += 1
            result = price_one(provider, proxy)
            detail["Target quantity"] = target_qty
            detail["Target unit"] = proxy.usage_unit
            detail["Target cost (USD)"] = result.monthly_cost
            if result.available:
                total += result.monthly_cost
                priced += 1
            else:
                reason += " Catalog lookup: " + result.reason
        detail["Reason"] = reason
        details.append(detail)
    if not details or (resource.canonical_type == "block_storage" and not mapped):
        return None
    return result_type(total if priced else None, sku=" + ".join(dict.fromkeys(d["Target component"] for d in details if d["Target cost (USD)"] is not None)) or "Component mapping required",
        confidence="Live catalog + billed component scenario", source="AWS Price List API + Azure billing meters",
        coverage=f"Partial components ({priced}/{len(details)})", components=details,
        reason=f"{priced}/{len(details)} billing components priced for the uploaded billing period. "
               "This subtotal is not the complete target workload cost. " + " | ".join(d["Meter"] + ": " + d["Reason"] for d in details))
