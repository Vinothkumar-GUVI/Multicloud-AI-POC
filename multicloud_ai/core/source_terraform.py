"""Provider-driven Azure source reconstruction. No apply or cloud writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import hcl2

from .terraform_runner import terraform_executable
from .terraform_progress import ResourceProgress, run_terraform


AZURE_TYPES = {
    'microsoft.resources/resourcegroups': 'azurerm_resource_group',
    'microsoft.compute/virtualmachines': 'azurerm_virtual_machine',
    'microsoft.compute/disks': 'azurerm_managed_disk',
    'microsoft.network/virtualnetworks': 'azurerm_virtual_network',
    'microsoft.network/virtualnetworks/subnets': 'azurerm_subnet',
    'microsoft.network/networkinterfaces': 'azurerm_network_interface',
    'microsoft.network/networksecuritygroups': 'azurerm_network_security_group',
    'microsoft.network/publicipaddresses': 'azurerm_public_ip',
    'microsoft.network/privatednszones': 'azurerm_private_dns_zone',
    'microsoft.network/privatednszones/virtualnetworklinks': 'azurerm_private_dns_zone_virtual_network_link',
    'microsoft.network/privateendpoints': 'azurerm_private_endpoint',
    'microsoft.network/routetables': 'azurerm_route_table',
    'microsoft.network/loadbalancers': 'azurerm_lb',
    'microsoft.network/natgateways': 'azurerm_nat_gateway',
    'microsoft.storage/storageaccounts': 'azurerm_storage_account',
    'microsoft.containerregistry/registries': 'azurerm_container_registry',
    'microsoft.cognitiveservices/accounts': 'azurerm_cognitive_account',
    'microsoft.datafactory/factories': 'azurerm_data_factory',
    'microsoft.documentdb/databaseaccounts': 'azurerm_cosmosdb_account',
    'microsoft.machinelearningservices/workspaces': 'azurerm_machine_learning_workspace',
    'microsoft.operationalinsights/workspaces': 'azurerm_log_analytics_workspace',
    'microsoft.search/searchservices': 'azurerm_search_service',
    'microsoft.insights/components': 'azurerm_application_insights',
    'microsoft.sql/servers': 'azurerm_mssql_server',
    'microsoft.sql/servers/databases': 'azurerm_mssql_database',
    'microsoft.dbforpostgresql/flexibleservers': 'azurerm_postgresql_flexible_server',
    'microsoft.dbformysql/flexibleservers': 'azurerm_mysql_flexible_server',
    'microsoft.keyvault/vaults': 'azurerm_key_vault',
    'microsoft.web/connections': 'azurerm_api_connection',
    'microsoft.web/serverfarms': 'azurerm_service_plan',
    'microsoft.web/sites': 'azurerm_app_service',
    'microsoft.managedidentity/userassignedidentities': 'azurerm_user_assigned_identity',
    'microsoft.cdn/profiles/endpoints': 'azurerm_cdn_endpoint',
}


def canonical_import_id(resource_id):
    # Resource Graph casing is not necessarily accepted by AzureRM's ID parser.
    value = re.sub(r'/providers/microsoft\.documentdb/databaseaccounts/',
                   '/providers/Microsoft.DocumentDB/databaseAccounts/', resource_id, flags=re.I)
    return re.sub(r'/providers/microsoft\.insights/components/',
                  '/providers/Microsoft.Insights/components/', value, flags=re.I)


def import_configuration(resources):
    resources = list(resources)
    if not resources:
        raise ValueError('No discovered Azure resources are available for source reconstruction.')
    subscriptions = set()
    records = []
    seen = set()
    for resource in resources:
        rid = str(resource.resource_id).rstrip('/')
        match = re.match(r'^/subscriptions/([0-9a-f-]{36})/', rid, re.I)
        if str(resource.cloud).upper() != 'AZURE' or not match:
            raise ValueError(f'{resource.name}: source reconstruction requires an Azure resource ID.')
        if rid.lower() in seen:
            continue
        seen.add(rid.lower())
        subscriptions.add(match[1].lower())
        raw = str(resource.raw_type).lower()
        kind = AZURE_TYPES.get(raw)
        if raw == 'microsoft.machinelearningservices/workspaces':
            workspace_kind = str(resource.configuration.get('kind') or resource.configuration.get('raw_properties', {}).get('kind') or '').lower()
            if workspace_kind in {'hub', 'project'}:
                kind = 'azurerm_ai_foundry' if workspace_kind == 'hub' else 'azurerm_ai_foundry_project'
        if raw == 'microsoft.cdn/profiles':
            sku = resource.configuration.get('sku') or resource.sku
            if isinstance(sku, dict):
                sku = sku.get('name')
            if not sku:
                raise ValueError(f'{resource.name}: CDN profile SKU is required to distinguish Front Door from CDN.')
            kind = 'azurerm_cdn_frontdoor_profile' if 'azurefrontdoor' in str(sku).lower() else 'azurerm_cdn_profile'
        if not kind:
            raise ValueError(f'{resource.name}: native source import mapping is unavailable for {resource.raw_type}; no incomplete code was returned.')
        name = re.sub(r'[^a-z0-9_]', '_', resource.name.lower()).strip('_')[:45] or 'resource'
        name = 'source_' + name + '_' + hashlib.sha256(rid.lower().encode()).hexdigest()[:10]
        if raw == 'microsoft.sql/servers/databases' and rid.rsplit('/', 1)[-1].lower() == 'master':
            kind = 'system_database'
        records.append((canonical_import_id(rid), kind + '.' + name, match[1].lower()))
    aliases = {sid: 'subscription_' + str(i) for i, sid in enumerate(sorted(subscriptions))}
    lines = ['terraform {', '  required_version = ">= 1.5.0"', '  required_providers {',
             '    azurerm = { source = "hashicorp/azurerm", version = "= 4.81.0" }', '  }', '}', '']
    for sid, alias in aliases.items():
        lines += ['provider "azurerm" {', f'  alias = "{alias}"', f'  subscription_id = "{sid}"',
                  '  resource_provider_registrations = "none"', '  features {}', '}', '']
    for rid, address, sid in records:
        # Literal import IDs are exact; no escaping/interpolation of cloud values.
        literal = json.dumps(rid).replace('${', '$${').replace('%{', '%%{')
        if address.startswith('system_database.'):
            lines += ['# SYSTEM RESOURCE: SQL master is provided by its existing server; it is not recreated.',
                      'locals {', f'  {address.split(".")[1]}_id = {literal}', '}', '']
            continue
        lines += ['import {', f'  to = {address}', f'  id = {literal}',
                  f'  provider = azurerm.{aliases[sid]}', '}', '']
    return '\n'.join(lines), {address for _, address, _ in records if not address.startswith('system_database.')}


def normalize_generated_configuration(text):
    """Remove absent optional values that AzureRM's generated HCL treats as set."""
    def resource_block(match):
        kind, name, block = match[1], match[2], match[0]
        block = re.sub(r'(?m)^\s+administrator_(?:login_)?password_wo\s*=\s*null[^\n]*\n', '', block)
        if not re.search(r'(?m)^\s+administrator_(?:login_)?password_wo\s*=', block):
            block = re.sub(r'(?m)^\s+administrator_(?:login_)?password_wo_version\s*=.*\n', '', block)
        if kind == 'azurerm_key_vault':
            # ARM's legacy "all" permission must be expressed as AzureRM enum values.
            permissions = {
                'certificate': 'Backup Create Delete DeleteIssuers Get GetIssuers Import List ListIssuers ManageContacts ManageIssuers Purge Recover Restore SetIssuers Update',
                'key': 'Backup Create Decrypt Delete Encrypt Get Import List Purge Recover Release Restore Rotate GetRotationPolicy SetRotationPolicy Sign UnwrapKey Update Verify WrapKey',
                'secret': 'Backup Delete Get List Purge Recover Restore Set',
            }
            for category, values in permissions.items():
                block = re.sub(r'(?m)^(\s*' + category + r'_permissions\s*=\s*)\["all"\]',
                               lambda m: m[1] + json.dumps(values.split()), block, flags=re.I)
        if kind == 'azurerm_managed_disk':
            block = re.sub(r'(?m)^\s+(?:disk_iops_read_only|disk_mbps_read_only|max_shares|upload_size_bytes)\s*=\s*0\s*\n', '', block)
        for optional in ('additional_capabilities', 'encryption', 'azuread_administrator'):
            block = re.sub(r'(?m)^  ' + optional + r'\s*\{\n((?:[^\n]*\n)*?)  \}\n',
                lambda m: '' if all(not line.strip() or re.fullmatch(r'\w+\s*=\s*null', line.strip()) for line in m[1].splitlines()) else m[0], block)
        if kind == 'azurerm_machine_learning_workspace' and not re.search(r'(?m)^  encryption\s*\{', block):
            block = re.sub(r'(?m)^\s+service_side_encryption_enabled\s*=\s*false[^\n]*\n', '', block)
        return block
    return re.sub(r'^resource "([^"]+)" "([^"]+)" \{.*?^\}', resource_block, text, flags=re.M | re.S)


def parameterize_sql_passwords(text, environment=None):
    declarations = []
    def block(match):
        code = match[0]
        if re.search(r'azuread_authentication_only\s*=\s*true', code):
            return code
        variable = 'source_sql_password_' + match[1].rsplit('_', 1)[-1]
        declarations.append(f'variable "{variable}" {{\n  type = string\n  sensitive = true\n}}\n')
        code = re.sub(r'(?m)^\s+administrator_login_password\s*=.*$', '  administrator_login_password = var.' + variable, code)
        if 'administrator_login_password = var.' not in code:
            code = code.replace('{\n', '{\n  administrator_login_password = var.' + variable + '\n', 1)
        return code
    text = re.sub(r'^resource "azurerm_mssql_server" "([^"]+)" \{.*?^\}', block, text, flags=re.M | re.S)
    def postgres_block(match):
        code = match[0]
        if not re.search(r'(?m)^\s*administrator_password\s*=\s*null', code):
            return code
        variable = 'source_postgres_password_' + match[1].rsplit('_', 1)[-1]
        declarations.append(f'variable "{variable}" {{\n  type = string\n  sensitive = true\n}}\n')
        return re.sub(r'(?m)^\s*administrator_password\s*=.*$',
                      '  administrator_password = var.' + variable, code)
    text = re.sub(r'^resource "azurerm_postgresql_flexible_server" "([^"]+)" \{.*?^\}', postgres_block, text, flags=re.M | re.S)
    return '\n'.join(declarations) + text


def resource_addresses(text):
    """Count HCL resources regardless of formatting, never comment text."""
    parsed = hcl2.loads(text)
    return {kind.strip('"') + '.' + name.strip('"') for block in parsed.get('resource', [])
            for kind, instances in block.items() for name in instances}


def denied_resource_addresses(output):
    denied = set()
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        diagnostic = event.get('diagnostic') or {}
        detail = str(diagnostic.get('detail', ''))
        if diagnostic.get('address') and re.search(r'AuthorizationFailed|403 Forbidden|status 403', detail, re.I):
            denied.add(diagnostic['address'])
    return denied


def missing_permission_summary(diagnostics):
    actions = sorted(set(re.findall(r"perform action ['\"]([^'\"]+)['\"]", diagnostics, re.I)))
    return ('Missing Azure permissions: ' + ', '.join(actions)
            + '. Ask an Azure administrator to grant only the required actions at the affected resource scope; refresh credentials afterwards. ') if actions else ''


def permission_template(address, resource, schema, provider, issue):
    """Native schema template; missing values are inputs, not claimed discoveries."""
    kind, name = address.split('.')
    declarations = []
    known = {'name': resource.name, 'location': resource.region,
             'resource_group_name': resource.group}
    group = re.search(r'/resourceGroups/([^/]+)', resource.resource_id, re.I)
    if group:
        known['resource_group_name'] = group[1]
    def body(block, indent='  ', path=''):
        lines = []
        for attr, spec in block.get('attributes', {}).items():
            if not spec.get('required'):
                continue
            if not path and attr in known and known[attr] and known[attr] not in {'unknown', 'default'}:
                value = json.dumps(known[attr]).replace('${', '$${').replace('%{', '%%{')
            else:
                variable = name + '_' + path + attr
                declarations.append(f'variable "{variable}" {{\n  type = any\n  sensitive = {str(bool(spec.get("sensitive"))).lower()}\n  description = "Supply the existing value for {kind}.{path}{attr}; permission prevented discovery."\n}}\n')
                value = 'var.' + variable
            lines.append(indent + attr + ' = ' + value)
        for nested, spec in block.get('block_types', {}).items():
            for _ in range(spec.get('min_items', 0)):
                lines += [indent + nested + ' {', *body(spec['block'], indent + '  ', path + nested + '_'), indent + '}']
        return lines
    lines = [f'# PERMISSION FALLBACK: {resource.name}', '# Source ID: ' + resource.resource_id,
             '# Permission issue: ' + issue.replace('\n', ' '),
             '# MANUAL VALUES REQUIRED: supply the variables and verify optional settings against the source.',
             '# This is a resource template, not a verified reconstruction.', f'resource "{kind}" "{name}" {{',
             '  provider = ' + provider, *body(schema.get('block', {})), '}']
    return '\n'.join(declarations + lines) + '\n'


def reconstruct_azure(resources, credential_environment=None, progress=None):
    """Generate complete source configuration; defer plans requiring absent secrets."""
    resources = list(resources)
    config, addresses = import_configuration(resources)
    if not addresses:
        return '# Source contains only system database references; no separate resources are managed.\n' + config
    names = {}
    for resource in resources:
        suffix = hashlib.sha256(resource.resource_id.rstrip('/').lower().encode()).hexdigest()[:10]
        for address in addresses:
            if address.endswith('_' + suffix):
                names[address] = resource.name
    executable = terraform_executable()
    if not executable:
        raise RuntimeError('Terraform CLI is required for native source reconstruction. Run scripts/install_terraform.py and retry.')
    allowed = {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT',
               'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'USERPROFILE', 'HOME'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed or k.startswith('ARM_')}
    supplied = credential_environment or {}
    env.update({k: str(v) for k, v in supplied.items() if k in {
        'ARM_TENANT_ID', 'ARM_CLIENT_ID', 'ARM_CLIENT_SECRET', 'ARM_SUBSCRIPTION_ID'} and v})
    env.update({k: str(v) for k, v in supplied.items() if re.fullmatch(r'TF_VAR_source_sql_password_[0-9a-f]{10}', k) and v})
    env.update(TF_IN_AUTOMATION='1', TF_INPUT='0', CHECKPOINT_DISABLE='1')
    # Avoid HTTP/2 stream resets seen on the provider-download connection.
    # TLS verification remains enabled; this only selects HTTP/1.1.
    env['GODEBUG'] = 'http2client=0'
    def command(args, folder, allow_failure=False):
        if progress:
            progress('Terraform ' + args[0])
        tracker = ResourceProgress(names, progress) if args[0] == 'plan' else None
        if args[0] == 'plan':
            args = [*args, '-json', '-parallelism=16']
        for attempt in range(3 if args[0] == 'init' else 1):
            result = run_terraform([executable, *args], progress_tracker=tracker, cwd=folder, env=env, capture_output=True,
                text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            diagnostics = (result.stderr or result.stdout).lower()
            transient = any(token in diagnostics for token in (
                'stream error', 'connection reset', 'unexpected eof', '503 service unavailable',
                '502 bad gateway', '504 gateway timeout', 'connection was forcibly closed'))
            if not result.returncode or not transient or args[0] != 'init':
                break
            if progress and attempt < 2:
                progress(f'Retrying Terraform provider download ({attempt + 2}/3)')
        if result.returncode and not allow_failure:
            from .agents import redact
            diagnostics = result.stderr or result.stdout
            for secret in supplied.values():
                if secret:
                    diagnostics = diagnostics.replace(str(secret), '[REDACTED]')
            raise RuntimeError('Native source reconstruction failed during ' + args[0] + ': ' + str(redact(diagnostics[-6000:])))
        return result if allow_failure else result.stdout
    with tempfile.TemporaryDirectory(prefix='multicloud-source-tf-') as folder:
        root = Path(folder)
        env['TF_CLI_CONFIG_FILE'] = str(root / 'empty.tfrc')
        mirror = Path(__file__).resolve().parents[2] / 'tools' / 'provider-mirror'
        provider_archives = mirror / 'registry.terraform.io' / 'hashicorp' / 'azurerm'
        cli_config = ''
        if provider_archives.exists() and any(provider_archives.glob('terraform-provider-azurerm_4.81.0_*.zip')):
            cli_config = ('provider_installation {\n  filesystem_mirror {\n    path = ' + json.dumps(mirror.as_posix())
                + '\n    include = ["registry.terraform.io/hashicorp/azurerm"]\n  }\n'
                + '  direct { exclude = ["registry.terraform.io/hashicorp/azurerm"] }\n}\n')
        (root / 'empty.tfrc').write_text(cli_config, encoding='utf-8')
        (root / 'imports.tf').write_text(config, encoding='utf-8')
        command(['init', '-backend=false', '-input=false', '-no-color'], folder)
        initial = command(['plan', '-input=false', '-no-color', '-generate-config-out=resources.tf', '-out=source.tfplan'], folder, allow_failure=True)
        generated_path = root / 'resources.tf'
        if not generated_path.exists():
            from .agents import redact
            diagnostics = (initial.stderr or initial.stdout)[-3000:]
            for secret in supplied.values():
                if secret:
                    diagnostics = diagnostics.replace(str(secret), '[REDACTED]')
            if re.search(r'AuthorizationFailed|403 Forbidden|status 403', initial.stderr or initial.stdout, re.I):
                generated_path.write_text('', encoding='utf-8')
            else:
                raise RuntimeError('Terraform returned no generated resource configuration: ' + str(redact(diagnostics)))
        generated = generated_path.read_text(encoding='utf-8')
        actual = resource_addresses(generated)
        missing = addresses - actual
        recovery_errors = []
        permission_errors = {}
        if missing and not (actual - addresses):
            # A bulk plan can emit only some configurations before encountering
            # another resource's provider-schema error. Read remaining IDs in
            # isolation so an unrelated invalid block cannot prevent export.
            generated_path.rename(root / 'resources.saved')
            try:
                for address in sorted(missing):
                    if address in denied_resource_addresses(initial.stdout):
                        permission_errors[address] = 'Azure denied access (403 AuthorizationFailed); required settings could not be read.'
                        recovery_errors.append(address + ': Azure denied access in the initial read; repeated reads were skipped.')
                        continue
                    single = re.sub(r'(?m)^import \{.*?^\}',
                        lambda m: m[0] if re.search(r'(?m)^\s*to\s*=\s*' + re.escape(address) + r'\s*$', m[0]) else '',
                        config, flags=re.S)
                    (root / 'imports.tf').write_text(single, encoding='utf-8')
                    if progress:
                        progress('Reading remaining source resource ' + address)
                    result = command(['plan', '-input=false', '-no-color', '-generate-config-out=recovery.tf'], folder, allow_failure=True)
                    recovery = root / 'recovery.tf'
                    if recovery.exists():
                        extra = recovery.read_text(encoding='utf-8')
                        if resource_addresses(extra) == {address}:
                            generated += '\n' + extra
                        recovery.unlink()
                    if result.returncode:
                        recovery_errors.append(address + ': ' + (result.stderr or result.stdout))
                        if re.search(r'AuthorizationFailed|403 Forbidden|status 403', result.stderr or result.stdout, re.I):
                            permission_errors[address] = missing_permission_summary(result.stderr or result.stdout) or 'Azure denied access (403); resource configuration could not be read.'
            finally:
                (root / 'imports.tf').write_text(config, encoding='utf-8')
                generated_path.write_text(generated, encoding='utf-8')
        generated = normalize_generated_configuration(generated)
        generated = parameterize_sql_passwords(generated, env)
        fallbacks = (addresses - resource_addresses(generated)) & set(permission_errors)
        if fallbacks:
            schema_data = json.loads(command(['providers', 'schema', '-json'], folder))
            schemas = schema_data['provider_schemas']['registry.terraform.io/hashicorp/azurerm']['resource_schemas']
            for address in sorted(fallbacks):
                suffix = address.rsplit('_', 1)[-1]
                resource = next(r for r in resources if hashlib.sha256(r.resource_id.rstrip('/').lower().encode()).hexdigest()[:10] == suffix)
                import_block = next(m[0] for m in re.finditer(r'(?m)^import \{.*?^\}', config, re.S)
                                    if re.search(r'\bto\s*=\s*' + re.escape(address) + r'\s*\n', m[0]))
                provider = re.search(r'provider\s*=\s*(azurerm\.\w+)', import_block)[1]
                generated += '\n' + permission_template(address, resource, schemas[address.split('.')[0]], provider, permission_errors[address])
        generated_path.write_text(generated, encoding='utf-8')
        actual = resource_addresses(generated)
        if actual != addresses:
            from .agents import redact
            diagnostics = (initial.stderr or '') + '\n' + '\n'.join(recovery_errors)
            permissions = missing_permission_summary(diagnostics)
            for secret in supplied.values():
                if secret:
                    diagnostics = diagnostics.replace(str(secret), '[REDACTED]')
            summaries = []
            for error in recovery_errors:
                for secret in supplied.values():
                    if secret:
                        error = error.replace(str(secret), '[REDACTED]')
                first_lines = [line.strip() for line in error.splitlines() if line.strip()]
                summaries.append(' '.join(first_lines[:2])[:450])
            raise RuntimeError(permissions + 'Terraform source coverage is incomplete. Missing: ' + ', '.join(sorted(addresses - actual))
                + '. Unexpected: ' + ', '.join(sorted(actual - addresses))
                + '. Resource failures: ' + str(redact('\n'.join(summaries)))
                + '. Provider diagnostics: ' + str(redact(diagnostics[-4000:])))
        template_validation = command(['validate', '-no-color'], folder, allow_failure=bool(fallbacks))
        if fallbacks:
            return ('# SOURCE PLAN PENDING: Permission-limited resource templates require manual values.\n'
                    + ('# PROVIDER VALIDATION PENDING: fill required template settings and validate before use.\n' if template_validation.returncode else '# PROVIDER VALIDATION PASSED: source equivalence for fallback resources remains unverified.\n')
                    + '# Resource blocks are included; permission fallback settings are not verified against Azure.\n'
                    + config + '\n' + generated)
        missing_passwords = [name for name in re.findall(r'variable "(source_(?:sql|postgres)_password_[0-9a-f]{10})"', generated)
                             if not env.get('TF_VAR_' + name)]
        if missing_passwords:
            return ('# SOURCE PLAN PENDING: SQL password variables have not been supplied.\n'
                    '# Resource coverage and Terraform validate passed; no-change plan has not been verified.\n'
                    '# Supply the sensitive variables privately before running terraform plan or apply.\n'
                    + config + '\n' + generated)
        command(['plan', '-input=false', '-no-color', '-out=source.tfplan'], folder)
        plan = json.loads(command(['show', '-json', 'source.tfplan'], folder))
        changes = plan.get('resource_changes', [])
        if {c['address'] for c in changes if c.get('mode', 'managed') == 'managed'} != addresses:
            raise RuntimeError('Source plan did not verify every imported resource.')
        if any(c.get('change', {}).get('actions') != ['no-op'] for c in changes if c.get('mode', 'managed') == 'managed'):
            raise RuntimeError('Generated source configuration would change existing resources; it was not accepted as an exact reconstruction.')
        return config + '\n' + generated
