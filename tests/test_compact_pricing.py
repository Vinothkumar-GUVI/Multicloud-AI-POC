from multicloud_ai.core.equivalence import pricing_comparison_rows, pricing_display_rows


def test_compact_costs_adjacent_and_requested_columns_hidden():
    row = {"Resource": "x", "Type": "object_storage", "Resource ID": "id", "Current Service": "Storage", "Current Usage": "10 GB", "Current Cost (USD)": 0, "AWS Cost (USD)": 2, "GCP Cost (USD)": None}
    result = pricing_display_rows([row], ["GCP", "AWS"])[0]
    keys = list(result)
    assert keys.index("AWS Cost (USD)") == keys.index("Current Cost (USD)") + 1
    assert not {"Resource ID", "Current Service", "Current Usage"} & result.keys()
    assert result["AWS Cost (USD)"] == 2
    assert result["GCP Cost (USD)"] is None
    assert row["Resource ID"] == "id"


def test_zero_and_unknown_remain_distinct():
    rows = [{"Resource": "x", "Type": "other", "Current Cost (USD)": 0, "AWS Cost (USD)": None},
            {"Resource": "y", "Type": "other", "Current Cost (USD)": 1, "AWS Cost (USD)": 0}]
    result = pricing_display_rows(rows, ["AWS"])
    assert result[0]["AWS Cost (USD)"] is None
    assert result[1]["AWS Cost (USD)"] == 0


def test_successful_price_does_not_report_missing_evidence():
    rows = pricing_comparison_rows("Azure", {"AWS": [{"Resource": "x", "Resource ID": "id", "Source Billed Cost (USD)": 0, "Target Monthly Cost (USD)": 2}]})
    assert "No independent" not in rows[0]["AWS Pricing reason"]
