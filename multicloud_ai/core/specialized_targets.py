"""Explicit infrastructure designs with required software and integration inputs.

These create infrastructure, not source data or application rewrites. Startup
scripts and application packages are customer-supplied deployment inputs.
"""
from .terraform import hcl_string

KINDS = {'message_broker', 'graph_database', 'zfs_storage', 'virtual_desktop', 'realtime_database'}


def capability(resource):
    kind = resource.canonical_type
    cfg = resource.configuration or {}
    if str(cfg.get('database', {}).get('engine', '')).lower() == 'neptune':
        return 'graph_database'
    if str(cfg.get('file_system', {}).get('FileSystemType', '')).upper() == 'OPENZFS':
        return 'zfs_storage'
    for section in ('message_broker', 'graph_database', 'virtual_desktop', 'realtime_database'):
        if isinstance(cfg.get(section), dict) and cfg[section]:
            return section
    return kind if kind in KINDS else None


def design_evidence(resource, target):
    kind = capability(resource)
    target = str(target).upper()
    if not kind:
        return None
    designs = {
        'message_broker': 'Managed Amazon MQ on AWS; self-managed broker VM with durable disk and software setup inputs on Azure/GCP. Preserve RabbitMQ versus ActiveMQ engine and protocol requirements.',
        'graph_database': 'Managed Neptune cluster on AWS; self-managed graph engine VM with durable disk on Azure/GCP. Source query API (RDF/SPARQL, Gremlin or openCypher) must be supplied when undiscovered; these are not interchangeable.',
        'zfs_storage': 'Managed FSx for OpenZFS on AWS; self-managed OpenZFS server with durable disk and setup inputs on Azure/GCP. Preserve filesystem, snapshot, protocol and performance requirements.',
        'virtual_desktop': 'WorkSpaces on AWS, Azure Virtual Desktop control plane and session host on Azure, or a GCP Windows session host integrated with an existing Citrix environment. Identity, licensed image and registration setup are required.',
        'realtime_database': 'Firestore database on GCP; DynamoDB + authenticated AppSync/Lambda adapter on AWS; Cosmos DB + SignalR + customer software adapter on Azure. Client offline synchronization, conflict handling and data migration require application code.',
    }
    return {'capability': kind, 'target_cloud': target, 'design': designs[kind],
            'pricing_scope': 'Include all target compute, durable storage, networking, backup and software/partner license components. Do not claim application or data migration is included.'}


def template(resource, name, cloud, value):
    kind = capability(resource)
    cloud = str(cloud).upper()
    if not kind or cloud not in {'AWS', 'AZURE', 'GCP'}:
        return [], ''
    blocks = []
    def add(typ, suffix, body):
        label = name + suffix
        blocks.append((typ + '.' + label, f'resource "{typ}" "{label}" {{\n{body}\n}}\n'))
        return typ + '.' + label
    def v(field, typ='string', secret=False):
        return value(name, field, typ, sensitive=secret)
    safe = name.replace('_', '-')[:50]
    note = design_evidence(resource, cloud)['design']
    note += ' Infrastructure coverage only; supply the declared configuration and software inputs. No data is copied and functional equivalence is not asserted.'
    if cloud == 'AWS' and kind == 'virtual_desktop':
        add('aws_workspaces_workspace', '', f'''  directory_id = {v('directory_id')}
  bundle_id = {v('bundle_id')}
  user_name = {v('user_name')}
  root_volume_encryption_enabled = true
  user_volume_encryption_enabled = true
  volume_encryption_key = {v('kms_key_id')}
  workspace_properties {{
    compute_type_name = {v('compute_type')}
    root_volume_size_gib = {v('root_volume_size_gib','number')}
    user_volume_size_gib = {v('user_volume_size_gib','number')}
    running_mode = {v('running_mode')}
  }}''')
        return blocks, note
    if cloud == 'AWS' and kind == 'message_broker':
        add('aws_mq_broker', '', f'''  broker_name = {hcl_string(safe)}
  engine_type = {v('broker_engine')}
  engine_version = {v('broker_engine_version')}
  host_instance_type = {v('broker_instance_type')}
  deployment_mode = {v('deployment_mode')}
  publicly_accessible = false
  subnet_ids = {v('subnet_ids','list(string)')}
  security_groups = {v('security_group_ids','list(string)')}
  encryption_options {{ use_aws_owned_key = true }}
  user {{
    username = {v('broker_username')}
    password = {v('broker_password',secret=True)}
  }}''')
        return blocks, note
    if cloud == 'AWS' and kind == 'graph_database':
        add('aws_neptune_cluster', '', f'''  cluster_identifier = {hcl_string(safe)}
  engine = "neptune"
  engine_version = {v('engine_version')}
  neptune_subnet_group_name = {v('neptune_subnet_group_name')}
  vpc_security_group_ids = {v('security_group_ids','list(string)')}
  storage_encrypted = true
  iam_database_authentication_enabled = true
  backup_retention_period = {v('backup_retention_days','number')}
  skip_final_snapshot = false
  final_snapshot_identifier = {v('final_snapshot_identifier')}
  deletion_protection = true''')
        add('aws_neptune_cluster_instance', '_instance', f'''  identifier = {hcl_string(safe+'-instance')}
  cluster_identifier = aws_neptune_cluster.{name}.id
  engine = "neptune"
  instance_class = {v('instance_class')}
  publicly_accessible = false''')
        return blocks, note
    if cloud == 'AWS' and kind == 'zfs_storage':
        add('aws_fsx_openzfs_file_system', '', f'''  storage_capacity = {v('storage_capacity_gib','number')}
  subnet_ids = {v('subnet_ids','list(string)')}
  security_group_ids = {v('security_group_ids','list(string)')}
  deployment_type = {v('deployment_type')}
  throughput_capacity = {v('throughput_capacity','number')}
  automatic_backup_retention_days = {v('backup_retention_days','number')}
  skip_final_backup = false''')
        return blocks, note
    if cloud == 'GCP' and kind == 'realtime_database':
        add('google_firestore_database', '', f'''  project = var.gcp_project_id
  name = {v('database_id')}
  location_id = {v('database_location')}
  type = "FIRESTORE_NATIVE"
  concurrency_mode = {v('concurrency_mode')}
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"''')
        return blocks, note
    if kind == 'realtime_database' and cloud == 'AWS':
        return realtime_aws(name, value), note
    if kind == 'virtual_desktop' and cloud == 'AZURE':
        add('azurerm_virtual_desktop_host_pool', '', f'''  name = {hcl_string(safe)}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  type = "Pooled"
  load_balancer_type = "BreadthFirst"
  validate_environment = false
  preferred_app_group_type = "Desktop"''')
        add('azurerm_virtual_desktop_workspace', '_workspace', f'''  name = {hcl_string(safe+'-workspace')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group''')
        add('azurerm_virtual_desktop_application_group', '_desktop', f'''  name = {hcl_string(safe+'-desktop')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  type = "Desktop"
  host_pool_id = azurerm_virtual_desktop_host_pool.{name}.id''')
        add('azurerm_virtual_desktop_workspace_application_group_association', '_association', f'''  workspace_id = azurerm_virtual_desktop_workspace.{name}_workspace.id
  application_group_id = azurerm_virtual_desktop_application_group.{name}_desktop.id''')
        add('azurerm_role_assignment', '_users', f'''  scope = azurerm_virtual_desktop_application_group.{name}_desktop.id
  role_definition_name = "Desktop Virtualization User"
  principal_id = {v('desktop_users_group_object_id')}''')
        # A session host with customer-provided licensed image and registration
        # extension is generated below, not just a control-plane-only mapping.
    if kind == 'realtime_database' and cloud == 'AZURE':
        add('azurerm_cosmosdb_account', '_database', f'''  name = {v('cosmos_account_name')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  offer_type = "Standard"
  kind = "GlobalDocumentDB"
  consistency_policy {{ consistency_level = "Session" }}
  capabilities {{ name = "EnableServerless" }}
  geo_location {{
    location = var.azure_location
    failover_priority = 0
  }}''')
        add('azurerm_cosmosdb_sql_database', '_documents', f'''  name = "documents"
  resource_group_name = var.azure_resource_group
  account_name = azurerm_cosmosdb_account.{name}_database.name''')
        add('azurerm_cosmosdb_sql_container', '_documents', f'''  name = "documents"
  resource_group_name = var.azure_resource_group
  account_name = azurerm_cosmosdb_account.{name}_database.name
  database_name = azurerm_cosmosdb_sql_database.{name}_documents.name
  partition_key_paths = ["/pk"]''')
        add('azurerm_signalr_service', '_realtime', f'''  name = {hcl_string(safe+'-realtime')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  service_mode = "Serverless"
  sku {{
    name = "Standard_S1"
    capacity = 1
  }}
  cors {{ allowed_origins = {v('allowed_origins','list(string)')} }}''')
        # The Linux host runs the supplied identity-aware sync/notification
        # adapter. It retrieves secrets through its managed identity, not tfvars.
    windows = kind == 'virtual_desktop'
    config = v('runtime_configuration','map(string)')
    setup = (v('session_host_setup_script' if windows else 'software_setup_script',secret=True)
             if cloud == 'GCP' or not windows else None)
    if cloud == 'GCP':
        disk = add('google_compute_disk', '_data', f'''  name = {hcl_string(safe+'-data')}
  zone = {v('zone')}
  size = {v('data_disk_size_gb','number')}
  type = {v('data_disk_type')}''')
        metadata = f'{{ "windows-startup-script-ps1" = {setup}, "migration-configuration" = jsonencode({config}) }}' if windows else f'{{ "startup-script" = {setup}, "migration-configuration" = jsonencode({config}) }}'
        add('google_compute_instance', '_host', f'''  name = {hcl_string(safe+'-host')}
  zone = {v('zone')}
  machine_type = {v('machine_type')}
  boot_disk {{
    auto_delete = false
    initialize_params {{
      image = {v('target_image')}
      size = {v('boot_disk_size_gb','number')}
    }}
  }}
  attached_disk {{
    source = {disk}.self_link
    device_name = "migration-data"
  }}
  network_interface {{ subnetwork = {v('subnetwork_self_link')} }}
  service_account {{
    email = {v('service_account_email')}
    scopes = ["cloud-platform"]
  }}
  metadata = {metadata}
  deletion_protection = true
  labels = {{ migration_capability = {hcl_string(kind)} }}''')
    elif cloud == 'AZURE':
        nic = add('azurerm_network_interface', '_nic', f'''  name = {hcl_string(safe+'-nic')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  ip_configuration {{
    name = "internal"
    subnet_id = {v('subnet_id')}
    private_ip_address_allocation = "Dynamic"
  }}''')
        add('azurerm_network_interface_security_group_association', '_security', f'''  network_interface_id = {nic}.id
  network_security_group_id = {v('network_security_group_id')}''')
        body = f'''  name = {hcl_string(safe[:60]+'-host')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  size = {v('vm_size')}
  admin_username = {v('admin_username')}
  network_interface_ids = [{nic}.id]
  source_image_id = {v('target_image_id')}
  identity {{ type = "SystemAssigned" }}
  os_disk {{
    caching = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb = {v('boot_disk_size_gb','number')}
  }}'''
        if windows:
            body += f'\n  admin_password = {v("admin_password",secret=True)}\n  computer_name = {v("computer_name")}'
        else:
            body += f'''\n  disable_password_authentication = true
  custom_data = base64encode({setup})
  admin_ssh_key {{
    username = {v('admin_username')}
    public_key = {v('admin_ssh_public_key')}
  }}'''
        typ = 'azurerm_windows_virtual_machine' if windows else 'azurerm_linux_virtual_machine'
        host = add(typ, '_host', body)
        disk = add('azurerm_managed_disk', '_data', f'''  name = {hcl_string(safe+'-data')}
  location = var.azure_location
  resource_group_name = var.azure_resource_group
  storage_account_type = "Premium_LRS"
  create_option = "Empty"
  disk_size_gb = {v('data_disk_size_gb','number')}''')
        add('azurerm_virtual_machine_data_disk_attachment', '_data', f'''  managed_disk_id = {disk}.id
  virtual_machine_id = {host}.id
  lun = 0
  caching = "None"''')
        # Runtime configuration is delivered as settings to a customer-selected
        # extension (also responsible for waiting for disk attachment).
        add('azurerm_virtual_machine_extension', '_setup', f'''  name = "migration-setup"
  virtual_machine_id = {host}.id
  publisher = {v('setup_extension_publisher')}
  type = {v('setup_extension_type')}
  type_handler_version = {v('setup_extension_version')}
  settings = jsonencode({config})
  protected_settings = {v('setup_extension_protected_settings_json',secret=True)}
  depends_on = [azurerm_virtual_machine_data_disk_attachment.{name}_data]''')
        if kind == 'realtime_database':
            add('azurerm_cosmosdb_sql_role_assignment', '_adapter', f'''  resource_group_name = var.azure_resource_group
  account_name = azurerm_cosmosdb_account.{name}_database.name
  role_definition_id = "${{azurerm_cosmosdb_account.{name}_database.id}}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id = {host}.identity[0].principal_id
  scope = azurerm_cosmosdb_account.{name}_database.id''')
            add('azurerm_role_assignment', '_signalr', f'''  scope = azurerm_signalr_service.{name}_realtime.id
  role_definition_name = "SignalR REST API Owner"
  principal_id = {host}.identity[0].principal_id''')
    elif cloud == 'AWS':
        # Portable self-managed capability fallback; no public IP or open ingress.
        add('aws_instance', '_host', f'''  ami = {v('ami_id')}
  instance_type = {v('instance_type')}
  subnet_id = {v('subnet_id')}
  vpc_security_group_ids = {v('security_group_ids','list(string)')}
  iam_instance_profile = {v('instance_profile_name')}
  associate_public_ip_address = false
  user_data = {setup}
  metadata_options {{ http_tokens = "required" }}
  root_block_device {{
    encrypted = true
    volume_size = {v('boot_disk_size_gb','number')}
    delete_on_termination = false
  }}
  tags = merge({config}, {{ Name = {hcl_string(safe+'-host')} }})''')
    # Primary workload first, so coverage and supporting counts remain stable.
    priority = {'google_compute_instance', 'azurerm_virtual_desktop_host_pool',
                'azurerm_linux_virtual_machine', 'azurerm_windows_virtual_machine'}
    blocks.sort(key=lambda item: item[0].split('.')[0] not in priority)
    return blocks, note


def realtime_aws(name, value):
    """Authenticated GraphQL/Lambda/DynamoDB infrastructure; adapter ZIP required."""
    v = lambda field, typ='string', secret=False: value(name, field, typ, sensitive=secret)
    blocks = []
    def add(kind, suffix, body):
        blocks.append((kind+'.'+name+suffix, f'resource "{kind}" "{name}{suffix}" {{\n{body}\n}}\n'))
    safe=name.replace('_','-')
    add('aws_dynamodb_table','_documents',f'''  name = {hcl_string(safe+'-documents')}
  billing_mode = "PAY_PER_REQUEST"
  hash_key = "pk"
  range_key = "sk"
  attribute {{
    name = "pk"
    type = "S"
  }}
  attribute {{
    name = "sk"
    type = "S"
  }}
  point_in_time_recovery {{ enabled = true }}
  server_side_encryption {{ enabled = true }}''')
    add('aws_iam_role','_adapter',f'''  name = {hcl_string(safe+'-adapter')}
  assume_role_policy = jsonencode({{ Version = "2012-10-17", Statement = [{{ Effect = "Allow", Action = "sts:AssumeRole", Principal = {{ Service = "lambda.amazonaws.com" }} }}] }})''')
    add('aws_cloudwatch_log_group','_adapter',f'''  name = {hcl_string('/aws/lambda/'+safe+'-adapter')}
  retention_in_days = 30''')
    add('aws_iam_role_policy','_adapter',f'''  role = aws_iam_role.{name}_adapter.id
  policy = jsonencode({{ Version = "2012-10-17", Statement = [
    {{ Effect = "Allow", Action = ["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:DeleteItem","dynamodb:Query"], Resource = aws_dynamodb_table.{name}_documents.arn }},
    {{ Effect = "Allow", Action = ["logs:CreateLogStream","logs:PutLogEvents"], Resource = "${{aws_cloudwatch_log_group.{name}_adapter.arn}}:*" }}
  ] }})''')
    add('aws_lambda_function','_adapter',f'''  function_name = {hcl_string(safe+'-adapter')}
  role = aws_iam_role.{name}_adapter.arn
  filename = {v('adapter_zip_path')}
  source_code_hash = filebase64sha256({v('adapter_zip_path')})
  handler = {v('adapter_handler')}
  runtime = {v('adapter_runtime')}
  timeout = 30
  environment {{ variables = {{ DOCUMENT_TABLE = aws_dynamodb_table.{name}_documents.name }} }}
  depends_on = [aws_iam_role_policy.{name}_adapter]''')
    add('aws_appsync_graphql_api','',f'''  name = {hcl_string(safe)}
  authentication_type = "OPENID_CONNECT"
  openid_connect_config {{ issuer = {v('oidc_issuer')} }}
  schema = {v('graphql_schema')}''')
    add('aws_iam_role','_api',f'''  name = {hcl_string(safe+'-appsync')}
  assume_role_policy = jsonencode({{ Version = "2012-10-17", Statement = [{{ Effect = "Allow", Action = "sts:AssumeRole", Principal = {{ Service = "appsync.amazonaws.com" }} }}] }})''')
    add('aws_iam_role_policy','_api',f'''  role = aws_iam_role.{name}_api.id
  policy = jsonencode({{ Version = "2012-10-17", Statement = [{{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.{name}_adapter.arn }}] }})''')
    add('aws_appsync_datasource','_adapter',f'''  api_id = aws_appsync_graphql_api.{name}.id
  name = "DocumentAdapter"
  type = "AWS_LAMBDA"
  service_role_arn = aws_iam_role.{name}_api.arn
  lambda_config {{ function_arn = aws_lambda_function.{name}_adapter.arn }}''')
    add('aws_appsync_resolver','_fields',f'''  for_each = {v('graphql_resolvers','map(object({ type = string, field = string, request_template = string, response_template = string }))')}
  api_id = aws_appsync_graphql_api.{name}.id
  type = each.value.type
  field = each.value.field
  data_source = aws_appsync_datasource.{name}_adapter.name
  request_template = each.value.request_template
  response_template = each.value.response_template''')
    blocks.sort(key=lambda item:not item[0].startswith('aws_appsync_graphql_api.'))
    return blocks
