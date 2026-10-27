"""Explicit user-confirmed meanings for ambiguous source export meter units."""
import json
import math
import re


def meter_key(kind, name, unit):
    return json.dumps([kind, name or "", unit or ""], separators=(",", ":"))


def correction_rows(billing):
    rows = {}
    for resource in billing:
        meter = resource.configuration.get("billing_meter", {})
        unit = resource.usage_unit
        if not re.match(r"^\d", str(unit).strip()):
            continue
        key = meter_key(resource.canonical_type, meter.get("name"), unit)
        rows.setdefault(key, {"Meter key": key, "Type": resource.canonical_type,
            "Source meter": meter.get("name", ""), "Export unit": unit,
            "Consumed unit": "", "Quantity multiplier": 1.0, "Confirmed": False})
    return list(rows.values())


def confirmed_overrides(rows):
    overrides = {}
    for row in rows:
        if not row.get("Confirmed"):
            raise ValueError("Confirm the consumed unit and quantity multiplier for every ambiguous source meter.")
        unit = str(row.get("Consumed unit", "")).strip()
        multiplier = float(row["Quantity multiplier"])
        if unit not in {"requests", "tokens", "GB-month", "TB-month", "GB", "Hours", "month", "RUs", "operations"}:
            raise ValueError("Choose an explicit consumed unit for every source meter.")
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("Source quantity multipliers must be positive and finite.")
        overrides[row["Meter key"]] = {"unit": unit, "multiplier": multiplier}
    return overrides


def automatic_overrides(billing):
    """Planning conventions for Azure export price labels, never label multipliers.

    These are disclosed in the calculation evidence, not provider-verified usage.
    Explicit caller overrides can replace them when authoritative units exist.
    """
    result = {}
    for resource in billing:
        if resource.cloud != "Azure":
            continue
        meter = resource.configuration.get("billing_meter", {})
        unit = str(resource.usage_unit).strip()
        name = str(meter.get("name", "")).lower()
        if not re.match(r"^\d", unit):
            continue
        storage = re.fullmatch(r"\d+(?:\.\d+)?\s*(GB|TB)[/-]Month", unit, re.I)
        if storage:
            consumed, factor = storage[1].upper() + "-month", 1
        elif "token" in name and re.fullmatch(r"\d+", unit):
            consumed, factor = "tokens", 1000
        elif ("operation" in name or "request" in name or "transaction" in name) and re.fullmatch(r"\d+", unit):
            consumed, factor = "requests", 1000
        elif re.fullmatch(r"1\s*/Month", unit, re.I):
            consumed, factor = "month", 1
        else:
            continue
        result[meter_key(resource.canonical_type, meter.get("name"), unit)] = {
            "unit": consumed, "multiplier": factor,
            "assumption": f"Automatic planning interpretation: exported quantities use {consumed} with multiplier {factor}; numeric price-label prefixes are ignored. Validate against source usage records.",
        }
    return result
