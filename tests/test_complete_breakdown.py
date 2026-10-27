import pytest
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.billing_breakdown import billing_breakdown


def item(rid, meter, cost, unit="Hours"):
    return NormalizedResource(rid, rid, "Azure", "other", cost=cost, usage_quantity=2, usage_unit=unit,
        configuration={"billing_meter": {"id": meter, "name": "Same name", "raw_unit": unit}})


def test_complete_inventory_preserves_costs_and_unpriced_resources():
    billing = [item("a", "m1", 3), item("a", "m1", 2), item("a", "m2", 0), item("b", "m3", 7)]
    prices = {"AWS": [{"Resource ID": "a", "Target Monthly Cost (USD)": 9,
        "Pricing Components": [{"Meter ID": "m1", "Meter": "Same name", "Target cost (USD)": 4}]}]}
    rows, summaries = billing_breakdown(billing, prices, ["AWS"])
    assert len(rows) == 3
    assert sum(r["Billing rows"] for r in rows) == 4
    assert sum(r["Source billed cost"] for r in rows) == 12
    assert [r["Target component cost (USD)"] for r in rows] == [4, None, None]
    assert summaries[0]["Resource estimate (USD)"] == 9
    assert summaries[0]["Mapped component subtotal (USD)"] == 4
    assert summaries[0]["Meter coverage"] == "Partial"
    assert rows[1]["Source billed cost"] == 0
    assert all(r["Required inputs / review"] for r in rows)


def test_resource_estimate_is_never_distributed_or_duplicated_across_meters():
    billing = [item("a", "m1", 3), item("a", "m2", 2)]
    rows, summaries = billing_breakdown(billing, {"AWS": [{"Resource ID": "a", "Target Monthly Cost (USD)": 10}]}, ["AWS"])
    assert all(r["Target component cost (USD)"] is None for r in rows)
    assert all("allocation unresolved" in r["Status"] for r in rows)
    assert summaries[0]["Resource estimate (USD)"] == 10


def test_legacy_ambiguous_meter_names_do_not_receive_duplicate_prices():
    rows, _ = billing_breakdown([item("a", "m1", 3), item("a", "m2", 2)],
        {"AWS": [{"Resource ID": "a", "Pricing Components": [{"Meter": "Same name", "Source unit": "Hours", "Target cost (USD)": 4}]}]}, ["AWS"])
    assert all(r["Target component cost (USD)"] is None for r in rows)
