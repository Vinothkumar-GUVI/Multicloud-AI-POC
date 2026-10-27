"""Static regression guard for Streamlit widget identity collisions."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [
    ROOT / "app.py",
    ROOT / "multicloud_ai" / "phase_ui.py",
    ROOT / "multicloud_ai" / "login.py",
]
WIDGETS_REQUIRING_KEYS = {
    "button", "download_button", "text_input", "selectbox", "multiselect",
    "checkbox", "file_uploader", "radio", "slider", "number_input",
    "date_input", "time_input",
}


def _calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in WIDGETS_REQUIRING_KEYS
        ):
            yield node


def test_interactive_widgets_use_explicit_keys():
    missing = []
    for path in SOURCE_FILES:
        for node in _calls(path):
            if not any(keyword.arg == "key" for keyword in node.keywords):
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.func.attr}")
    assert not missing, "Streamlit widgets missing explicit keys: " + ", ".join(missing)


def test_literal_widget_keys_are_unique():
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for path in SOURCE_FILES:
        for node in _calls(path):
            key_kw = next((kw for kw in node.keywords if kw.arg == "key"), None)
            if key_kw is None:
                continue
            value = key_kw.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                key = value.value
                location = f"{path.relative_to(ROOT)}:{node.lineno}"
                if key in seen:
                    duplicates.append(f"{key!r}: {seen[key]} and {location}")
                else:
                    seen[key] = location
    assert not duplicates, "Duplicate literal Streamlit widget keys: " + "; ".join(duplicates)
