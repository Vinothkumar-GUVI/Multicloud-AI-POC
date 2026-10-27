"""Explicit GCP migration architectures, with required inputs and scope notes."""
from .terraform import hcl_string


def template(resource, name, value):
    raw = resource.raw_type.lower()
    safe = name.replace('_', '-')[:50]
    blocks = []
    def add(kind, suffix, body):
        address_name = name + suffix
        blocks.append((kind + '.' + address_name,
                       f'resource "{kind}" "{address_name}" {{\n{body}\n}}\n'))
    if raw == 'microsoft.storage/storageaccounts':
        add('google_storage_bucket', '', f'''  name = {value(name,'bucket_name')}
  location = {value(name,'storage_location')}
  storage_class = {value(name,'storage_class')}
  force_destroy = false
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  lifecycle {{ prevent_destroy = true }}''')
        note = 'Cloud Storage object-storage destination. Supply a globally unique bucket name, location and storage class. Source file shares, queues and tables are separate services; objects are not copied by Terraform.'
    elif raw == 'microsoft.cdn/profiles':
        add('google_compute_backend_service', '', f'''  name = "{safe}-backend"
  protocol = {value(name,'origin_protocol')}
  load_balancing_scheme = "EXTERNAL_MANAGED"
  enable_cdn = true
  health_checks = {value(name,'health_check_self_links','list(string)')}
  dynamic "backend" {{
    for_each = {value(name,'backend_group_self_links','set(string)')}
    content {{ group = backend.value }}
  }}
  cdn_policy {{ cache_mode = {value(name,'cache_mode')} }}''')
        add('google_compute_url_map', '_routes', f'''  name = "{safe}-routes"
  default_service = google_compute_backend_service.{name}.id''')
        add('google_compute_target_https_proxy', '_https', f'''  name = "{safe}-https"
  url_map = google_compute_url_map.{name}_routes.id
  ssl_certificates = {value(name,'ssl_certificate_self_links','list(string)')}''')
        add('google_compute_global_address', '_address', f'  name = "{safe}-address"')
        add('google_compute_global_forwarding_rule', '_forwarding', f'''  name = "{safe}-forwarding"
  ip_address = google_compute_global_address.{name}_address.address
  target = google_compute_target_https_proxy.{name}_https.id
  port_range = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"''')
        note = 'HTTPS load balancer and Cloud CDN. Supply existing compatible backend groups, health checks and certificates; migrate DNS, WAF and non-default routing rules separately.'
    elif raw == 'microsoft.machinelearningservices/workspaces':
        add('google_workbench_instance', '', f'''  name = "{safe}"
  location = {value(name,'workbench_zone')}
  gce_setup {{
    machine_type = {value(name,'machine_type')}
    disable_public_ip = true
    service_accounts {{ email = {value(name,'service_account_email')} }}
    network_interfaces {{
      network = {value(name,'network_self_link')}
      subnet = {value(name,'subnet_self_link')}
    }}
    vm_image {{
      project = {value(name,'image_project')}
      family = {value(name,'image_family')}
    }}
  }}''')
        note = 'Vertex AI Workbench development environment. Migrate notebooks and data; Foundry projects, model deployments, pipelines and workspace permissions are not reproduced by this instance.'
    elif raw == 'microsoft.cognitiveservices/accounts':
        add('google_cloud_run_v2_service', '', f'''  name = "{safe}"
  location = var.gcp_region
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  template {{
    service_account = {value(name,'service_account_email')}
    containers {{
      image = {value(name,'ai_adapter_container_image')}
      env {{
        name = "TARGET_MODEL_ENDPOINT"
        value = {value(name,'target_model_endpoint')}
      }}
    }}
  }}''')
        note = 'Proposed private Cloud Run AI adapter, not a recreated Azure AI account. Supply an implemented adapter image and compatible model endpoint; configure model access, caller networking and API authentication separately.'
    elif raw == 'microsoft.documentdb/databaseaccounts':
        add('mongodbatlas_advanced_cluster', '', f'''  project_id = {value(name,'atlas_project_id')}
  name = {hcl_string(safe)}
  cluster_type = "REPLICASET"
  replication_specs {{
    region_configs {{
      provider_name = "GCP"
      region_name = {value(name,'atlas_region')}
      priority = 7
      electable_specs {{
        instance_size = {value(name,'atlas_instance_size')}
        node_count = {value(name,'atlas_node_count','number')}
      }}
    }}
  }}''')
        note = 'MongoDB Atlas on GCP, selected by the user. Validate Cosmos MongoDB API compatibility and migrate data, indexes, database users and private networking separately. Non-Mongo Cosmos APIs require a different design.'
    else:
        return [], ''
    return blocks, note
