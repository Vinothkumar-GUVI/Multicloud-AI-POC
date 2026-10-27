"""Streamlit smoke flow with synthetic billing and mocked external cloud calls."""
from pathlib import Path
import unittest
import pytest

streamlit = pytest.importorskip('streamlit')
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class UIWorkBenchTests(unittest.TestCase):
    def test_empty_startup(self):
        app = AppTest.from_file(str(ROOT / 'app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any(x.label == 'AI API key' for x in app.text_input))
        self.assertTrue(any('Upload AWS, Azure, or GCP billing export' in x.label for x in app.file_uploader))

    def test_requested_sections_are_present_in_source(self):
        text = (ROOT / 'app.py').read_text(encoding='utf-8') + (ROOT / 'multicloud_ai/review_workflow.py').read_text(encoding='utf-8')
        for heading in (
            'Current Cloud Overview', 'Dependency Architecture', 'Cloud-Neutral Resource Model',
            'Pricing Comparison', 'Target Cloud Decision', 'Current resource configurations',
            'Current cloud Terraform', 'Target cloud Terraform',
        ):
            self.assertIn(heading, text)
        self.assertNotIn('Phase 0 —', text)
        self.assertNotIn('Phase 2 — Discovery Planner', text)
