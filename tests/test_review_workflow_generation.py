from streamlit.testing.v1 import AppTest
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.review_workflow import draft_mappings
from multicloud_ai.core.terraform import generate


def test_source_aws_preserves_existing_instance_type():
    r=NormalizedResource("r","vm","AWS","compute_instance",region="us-east-1",sku="t3.medium",
                         configuration={"compute":{"instance_type":"t3.medium","vcpu":2,"memory_gb":4}})
    rows=draft_mappings([r],"AWS",True)
    assert rows[0]["Target SKU"]=="t3.medium"
    assert 'instance_type = "t3.medium"' in generate([r],[],"AWS",target_configurations=rows)


def test_aws_source_ai_receives_billing_configuration_and_dependency_evidence(monkeypatch):
    import multicloud_ai.review_workflow as workflow
    calls=[]
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        return {"report":{"terraform": evidence["draft"]["terraform"]}}
    monkeypatch.setattr(workflow,"client",lambda: object())
    monkeypatch.setattr(workflow,"run_agent",agent)
    script = """
from multicloud_ai.review_workflow import render_workflow
from multicloud_ai.core.models import NormalizedResource
r=NormalizedResource('r','disk','AWS','block_storage',region='us-east-1',sku='gp3',cost=10,configuration={'storage':{'size_gb':32}})
render_workflow('AWS',[r],[r],[],{'days':30})
"""
    app=AppTest.from_string(script).run()
    assert not app.exception
    assert not any('Pricing Comparison' in h.value for h in app.header)
    app.button(key='current_cloud_tf_generate').click().run()
    assert not app.exception
    assert calls and calls[0]['billing'][0]['Cost USD']==10
    assert calls[0]['configurations'][0]['Configuration']['storage_gb']==32
    assert 'dependencies' in calls[0]
    assert any('Pricing Comparison' in h.value for h in app.header)
    assert any('AI-generated draft' in c.value for c in app.caption)


import pytest

@pytest.fixture(autouse=True)
def isolated_provider_validation(monkeypatch):
    # UI tests exercise the generation flow; provider checks have separate tests.
    import multicloud_ai.review_workflow as workflow
    monkeypatch.setattr(workflow, 'validate_cli', lambda text, cloud: {
        'status': 'passed', 'valid': True, 'diagnostics': [], 'formatted_terraform': text})

@pytest.mark.parametrize("response", ["", "not terraform", RuntimeError("AI connection failed")])
def test_ai_failure_retains_draft_and_allows_pricing(monkeypatch, response):
    import multicloud_ai.review_workflow as workflow
    def agent(*args, **kwargs):
        if isinstance(response, Exception):
            raise response
        return {"report": {"terraform": response}}
    monkeypatch.setattr(workflow, "client", lambda: object())
    monkeypatch.setattr(workflow, "run_agent", agent)
    script = """
from multicloud_ai.review_workflow import render_workflow
from multicloud_ai.core.models import NormalizedResource
r=NormalizedResource('r','disk','AWS','block_storage',region='us-east-1',sku='gp3',cost=10,configuration={'storage':{'size_gb':32}})
render_workflow('AWS',[r],[r],[],{'days':30})
"""
    app = AppTest.from_string(script).run()
    app.button(key="current_cloud_tf_generate").click().run()
    assert not app.exception
    assert not app.error
    assert any("Pricing Comparison" in h.value for h in app.header)
    saved = app.session_state["current_cloud_tf_result"]
    assert saved["text"] and saved["origin"] == "Deterministic draft"
    assert saved["ai_notice"]
    if response == 'not terraform':
        assert 'AI output rejected:' in saved['ai_notice']
        assert 'HCL syntax error' in saved['ai_notice']
        assert 'review it before use' not in saved['ai_notice']
    assert app.code[0].value.strip() == saved["text"].strip()
    app.run()
    assert any(saved["ai_notice"] == w.value for w in app.warning)


def test_configuration_table_wraps_full_values_and_escapes_html():
    from multicloud_ai.review_workflow import configuration_table_html
    long_value = "long-value-" * 100
    output = configuration_table_html([{"Resource":"<script>alert(1)</script>", "Service":"Disk",
                                       "Region":"eastus", "Configuration":{"details":long_value}}])
    assert long_value in output
    assert "overflow-wrap:anywhere" in output
    assert "white-space:normal" in output
    assert "<script>" not in output
    assert "&lt;script&gt;" in output


def test_failed_provider_validation_does_not_save_or_display_candidate(monkeypatch):
    import multicloud_ai.review_workflow as workflow
    monkeypatch.setattr(workflow, 'validate_cli', lambda *args: {
        'status': 'failed', 'valid': False, 'diagnostics': [{'summary': 'Unsupported argument', 'detail': 'bad field'}]})
    script = '''
from multicloud_ai.review_workflow import tf_panel
from multicloud_ai.core.models import NormalizedResource
r=NormalizedResource('r','disk','AWS','block_storage',region='us-east-1',sku='gp3',configuration={'storage':{'size_gb':32}})
tf_panel('Source','AWS',[r],[],[],[],'current_cloud_tf','test')
'''
    app = AppTest.from_string(script).run()
    app.checkbox(key='current_cloud_tf_ai').uncheck().run()
    app.button(key='current_cloud_tf_generate').click().run()
    assert not app.exception
    assert any('failed provider validation' in error.value for error in app.error)
    assert not app.code
    with pytest.raises(KeyError):
        app.session_state['current_cloud_tf_result']
