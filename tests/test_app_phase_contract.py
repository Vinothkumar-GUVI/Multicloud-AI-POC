from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_uses_requested_migration_workbench_flow_without_phase_labels():
    text = (ROOT / 'app.py').read_text(encoding='utf-8') + (ROOT / 'multicloud_ai/review_workflow.py').read_text(encoding='utf-8')
    for heading in [
        'Current Cloud Overview',
        'Dependency Architecture',
        'Cloud-Neutral Resource Model',
        'Pricing Comparison',
        'Target Cloud Decision',
        'Current resource configurations',
        'Current cloud Terraform',
        'Target cloud Terraform',
    ]:
        assert heading in text
    assert 'Phase 0 —' not in text
    assert 'Phase 1 —' not in text
    assert 'Phase 2 — Discovery Planner' not in text
    assert 'Discovery Planner' not in text
    assert 'Run Scout AI Agent' not in text
    assert 'Run FinOps AI Agent' not in text
    assert 'Generate AI migration advisory' in (ROOT / 'multicloud_ai' / 'phase_ui.py').read_text(encoding='utf-8')


def test_release_keeps_in_app_cloud_credentials():
    text = (ROOT / 'app.py').read_text(encoding='utf-8') + (ROOT / 'multicloud_ai/review_workflow.py').read_text(encoding='utf-8')
    assert 'Tenant ID' in text and 'Client Secret' in text
    assert 'Access Key ID' in text and 'Secret Access Key' in text
    assert 'Service Account JSON file' in text


def test_terraform_is_gated_by_target_confirmation_and_client_approval():
    text = (ROOT / 'app.py').read_text(encoding='utf-8') + (ROOT / 'multicloud_ai/review_workflow.py').read_text(encoding='utf-8')
    assert 'Accept recommendation: ' in text
    assert 'model_decision' in text
    assert 'decision_sig' in text
