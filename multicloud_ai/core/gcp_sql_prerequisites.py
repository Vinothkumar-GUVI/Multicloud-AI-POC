"""Wire generated private Cloud SQL instances to managed networking and APIs."""
import re


def complete_private_sql(text):
    blocks = list(re.finditer(r'^resource "google_sql_database_instance" "([^"]+)" \{.*?^\}', text, re.M | re.S))
    private = [m for m in blocks if re.search(r'\bprivate_network\s*=', m[0])]
    if not private:
        return text
    marker = '# MANAGED CLOUD SQL PRIVATE PREREQUISITES'
    if marker in text:
        return text
    # Use an existing generated VPC; create a dedicated one only if necessary.
    network = re.search(r'^resource "google_compute_network" "([^"]+)"', text, re.M)
    network_name = network[1] if network else 'sql_migration_network'
    network_ref = 'google_compute_network.' + network_name
    api_ref = 'google_project_service.sql_migration_apis'
    additions = f'''
{marker}
resource "google_project_service" "sql_migration_apis" {{
  for_each = toset(["compute.googleapis.com", "servicenetworking.googleapis.com", "sqladmin.googleapis.com"])
  project = var.gcp_project_id
  service = each.value
  disable_on_destroy = false
}}
'''
    if not network:
        additions += f'''
resource "google_compute_network" "{network_name}" {{
  name = "sql-migration-network"
  auto_create_subnetworks = false
  depends_on = [{api_ref}]
}}
'''
    else:
        pattern = r'^resource "google_compute_network" "' + re.escape(network_name) + r'" \{.*?^\}'
        def depend(match):
            block = match[0]
            if re.search(r'\bdepends_on\s*=', block):
                return re.sub(r'(\bdepends_on\s*=\s*\[)', r'\1' + api_ref + ', ', block, count=1)
            return block[:-1] + f'  depends_on = [{api_ref}]\n}}'
        text = re.sub(pattern, depend, text, flags=re.M | re.S)
    additions += f'''
resource "google_compute_global_address" "sql_migration_range" {{
  name = "sql-migration-private-range"
  purpose = "VPC_PEERING"
  address_type = "INTERNAL"
  prefix_length = 16
  network = {network_ref}.id
  depends_on = [{api_ref}]
}}

resource "google_service_networking_connection" "sql_migration_connection" {{
  network = {network_ref}.id
  service = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_migration_range.name]
  depends_on = [{api_ref}]
}}
'''
    def wire(match):
        block = match[0]
        if not re.search(r'\bprivate_network\s*=', block):
            return block
        block = re.sub(r'(?m)^(\s*private_network\s*=)[^\n]*', r'\1 ' + network_ref + '.id', block)
        dependency = 'google_service_networking_connection.sql_migration_connection'
        if re.search(r'\bdepends_on\s*=', block):
            block = re.sub(r'(\bdepends_on\s*=\s*\[)', r'\1' + dependency + ', ', block, count=1)
        else:
            block = block[:-1] + f'  depends_on = [{dependency}]\n}}'
        if not re.search(r'\bedition\s*=', block):
            block = re.sub(r'\bsettings\s*\{', 'settings {\n    edition = "ENTERPRISE"', block, count=1)
        return block
    text = re.sub(r'^resource "google_sql_database_instance" "([^"]+)" \{.*?^\}', wire, text, flags=re.M | re.S)
    # Remove variables made redundant by direct resource references. Preserve a
    # declaration if another resource still uses it.
    def remove_unused(match):
        return match[0] if re.search(r'\bvar\.' + re.escape(match[1]) + r'\b', text) else ''
    text = re.sub(r'^variable "(target_\w+_private_network)" \{.*?^\}\n?', remove_unused, text, flags=re.M | re.S)
    return text + additions
