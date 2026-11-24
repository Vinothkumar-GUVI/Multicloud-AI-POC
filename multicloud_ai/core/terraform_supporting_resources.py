"""Explain generated blocks beyond the primary source-resource mappings."""
import json
import re
from .target_terraform import _resource_blocks


PURPOSES = {
    'random_string': 'Generates a suffix for target resource names that need uniqueness.',
    'random_id': 'Generates a unique identifier used by target resources.',
    'random_password': 'Generates a password referenced by target resources.',
    'aws_vpc': 'Defines the target network used by migrated services.',
    'aws_subnet': 'Defines a subnet for target network placement.',
    'aws_internet_gateway': 'Provides an internet gateway for the target VPC.',
    'aws_route_table': 'Defines routing for target subnets.',
    'aws_route_table_association': 'Connects a target subnet to its route table.',
    'aws_security_group': 'Defines network access rules for target services.',
    'aws_iam_role': 'Defines an identity that a target service can assume.',
    'aws_iam_role_policy': 'Provides permissions to a target service role.',
    'aws_iam_role_policy_attachment': 'Attaches a permissions policy to a target role.',
    'aws_db_subnet_group': 'Groups subnets for a target database.',
    'aws_docdb_cluster_instance': 'Provides a database instance within the DocumentDB cluster.',
    'aws_eip_association': 'Attaches an allocated public IP to a target instance or interface.',
    'aws_s3_bucket_public_access_block': 'Configures public-access restrictions for the target bucket.',
    'aws_s3_bucket_versioning': 'Configures versioning separately from the target bucket definition.',
    'aws_s3_bucket_server_side_encryption_configuration': 'Configures encryption separately from the target bucket definition.',
    'google_project_service': 'Enables the cloud API required by target resources.',
    'google_compute_network': 'Defines the target VPC network.',
    'google_compute_subnetwork': 'Defines the target subnet and its address range.',
    'google_compute_global_address': 'Reserves an address or address range for target networking.',
    'google_service_networking_connection': 'Connects the VPC to managed services through private service access.',
    'google_compute_url_map': 'Routes target load-balancer requests to backends.',
    'google_compute_target_https_proxy': 'Provides the HTTPS proxy for the target load balancer.',
    'google_compute_global_forwarding_rule': 'Connects the load-balancer frontend to its target proxy.',
    'google_compute_backend_service': 'Configures target load-balancer backends.',
    'google_compute_backend_bucket': 'Connects a storage bucket to the target load balancer or CDN.',
    'google_service_account': 'Defines a service identity for target workloads.',
    'google_project_iam_member': 'Grants a project role to the target service identity.',
    'azurerm_resource_group': 'Groups target Azure resources for management.',
    'azurerm_virtual_network': 'Defines the target Azure network.',
    'azurerm_subnet': 'Defines a subnet for target resource placement.',
    'azurerm_network_interface': 'Provides the network interface required by a target VM.',
    'azurerm_network_interface_security_group_association': 'Connects a target interface to its network security group.',
}


def supporting_resource_rows(text):
    blocks = {match[1] + '.' + match[2]: (match[1], match[0])
              for _, _, match in _resource_blocks(text)}
    primary, mapped_to = set(), {}
    manifests = []
    for line in text.splitlines():
        if line.startswith('# RESOURCE COVERAGE: '):
            manifests.append(json.loads(line[len('# RESOURCE COVERAGE: '):]))
    if not manifests:
        return []
    for row in manifests:
        addresses = [address for address in row.get('target_addresses', []) if address in blocks]
        if addresses:
            primary.add(addresses[0])
        for address in addresses:
            mapped_to.setdefault(address, set()).add(row['source_id'].rstrip('/').rsplit('/', 1)[-1])
    result = []
    for address in sorted(set(blocks) - primary):
        kind, code = blocks[address]
        used_by = [other for other, (_, body) in blocks.items() if other != address
                   and re.search(r'\b' + re.escape(address) + r'(?![\w])', body)]
        result.append({'Terraform resource': address,
                       'Purpose': PURPOSES.get(kind, 'Additional configuration block in the target draft; inspect its settings and references for its specific purpose.'),
                       'Relationship': 'Supporting component of a source mapping' if address in mapped_to else 'Shared target infrastructure',
                       'Related resources': ', '.join(sorted(mapped_to.get(address, set()))) or ', '.join(used_by) or 'No direct resource reference detected'})
    return result


def target_resource_counts(text):
    blocks = {m[1] + '.' + m[2] for _, _, m in _resource_blocks(text)}
    additional = supporting_resource_rows(text)
    manifests = {row['source_id'].rstrip('/').lower(): row for row in
                 (json.loads(line[len('# RESOURCE COVERAGE: '):]) for line in text.splitlines()
                  if line.startswith('# RESOURCE COVERAGE: '))}
    covered = sum(any(address in blocks for address in row.get('target_addresses', []))
                  for row in manifests.values())
    has_manifest = bool(manifests)
    primary_count = len(blocks) - len(additional)
    return {'total_blocks': len(blocks), 'mapped_blocks': len(blocks) - len(additional) if has_manifest else None,
            'additional_blocks': len(additional) if has_manifest else None,
            'covered_sources': covered, 'source_entries': len(manifests),
            'shared_source_entries': covered - primary_count if has_manifest else 0}


def source_resource_coverage(resources, text):
    """Count discovered identities once, including explicit system references."""
    import hcl2
    from .terraform import _resource_maps, _rid
    parsed = hcl2.loads(text)
    available = {m[1] + '.' + m[2] for _, _, m in _resource_blocks(text)}
    def literal(value):
        return str(value).strip('"').rstrip('/').lower()
    represented = {literal(block.get('id', '')) for block in parsed.get('import', [])
                   if str(block.get('to', '')).strip('"').removeprefix('${').removesuffix('}') in available}
    for block in parsed.get('locals', []):
        represented.update(literal(value) for key, value in block.items()
                           if key.strip('"').endswith('_id') and isinstance(value, str))
    _, names = _resource_maps(resources)
    available_names = {address.split('.', 1)[1] for address in available}
    ids = {_rid(resource) for resource in resources}
    if not parsed.get('import'):
        represented.update(rid for rid, name in names.items() if name in available_names)
    return len(ids & represented), len(ids)
