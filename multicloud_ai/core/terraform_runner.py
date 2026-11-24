"""Terraform syntax/schema checks in an isolated directory. Never plan or apply."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from .validation import validate_terraform_text

_PROVIDER_CACHE_LOCK = threading.Lock()


def validation_cli_config(root):
    """Reuse verified provider packages without inheriting user CLI settings."""
    root = Path(root)
    cache = root / 'tools' / 'terraform-provider-cache'
    cache.mkdir(parents=True, exist_ok=True)
    config = 'plugin_cache_dir = ' + json.dumps(cache.as_posix()) + '\n'
    mirror = root / 'tools' / 'provider-mirror'
    available = []
    for provider in ('hashicorp/aws', 'hashicorp/azurerm', 'hashicorp/google',
                     'hashicorp/random', 'mongodb/mongodbatlas'):
        directory = mirror / 'registry.terraform.io' / provider
        cached = cache / 'registry.terraform.io' / provider
        # A plugin cache alone still requires registry version discovery. Make
        # complete installed packages available as an unpacked filesystem mirror.
        if cached.is_dir():
            for package in cached.glob('*/*/terraform-provider-*'):
                if not package.is_file() or package.stat().st_size == 0:
                    continue
                if not re.fullmatch(r'\d+\.\d+\.\d+', package.parent.parent.name):
                    continue
                if not re.fullmatch(r'(windows|linux|darwin)_(amd64|arm64)', package.parent.name):
                    continue
                destination = directory / package.relative_to(cached)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    try:
                        os.link(package, destination)
                    except OSError:
                        shutil.copy2(package, destination)
        if directory.is_dir() and (any(directory.glob('terraform-provider-*.zip'))
                                  or any(directory.glob('*/*/terraform-provider-*'))):
            available.append('registry.terraform.io/' + provider)
    if available:
        patterns = json.dumps(available)
        config += ('provider_installation {\n  filesystem_mirror {\n    path = '
                   + json.dumps(mirror.as_posix()) + '\n    include = ' + patterns
                   + '\n  }\n  direct {\n    exclude = ' + patterns + '\n  }\n}\n')
    return config


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
    with _PROVIDER_CACHE_LOCK, tempfile.TemporaryDirectory(prefix='multicloud-tf-') as folder:
        env['HOME'] = folder
        env['USERPROFILE'] = folder
        env['TF_CLI_CONFIG_FILE'] = str(Path(folder) / 'empty.tfrc')
        Path(env['TF_CLI_CONFIG_FILE']).write_text(
            validation_cli_config(Path(__file__).resolve().parents[2]), encoding='utf-8')
        Path(folder, 'main.tf').write_text(text, encoding='utf-8')
        for args in (['fmt', '-no-color'], ['init', '-backend=false', '-input=false', '-no-color'], ['validate', '-json', '-no-color']):
            try:
                for attempt in range(3 if args[0] == 'init' else 1):
                    result = subprocess.run([executable, *args], cwd=folder, env=env, capture_output=True,
                        text=True, timeout=600 if args[0] == 'init' else 120,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    diagnostic_text = (result.stderr or '') + '\n' + (result.stdout or '')
                    transient_download = args[0] == 'init' and any(token in diagnostic_text.lower() for token in (
                        'stream error', 'unexpected eof', 'connection reset', '503', '502 bad gateway',
                        '504 gateway timeout', 'connection was forcibly closed'))
                    if not result.returncode or not transient_download:
                        break
                    if attempt < 2:
                        time.sleep(attempt + 1)
            except subprocess.TimeoutExpired:
                report.update(status='timed_out', diagnostics=['Terraform ' + args[0] + ' timed out; provider downloads or registry access may be slow. No cloud resources were changed.'])
                return report
            except OSError:
                report.update(status='error', diagnostics=['Terraform command could not be started: ' + args[0]])
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
                report.update(status='providers_unavailable' if transient_download else 'failed',
                              diagnostics=[diagnostic_text[-16000:]])
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
        if check['valid'] or check['status'] in {'blocked', 'not_run', 'error', 'timed_out', 'providers_unavailable'} or attempt == attempts:
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
