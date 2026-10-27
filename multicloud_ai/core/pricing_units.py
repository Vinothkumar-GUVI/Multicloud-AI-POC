"""Explicit dimensional conversions for target pricing components."""
import re


def dimension(unit):
    text = str(unit or "").lower().replace(",", "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(million|thousand)\s+", r"1 \1 ", text)
    if text in {"hour","hours","hr","hrs","instance-hour","instance-hours"}:
        return "hours", 1.0
    if text in {"month", "months", "1 /month", "1/month"}:
        return "month", 1.0
    data = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*)?(gb|gib|tb|tib|mb|mib|bytes?)", text)
    if data:
        return "data", float(data[1] or 1) * {"gb": 1, "gib": 2**30 / 10**9,
            "tb": 1000, "tib": 2**40 / 10**9, "mb": .001,
            "mib": 2**20 / 10**9, "byte": 1e-9, "bytes": 1e-9}[data[2]]
    packed_hours = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|instance-hours?)", text)
    if packed_hours:
        return "hours", float(packed_hours[1])
    storage = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*)?(gb|tb)(?:/|-| )months?", text)
    if storage:
        return "storage-month", float(storage[1] or 1) * (1000 if storage[2] == "tb" else 1)
    count = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*(k|m|million|thousand)?\s*)?(requests?|operations?|ops|tokens?)", text)
    if count:
        family = "tokens" if count[3].startswith("token") else "requests"
        factor = {"k":1000,"thousand":1000,"m":1000000,"million":1000000}.get(count[2],1)
        return family, float(count[1] or 1)*factor
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return "requests", float(text)
    return None


def convert(quantity, source_unit, target_unit, allow_data=False):
    src, dst = dimension(source_unit), dimension(target_unit)
    if not src or not dst or src[0] != dst[0] or dst[1] <= 0:
        return None
    if src[0] == "data" and not allow_data:
        return None
    return quantity * src[1] / dst[1]
