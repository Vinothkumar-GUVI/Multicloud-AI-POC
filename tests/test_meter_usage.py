import unittest
from unittest.mock import Mock

import pandas as pd

from multicloud_ai.core.billing import parse
from multicloud_ai.core.pricing import _aggregate_billing
from multicloud_ai.core.usage import normalize_usage


class MeterUsageTests(unittest.TestCase):
    def test_azure_pricing_unit_prefix_is_not_a_usage_multiplier(self):
        self.assertEqual(normalize_usage(0.800015, "100 Hours"), (0.800015, "Hours"))
        self.assertEqual(normalize_usage(24, "1000 Hours"), (24.0, "Hours"))
        self.assertEqual(normalize_usage(1, "200 Hours"), (1.0, "Hours"))
        self.assertEqual(normalize_usage(2, "vCPU-hours"), (2.0, "vCPU-hours"))
        # Storage pricing-unit labels are preserved; target capacity comes from live discovery.
        self.assertEqual(normalize_usage(2, "100 GB/Month"), (2.0, "100 GB/Month"))

    def test_resource_aggregation_preserves_cost_meters_and_dates(self):
        rows, _ = parse(pd.DataFrame([
            dict(
                InstanceId="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/poc/providers/Microsoft.Compute/virtualMachines/vm",
                ResourceType="Microsoft.Compute/virtualMachines",
                MeterId=meter,
                MeterName=meter,
                MeterCategory="Virtual Machines",
                UsageDateTime=day,
                UsageQuantity=2,
                UnitOfMeasure="1 Hour",
                PreTaxCost=3,
                Currency="USD",
            )
            for meter, day in [
                ("cpu", "2026-09-01"),
                ("cpu", "2026-09-02"),
                ("license", "2026-09-01"),
            ]
        ]), "Azure")
        grouped = _aggregate_billing(rows)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0].usage_quantity, 6)
        self.assertEqual(grouped[0].cost, 9)
        self.assertEqual(len(grouped[0].configuration["billing_usage"]["dates"]), 2)
        self.assertEqual(len(grouped[0].configuration["billing_meters"]), 2)
        self.assertEqual(len(rows[0].configuration["billing_usage"]["dates"]), 1)

    def test_short_runtime_remains_short_runtime(self):
        rows, _ = parse(pd.DataFrame([dict(
            InstanceId="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/poc/providers/Microsoft.Compute/virtualMachines/vm",
            ResourceType="Microsoft.Compute/virtualMachines",
            UsageDateTime="2026-09-01",
            UsageQuantity=0.800015,
            UnitOfMeasure="100 Hours",
            PreTaxCost=31.02,
        )]), "Azure")
        self.assertAlmostEqual(rows[0].usage_quantity, 0.800015)
        self.assertEqual(rows[0].usage_unit, "Hours")
        self.assertNotIn("error", rows[0].configuration["billing_usage"])
