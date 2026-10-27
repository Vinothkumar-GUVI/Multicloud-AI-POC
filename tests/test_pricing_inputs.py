import unittest
from unittest.mock import Mock, patch
import requests
from multicloud_ai.core import pricing
from multicloud_ai.core.models import NormalizedResource

class PricingInputsTests(unittest.TestCase):
    def test_gcp_can_use_environment_key_without_ui_input(self):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {'ok': True}
        with patch.dict('os.environ', {'GCP_BILLING_API_KEY': 'ambient'}), patch.object(pricing.requests, 'get', return_value=response) as get:
            provider = pricing.GCPPriceProvider()
            self.assertEqual(provider._get_json(pricing.GCP_CATALOG, {}), {'ok': True})
            self.assertEqual(get.call_args.kwargs['headers']['X-Goog-Api-Key'], 'ambient')

    def test_gcp_key_in_header_and_errors_redacted(self):
        response = Mock(status_code=403)
        response.raise_for_status.side_effect = requests.HTTPError('sensitive-key', response=response)
        with patch.object(pricing.requests, 'get', return_value=response) as get:
            with self.assertRaises(RuntimeError) as error:
                pricing.GCPPriceProvider('sensitive-key')._get_json(pricing.GCP_CATALOG, {'key':'sensitive-key'})
            self.assertNotIn('sensitive-key', str(error.exception))
            self.assertIn('403', str(error.exception))
            self.assertEqual(get.call_args.kwargs['params'], {})
            self.assertEqual(get.call_args.kwargs['headers']['X-Goog-Api-Key'], 'sensitive-key')

    def test_gcp_catalog_cache_is_per_instance(self):
        first, second = pricing.GCPPriceProvider('first'), pricing.GCPPriceProvider('second')
        with patch.object(first, '_get_json', return_value={'skus':[{'name':'first'}]}) as a, patch.object(second, '_get_json', return_value={'skus':[{'name':'second'}]}) as b:
            self.assertEqual(first._skus('svc'), ({'name':'first'},))
            first._skus('svc')
            self.assertEqual(second._skus('svc'), ({'name':'second'},))
            a.assert_called_once()
            b.assert_called_once()


    def test_reported_gpu_gets_explicit_approximate_candidate(self):
        r=NormalizedResource('vm','mlops','Azure','compute_instance',region='eastus',usage_quantity=5,usage_unit='Hours',
            configuration={'compute':{'vm_size':'Standard_NV8as_v4'}})
        provider=Mock()
        provider.price.return_value=pricing.PriceResult(5,confidence='Live catalog + billed usage',coverage='Full')
        result=pricing.price_resource(r,'AWS',pricing_provider=provider)
        self.assertEqual(provider.price.call_args.args[0].configuration['target_instance_type'],'g4ad.2xlarge')
        self.assertIn('not an exact equivalent',result.reason)
        self.assertEqual(pricing._pricing_reliability(result),'Baseline / assumption')
