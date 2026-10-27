import pandas as pd
from multicloud_ai.core.pricing_presentation import with_input_guidance, wrapped_table, next_input


def test_guidance_keeps_numeric_zero_and_does_not_mutate_evidence():
    rows=[{"Type":"search","AWS Cost (USD)":None},{"AWS Cost (USD)":0}]
    display=[{"AWS Cost (USD)":"Sizing required"},{"AWS Cost (USD)":"0.000000"}]
    output=with_input_guidance(rows,display,["AWS"])
    assert "(Client:" in output[0]["AWS Cost (USD)"]
    assert "node type/count" in output[0]["AWS Cost (USD)"]
    assert output[1]["AWS Cost (USD)"]=="0.000000"
    assert display[0]["AWS Cost (USD)"]=="Sizing required"
    assert rows[0]["AWS Cost (USD)"] is None


def test_sql_guidance_does_not_ask_to_create_database():
    text=next_input({"AWS Display status":"RDS pricing not applicable - no user database identified"})
    assert "No database needs to be created" in text
    assert "If none exists, no RDS estimate is applicable" in text


def test_html_escapes_resource_and_reason_and_enables_wrapping():
    html=wrapped_table(pd.DataFrame([{"Resource":"<script>alert(1)</script>","AWS Cost (USD)":"<img src=x onerror=alert(1)>"}]))
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
    assert "white-space:normal" in html
