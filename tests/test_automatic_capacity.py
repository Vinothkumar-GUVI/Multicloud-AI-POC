import unittest
from unittest.mock import Mock
from multicloud_ai.cloud_adapters.azure import AzureAdapter
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core import pricing

class AutomaticCapacityTests(unittest.TestCase):
    def resource(self, registry=False):
        return NormalizedResource('/subscriptions/test/resourceGroups/test/providers/Microsoft.Storage/storageAccounts/test', 'test', 'Azure',
            'container_registry' if registry else 'object_storage',
            raw_type='Microsoft.ContainerRegistry/registries' if registry else 'Microsoft.Storage/storageAccounts')

    def test_registry_uses_current_usage_not_quota(self):
        adapter = AzureAdapter.__new__(AzureAdapter)
        adapter._arm_get = Mock(return_value={'value':[{'name':'Size','unit':'Bytes','currentValue':1024**3,'limit':100*1024**3}]})
        r = self.resource(True)
        adapter._enrich_storage_capacity(r)
        self.assertEqual(r.configuration['storage_gb'], 1)

    def test_latest_blob_measurement_preserves_zero(self):
        adapter = AzureAdapter.__new__(AzureAdapter)
        adapter._arm_get = Mock(return_value={'value':[{'name':{'value':'BlobCapacity'},'unit':'Bytes','timeseries':[{'data':[
            {'timeStamp':'2026-09-12T01:00:00Z','average':1024},
            {'timeStamp':'2026-09-12T02:00:00Z','average':0}]}]}]})
        r = self.resource()
        adapter._enrich_storage_capacity(r)
        self.assertEqual(r.configuration['measured_storage_bytes'], 0)
        provider = pricing.AWSPriceProvider.__new__(pricing.AWSPriceProvider)
        provider.enabled = True
        provider.client = Mock()
        result = provider.price(r)
        self.assertEqual(result.monthly_cost, 0)
        self.assertEqual(pricing._pricing_reliability(result), 'Baseline / assumption')

    def test_missing_metric_is_not_zero(self):
        adapter = AzureAdapter.__new__(AzureAdapter)
        adapter._arm_get = Mock(return_value={'value':[]})
        r = self.resource()
        adapter._enrich_storage_capacity(r)
        self.assertNotIn('measured_storage_bytes', r.configuration)
        self.assertIn('storage_capacity_error', r.configuration)

    def test_measured_storage_reaches_live_catalog(self):
        r = self.resource()
        r.configuration.update(measured_storage_bytes=2*1024**3, target_region='us-east-1',storage_capacity_source='Azure Monitor')
        provider = pricing.AWSPriceProvider.__new__(pricing.AWSPriceProvider)
        provider.enabled = True
        provider.client = Mock()
        provider._query = Mock(return_value=([{'terms': {'OnDemand': {'term': {
            'priceDimensions': {'storage': {'beginRange': '0', 'endRange': 'Inf',
                'unit': 'GB-Mo', 'pricePerUnit': {'USD': '0.023'}}}
        }}}}], ''))
        result = provider.price(r)
        self.assertAlmostEqual(result.monthly_cost, 0.046)
        self.assertEqual(result.coverage, 'Storage only')
        self.assertEqual(r.usage_quantity, 0)
        self.assertIn({'Type': 'TERM_MATCH', 'Field': 'volumeType', 'Value': 'Standard'},
                      provider._query.call_args.args[1])

    def test_bad_request_retries_minimal_query(self):
        import requests
        adapter = AzureAdapter.__new__(AzureAdapter)
        response = Mock(status_code=400)
        adapter._arm_get = Mock(side_effect=[requests.HTTPError(response=response),
            {'value':[{'name':{'value':'BlobCapacity'},'unit':'Bytes','timeseries':[{'data':[
                {'timeStamp':'2026-09-12T02:00:00Z','average':1024**3}]}]}]}])
        r = self.resource()
        adapter._enrich_storage_capacity(r)
        self.assertEqual(r.configuration['storage_gb'], 1)
        first, second = adapter._arm_get.call_args_list
        self.assertIn('AutoAdjustTimegrain', first.args[1])
        self.assertNotIn('metricnamespace', second.args[1])
        self.assertNotIn('interval', second.args[1])
        self.assertIn('Z/', second.args[1]['timespan'])

    def test_forbidden_is_not_retried_and_bad_request_has_service_detail(self):
        import requests
        for status in [400,403]:
            adapter = AzureAdapter.__new__(AzureAdapter)
            response = Mock(status_code=status)
            response.json.return_value = {'error':{'code':'TestCode','message':'Test metric detail'}}
            adapter._arm_get = Mock(side_effect=requests.HTTPError(response=response))
            r = self.resource()
            adapter._enrich_storage_capacity(r)
            self.assertIn('Test metric detail', r.configuration['storage_capacity_error'])
            self.assertEqual(adapter._arm_get.call_count, 2 if status == 400 else 1)
            if status == 400:
                self.assertNotIn('Check Azure read permissions',r.configuration['storage_capacity_error'])
