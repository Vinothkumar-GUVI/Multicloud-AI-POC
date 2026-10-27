from types import SimpleNamespace
import pytest
from multicloud_ai.core.ai_comparison import apply_estimates
from multicloud_ai.core.comparison_model import compare_model
from multicloud_ai.core.terraform import provider
from multicloud_ai.core.validation import validate_terraform_text


def base():
    return compare_model([SimpleNamespace(resource_id="r",name="r",canonical_type="other",currency="USD",cost=100)], "Azure", {"AWS":1,"GCP":1})


def estimates(aws=80, gcp=90):
    return [{"resource_id":"r","targets":{c:{"monthly_cost_usd":n,"service":"Example","assumptions":"One instance, 730 hours; approximate rate", "components":[{"quantity":1,"unit":"month","rate_unit":"month","unit_price_usd":n,"description":"Monthly component","rate_basis":"Test fixture"}]} for c,n in [("AWS",aws),("GCP",gcp)]}}]


@pytest.mark.parametrize('problem', ['identical_duplicate', 'conflicting_duplicate', 'extra_unknown'])
def test_batch_id_errors_recover_without_double_counting_or_losing_cache(monkeypatch, problem):
    from copy import deepcopy
    from multicloud_ai.core import ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    responses = []
    def agent(*args, **kwargs):
        responses.append(kwargs)
        valid = estimates()
        if len(responses) == 1:
            extra = deepcopy(valid[0])
            if problem == 'extra_unknown':
                extra['resource_id'] = 'not-requested'
            elif problem == 'conflicting_duplicate':
                extra = estimates(70, 75)[0]
            valid.append(extra)
        return {'report': {'estimates': valid}}
    monkeypatch.setattr(comparison, 'run_agent', agent)
    cache = {}
    result = comparison.estimate_comparison(object(), [NormalizedResource('r','r','Azure','other',cost=100)],
                                            'Azure', None, [], [], estimate_cache=cache)
    assert result['totals']['AWS'] == 80
    assert result['totals']['GCP'] == 90
    assert len(cache[('r',)]) == 1
    assert ('not-requested',) not in cache
    assert len(responses) == (2 if problem == 'conflicting_duplicate' else 1)


@pytest.mark.parametrize("unit", ["100 GB/Month", "10000000", "1000 requests", ""])
def test_generated_estimates_require_explicit_unpacked_target_units(unit):
    baseline = base()
    baseline.update(require_components=True, require_canonical_target_units=True)
    rows = estimates()
    rows[0]["targets"]["AWS"]["components"][0]["rate_unit"] = unit
    with pytest.raises(ValueError, match="Ambiguous packed target pricing unit"):
        apply_estimates(baseline, rows)


def test_ai_estimates_determine_totals_and_current_can_win():
    assert apply_estimates(base(),estimates())["recommended"]=="AWS"
    assert apply_estimates(base(),estimates(110,120))["recommended"]=="Azure"
    assert apply_estimates(base(),estimates())["totals"]["Azure"]==100


@pytest.mark.parametrize("source_unit,target_unit,source_quantity,ai_quantity", [
    ("100000000", "requests", 16.032, 16032.19),
    ("100 GB/Month", "GB-month", 31.478, 32),
    ("100000000", "tokens", 211, 211000),
])
def test_export_pricing_labels_do_not_multiply_consumed_quantities(source_unit, target_unit, source_quantity, ai_quantity):
    import json
    baseline = base()
    baseline.update(require_components=True, usage_contracts={"r": {
        "meters": [{"quantity": source_quantity, "unit": source_unit}]}})
    rows = estimates()
    for detail in rows[0]["targets"].values():
        detail["components"] = [{"quantity": ai_quantity, "unit": target_unit, "rate_unit": target_unit,
            "unit_price_usd": .001, "meter_index": 0, "description": "test", "rate_basis": "unverified"}]
    result = apply_estimates(baseline, rows)
    part = json.loads(result["rows"][0]["AWS Calculation"])[0]
    assert part["quantity"] == ai_quantity
    assert "automatic pack multiplication" in part["usage_review"]
    assert "usage_conversion" not in part


def test_unreferenced_components_remain_estimates_with_review_flags():
    baseline = base()
    baseline.update(require_components=True, usage_contracts={"r": {
        "enforce_meter_units": True, "meters": [{"name": "usage", "quantity": 1, "unit": "month"}]}})
    result = apply_estimates(baseline, estimates())
    assert result["totals"]["AWS"] == 80
    import json
    assert "AI assumption" in json.loads(result["rows"][0]["AWS Calculation"])[0]["usage_review"]
    assert json.loads(result["rows"][0]["AWS Excluded Components"]) == []


def test_source_cost_allowance_is_not_accepted_as_target_estimate():
    rows = estimates()
    rows[0]["targets"]["AWS"]["service"] = "Source-cost planning allowance"
    with pytest.raises(ValueError, match="not a target estimate"):
        apply_estimates(base(), rows)


def test_missing_batch_resources_are_recovered_without_repricing_returned_rows(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    resources = [NormalizedResource(rid, rid, "Azure", "other", cost=100) for rid in ["r", "missing"]]
    calls = []

    def agent(role, client, evidence, **kwargs):
        requested = [r["resource_id"] for r in evidence["resources"]]
        calls.append(requested)
        result = estimates()
        result[0]["resource_id"] = requested[0]
        return {"report": {"estimates": result}}

    monkeypatch.setattr(comparison, "run_agent", agent)
    result = comparison.estimate_comparison(object(), resources, "Azure", None, [], [])
    assert calls == [["r", "missing"], ["missing"]]
    assert result["totals"] == {"Azure": 200, "AWS": 160, "GCP": 180}
    assert result["comparable_resources"] == 2


def test_invalid_row_retries_do_not_regenerate_valid_rows(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    resources = [NormalizedResource(rid, rid, "Azure", "other", cost=100) for rid in ["r", "repair"]]
    calls = []
    def agent(role, client, evidence, **kwargs):
        requested = [row["resource_id"] for row in evidence["resources"]]
        calls.append(requested)
        returned = []
        for rid in requested:
            entry = estimates()[0]
            entry["resource_id"] = rid
            if rid == "repair" and len(calls) == 1:
                entry["targets"]["AWS"]["components"][0]["unit"] = ""
            returned.append(entry)
        return {"report": {"estimates": returned}}
    monkeypatch.setattr(comparison, "run_agent", agent)
    result = comparison.estimate_comparison(object(), resources, "Azure", None, [], [])
    assert calls == [["r", "repair"], ["repair"]]
    assert result["totals"]["AWS"] == 160


def test_complex_resources_are_distributed_to_early_batches(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    resources = [NormalizedResource(str(i), str(i), "Azure", "other", cost=100) for i in range(9)]
    resources += [NormalizedResource(str(i), str(i), "Azure", "generative_ai", cost=100) for i in range(9, 12)]
    calls = []
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence["resources"])
        returned = []
        for row in evidence["resources"]:
            entry = estimates()[0]
            entry["resource_id"] = row["resource_id"]
            returned.append(entry)
        return {"report": {"estimates": returned}}
    monkeypatch.setattr(comparison, "run_agent", agent)
    result = comparison.estimate_comparison(object(), resources, "Azure", None, [], [])
    assert len(calls) == 3
    assert all(sum(row["type"] == "generative_ai" for row in batch) == 1 for batch in calls)
    assert result["totals"]["AWS"] == 960


def test_persistently_omitted_single_resource_has_bounded_retries(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    calls = []

    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        return {"report": {"estimates": []}}

    monkeypatch.setattr(comparison, "run_agent", agent)
    resource = NormalizedResource("r", "r", "Azure", "other", cost=100)
    with pytest.raises(ValueError, match="AI pricing omitted resources"):
        comparison.estimate_comparison(object(), [resource], "Azure", None, [], [])
    assert len(calls) == 3


def test_pricing_agent_answers_from_inline_evidence_in_one_request():
    import json
    from multicloud_ai.core.agents import run_agent
    calls = []

    class Client:
        model = "test-model"
        provider = "test-provider"
        def request(self, messages, tools, **kwargs):
            calls.append((messages, tools))
            return {"output": [{"type": "message", "content": [{"type": "output_text",
                "text": json.dumps({"estimates": estimates()})}]}]}

    result = run_agent("PricingEstimator", Client(), {"resources": [{"resource_id": "r"}]})
    assert result["report"]["estimates"] == estimates()
    assert len(calls) == 1
    assert calls[0][1] == []
    assert '"resource_id": "r"' in calls[0][0][1]["content"]
    assert "Never copy packed source" in calls[0][0][0]["content"]


def test_pricing_workers_have_no_http_timeout_or_processing_deadline(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    client = SimpleNamespace(request=lambda *args: None)
    def agent(role, worker, evidence, **kwargs):
        assert worker.request_timeout is None
        assert not hasattr(worker, "request_deadline")
        return {"report": {"estimates": estimates()}}
    monkeypatch.setattr(comparison, "run_agent", agent)
    result = comparison.estimate_comparison(client, [NormalizedResource("r", "r", "Azure", "other", cost=100)], "Azure", None, [], [])
    assert result["totals"]["AWS"] == 80


def test_inline_builder_returns_complete_draft_without_tool_round_trips():
    import json
    from multicloud_ai.core.agents import run_agent
    calls = []
    class Client:
        model = "test"
        provider = "test"
        def request(self, messages, tools, **kwargs):
            calls.append(tools)
            answer = {"summary": "Draft", "findings": [], "next_steps": [], "terraform": "resource draft"}
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]}
    result = run_agent("Builder", Client(), {"draft": {"terraform": "resource draft"}}, inline_evidence=True)
    assert result["report"]["terraform"] == "resource draft"
    assert calls == [[]]


@pytest.mark.parametrize("text", ["not JSON", '{"summary":"missing estimates"}'])
def test_malformed_inline_pricing_response_reports_format_error(text):
    from multicloud_ai.core.agents import run_agent
    calls = []

    class Client:
        model = "test-model"
        provider = "test-provider"
        def request(self, messages, tools, **kwargs):
            calls.append(messages[-1]["content"] if "content" in messages[-1] else "")
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    with pytest.raises(RuntimeError, match="invalid JSON or missing required report fields"):
        run_agent("PricingEstimator", Client(), {"resources": []}, max_turns=3)
    assert len(calls) == 2
    assert "No evidence-reading tool is required" in calls[1]


@pytest.mark.parametrize("wrapper", ["prose", "array", "nested", "singleton"])
def test_complete_pricing_json_wrappers_are_normalized(wrapper):
    import json
    from multicloud_ai.core.agents import _pricing_json
    rows = estimates()
    values = {"prose": "Here is the result:\n```json\n" + json.dumps({"estimates": rows}) + "\n```",
              "array": json.dumps(rows), "nested": json.dumps({"report": {"estimates": rows}}),
              "singleton": json.dumps(rows[0])}
    assert _pricing_json(values[wrapper])["estimates"] == rows


def test_truncated_pricing_json_is_not_repaired():
    from multicloud_ai.core.agents import _pricing_json
    with pytest.raises(ValueError):
        _pricing_json('{"estimates":[{"resource_id":"r","targets":')


def test_single_resource_format_failure_gets_one_fresh_retry(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    calls = []
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        if len(calls) == 1:
            raise RuntimeError("AI report rejected: invalid JSON or missing required report fields")
        return {"report": {"estimates": estimates()}}
    monkeypatch.setattr(comparison, "run_agent", agent)
    result = comparison.estimate_comparison(object(), [NormalizedResource("r", "r", "Azure", "other", cost=100)], "Azure", None, [], [])
    assert len(calls) == 2
    assert result["totals"]["AWS"] == 80


def test_read_timeout_splits_batch_and_saved_estimates_are_reused(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    calls = []
    resources = [NormalizedResource(rid, rid, "Azure", "other", cost=100) for rid in ["r", "s"]]

    def agent(role, client, evidence, **kwargs):
        requested = [r["resource_id"] for r in evidence["resources"]]
        calls.append(requested)
        if len(requested) > 1:
            raise RuntimeError("AI service did not return a response before the read timeout")
        result = estimates()
        result[0]["resource_id"] = requested[0]
        return {"report": {"estimates": result}}

    monkeypatch.setattr(comparison, "run_agent", agent)
    cache = {}
    first = comparison.estimate_comparison(object(), resources, "Azure", None, [], [], estimate_cache=cache)
    assert calls == [["r", "s"], ["r"], ["s"]]
    assert ("r",) in cache and ("s",) in cache
    second = comparison.estimate_comparison(object(), resources, "Azure", None, [], [], estimate_cache=cache)
    assert second["totals"] == first["totals"]
    assert len(calls) == 3


@pytest.mark.parametrize("repair", [True, False])
def test_logical_sql_mapping_retries_with_feedback_without_inventing_database(monkeypatch, repair):
    import multicloud_ai.core.ai_comparison as comparison
    from multicloud_ai.core.models import NormalizedResource
    rid = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Sql/servers/logical"
    resource = NormalizedResource(rid, "logical", "Azure", "relational_database", cost=10)
    calls = []

    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        service = "AWS security monitoring" if repair and len(calls) > 1 else "Amazon RDS PostgreSQL"
        details = estimates(2, 3)
        details[0]["resource_id"] = rid.lower()
        details[0]["targets"]["AWS"]["service"] = service
        details[0]["targets"]["GCP"]["service"] = "Google security monitoring"
        return {"report": {"estimates": details}}

    monkeypatch.setattr(comparison, "run_agent", agent)
    if repair:
        result = comparison.estimate_comparison(object(), [resource], "Azure", None, [], [])
        assert result["totals"] == {"Azure": 10, "AWS": 2, "GCP": 3}
        assert result["excluded_resources"] == 0
        assert len(calls) == 2
    else:
        with pytest.raises(ValueError, match="SQL logical server/security charges"):
            comparison.estimate_comparison(object(), [resource], "Azure", None, [], [])
        assert len(calls) == 3
    assert "security/control-plane workload" in calls[1]["validation_feedback"]["error"]
    assert rid.lower() in calls[1]["validation_feedback"]["error"]


@pytest.mark.parametrize("value", [-1,float("nan"),float("inf"),True])
def test_bad_ai_prices_rejected(value):
    with pytest.raises(ValueError):apply_estimates(base(),estimates(value))


def test_missing_duplicate_or_unexplained_estimates_rejected():
    for rows in [[], estimates()*2]:
        with pytest.raises(ValueError):apply_estimates(base(),rows)
    rows=estimates();rows[0]["targets"]["AWS"]["assumptions"]=""
    with pytest.raises(ValueError):apply_estimates(base(),rows)


@pytest.mark.parametrize("name", ["Azure","AZURE","azure"])
def test_azure_provider_is_case_insensitive(name):
    text=provider(name)
    assert 'hashicorp/azurerm' in text
    assert 'hashicorp/google' not in text
    assert validate_terraform_text(text,"Azure").valid


def test_wrong_cloud_draft_rejected_even_with_azure_comments():
    report=validate_terraform_text(provider("GCP")+'\n# Azure azurerm reconstruction',"Azure")
    assert not report.valid
    assert any("cloud mismatch" in e for e in report.errors)


def test_ai_pricing_ui_generates_comparison_and_recommendation(monkeypatch):
    import multicloud_ai.review_workflow as ui
    import multicloud_ai.core.ai_comparison as comparison
    from streamlit.testing.v1 import AppTest
    calls=[]
    monkeypatch.setattr(ui,"client",lambda: object())
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        return {"report":{"estimates":estimates()}}
    monkeypatch.setattr(comparison,"run_agent",agent)
    drafts=[]
    def draft(*args, **kwargs):
        drafts.append(args[:2])
        return {"text":"terraform {}\n"}
    monkeypatch.setattr(ui,"tf_panel",draft)
    app=AppTest.from_string("""
from multicloud_ai.review_workflow import render_workflow
from multicloud_ai.core.models import NormalizedResource
r=NormalizedResource('r','r','Azure','block_storage',cost=100,region='eastus',configuration={'storage':{'size_gb':32}})
render_workflow('Azure',[r],[r],[],{'days':30})
""").run()
    assert not app.exception
    assert app.radio(key="pricing_method").value=="AI resource estimates"
    app.button(key="generate_ai_pricing").click().run()
    assert not app.exception
    assert calls[0]["scope"]["targets"]==["AWS","GCP"]
    assert len(calls[0]["resources"])==1
    assert any("Recommended" in message.value and "AWS" in message.value for message in app.success)
    app.button(key="accept_model_target").click().run()
    assert not app.exception
    assert ("Target cloud Terraform", "AWS") in drafts
    assert app.metric[1].value=="$80.00"
    requests_before=len(calls)
    app.button(key="generate_ai_pricing").click().run()
    assert len(calls)==requests_before
    app.checkbox(key="refresh_ai_pricing").check().run()
    app.button(key="generate_ai_pricing").click().run()
    assert len(calls)==requests_before+1
