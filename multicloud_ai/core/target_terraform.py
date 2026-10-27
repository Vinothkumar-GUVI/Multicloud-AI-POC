"""Explicit source-ID coverage and input-driven target templates."""
import json
import re

from .terraform import _resource_maps, _rid, hcl_string
from .source_terraform import resource_addresses


def _references_id(config, rid):
    if isinstance(config, dict):
        return any(_references_id(value, rid) for value in config.values())
    if isinstance(config, (list, tuple)):
        return any(_references_id(value, rid) for value in config)
    return isinstance(config, str) and config.strip('"').rstrip('/').lower() == rid


def required_inputs(text):
    return {m[1] for m in re.finditer(r'^variable "([^"]+)" \{.*?^\}', text, re.M | re.S)
            if not re.search(r'(?m)^\s*default\s*=', m[0])}


def complete_target(text, resources, cloud, dependencies=(), source_text=''):
    """Replace supported omissions with templates; retain genuine unmapped items."""
    resources = list(resources)
    if str(cloud).upper() == 'GCP':
        text = re.sub(r'(allow|deny)\s*\{\s*protocol\s*=\s*("[^"\n]+")\s+ports\s*=\s*(\[[^\n]*?\])\s*\}',
                      lambda m: m[1] + ' {\n    protocol = ' + m[2] + '\n    ports = ' + m[3] + '\n  }', text)
        # Expand legacy/AI compact blocks before adding new attributes. A block
        # becomes multiline as soon as an attribute is injected into it.
        text = re.sub(r'network_interface\s*\{\s*network\s*=\s*([^\n{}]+?)\s*\}',
                      lambda m: 'network_interface {\n    network = ' + m[1].strip() + '\n  }', text)
        text = re.sub(r'replication\s*\{\s*auto\s*\{\s*\}\s*\}',
                      'replication {\n    auto {}\n  }', text)
    native_links = set()
    if source_text:
        import hcl2
        parsed = hcl2.loads(source_text)
        ids = {str(item['to']).removeprefix('${').removesuffix('}'): str(item['id']).strip('"').lower()
               for item in parsed.get('import', [])}
        known_ids = {_rid(r) for r in resources}
        for block in parsed.get('resource', []):
            for kind, instances in block.items():
                for name, config in instances.items():
                    rid = ids.get(kind.strip('"') + '.' + name.strip('"'))
                    if rid:
                        native_links.update((rid, other) for other in known_ids if other != rid and _references_id(config, other))
    text = re.sub(r'^# RESOURCE COVERAGE: .*\n?', '', text, flags=re.M)
    _, names = _resource_maps(resources)
    if str(cloud).upper() == 'GCP':
        for resource in resources:
            if resource.raw_type.lower() == 'microsoft.sql/servers/databases' and resource.name.lower() == 'master':
                name = names[_rid(resource)]
                text = re.sub(r'^resource "google_sql_database_instance" "' + re.escape(name) + r'" \{.*?^\}\n?', '', text, flags=re.M | re.S)
    declarations = []
    existing_variables = set(re.findall(r'variable "([^"]+)"', text))
    def value(name, field, type='string', sensitive=False):
        variable = 'target_' + name + '_' + field
        if variable not in existing_variables:
            declarations.append(f'variable "{variable}" {{\n  type = {type}\n  sensitive = {str(sensitive).lower()}\n  description = "Required target configuration: {name} {field}. Supply a validated value."\n}}\n')
            existing_variables.add(variable)
        return 'var.' + variable
    blocks = list(re.finditer(r'^resource "([^"]+)" "([^"]+)" \{.*?^\}', text, re.M | re.S))
    owners = {}
    for block in blocks:
        candidates = [(rid, name) for rid, name in names.items() if block[2] == name or block[2].startswith(name + '_')]
        if candidates:
            rid = max(candidates, key=lambda item: len(item[1]))[0]
            owners.setdefault(rid, []).append(block[1] + '.' + block[2])
    reasons = {}
    conditional_plans = []
    if str(cloud).upper() == 'GCP':
        for resource in resources:
            raw = resource.raw_type.lower()
            if raw not in {'microsoft.network/networkinterfaces', 'microsoft.web/serverfarms'}:
                continue
            candidates = []
            for other in resources:
                other_raw = other.raw_type.lower()
                expected = 'microsoft.compute/virtualmachines' if 'networkinterfaces' in raw else 'microsoft.web/sites'
                if other_raw != expected:
                    continue
                linked = _references_id(other.configuration, _rid(resource)) or _references_id(resource.configuration, _rid(other))
                linked = linked or any({_rid(resource), _rid(other)} == {str(e.source_id).rstrip('/').lower(), str(e.target_id).rstrip('/').lower()} for e in dependencies)
                linked = linked or (_rid(resource), _rid(other)) in native_links or (_rid(other), _rid(resource)) in native_links
                if linked:
                    candidates.extend(owners.get(_rid(other), []))
            if candidates:
                owners[_rid(resource)] = sorted(set(candidates))
                reasons[_rid(resource)] = ('Shared VM resource: GCP network interfaces are inline VM configuration. Verify subnet, private IP and network attachments.' if 'networkinterfaces' in raw else
                                           'Shared application resources: Cloud Run capacity is configured per application. Supply scaling and CPU/memory limits; a separate Azure-style service plan is not created.')
            elif raw == 'microsoft.web/serverfarms':
                apps = [(address, other.name) for other in resources if other.raw_type.lower() == 'microsoft.web/sites'
                        for address in owners.get(_rid(other), []) if address.startswith('google_cloud_run_v2_service.')]
                if apps:
                    plan_name = names[_rid(resource)]
                    selected = value(plan_name, 'application_names', 'set(string)')
                    allowed_names = '[' + ', '.join(hcl_string(app_name) for _, app_name in apps) + ']'
                    variable_name = selected.removeprefix('var.')
                    for index, declaration in enumerate(declarations):
                        if declaration.startswith(f'variable "{variable_name}" '):
                            declarations[index] = declaration[:-2] + f'''  validation {{
    condition = length(setsubtract({selected}, {allowed_names})) == 0
    error_message = "Choose only application names present in this target draft."
  }}
}}
'''
                    conditional_plans.append((plan_name, selected, dict(apps)))
                    owners[_rid(resource)] = [address for address, _ in apps]
                    reasons[_rid(resource)] = 'Conditional shared capacity mapping: source permissions prevented confirming plan membership. Select the actual applications in application_names; only selected Cloud Run applications receive this plan scaling configuration. Listed blocks are candidates until that input is supplied.'
    for resource in resources:
        rid, name = _rid(resource), names[_rid(resource)]
        raw = resource.raw_type.lower()
        if str(cloud).upper() == 'GCP' and rid not in owners:
            from .gcp_target_templates import template
            extra, note = template(resource, name, value)
            if extra:
                text += f'\n# TARGET INPUTS REQUIRED: {resource.name}\n# Source ID: {resource.resource_id}\n# Mapping assumption: {note}\n' + '\n'.join(code for _, code in extra)
                owners[rid] = [address for address, _ in extra]
                reasons[rid] = note
                text = re.sub(r'^# REVIEW REQUIRED:[^\n]*\n(?:#[^\n]*(?:\n|$))*',
                    lambda m: '' if '# Source ID: ' + resource.resource_id + '\n' in m[0] else m[0], text, flags=re.M)
                if any(address.startswith('mongodbatlas.') or address.startswith('mongodbatlas_') for address, _ in extra) and 'source = "mongodb/mongodbatlas"' not in text:
                    text = re.sub(r'(required_providers\s*\{)', r'\1\n    mongodbatlas = {\n      source = "mongodb/mongodbatlas"\n      version = "~> 1.20"\n    }', text, count=1)
                    text += '\n# Configure Atlas credentials privately with MONGODB_ATLAS_PUBLIC_KEY and MONGODB_ATLAS_PRIVATE_KEY.\nprovider "mongodbatlas" {}\n'
                continue
            kind, body, reason = None, None, None
            safe_name = name.replace('_', '-')[:63]
            if raw in {'microsoft.operationalinsights/workspaces', 'microsoft.insights/components'}:
                kind = 'google_logging_project_bucket_config'
                body = f'''  project = var.gcp_project_id
  location = {value(name,'logging_location')}
  bucket_id = {hcl_string(safe_name)}
  retention_days = {value(name,'retention_days','number')}'''
                reason = 'Logging destination; configure log routing, application instrumentation and migrated queries separately.'
            elif raw in {'microsoft.datafactory/factories', 'microsoft.web/connections'}:
                kind = 'google_workflows_workflow'
                body = f'''  name = {hcl_string(safe_name)}
  region = var.gcp_region
  service_account = {value(name,'service_account')}
  source_contents = {value(name,'workflow_yaml')}'''
                reason = 'Proposed orchestration workflow; supply translated pipeline or connector logic and grant its service account the required access.'
            elif raw == 'microsoft.search/searchservices':
                kind = 'google_discovery_engine_data_store'
                body = f'''  data_store_id = {hcl_string(safe_name)}
  display_name = {hcl_string(resource.name)}
  location = {value(name,'search_location')}
  industry_vertical = {value(name,'industry_vertical')}
  content_config = {value(name,'content_config')}
  solution_types = {value(name,'solution_types','list(string)')}'''
                reason = 'Proposed search data store; migrate documents and schemas, configure a search engine and validate query compatibility.'
            elif raw == 'microsoft.sql/servers':
                kind = 'google_sql_database_instance'
                body = f'''  name = {hcl_string(safe_name)}
  region = var.gcp_region
  database_version = {value(name,'sqlserver_database_version')}
  root_password = {value(name,'administrator_password',sensitive=True)}
  deletion_protection = true
  settings {{
    tier = {value(name,'tier')}
    disk_size = {value(name,'disk_size_gb','number')}
    availability_type = {value(name,'availability_type')}
    ip_configuration {{
      ipv4_enabled = false
      private_network = {value(name,'private_network')}
    }}
  }}'''
                reason = 'Proposed Cloud SQL SQL Server instance; choose a SQLSERVER version, provision private service access, and validate database features before migrating data.'
            if body:
                text += f'\n# TARGET INPUTS REQUIRED: {resource.name}\n# Source ID: {resource.resource_id}\n# Mapping assumption: {reason}\nresource "{kind}" "{name}" {{\n{body}\n}}\n'
                owners[rid] = [kind + '.' + name]
                reasons[rid] = reason
                text = re.sub(r'^# REVIEW REQUIRED:[^\n]*\n(?:#[^\n]*(?:\n|$))*',
                    lambda m: '' if '# Source ID: ' + resource.resource_id + '\n' in m[0] else m[0], text, flags=re.M)
        if str(cloud).upper() != 'AWS' or rid in owners:
            continue
        body = None
        kind = None
        reason = 'Proposed target service; enter required inputs and validate service equivalence.'
        if raw == 'microsoft.storage/storageaccounts':
            kind = 'aws_s3_bucket'
            body = f'''  bucket = {value(name,'bucket_name')}
  force_destroy = false
  lifecycle {{ prevent_destroy = true }}'''
            reason = 'S3 object-storage destination. Supply a globally unique bucket name. Source file shares, queues and tables are separate services; objects are not copied by Terraform.'
        elif raw == 'microsoft.insights/components':
            kind = 'aws_cloudwatch_log_group'
            body = f'  name = {hcl_string("/migration/" + name)}\n  retention_in_days = {value(name,"retention_days","number")}'
            reason = 'CloudWatch log destination only; application instrumentation and telemetry migration remain required.'
        elif raw == 'microsoft.web/sites':
            kind = 'aws_apprunner_service'
            body = f'''  service_name = {hcl_string(name.replace('_','-'))}
  auto_scaling_configuration_arn = {value(name,'auto_scaling_configuration_arn')}
  source_configuration {{
    auto_deployments_enabled = false
    authentication_configuration {{ access_role_arn = {value(name,'image_access_role_arn')} }}
    image_repository {{
      image_identifier = {value(name,'image_identifier')}
      image_repository_type = "ECR"
      image_configuration {{ port = {value(name,'container_port')} }}
    }}
  }}
  instance_configuration {{
    cpu = {value(name,'cpu')}
    memory = {value(name,'memory')}
    instance_role_arn = {value(name,'instance_role_arn')}
  }}'''
            reason = 'App Runner container deployment requires a compatible image, access roles and application migration.'
        elif raw == 'microsoft.web/serverfarms':
            kind = 'aws_apprunner_auto_scaling_configuration_version'
            body = f'''  auto_scaling_configuration_name = {hcl_string(name.replace('_','-'))}
  max_concurrency = {value(name,'max_concurrency','number')}
  min_size = {value(name,'min_size','number')}
  max_size = {value(name,'max_size','number')}'''
            reason = 'Proposed App Runner scaling configuration; associate its ARN with migrated application services.'
        elif raw == 'microsoft.web/connections':
            kind = 'aws_iam_policy'
            body = f'  name = {hcl_string(name)}\n  policy = {value(name,"connector_policy_json")}'
            reason = 'Connector access policy only; attach it to the application role and implement the target integration.'
        elif raw == 'microsoft.search/searchservices':
            kind = 'aws_opensearch_domain'
            body = f'''  domain_name = {hcl_string(name.replace('_','-')[:28])}
  engine_version = {value(name,'engine_version')}
  access_policies = {value(name,'access_policies_json')}
  cluster_config {{
    instance_type = {value(name,'instance_type')}
    instance_count = {value(name,'instance_count','number')}
  }}
  ebs_options {{
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = {value(name,'volume_size_gb','number')}
  }}
  vpc_options {{
    subnet_ids = {value(name,'subnet_ids','list(string)')}
    security_group_ids = {value(name,'security_group_ids','list(string)')}
  }}
  encrypt_at_rest {{ enabled = true }}
  node_to_node_encryption {{ enabled = true }}
  domain_endpoint_options {{ enforce_https = true }}'''
            reason = 'OpenSearch is a proposed search destination; rebuild indexes and validate analyzer, query and vector-search compatibility.'
        elif raw == 'microsoft.cdn/profiles':
            kind = 'aws_cloudfront_distribution'
            body = f'''  enabled = true
  origin {{
    domain_name = {value(name,'origin_domain_name')}
    origin_id = "migration-origin"
    custom_origin_config {{
      http_port = 80
      https_port = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols = ["TLSv1.2"]
    }}
  }}
  default_cache_behavior {{
    target_origin_id = "migration-origin"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods = {value(name,'allowed_methods','list(string)')}
    cached_methods = {value(name,'cached_methods','list(string)')}
    cache_policy_id = {value(name,'cache_policy_id')}
    origin_request_policy_id = {value(name,'origin_request_policy_id')}
  }}
  restrictions {{
    geo_restriction {{ restriction_type = "none" }}
  }}
  viewer_certificate {{ cloudfront_default_certificate = true }}'''
            reason = 'Proposed CloudFront HTTPS custom origin; supply caching policies and migrate custom domains, certificates and routing rules separately.'
        elif raw == 'microsoft.documentdb/databaseaccounts' and str(resource.configuration.get('kind', '')).lower() == 'mongodb':
            kind = 'aws_docdb_cluster'
            body = f'''  cluster_identifier = {hcl_string(name.replace('_','-'))}
  engine = "docdb"
  engine_version = {value(name,'engine_version')}
  master_username = {value(name,'administrator_login')}
  master_password = {value(name,'administrator_password',sensitive=True)}
  db_subnet_group_name = {value(name,'db_subnet_group_name')}
  vpc_security_group_ids = {value(name,'security_group_ids','list(string)')}
  skip_final_snapshot = false
  final_snapshot_identifier = {value(name,'final_snapshot_identifier')}'''
            text += f'''\nresource "aws_docdb_cluster_instance" "{name}_instance" {{
  identifier = {hcl_string(name.replace('_','-') + '-instance')}
  cluster_identifier = aws_docdb_cluster.{name}.id
  instance_class = {value(name,'instance_class')}
}}\n'''
            reason = 'DocumentDB is a proposed MongoDB-compatible destination; verify supported commands, indexes and consistency, then migrate data separately.'
        elif raw == 'microsoft.cognitiveservices/accounts' and ('openai' in str(resource.configuration).lower() or 'openai' in str(resource.service).lower()):
            kind = 'aws_bedrock_inference_profile'
            body = f'  name = {hcl_string(name)}\n  model_source {{ copy_from = {value(name,"model_source_arn")} }}'
            reason = 'Bedrock inference profile is a proposed OpenAI workload mapping; validate model access, region and application API compatibility.'
        elif raw in {'microsoft.dbforpostgresql/flexibleservers','microsoft.sql/servers'}:
            kind = 'aws_db_instance'
            engine = '"postgres"' if 'postgresql' in raw else value(name,'sqlserver_engine')
            body = f'''  identifier = {hcl_string(name.replace('_','-'))}
  engine = {engine}
  engine_version = {value(name,'engine_version')}
  instance_class = {value(name,'instance_class')}
  allocated_storage = {value(name,'allocated_storage_gb','number')}
  username = {value(name,'administrator_login')}
  password = {value(name,'administrator_password',sensitive=True)}
  db_subnet_group_name = {value(name,'db_subnet_group_name')}
  vpc_security_group_ids = {value(name,'security_group_ids','list(string)')}
  publicly_accessible = false
  skip_final_snapshot = false
  final_snapshot_identifier = {value(name,'final_snapshot_identifier')}'''
            reason = 'RDS is a proposed database-engine mapping; migrate data separately and validate engine, licensing and availability requirements.'
        if body:
            text += f'\n# TARGET INPUTS REQUIRED: {resource.name}\n# Source ID: {resource.resource_id}\n# Mapping assumption: {reason}\nresource "{kind}" "{name}" {{\n{body}\n}}\n'
            owners[rid] = [kind + '.' + name] + (['aws_docdb_cluster_instance.' + name + '_instance'] if kind == 'aws_docdb_cluster' else [])
            reasons[rid] = reason
            text = re.sub(r'^# REVIEW REQUIRED:[^\n]*\n(?:#[^\n]*(?:\n|$))*',
                lambda m: '' if '# Source ID: ' + resource.resource_id + '\n' in m[0] else m[0], text, flags=re.M)
    # AMIs and existing Azure disk contents cannot be reconstructed as new EC2/EBS defaults.
    def parameterize(match):
        kind, name, block = match[1], match[2], match[0]
        if str(cloud).upper() == 'AWS' and kind == 'aws_instance':
            block = re.sub(r'(?m)^\s*ami\s*=.*$', '  ami = ' + value(name,'ami_id'), block)
        if str(cloud).upper() == 'AWS' and kind == 'aws_ebs_volume' and not re.search(r'\bsnapshot_id\s*=', block):
            block = block[:-1] + '  snapshot_id = ' + value(name,'snapshot_id') + '\n}'
        if str(cloud).upper() == 'GCP':
            if kind == 'google_compute_disk' and not re.search(r'\bsnapshot\s*=', block):
                block = block[:-1] + '  snapshot = ' + value(name,'migrated_snapshot') + '\n}'
            fields = {
                'google_compute_instance': [('image','boot_image','string'), ('machine_type','machine_type','string')],
                'google_cloud_run_v2_service': [('image','container_image','string')],
                'google_sql_database_instance': [('database_version','database_version','string'), ('tier','tier','string'), ('disk_size','disk_size_gb','number'), ('availability_type','availability_type','string')],
                'google_compute_firewall': [('source_ranges','source_ranges','list(string)')],
            }
            if kind == 'google_cloud_run_v2_service' and 'scaling {' not in block:
                block = re.sub(r'\btemplate\s*\{', 'template {\n    scaling {\n      min_instance_count = ' + value(name,'min_instance_count','number') + '\n      max_instance_count = ' + value(name,'max_instance_count','number') + '\n    }', block, count=1)
            if kind == 'google_cloud_run_v2_service' and not re.search(r'\bresources\s*\{', block):
                block = re.sub(r'\bcontainers\s*\{', 'containers {\n      resources {\n        limits = {\n          cpu = ' + value(name,'cpu') + '\n          memory = ' + value(name,'memory') + '\n        }\n      }', block)
            if kind == 'google_cloud_run_v2_service':
                for plan_name, selected, apps in conditional_plans:
                    if kind + '.' + name not in apps:
                        continue
                    app_name = hcl_string(apps[kind + '.' + name])
                    for field in ('min_instance_count', 'max_instance_count', 'cpu', 'memory'):
                        replacement = value(plan_name, field, 'number' if field.endswith('instance_count') else 'string')
                        block = re.sub(r'(?m)^(\s*' + field + r'\s*=\s*)([^\n]+)$',
                            lambda m: m[1] + f'contains({selected}, {app_name}) ? {replacement} : ({m[2]})', block)
            if kind == 'google_compute_instance' and not re.search(r'\bsubnetwork\s*=', block):
                block = re.sub(r'\bnetwork_interface\s*\{', 'network_interface {\n    subnetwork = ' + value(name,'subnetwork_self_link') + '\n', block)
            for field, suffix, type in fields.get(kind, []):
                block = re.sub(r'(?m)^(\s*)' + field + r'\s*=.*$',
                    lambda m: m[0] if re.search(r'=\s*var\.', m[0]) else m[1] + field + ' = ' + value(name,suffix,type), block)
            if kind == 'google_dns_managed_zone' and re.search(r'visibility\s*=\s*"public"', block):
                owner = next((r for r in resources if 'google_dns_managed_zone.' + name in owners.get(_rid(r), [])), None)
                if owner and owner.raw_type.lower() == 'microsoft.network/privatednszones':
                    block = re.sub(r'visibility\s*=\s*"public"', 'visibility = "private"', block)
                    if 'private_visibility_config' not in block:
                        block = block[:-1] + f'''  private_visibility_config {{
    dynamic "networks" {{
      for_each = {value(name,'network_self_links','set(string)')}
      content {{ network_url = networks.value }}
    }}
  }}
}}'''
            if kind == 'google_dns_managed_zone':
                block = re.sub(r'(?m)^\s*name\s*=\s*"([^"\n]+)"',
                               lambda m: '  name = ' + hcl_string(m[1].replace('_','-')), block)
            for rid, addresses in owners.items():
                if kind + '.' + name in addresses and kind in {'google_secret_manager_secret', 'google_storage_bucket'}:
                    reasons[rid] = ('Secret container only; migrate secret values, versions, access policies and any keys or certificates separately.'
                                    if kind == 'google_secret_manager_secret' else
                                    'Object-storage destination only; validate any source file shares, queues, tables and access policies separately.')
        return block
    text = re.sub(r'^resource "([^"]+)" "([^"]+)" \{.*?^\}', parameterize, text, flags=re.M | re.S)
    text += '\n' + '\n'.join(declarations)
    inputs = required_inputs(text)
    mappings = []
    resource_blocks = {m[1] + '.' + m[2]: m[0] for m in re.finditer(r'^resource "([^"]+)" "([^"]+)" \{.*?^\}', text, re.M | re.S)}
    for resource in resources:
        rid = _rid(resource)
        addresses = owners.get(rid, [])
        if not addresses and resource.raw_type.lower() == 'microsoft.sql/servers/databases' and resource.name.lower() == 'master':
            parent = resource.resource_id.rsplit('/databases/', 1)[0].lower()
            addresses = owners.get(parent, [])
            reasons[rid] = 'System master database is provided by its SQL Server instance; it is not recreated as an application database.'
        referenced = set()
        pending = list(addresses)
        visited = set()
        while pending:
            address = pending.pop()
            if address in visited:
                continue
            visited.add(address)
            code = resource_blocks.get(address, '')
            referenced.update(re.findall(r'\bvar\.(\w+)', code))
            pending.extend(a for a in resource_blocks if re.search(r'\b' + re.escape(a) + r'\.', code))
        needed = sorted(inputs & referenced)
        mappings.append({'source_id': resource.resource_id, 'target_addresses': addresses,
            'required_variables': needed, 'mapping_note': reasons.get(rid, '')})
        if addresses:
            text = re.sub(r'^# REVIEW REQUIRED:[^\n]*\n(?:#[^\n]*(?:\n|$))*',
                          lambda m: '' if '# Source ID: ' + resource.resource_id + '\n' in m[0] else m[0], text, flags=re.M)
    manifest = '\n'.join('# RESOURCE COVERAGE: ' + json.dumps(row, separators=(',', ':')) for row in mappings)
    return text + '\n' + manifest + '\n'


def coverage_rows(resources, source_text, target_text):
    source_imports = {}
    for match in re.finditer(r'^import \{.*?^\}', source_text, re.M | re.S):
        id_match = re.search(r'\bid\s*=\s*("[^\n]+")', match[0])
        address = re.search(r'\bto\s*=\s*(\w+\.\w+)', match[0])
        if id_match and address:
            source_imports[json.loads(id_match[1]).lower()] = address[1]
    available = resource_addresses(target_text)
    source_available = resource_addresses(source_text)
    source_imports = {rid: a for rid, a in source_imports.items() if a in source_available}
    manifest = {}
    for line in target_text.splitlines():
        if line.startswith('# RESOURCE COVERAGE: '):
            row = json.loads(line[len('# RESOURCE COVERAGE: '):])
            manifest[row['source_id'].lower()] = row
    result = []
    for resource in resources:
        row = manifest.get(resource.resource_id.lower(), {})
        targets = [a for a in row.get('target_addresses', []) if a in available]
        required = row.get('required_variables', [])
        note = row.get('mapping_note', '')
        status = 'Missing' if not targets else 'Inputs / mapping review' if required or note else 'Generated'
        result.append({'Resource': resource.name,
            'Source Terraform': source_imports.get(resource.resource_id.lower(), 'System reference' if resource.name.lower() == 'master' else 'Not found'),
            'Target Terraform': ', '.join(targets) or 'No safe target mapping',
            'Status': ('🔴 ' if not targets else '🟠 ' if required or note else '🟢 ') + status,
            'Required variables': ', '.join(required), 'Mapping notes': note})
    return result
