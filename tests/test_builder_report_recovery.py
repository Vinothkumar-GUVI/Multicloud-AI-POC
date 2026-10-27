import json
from unittest.mock import Mock
import pytest
from multicloud_ai.core.agents import run_agent


def final(text):
    return {"output": [{"type":"message", "content":[{"type":"output_text", "text":text}]}]}


def test_builder_retries_bad_format_once_after_reading_evidence():
    c=Mock(model="test", provider="test")
    tool={"output":[{"type":"function_call", "name":"read_evidence", "call_id":"1",
                     "arguments":json.dumps({"section":"draft","offset":0})}]}
    answer={"summary":"Reviewed", "findings":[], "next_steps":[], "terraform":"terraform {}"}
    c.request.side_effect=[tool, final("Here is the code"), final(json.dumps(answer))]
    result=run_agent("Builder", c, {"draft":{"terraform":"terraform {}"}})
    assert result["report"]["terraform"]=="terraform {}"
    assert c.request.call_count==3


def test_builder_does_not_accept_report_without_evidence_after_retry():
    c=Mock()
    c.request.return_value=final(json.dumps({"summary":"Reviewed", "findings":[], "next_steps":[], "terraform":"terraform {}"}))
    with pytest.raises(RuntimeError, match="no successful evidence read"):
        run_agent("Builder",c,{"draft":{}})
    assert c.request.call_count==2


def test_incomplete_response_is_not_treated_as_complete_code():
    c=Mock()
    c.request.return_value={"status":"incomplete", "incomplete_details":{"reason":"max_output_tokens"}, "output":[]}
    with pytest.raises(RuntimeError, match="max_output_tokens"):
        run_agent("Builder",c,{"draft":{}})


def test_pricing_accepts_estimates_without_unrelated_advisory_fields():
    c=Mock(model="test", provider="test")
    tool={"output":[{"type":"function_call", "name":"read_evidence", "call_id":"1",
                     "arguments":json.dumps({"section":"resources","offset":0})}]}
    c.request.side_effect=[tool, final("not JSON"), final(json.dumps({"estimates":[]}))]
    result=run_agent("PricingEstimator",c,{"resources":[]})
    assert result["report"]["estimates"]==[]
    assert c.request.call_count==3
    assert "No Markdown" in c.request.call_args[0][0][-2]["content"]


def test_builder_retries_truncation_with_larger_budget_without_partial_code():
    c=Mock(model="test",provider="test")
    tool={"output":[{"type":"function_call", "name":"read_evidence", "call_id":"1",
                     "arguments":json.dumps({"section":"draft","offset":0})}]}
    incomplete={"status":"incomplete", "incomplete_details":{"reason":"max_output_tokens"}, "output":[]}
    answer={"summary":"Reviewed","findings":[],"next_steps":[],"terraform":"complete code"}
    c.request.side_effect=[tool,incomplete,final(json.dumps(answer))]
    result=run_agent("Builder",c,{"draft":{}})
    assert result["report"]["terraform"]=="complete code"
    assert [call.kwargs["max_output_tokens"] for call in c.request.call_args_list]==[16000,16000,32000]


def test_pricing_ignores_unrelated_report_fields():
    c=Mock(model="test", provider="test")
    tool={"output":[{"type":"function_call", "name":"read_evidence", "call_id":"1",
                     "arguments":json.dumps({"section":"resources","offset":0})}]}
    c.request.side_effect=[tool, final(json.dumps({"estimates":[], "findings":None,"terraform":None,"summary":None}))]
    assert run_agent("PricingEstimator",c,{"resources":[]})["report"]["estimates"] == []


def test_pricing_rejects_advisory_report_without_estimates():
    c=Mock(model="test", provider="test")
    tool={"output":[{"type":"function_call", "name":"read_evidence", "call_id":"1",
                     "arguments":json.dumps({"section":"resources","offset":0})}]}
    answer=final(json.dumps({"summary":"ok","findings":[],"next_steps":[],"terraform":""}))
    c.request.side_effect=[tool,answer,answer]
    with pytest.raises(RuntimeError,match="invalid JSON"):
        run_agent("PricingEstimator",c,{"resources":[]})
    assert '"components"' in c.request.call_args[0][0][-2]["content"]
