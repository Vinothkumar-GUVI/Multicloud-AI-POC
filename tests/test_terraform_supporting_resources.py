import json
from multicloud_ai.core.terraform_supporting_resources import supporting_resource_rows, target_resource_counts, source_resource_coverage


def test_shared_support_and_multiple_components_are_explained_without_counting_data():
    code = '''resource "aws_docdb_cluster" "database" { cluster_identifier = "test" }
resource "aws_docdb_cluster_instance" "instance" {
  cluster_identifier = aws_docdb_cluster.database.id
}
resource "random_string" "suffix" { length = 6 }
data "aws_vpc" "existing" { default = true }
'''
    code += '# RESOURCE COVERAGE: ' + json.dumps({'source_id': '/source/database',
        'target_addresses': ['aws_docdb_cluster.database', 'aws_docdb_cluster_instance.instance']})
    rows = supporting_resource_rows(code)
    assert len(rows) == 2
    by_address = {row['Terraform resource']: row for row in rows}
    assert by_address['aws_docdb_cluster_instance.instance']['Related resources'] == 'database'
    assert 'suffix' in by_address['random_string.suffix']['Purpose']
    counts = target_resource_counts(code)
    assert counts == {'total_blocks': 3, 'mapped_blocks': 1, 'additional_blocks': 2,
                      'covered_sources': 1, 'source_entries': 1, 'shared_source_entries': 0}


def test_shared_primary_and_nonexistent_manifest_addresses_do_not_inflate_support():
    code = 'resource "google_sql_database_instance" "sql" { name = "sql" }\n'
    for name in ['server', 'master']:
        code += '# RESOURCE COVERAGE: ' + json.dumps({'source_id': '/source/' + name,
            'target_addresses': ['google_sql_database_instance.sql', 'google_compute_network.absent']}) + '\n'
    assert supporting_resource_rows(code) == []
    assert target_resource_counts(code)['shared_source_entries'] == 1


def test_no_manifest_does_not_mislabel_all_resources_as_additions():
    assert supporting_resource_rows('resource "aws_vpc" "network" { cidr_block = "10.0.0.0/16" }') == []


def test_source_coverage_counts_system_reference_without_duplicate_resource():
    from multicloud_ai.core.models import NormalizedResource
    resources = [NormalizedResource('/source/server', 'server', 'Azure', 'relational_database'),
                 NormalizedResource('/source/server/databases/master', 'master', 'Azure', 'relational_database')]
    text = '''resource "azurerm_mssql_server" "server" { name = "server" }
import {
  to = azurerm_mssql_server.server
  id = "/source/server"
}
locals { source_master_id = "/source/server/databases/master" }
'''
    assert source_resource_coverage(resources, text) == (2, 2)
    assert source_resource_coverage(resources, text.replace('azurerm_mssql_server.server\n', 'azurerm_mssql_server.missing\n')) == (1, 2)
