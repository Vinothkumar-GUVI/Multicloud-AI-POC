from types import SimpleNamespace
from multicloud_ai.core.advisory_presentation import assessment_counts
from streamlit.testing.v1 import AppTest


def test_counts_use_plan_not_ai_summary():
    counts = assessment_counts([1, 2, 3], [{"strategy": "Rehost", "wave": 1}, {"strategy": "Rehost", "wave": 2}, {"strategy": "Review", "wave": 3}])
    assert counts == {"resources": 3, "strategies": {"Rehost": 2, "Review": 1}, "waves": {1: 1, 2: 1, 3: 1}}


def test_dashboard_renders_without_promoting_partial_savings():
    app = AppTest.from_string("""
from multicloud_ai.core.advisory_presentation import render_assessment
render_assessment('AWS', [1, 2], [{"Current Service": "Azure VM", "Target Service": "EC2", "Target Configuration Status": "Validation required"}],
    [{"strategy": "Rehost", "wave": 1}, {"strategy": "Review", "wave": 2}],
    {"coverage_pct": 75.6, "comparable_savings": 7.19, "comparable_savings_pct": 10.6})
""").run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['2', '75.6%', 'Not established', 'Validation required']
    assert len(app.dataframe) == 1
