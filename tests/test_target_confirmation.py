from streamlit.testing.v1 import AppTest

SCRIPT = """
import streamlit as st
from types import SimpleNamespace
import multicloud_ai.review_workflow as workflow
from multicloud_ai.core.models import NormalizedResource
r=NormalizedResource("r", "disk", "Azure", "block_storage", region="eastus", cost=100, configuration={"storage":{"size_gb":32}})
def fake_panel(label, cloud, *args):
    st.header(label)
    return {"text":"draft"}
workflow.tf_panel=fake_panel
workflow.render_workflow("Azure", [r], [r], [], {"days":30})
"""


def test_acceptance_is_invalidated_by_factor_change_and_stay_has_no_target_code():
    app=AppTest.from_string(SCRIPT).run()
    assert not app.exception
    app.radio(key="pricing_method").set_value("Manual factor scenario").run()
    assert all(h.value != "Target cloud Terraform" for h in app.header)
    app.button(key="accept_model_target").click().run()
    assert any(h.value == "Target cloud Terraform" for h in app.header)
    app.number_input(key="model_factor_Azure_GCP").set_value(1.2).run()
    assert all(h.value != "Target cloud Terraform" for h in app.header)
    app.number_input(key="model_factor_Azure_AWS").set_value(1.2).run()
    app.button(key="accept_model_target").click().run()
    assert not app.exception
    assert any("Current cloud retained" in m.value for m in app.success)
    assert all(h.value != "Target cloud Terraform" for h in app.header)
