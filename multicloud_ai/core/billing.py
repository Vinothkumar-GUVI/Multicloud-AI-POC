from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Iterable

import pandas as pd

from .models import NormalizedResource
from .classification import classify
from .usage import normalize_usage

CLOUDS = ["AWS", "Azure", "GCP"]


def get(row, names, default=""):
    for n in names:
        if n in row.index and pd.notna(row[n]) and str(row[n]).strip():
            return str(row[n]).strip()
    return default


def num(row, names):
    s = get(row, names, "0")
    try:
        return float(
            s.replace(",", "")
            .replace("$", "")
            .replace("₹", "")
            .replace("€", "")
            .replace("£", "")
            .replace("â‚¬", "")
            .replace("Â£", "")
        )
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _uploaded_bytes(uploaded) -> bytes:
    """Read an upload without depending on its current file-pointer position."""
    if hasattr(uploaded, "getvalue"):
        data = uploaded.getvalue()
        return bytes(data)
    if hasattr(uploaded, "seek"):
        try:
            uploaded.seek(0)
        except Exception:
            pass
    data = uploaded.read()
    if hasattr(uploaded, "seek"):
        try:
            uploaded.seek(0)
        except Exception:
            pass
    return bytes(data)


def read_table(uploaded):
    raw = _uploaded_bytes(uploaded)
    if not raw:
        raise ValueError("The uploaded billing file is empty.")
    bio = io.BytesIO(raw)
    name = str(getattr(uploaded, "name", "billing.csv") or "billing.csv").lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(bio)
    else:
        try:
            df = pd.read_csv(bio)
        except UnicodeDecodeError:
            bio.seek(0)
            df = pd.read_csv(bio, encoding="latin1")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def detect(df):
    cols = {str(c).strip() for c in df.columns}
    low = {c.lower() for c in cols}
    if any(c.startswith(("lineItem/", "product/", "bill/")) for c in cols):
        return "AWS"
    aws_invoice_cols = {"ProductCode", "UsageType", "UsageQuantity", "CurrencyCode", "Actual Cost"}
    if len(aws_invoice_cols & cols) >= 4:
        return "AWS"
    azure_markers = {
        "resourceid", "resource id", "instanceid", "resourcegroup", "metercategory",
        "subscriptionid", "subscriptionguid", "pretaxcost", "consumedservice", "resourcetype",
    }
    if len(azure_markers & low) >= 3:
        return "Azure"
    if len({"service.description", "sku.description", "usage.amount", "project.id", "cost"} & cols) >= 2:
        return "GCP"
    if {"service", "sku", "project"} & low and "cost" in low:
        return "GCP"
    return "Unknown"


def _azure_tags(value: str) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception:
        return {}
    return {}


def _azure_kind(raw_type: str, service: str) -> str:
    """Prefer the actual ARM resource type over the billing meter description."""
    if str(raw_type or "").strip():
        kind = classify(raw_type, "")
        if kind != "other":
            return kind
    return classify(raw_type, service)


def parse(df, cloud):
    out = []
    skipped = 0
    for i, row in df.iterrows():
        if cloud == "AWS":
            lt = get(row, ["lineItem/LineItemType", "RecordType"]).lower()
            if lt in {"tax", "credit", "discount", "fee", "refund"}:
                skipped += 1
                continue
            rid = get(row, ["lineItem/ResourceId", "ResourceId", "resource_id"])
            invoice_style = not bool(rid) and any(c in row.index for c in ["ProductCode", "Actual Cost", "RecordID"])
            if invoice_style:
                account = get(row, ["LinkedAccountId", "PayerAccountId"], "default")
                product = get(row, ["ProductCode"], "AWS") or "AWS"
                usage_type = get(row, ["UsageType"], "usage") or "usage"
                operation = get(row, ["Operation"], "")
                rate_id = get(row, ["RateId"], "")
                record_id = get(row, ["RecordID"], str(i))
                rid = f"billing://aws/{account}/{product}/{usage_type}/{operation or rate_id or record_id}"
            if not rid:
                skipped += 1
                continue
            raw = get(row, ["lineItem/ProductCode", "ProductCode", "ResourceType"])
            service = get(row, ["product/ProductName", "ProductName", "lineItem/ProductCode", "ProductCode"])
            item_desc = get(row, ["ItemDescription"], "")
            name = get(row, ["ResourceName", "resource_name"], "") or (f"{service} - {get(row,['UsageType'],'usage')}" if invoice_style else rid)
            region = get(row, ["product/region", "Region"], "unknown")
            group = get(row, ["lineItem/UsageAccountId", "LinkedAccountId", "bill/PayerAccountId", "PayerAccountId"], "default")
            sku = get(row, ["product/instanceType", "product/sku", "lineItem/UsageType", "UsageType", "RateId"])
            usage_qty = num(row, ["lineItem/UsageAmount", "UsageQuantity"])
            usage_type = get(row, ["lineItem/UsageType", "UsageType"])
            from .aws_billing import billing_kind, consumed_unit
            usage_unit = consumed_unit(get(row, ["pricing/unit", "Unit", "UsageUnit"]), item_desc, usage_type)
            currency = get(row, ["lineItem/CurrencyCode", "CurrencyCode"], "USD")
            cost = num(row, ["lineItem/UnblendedCost", "lineItem/BlendedCost", "Actual Cost"])
            r = NormalizedResource(rid, name, "AWS", billing_kind(raw, service, usage_type), raw, service, region, group, sku, usage_qty, usage_unit, currency, cost)
            r.configuration["billing_meter"] = {"name": usage_type, "category": service,
                "raw_unit": usage_unit, "description": item_desc}
            if invoice_style:
                r.configuration["billing_scope"] = "service_usage_line"
                r.configuration["billing_has_resource_id"] = False
                r.configuration["billing_record_id"] = get(row, ["RecordID"], "")
                r.configuration["billing_operation"] = operation
                r.configuration["billing_item_description"] = item_desc
            out.append(r)

        elif cloud == "Azure":
            rid = get(row, ["ResourceId", "Resource ID", "ResourceUri", "Resource URI", "InstanceId"])
            if not rid:
                skipped += 1
                continue
            raw = get(row, ["ResourceType", "Resource Type"])
            service = get(row, ["ServiceName", "MeterCategory", "ConsumedService"])
            name = get(row, ["ResourceName", "Resource Name", "Resource"], rid.rstrip("/").split("/")[-1])
            region = get(row, ["ResourceLocation", "Location", "Region", "MeterRegion"], "unknown")
            group = get(row, ["ResourceGroup", "Resource Group", "ResourceGroupName"], "default")
            sku = get(row, ["SkuName", "SKU", "Sku", "ServiceTier", "MeterName"])
            if get(row, ["CostUSD", "CostInUsd", "CostInUSD", "costInUsd"]):
                cost = num(row, ["CostUSD", "CostInUsd", "CostInUSD", "costInUsd"])
                currency = "USD"
            else:
                cost = num(row, ["PreTaxCost", "Cost", "CostInBillingCurrency"])
                currency = get(row, ["BillingCurrencyCode", "BillingCurrency", "CurrencyCode", "Currency"], "USD").upper()

            original_quantity = num(row, ["Quantity", "UsageQuantity"])
            original_unit = get(row, ["UnitOfMeasure", "UsageUnit"])
            normalized_quantity, normalized_unit = normalize_usage(original_quantity, original_unit)
            day = get(row, ["UsageDateTime", "Date", "UsageDate"])
            kind = _azure_kind(raw, service)
            r = NormalizedResource(
                rid, name, "Azure", kind, raw, service, region, group, sku,
                normalized_quantity, normalized_unit, currency, cost,
                tags=_azure_tags(get(row, ["Tags"])),
            )
            r.configuration["billing_meter"] = {
                "id": get(row, ["MeterId", "MeterID"]),
                "category": get(row, ["MeterCategory", "ServiceName"]),
                "name": get(row, ["MeterName", "Meter"]),
                "subcategory": get(row, ["MeterSubCategory", "ServiceTier"]),
                "rate": num(row, ["ResourceRate"]),
                "raw_unit": original_unit,
            }
            r.configuration["billing_usage"] = {
                "original_quantity": original_quantity,
                "original_unit": original_unit,
                "dates": [day] if day else [],
            }
            r.configuration["billing_subscription_id"] = get(row, ["SubscriptionGuid", "SubscriptionId", "Subscription ID"])
            r.configuration["billing_offer_id"] = get(row, ["OfferId"])
            out.append(r)

        elif cloud == "GCP":
            service = get(row, ["service.description", "service_description", "Service Description"])
            sku = get(row, ["sku.description", "sku_description", "SKU Description"])
            rid = get(row, ["resource.name", "resource_name", "Resource Name"])
            project = get(row, ["project.id", "project_id"])
            cost = num(row, ["cost", "Cost"])
            if not rid:
                skipped += 1
                continue
            name = rid.split("/")[-1] or rid
            out.append(NormalizedResource(
                rid, name, "GCP", classify(service, sku), sku, service,
                get(row, ["location.region", "region", "Region"], "unknown"),
                project or "default", sku,
                num(row, ["usage.amount", "usage_amount"]),
                get(row, ["usage.unit", "usage_unit"]),
                get(row, ["currency", "currency_code"], "USD"), cost,
            ))
        else:
            raise ValueError(f"Unsupported cloud: {cloud}")
    return out, skipped


def billing_period(resources: Iterable[NormalizedResource]) -> dict:
    """Return the inclusive billing date range carried by normalized rows."""
    dates = []
    for resource in resources or []:
        info = (getattr(resource, "configuration", {}) or {}).get("billing_usage", {})
        for value in info.get("dates", []) or []:
            text = str(value or "").strip()
            if not text:
                continue
            try:
                dates.append(pd.to_datetime(text).date())
            except Exception:
                continue
    if not dates:
        return {"start": None, "end": None, "days": None}
    start, end = min(dates), max(dates)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1}
