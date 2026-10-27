import pytest
from multicloud_ai.core.ai_settings import load_ai_defaults


def test_local_ai_values_and_env_fallback(tmp_path):
    p=tmp_path/"ai.toml"
    p.write_text('[ai]\nprovider="Azure OpenAI"\nmodel="deployment"\napi_key=""\n',encoding="utf-8")
    result=load_ai_defaults(p,{"OPENAI_API_KEY":"env-test-key"})
    assert result["ai_provider"]=="Azure OpenAI"
    assert result["ai_model"]=="deployment"
    assert result["ai_api_key"]=="env-test-key"
    assert "ai_consent" not in result


def test_missing_file_keeps_existing_environment_behavior(tmp_path):
    assert load_ai_defaults(tmp_path/"missing",{})["ai_provider"]=="OpenAI"


def test_parse_error_does_not_include_secret(tmp_path):
    p=tmp_path/"ai.toml";p.write_text('[ai]\napi_key=secret-test-value',encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_ai_defaults(p,{})
    assert "secret-test-value" not in str(error.value)
