import os
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from multicloud_ai.core.billing import detect, parse
from multicloud_ai.core.currency import convert_billing
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.quality import build_readiness_report
from multicloud_ai.core.recommendation import assess_target, recommend
from multicloud_ai.core.validation import validate_terraform_text
from multicloud_ai.core.package import build_migration_package
from multicloud_ai.cloud_adapters.aws import AWSAdapter


class ProductionFeatureTests(unittest.TestCase):
    def test_aws_invoice_schema_auto_detects_and_parses(self):
        df = pd.DataFrame([{
            'ProductCode': 'AmazonEC2', 'UsageType': 'BoxUsage:t3.small',
            'UsageQuantity': 10, 'CurrencyCode': 'USD', 'Actual Cost': 1.23,
            'LinkedAccountId': '123456789012', 'ProductName': 'EC2'
        }])
        self.assertEqual(detect(df), 'AWS')
        rows, skipped = parse(df, 'AWS')
        self.assertEqual(skipped, 0)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].resource_id.startswith('billing://aws/'))

    def test_azure_inr_currency_code_is_recognized_and_normalized(self):
        df = pd.DataFrame([{
            'ResourceId': '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
            'ResourceType': 'Microsoft.Compute/disks', 'Cost': '₹8300.00',
            'BillingCurrencyCode': 'INR', 'Quantity': 100, 'UnitOfMeasure': 'GB/Month'
        }])
        rows, _ = parse(df, 'Azure')
        self.assertEqual(rows[0].currency, 'INR')
        self.assertAlmostEqual(rows[0].cost, 8300)
        converted = convert_billing(rows, {'INR': 0.012})
        self.assertEqual(converted[0].currency, 'USD')
        self.assertAlmostEqual(converted[0].cost, 99.6)

    def test_recommendation_does_not_choose_low_coverage_target(self):
        poor = [{'Target Monthly Cost (USD)': 1, 'Pricing Reliability': 'Reliable', 'Source Currency': 'USD', 'Source Billed Cost': 100}] + [
            {'Target Monthly Cost (USD)': None, 'Pricing Reliability': 'Unavailable', 'Source Currency': 'USD', 'Source Billed Cost': 1}
            for _ in range(9)
        ]
        good = [
            {'Target Monthly Cost (USD)': 8, 'Pricing Reliability': 'Reliable', 'Source Currency': 'USD', 'Source Billed Cost': 10}
            for _ in range(10)
        ]
        a, b = assess_target('AWS', poor), assess_target('GCP', good)
        result = recommend([a, b])
        self.assertEqual(result['recommended_target'], 'GCP')

    def test_readiness_flags_synthetic_aws_billing(self):
        r = NormalizedResource('billing://aws/1/ec2/usage/x', 'line', 'AWS', 'compute_instance', cost=5,
                               configuration={'billing_scope':'service_usage_line'})
        report = build_readiness_report([r], [], [], [], '')
        self.assertTrue(any('resource IDs' in b for b in report.blockers))

    def test_terraform_validation_catches_duplicate_address(self):
        text = 'provider "aws" {}\nresource "aws_s3_bucket" "x" {}\nresource "aws_s3_bucket" "x" {}\n'
        report = validate_terraform_text(text, 'AWS')
        self.assertFalse(report.valid)
        self.assertTrue(any('Duplicate' in e for e in report.errors))

    def test_package_contains_required_artifacts(self):
        import io, zipfile
        data = build_migration_package(terraform_text='provider "aws" {}', target='AWS', manifest={'a':1}, validation={'valid':True})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        self.assertIn('terraform/main_aws.tf', names)
        self.assertIn('migration_manifest.json', names)
        self.assertIn('validation_report.json', names)

    def test_aws_adapter_accepts_default_chain(self):
        fake_session = Mock()
        fake_session.get_credentials.return_value = Mock()
        fake_session.client.return_value = Mock()
        with patch('multicloud_ai.cloud_adapters.aws.boto3.Session', return_value=fake_session):
            adapter = AWSAdapter(region='us-east-1')
            self.assertIs(adapter.session, fake_session)


if __name__ == '__main__':
    unittest.main()

class FxReliabilityRegressionTests(unittest.TestCase):
    def test_fx_normalized_usd_does_not_downgrade_reliable_pricing(self):
        from multicloud_ai.core import pricing
        r = NormalizedResource('disk','disk','Azure','block_storage',cost=8300,currency='INR')
        converted = convert_billing([r], {'INR':0.012})[0]
        row = pricing._row(converted, converted, 'AWS', converted.cost,
                           pricing.PriceResult(80, confidence='Live catalog + billed usage', coverage='Full'))
        self.assertEqual(row['Source Currency'], 'USD')
        self.assertEqual(row['Pricing Reliability'], 'Reliable')
        self.assertIsNotNone(row['Savings (USD)'])

class CrossCloudGenerationSmokeTests(unittest.TestCase):
    def test_azure_source_generates_valid_aws_and_gcp_terraform(self):
        from multicloud_ai.core.terraform import generate
        source = [
            NormalizedResource('/subscriptions/x/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet', 'vnet', 'Azure', 'virtual_network', region='eastus', configuration={'network': {'address_spaces':['10.0.0.0/16']}}),
            NormalizedResource('/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1', 'd1', 'Azure', 'block_storage', region='eastus', configuration={'storage': {'size_gb':32,'disk_type':'Premium_LRS'}}),
        ]
        for target in ('AWS','GCP'):
            text = generate(source, [], target)
            report = validate_terraform_text(text, target)
            self.assertTrue(report.valid, report.errors)
            self.assertGreater(report.resource_count, 0)

    def test_aws_source_generates_target_artifacts_without_exception(self):
        from multicloud_ai.core.terraform import generate
        source = [NormalizedResource('arn:aws:ec2:us-east-1:1:vpc/vpc-1','vpc-1','AWS','virtual_network',region='us-east-1',configuration={'network':{'cidr':'10.0.0.0/16'}})]
        for target in ('Azure','GCP'):
            text = generate(source, [], target)
            self.assertTrue(text.strip())
            self.assertTrue(validate_terraform_text(text, target).valid)

    def test_gcp_source_generates_target_artifacts_without_exception(self):
        from multicloud_ai.core.terraform import generate
        source = [NormalizedResource('//compute.googleapis.com/projects/p/global/networks/vpc','vpc','GCP','virtual_network',region='us-central1',configuration={'network':{'cidr':'10.0.0.0/16'}})]
        for target in ('AWS','Azure'):
            text = generate(source, [], target)
            self.assertTrue(text.strip())
            self.assertTrue(validate_terraform_text(text, target).valid)

class MigrationPlanTests(unittest.TestCase):
    def test_dependency_target_is_scheduled_before_dependent(self):
        from multicloud_ai.core.models import Dependency
        from multicloud_ai.core.strategy import build_migration_plan
        network = NormalizedResource('net','network','Azure','virtual_network')
        vm = NormalizedResource('vm','vm','Azure','compute_instance')
        plan = build_migration_plan([vm, network], [Dependency('vm','net','references','explicit')])
        waves = {x.resource_id:x.wave for x in plan}
        self.assertLess(waves['net'], waves['vm'])
        self.assertEqual({x.resource_id:x.strategy for x in plan}['vm'], 'Rehost')
