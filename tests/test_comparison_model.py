from types import SimpleNamespace
import pytest
from multicloud_ai.core.comparison_model import compare_model


def row(rid, cost):
    return SimpleNamespace(resource_id=rid, name=rid, canonical_type="other", currency="USD", cost=cost)


def test_v1_factors_aggregate_ids_and_include_zero_rows():
    result=compare_model([row("A",100),row("a/",46.99),row("zero",0)],"Azure",{"AWS":.92,"GCP":.90})
    assert len(result["rows"])==2
    assert result["totals"]["AWS"]==pytest.approx(135.2308)
    assert result["totals"]["GCP"]==pytest.approx(132.291)
    assert result["recommended"]=="GCP"
    assert result["rows"][1]["Recommended Cloud"]=="Azure"


@pytest.mark.parametrize("source", ["Azure","AWS","GCP"])
def test_current_cloud_wins_when_targets_are_more_expensive(source):
    others={c:1.2 for c in ["Azure","AWS","GCP"] if c!=source}
    assert compare_model([row("r",100)],source,others)["recommended"]==source


def test_monthly_projection_is_explicit():
    r=compare_model([row("r",21)],"Azure",{"AWS":1,"GCP":1},21)
    assert r["monthly"]
    assert r["totals"]["Azure"]==pytest.approx(730/24)
    assert r["recommended"]=="Azure"
