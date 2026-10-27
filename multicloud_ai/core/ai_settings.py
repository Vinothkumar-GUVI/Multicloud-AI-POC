"""Load only AI connection settings; never persist session overrides or consent."""
import os
import tomllib
from pathlib import Path

AI_FILE = Path(__file__).resolve().parents[2] / ".streamlit" / "ai.toml"


def load_ai_defaults(path=None, environ=None):
    env = os.environ if environ is None else environ
    defaults = {"ai_provider":env.get("AI_PROVIDER", "OpenAI"),
                "ai_api_key":env.get("OPENAI_API_KEY", ""),
                "ai_model":env.get("OPENAI_MODEL", ""),
                "ai_base_url":env.get("OPENAI_BASE_URL", ""),
                "ai_proxy_url":env.get("AI_HTTPS_PROXY", "")}
    path = Path(path) if path is not None else AI_FILE
    if path.exists():
        try:
            with path.open("rb") as f:
                data=tomllib.load(f).get("ai", {})
            if not isinstance(data,dict):
                raise ValueError()
            for name in ("provider","api_key","model","base_url","proxy_url"):
                value=data.get(name, "")
                if not isinstance(value,str):
                    raise ValueError()
                if value.strip():
                    defaults["ai_"+name]=value.strip()
        except (OSError,ValueError):
            raise ValueError("Could not read .streamlit/ai.toml. Check TOML syntax and use quoted text values; configuration contents are not included in this error.") from None
    if defaults["ai_provider"] not in {"OpenAI","Azure OpenAI","OpenAI-compatible"}:
        raise ValueError("AI provider must be OpenAI, Azure OpenAI, or OpenAI-compatible.")
    return defaults
