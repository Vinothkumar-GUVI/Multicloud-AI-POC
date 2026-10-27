import unittest
from unittest.mock import Mock
from multicloud_ai.core import pricing
from multicloud_ai.core.models import NormalizedResource

class RuntimePricingTests(unittest.TestCase):
    def test_missing_runtime_never_uses_configured_month(self):
        r=NormalizedResource('vm','vm','Azure','compute_instance',configuration={'runtime_hours':730})
        for target in ['AWS','GCP','Azure']:
            provider=Mock()
            result=pricing.price_resource(r,target,pricing_provider=provider)
            self.assertIsNone(result.monthly_cost)
            provider.price.assert_not_called()
        self.assertEqual(pricing._enhanced_hours_from_usage(r),(None,''))

    def test_time_units_convert_but_capacity_hours_do_not(self):
        for qty,unit,expected in [(2,'Hours',2),(120,'minutes',2),(7200,'seconds',2),(2,'vCPU-hours',None),(2,'GB-hours',None)]:
            r=NormalizedResource('vm','vm','Azure','compute_instance',usage_quantity=qty,usage_unit=unit)
            self.assertEqual(pricing._hours_from_usage(r),expected)

    def test_aws_compute_prices_billed_hours_only(self):
        provider=pricing.AWSPriceProvider.__new__(pricing.AWSPriceProvider)
        provider.enabled=True
        provider.client=Mock()
        provider._query=Mock(return_value=([{}],''))
        provider._best_price=Mock(return_value=(0.541,'Hrs','compute'))
        r=NormalizedResource('vm','vm','Azure','compute_instance',usage_quantity=2,usage_unit='Hours',configuration={'target_instance_type':'g4ad.2xlarge','target_region':'us-east-1'})
        result=provider.price(r)
        self.assertAlmostEqual(result.monthly_cost,1.082)
