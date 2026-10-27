"""Regression checks for Streamlit widget identity collisions.

Streamlit auto-generates widget IDs from widget type and arguments. Download buttons
that intentionally expose similar artifacts in different parts of the page therefore
must use explicit unique keys.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "app.py", ROOT / "multicloud_ai" / "phase_ui.py"]


def _download_button_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "download_button"
        ):
            yield node


def test_every_download_button_has_explicit_key():
    missing = []
    for path in FILES:
        for node in _download_button_calls(path):
            if not any(keyword.arg == "key" for keyword in node.keywords):
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not missing, "download_button calls missing explicit key: " + ", ".join(missing)


def test_literal_download_button_keys_are_unique():
    seen: dict[str, str] = {}
    duplicates = []
    for path in FILES:
        for node in _download_button_calls(path):
            key_kw = next((kw for kw in node.keywords if kw.arg == "key"), None)
            if key_kw is None or not isinstance(key_kw.value, ast.Constant) or not isinstance(key_kw.value.value, str):
                continue
            key = key_kw.value.value
            location = f"{path.relative_to(ROOT)}:{node.lineno}"
            if key in seen:
                duplicates.append(f"{key!r}: {seen[key]} and {location}")
            else:
                seen[key] = location
    assert not duplicates, "duplicate literal Streamlit download keys: " + "; ".join(duplicates)
