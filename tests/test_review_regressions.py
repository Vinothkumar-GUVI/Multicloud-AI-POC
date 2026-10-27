import unittest
from unittest.mock import Mock, patch
import requests
import importlib.util
from multicloud_ai.core import pricing
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.terraform import generate, hcl_string
from multicloud_ai.core.migration_mapper import _map_storage_final


class ReviewRegressionTests(unittest.TestCase):
    def test_gcp_service_account_can_load_skus(self):
        provider = pricing.GCPPriceProvider()
        provider.api_key = ''
        provider._adc_credentials = Mock(valid=True, token='test-token')
        response = Mock()
        response.json.return_value = {'skus': [{'name': 'sku'}]}
        with patch.object(pricing.requests, 'get', return_value=response) as get:
            self.assertEqual(len(provider._skus('compute')), 1)
            self.assertEqual(len(provider._skus('compute')), 1)
            get.assert_called_once()
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer test-token')

    @unittest.skipUnless(importlib.util.find_spec('google.auth') is not None, 'google-auth not installed on validation host')
    def test_gcp_failed_auth_attempted_once_per_analysis(self):
        provider = pricing.GCPPriceProvider()
        provider.api_key = ''
        with patch('google.auth.default', side_effect=RuntimeError('unavailable')) as auth:
            for _ in range(10):
                with self.assertRaises(ValueError):
                    provider._service_id(('Compute Engine',))
            auth.assert_called_once()

    def test_gcp_timeout_not_repeated_for_each_resource_but_new_run_retries(self):
        with patch.object(pricing.requests, 'get', side_effect=requests.Timeout()) as get:
            provider = pricing.GCPPriceProvider(api_key='test')
            for _ in range(10):
                with self.assertRaises(RuntimeError):
                    provider._service_id(('Compute Engine',))
            self.assertEqual(get.call_count, 1)
            with self.assertRaises(RuntimeError):
                pricing.GCPPriceProvider(api_key='test')._service_id(('Compute Engine',))
            self.assertEqual(get.call_count, 2)

    def test_gcp_service_catalog_reused_across_services(self):
        provider = pricing.GCPPriceProvider(api_key='test')
        response = Mock()
        response.json.return_value = {'services': [
            {'displayName': 'Compute Engine', 'serviceId': 'compute'},
            {'displayName': 'Cloud Storage', 'serviceId': 'storage'}]}
        with patch.object(pricing.requests, 'get', return_value=response) as get:
            self.assertEqual(provider._service_id(('Compute Engine',)), 'compute')
            self.assertEqual(provider._service_id(('Cloud Storage',)), 'storage')
            get.assert_called_once()

    def test_s3_tiers_apply_only_to_usage_in_each_band(self):
        product = {'terms': {'OnDemand': {'term': {'priceDimensions': {
            'first': {'beginRange': '0', 'endRange': '100', 'unit': 'GB-Mo', 'pricePerUnit': {'USD': '0.023'}},
            'next': {'beginRange': '100', 'endRange': 'Inf', 'unit': 'GB-Mo', 'pricePerUnit': {'USD': '0.0125'}}}}}}}
        self.assertAlmostEqual(pricing.AWSPriceProvider._tiered_storage_price([product], 1)[0], .023)
        self.assertAlmostEqual(pricing.AWSPriceProvider._tiered_storage_price([product], 150)[0], 2.925)

    def test_disk_mapping_and_terraform_use_gp3_baseline(self):
        disk = NormalizedResource('disk', 'disk', 'Azure', 'block_storage', region='eastus', configuration={'storage': {'size_gb': 30, 'disk_iops': 120, 'disk_mbps': 25}})
        text = generate([disk], [], 'AWS')
        self.assertIn('iops = 3000', text)
        self.assertIn('throughput = 125', text)
        self.assertNotIn('type = map(string) default', text)
        self.assertIn('IOPS=3000', _map_storage_final(disk, 'AWS')[0])

    def test_sql_server_is_not_silently_generated_as_postgres(self):
        db = NormalizedResource('db', 'db', 'Azure', 'relational_database', configuration={'database': {'engine': 'sqlserver'}})
        text = generate([db], [], 'AWS')
        self.assertNotIn('resource "aws_db_instance"', text)
        self.assertIn('REVIEW REQUIRED', text)

    def test_compute_default_network_is_declared_and_filters_are_multiline(self):
        vm = NormalizedResource('vm', 'vm', 'Azure', 'compute_instance', region='eastus', configuration={'compute': {'vm_size': 'Standard_B2s', 'os_type': 'Linux'}})
        text = generate([vm], [], 'AWS')
        self.assertIn('data "aws_subnets" "default"', text)
        self.assertNotIn('filter { name', text)
        self.assertEqual(hcl_string('a\nb'), '"a\\nb"')

    def test_progress_reaches_all_billing_groups(self):
        resource = NormalizedResource('x', 'x', 'Azure', 'other')
        progress = Mock()
        rows = pricing.compare_billing_to_target([resource], [], 'AWS', progress_callback=progress)
        self.assertEqual(len(rows), 1)
        self.assertEqual(progress.call_args.args, (1, 1))
