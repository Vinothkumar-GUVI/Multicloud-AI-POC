"""Terraform syntax/schema checks in an isolated directory. Never plan or apply."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from .validation import validate_terraform_text


def terraform_executable():
    local = Path(__file__).resolve().parents[2] / 'tools' / ('terraform.exe' if os.name == 'nt' else 'terraform')
    return str(local) if local.exists() else shutil.which('terraform')


def validate_cli(text, target):
    basic = validate_terraform_text(text, target).to_dict()
    report = {'status': 'not_run', 'valid': False, 'basic': basic, 'commands': [],
              'diagnostics': [], 'sha256': hashlib.sha256(text.encode()).hexdigest()}
    # Untrusted generated code cannot introduce executable provisioners or providers.
    import hcl2
    try:
        parsed = hcl2.loads(text)
    except Exception:
        report.update(status='blocked', diagnostics=['HCL must parse successfully before automatic initialization.'])
        return report
    remote_backend = any('backend' in block for block in parsed.get('terraform', []))
    if remote_backend or re.search(r'\b(provisioner|module)\s*["{]|\bdata\s+"external"', text):
        report.update(status='blocked', diagnostics=['External modules, backends, external data and provisioners are prohibited in automatic validation.'])
        return report
    sources = re.findall(r'\bsource\s*=\s*"([^"]+)"', text)
    approved_sources = {'hashicorp/aws', 'hashicorp/azurerm', 'hashicorp/google', 'hashicorp/random'}
    approved_families = {'aws', 'azurerm', 'google', 'random', 'terraform'}
    if str(target).upper() == 'GCP':
        approved_sources.add('mongodb/mongodbatlas')
        approved_families.add('mongodbatlas')
    if any(s not in approved_sources for s in sources):
        report.update(status='blocked', diagnostics=['Only approved cloud and MongoDB Atlas providers can be initialized.'])
        return report
    declarations = re.findall(r'\b(?:resource|data)\s+"([^"]+)"', text)
    providers = re.findall(r'\bprovider\s+"([^"]+)"', text)
    if any(t.split('_')[0] not in approved_families for t in declarations) or any(p not in approved_families - {'terraform'} for p in providers):
        report.update(status='blocked', diagnostics=['Unapproved provider or resource type in candidate.'])
        return report
    executable = terraform_executable()
    if not executable:
        report['diagnostics'] = ['Terraform CLI not installed. Install Terraform or place it in the project tools directory.']
        return report
    # No cloud or model secrets are inherited by validation subprocesses.
    allowed = {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(TF_IN_AUTOMATION='1', CHECKPOINT_DISABLE='1', TF_INPUT='0')
    with tempfile.TemporaryDirectory(prefix='multicloud-tf-') as folder:
        env['HOME'] = folder
        env['USERPROFILE'] = folder
        env['TF_CLI_CONFIG_FILE'] = str(Path(folder) / 'empty.tfrc')
        Path(env['TF_CLI_CONFIG_FILE']).write_text('', encoding='utf-8')
        Path(folder, 'main.tf').write_text(text, encoding='utf-8')
        for args in (['fmt', '-no-color'], ['init', '-backend=false', '-input=false', '-no-color'], ['validate', '-json', '-no-color']):
            try:
                result = subprocess.run([executable, *args], cwd=folder, env=env, capture_output=True,
                    text=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (subprocess.TimeoutExpired, OSError):
                report.update(status='error', diagnostics=['Terraform command failed or timed out: ' + args[0]])
                return report
            report['commands'].append({'command': args[0], 'exit_code': result.returncode})
            if args[0] == 'validate':
                try:
                    payload = json.loads(result.stdout)
                except ValueError:
                    payload = {'valid': False, 'diagnostics': [{'summary': 'Invalid Terraform CLI response'}]}
                report.update(status='passed' if payload.get('valid') and result.returncode == 0 else 'failed',
                              valid=bool(payload.get('valid')) and result.returncode == 0,
                              diagnostics=payload.get('diagnostics', []))
            elif result.returncode:
                report.update(status='failed', diagnostics=[(result.stderr or result.stdout)[-16000:]])
                return report
        report['formatted_terraform'] = Path(folder, 'main.tf').read_text(encoding='utf-8')
    return report


def repair_terraform(text, target, client, evidence, attempts=2):
    from .agents import run_agent
    original_addresses = set(re.findall(r'^resource\s+"([^"]+)"\s+"([^"]+)"', text, re.M))
    history = []
    current = text
    for attempt in range(attempts + 1):
        check = validate_cli(current, target)
        history.append({'attempt': attempt, 'validation': check})
        if check['valid'] or check['status'] in {'blocked', 'not_run', 'error'} or attempt == attempts:
            return {'terraform': current, 'validation': check, 'history': history}
        context = dict(evidence, terraform={'target': target, 'text': current}, diagnostics=check)
        agent = run_agent('Builder', client, context)
        proposal = agent['report'].get('terraform', '')
        history[-1]['agent'] = agent
        addresses = set(re.findall(r'^resource\s+"([^"]+)"\s+"([^"]+)"', proposal, re.M))
        if not proposal or addresses != original_addresses:
            history[-1]['rejection'] = 'Repair must preserve the complete set of resource addresses.'
            return {'terraform': current, 'validation': check, 'history': history}
        current = proposal
