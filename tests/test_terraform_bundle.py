from io import BytesIO
from pathlib import Path
import subprocess
from zipfile import ZipFile
import hcl2
import pytest
from multicloud_ai.core.terraform_bundle import split_terraform, bundle_zip
from multicloud_ai.core.terraform_runner import terraform_executable


def test_split_project_preserves_nested_variables_comments_and_defaults(tmp_path):
    text = '''# source import mapping stays in main
variable "settings" {
  type = map(string)
  default = { region = "eastus", label = "brace } stays quoted" }
}
variable "password" {
  type = string
  sensitive = true
}
resource "terraform_data" "example" {
  input = var.settings
}
'''
    files = split_terraform(text)
    assert set(files) == {'main.tf', 'variables.tf', 'terraform.tfvars'}
    assert 'variable "' not in files['main.tf']
    assert '# source import mapping' in files['main.tf']
    assert 'password = null' in files['terraform.tfvars']
    assert hcl2.loads(files['terraform.tfvars'])['settings']
    original = hcl2.loads(text)
    combined = hcl2.loads(files['main.tf'] + files['variables.tf'])
    assert original == combined
    with ZipFile(BytesIO(bundle_zip(files))) as archive:
        assert set(archive.namelist()) == set(files)
        archive.extractall(tmp_path)
    executable = terraform_executable()
    if not executable:
        pytest.skip('Terraform unavailable')
    for args in [['fmt', '-no-color'], ['init', '-backend=false', '-input=false'], ['validate', '-no-color']]:
        result = subprocess.run([executable, *args], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_variable_heredoc_and_resource_comments_are_preserved():
    text = '''variable "script" {
  default = <<-EOT
hello { braces }
EOT
}
locals {
  text = "variable fake { }"
}
'''
    files = split_terraform(text)
    assert hcl2.loads(files['terraform.tfvars'])['script']
    assert 'locals {' in files['main.tf']


def test_split_removes_variable_gaps_but_preserves_multiline_value_spacing():
    text = '''resource "terraform_data" "first" { input = "first" }
''' + '\n' * 180 + '''variable "script" {
  default = <<-EOT
first



last
EOT
}
''' + '\n' * 10 + '''resource "terraform_data" "second" { input = var.script }
'''
    files = split_terraform(text)
    assert '\n\n\n' not in files['main.tf']
    assert 'first\n\n\n\nlast' in files['variables.tf']
    assert 'first\n\n\n\nlast' in files['terraform.tfvars']
    assert hcl2.loads(text) == hcl2.loads(files['main.tf'] + files['variables.tf'])


@pytest.mark.parametrize('key,cloud', [('current_cloud_tf','AWS'), ('confirmed_target_tf','GCP')])
def test_panels_offer_all_three_files_and_zip_by_default(monkeypatch,key,cloud):
    from streamlit.testing.v1 import AppTest
    from multicloud_ai import review_workflow as workflow
    monkeypatch.setattr(workflow, 'validate_cli', lambda text, target: {'valid':True,'status':'passed','diagnostics':[]})
    def no_ai(*args, **kwargs):
        raise AssertionError('Default fast generation must not call AI')
    monkeypatch.setattr(workflow, 'run_agent', no_ai)
    script = f'''
from multicloud_ai.review_workflow import tf_panel
from multicloud_ai.core.models import NormalizedResource
r=NormalizedResource('r','store','AWS','object_storage',region='us-east-1')
tf_panel('Terraform','{cloud}',[r],[],[],[],'{key}','test')
'''
    app = AppTest.from_string(script).run()
    assert not app.checkbox(key=key+'_ai').value
    app.button(key=key+'_generate').click().run()
    assert not app.exception and not app.error
    assert [t.label for t in app.tabs] == ['main.tf','variables.tf','terraform.tfvars']
    assert set(app.session_state[key+'_result']['files']) == {'main.tf','variables.tf','terraform.tfvars'}
