"""Published base-zone fees for Azure private-zone-only billing scope."""


def private_zone_estimate(resource_id, contract, monthly):
    meters = contract.get("meters", [])
    if contract.get("resource_type") != "dns" or not meters or not all(
        str(m.get("name", "")).strip().lower() == "private zone" for m in meters
    ):
        return None
    source_months = sum(m["quantity"] for m in meters)
    details = {}
    for cloud, service, rate, url in [
        ("AWS", "Amazon Route 53 Private Hosted Zone", .50, "https://aws.amazon.com/route53/pricing/"),
        ("GCP", "Google Cloud DNS Private Zone", .20, "https://cloud.google.com/dns/pricing"),
    ]:
        quantity = 1 if monthly or cloud == "AWS" else source_months
        note = ("One private DNS zone; first-25-zones list-price tier assumed. "
                "Comparison covers the billed zone fee only. Resolver endpoints, logging and private network connectivity are separate workloads. ")
        note += ("AWS private hosted-zone queries have no additional charge; AWS zone fees are not prorated."
                 if cloud == "AWS" else "GCP query fees are additional; no query volume is present in the source zone meter, so no query volume is invented. Observed-period zone-month usage follows the source billing fraction.")
        details[cloud] = {"monthly_cost_usd": quantity * rate, "service": service,
            "assumptions": note, "components": [{"quantity": quantity, "unit": "month", "rate_unit": "month",
                "unit_price_usd": rate, "meter_index": 0, "fixed_zone_fee": True,
                "description": "Private zone base fee", "rate_basis": "Published first-25-zones list rate",
                "rate_source": url, "rate_checked": "2026-10-06"}]}
    return {"resource_id": resource_id, "targets": details}
