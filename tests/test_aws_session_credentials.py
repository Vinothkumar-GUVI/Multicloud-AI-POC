import unittest
from unittest.mock import Mock, patch
from multicloud_ai.core import pricing
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.cloud_adapters.aws import AWSAdapter

class SessionCredentialsTests(unittest.TestCase):
    def test_missing_keys_use_standard_sdk_chain(self):
        fake = Mock()
        fake.get_credentials.return_value = Mock()
        fake.client.return_value = Mock()
        with patch.object(pricing.boto3, 'Session', return_value=fake) as session:
            pricing._aws_session()
            session.assert_called_with(region_name='us-east-1')

    def test_explicit_keys_and_token_reach_sdk(self):
        with patch.object(pricing.boto3, 'Session') as session:
            pricing._aws_session('test-key', 'test-secret', 'test-token')
            session.assert_called_once_with(aws_access_key_id='test-key', aws_secret_access_key='test-secret', aws_session_token='test-token', region_name='us-east-1')

    def test_comparisons_use_their_own_provider(self):
        resource = NormalizedResource('vm', 'vm', 'Azure', 'compute_instance', cost=1, usage_quantity=5, usage_unit='Hours')
        first, second = Mock(), Mock()
        first.price.return_value = pricing.PriceResult(2)
        second.price.return_value = pricing.PriceResult(3)
        with patch.object(pricing, '_provider') as global_provider, patch.object(pricing, '_target_sku', return_value={}):
            rows1 = pricing.compare_billing_to_target([resource], [resource], 'AWS', pricing_provider=first)
            rows2 = pricing.compare_billing_to_target([resource], [resource], 'AWS', pricing_provider=second)
        global_provider.assert_not_called()
        self.assertEqual(rows1[0]['Target Monthly Cost (USD)'], 2)
        self.assertEqual(rows2[0]['Target Monthly Cost (USD)'], 3)
