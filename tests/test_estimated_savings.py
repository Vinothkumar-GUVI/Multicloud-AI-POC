import unittest
from unittest.mock import Mock
from multicloud_ai.core import pricing
from multicloud_ai.core.models import NormalizedResource

class EstimatedSavingsTests(unittest.TestCase):
    def test_zero_source_without_discovery_does_not_query_provider(self):
        r=NormalizedResource('zero','zero','Azure','other',cost=0)
        provider=Mock()
        row=pricing.compare_billing_to_target([r], [], 'AWS', pricing_provider=provider)[0]
        self.assertIsNone(row['Target Monthly Cost (USD)'])
        self.assertIsNone(row['Estimated Savings (USD)'])
        self.assertNotEqual(row['Pricing Reliability'],'Reliable')
        provider.price.assert_not_called()

    def test_baseline_difference_and_summary_exclude_unpriced_rows(self):
        r=NormalizedResource('vm','vm','Azure','compute_instance',cost=1.73)
        row=pricing._row(r,r,'AWS',1.73,pricing.PriceResult(3.90,confidence='baseline',coverage='Partial'))
        self.assertAlmostEqual(row['Estimated Savings (USD)'],-2.17)
        self.assertIsNone(row['Savings (USD)'])
        missing=pricing._row(r,r,'AWS',28.15,pricing.PriceResult(None))
        summary=pricing.summarize([row,missing],'Azure')
        self.assertAlmostEqual(summary['estimated_savings'],-2.17)
        self.assertEqual(summary['estimated_savings_count'],1)

    def test_near_zero_source_does_not_invent_zero_target_and_currency_must_match(self):
        r=NormalizedResource('tiny','tiny','Azure','other',cost=0.0001)
        row=pricing.compare_billing_to_target([r],[],'AWS')[0]
        self.assertIsNone(row['Target Monthly Cost (USD)'])
        self.assertIsNone(row['Estimated Savings (USD)'])
        r.currency='INR'
        row=pricing._row(r,r,'AWS',100,pricing.PriceResult(2))
        self.assertIsNone(row['Estimated Savings (USD)'])

    def test_zero_rule_applies_after_aggregation(self):
        r=NormalizedResource('tiny','tiny','Azure','other',cost=0.003)
        row=pricing.compare_billing_to_target([r,r],[],'AWS')[0]
        self.assertIsNone(row['Target Monthly Cost (USD)'])

    def test_difference_matches_displayed_prices(self):
        r=NormalizedResource('disk','disk','Azure','block_storage',cost=1.934)
        row=pricing._row(r,r,'AWS',1.934,pricing.PriceResult(2.736))
        self.assertEqual(row['Estimated Savings (USD)'], -0.81)
