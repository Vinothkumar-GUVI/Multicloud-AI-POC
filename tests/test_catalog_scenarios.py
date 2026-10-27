import json
from unittest.mock import Mock
import pytest
from multicloud_ai.core.catalog_scenarios import flat_rates, catalog_page, calculate


def product():
    return {"product": {"sku": "example", "attributes": {"instanceType": "test.size", "regionCode": "us-east-1"}},
        "terms": {"OnDemand": {"term": {"effectiveDate": "2026-01-01", "priceDimensions": {
            "flat": {"pricePerUnit": {"USD": "0.12"}, "unit": "Hrs", "beginRange": "0", "endRange": "Inf", "description": "instance hour"},
            "tier": {"pricePerUnit": {"USD": "0.1"}, "unit": "Hrs", "beginRange": "100", "endRange": "Inf"},
            "conditional": {"pricePerUnit": {"USD": "0"}, "unit": "Hrs", "beginRange": "0", "endRange": "Inf", "appliesTo": ["other"]}
        }}}}}


def test_only_flat_unconditional_rates_selected():
    rates = flat_rates([product()])
    assert len(rates) == 1
    assert rates[0]["rate_id"] == "flat"
    assert rates[0]["rate_usd"] == .12


def test_catalog_pagination_preserves_exact_region_and_size():
    client = Mock()
    client.get_products.return_value = {"PriceList": [json.dumps(product())], "NextToken": "next"}
    rates, token = catalog_page(client, "AmazonES", "us-east-1", "test.size", "previous")
    assert len(rates) == 1 and token == "next"
    request = client.get_products.call_args.kwargs
    assert request["NextToken"] == "previous"
    assert request["Filters"][1]["Value"] == "test.size"


@pytest.mark.parametrize("qty", [-1, float("nan"), float("inf")])
def test_invalid_quantities_rejected(qty):
    with pytest.raises(ValueError):
        calculate(flat_rates([product()])[0], qty, "r", "September", "chosen configuration")


def test_scenario_calculates_explicit_usage_and_preserves_provenance():
    rate = flat_rates([product()])[0]
    row = calculate(rate, 232, "resource", "10 days", "single chosen instance")
    assert row["Scenario cost (USD)"] == pytest.approx(27.84)
    assert row["Rate ID"] == "flat"
    assert row["Status"] == "User-selected component scenario"
    with pytest.raises(ValueError):
        calculate(rate, 232, "resource", "", "")


def test_scenario_panel_renders_and_loads_catalog():
    from streamlit.testing.v1 import AppTest
    script = '''
from types import SimpleNamespace
from unittest.mock import Mock
from multicloud_ai.scenario_ui import render_scenarios
client=Mock()
client.get_products.return_value={"PriceList": [], "NextToken": None}
provider=SimpleNamespace(enabled=True, client=client)
render_scenarios([{"Resource ID":"r", "Resource":"search", "Type":"search"}], lambda:provider, str)
'''
    app = AppTest.from_string(script).run()
    assert not app.exception
    app.button(key="scenario_find").click().run()
    assert not app.exception
    assert "No matching flat rates" in app.info[0].value


def test_billing_window_uses_inclusive_dates_not_assumed_month():
    from multicloud_ai.core.catalog_scenarios import billing_window_hours
    assert billing_window_hours({"start":"2026-09-01", "end":"2026-09-10"}) == 240
    assert billing_window_hours({"start":"2026-01-31", "end":"2026-02-01"}) == 48
    assert billing_window_hours({"start":"2026-09-10", "end":"2026-09-01"}) is None
    assert billing_window_hours({}) is None


def test_resource_defaults_follow_service_and_region():
    from multicloud_ai.core.catalog_scenarios import scenario_defaults
    assert scenario_defaults({"AWS Equivalent":"Amazon DocumentDB", "AWS Pricing Region":"ap-south-1"}) == ("DocumentDB", "ap-south-1")
    assert scenario_defaults({"AWS Equivalent":"Amazon CloudFront", "AWS Pricing Region":"us-east-1"}) == ("CloudFront", "")


def test_scenario_display_does_not_mix_periods_or_change_verified_cost():
    from multicloud_ai.core.catalog_scenarios import scenario_display
    source=[{"Resource ID":"r", "AWS Cost (USD)":None}]
    original=[{"AWS Cost (USD)":"Target estimate pending"}]
    scenarios=[{"Resource ID":"r", "Period":"month", "Region":"us-east-1", "Scenario cost (USD)":2},
               {"Resource ID":"r", "Period":"week", "Region":"us-east-1", "Scenario cost (USD)":3}]
    output=scenario_display(source,original,scenarios)
    assert "$2.000000 | month" in output[0]["AWS planning component estimates"]
    assert "$3.000000 | week" in output[0]["AWS planning component estimates"]
    assert output[0]["AWS Cost (USD)"].startswith("User-defined scenario:")
    assert source[0]["AWS Cost (USD)"] is None
    assert original[0]["AWS Cost (USD)"] == "Target estimate pending"
    assert "AWS planning component estimates" not in original[0]


def test_monthly_scenario_can_be_saved_without_billing_dates():
    from streamlit.testing.v1 import AppTest
    script = """
from types import SimpleNamespace
from unittest.mock import Mock
from multicloud_ai.scenario_ui import render_scenarios
import streamlit as st
st.session_state.scenario_catalog={"query":("AmazonRDS","us-east-2",""),"rates":[{"rate_id":"r1","sku":"s1","region":"us-east-2","unit":"Hrs","rate_usd":0.1,"description":"instance","instance_type":"db.test","effective_date":"2026-01-01","attributes":{}}]}
render_scenarios([{"Resource ID":"db", "Resource":"database", "Type":"relational_database", "AWS Equivalent":"Amazon RDS", "AWS Pricing Region":"us-east-2"}],lambda:None,str)
"""
    app=AppTest.from_string(script).run()
    assert not app.exception
    assert app.selectbox(key="scenario_service").value == "RDS"
    app.checkbox(key="scenario_month_db").check().run()
    assert not app.exception
    assert app.number_input[0].value == 730
    next(x for x in app.text_input if x.label == "Target configuration and usage assumptions").set_value("One selected instance")
    next(x for x in app.button if x.label == "Calculate and save component scenario").click().run()
    assert not app.exception
    assert app.session_state["aws_component_scenarios"][0]["Scenario cost (USD)"] == 73


def test_scenario_acknowledgement_is_resource_specific_and_preserves_numeric_costs():
    from multicloud_ai.core.catalog_scenarios import scenario_display
    from multicloud_ai.core.pricing_presentation import with_input_guidance
    source = [{"Resource ID": "/A", "AWS Cost (USD)": None, "Type": "generative_ai", "AWS Pricing reason": "select model"},
              {"Resource ID": "/B", "AWS Cost (USD)": None},
              {"Resource ID": "/C", "AWS Cost (USD)": 4}]
    display = [{"AWS Cost (USD)": "Missing"}, {"AWS Cost (USD)": "Missing"}, {"AWS Cost (USD)": "4.000000"}]
    items = [{"Resource ID": rid, "Period": "October", "Region": "us-east-1", "Scenario cost (USD)": 0.5,
              "Description": "Input tokens", "Usage": 1000, "Unit": "1K tokens", "Assumptions": "Test only"} for rid in ["/a/", "/C"]]
    result = with_input_guidance(source, scenario_display(source, display, items), ["AWS"])
    assert result[0]["AWS Cost (USD)"] == "User-defined scenario: $0.500000 | October | us-east-1"
    assert "Test only" in result[0]["AWS scenario details"]
    assert "select model" in result[0]["AWS required evidence"]
    assert "User-defined scenario" not in result[1]["AWS Cost (USD)"]
    assert result[2]["AWS Cost (USD)"] == "4.000000"
    assert source[0]["AWS Cost (USD)"] is None
