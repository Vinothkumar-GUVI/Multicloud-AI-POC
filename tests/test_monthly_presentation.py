from copy import deepcopy
from multicloud_ai.core.monthly_presentation import planning_tables


def test_missing_costs_stay_in_review_zero_remains_estimate_and_input_unchanged():
    rows = [{"Resource": "one", "Current monthly component (USD)": None,
             "AWS monthly component (USD)": 0.0, "AWS estimate basis": "Default assumption",
             "Current estimate basis": "Source catalog unavailable", "Current basis": "Network error"},
            {"Resource": "two", "Current monthly component (USD)": 5.0,
             "AWS monthly component (USD)": float("inf"), "AWS basis": "Missing rate"}]
    original = deepcopy(rows)
    estimates, review = planning_tables(rows)
    assert len(estimates["AWS"]) == len(estimates["Azure"]) == 1
    assert estimates["AWS"][0]["Monthly component (USD)"] == 0
    assert estimates["AWS"][0]["Estimate basis"] == "Default assumptions"
    assert len(review) == 2
    assert review[0]["Status"] == "Source catalog unavailable"
    assert review[0]["Explanation"] == "Network error"
    assert rows == original
