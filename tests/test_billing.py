import io
import unittest

import pandas as pd

from multicloud_ai.core.billing import billing_period, detect, parse, read_table


class NamedBytesIO(io.BytesIO):
    name = "Azure Billing.csv"


class AzureBillingTests(unittest.TestCase):
    def test_instance_id_export_preserves_usage_and_currency(self):
        rows, skipped = parse(pd.DataFrame([{
            "SubscriptionGuid": "2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7",
            "InstanceId": "/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/poc/providers/Microsoft.Compute/virtualMachines/vm",
            "ResourceType": "Microsoft.Compute/virtualMachines",
            "UsageQuantity": 1.5,
            "UnitOfMeasure": "200 Hours",
            "PreTaxCost": 12.75,
            "Currency": "INR",
            "UsageDateTime": "2026-09-10",
        }]), "Azure")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].resource_id.endswith("/vm"))
        self.assertEqual(rows[0].usage_quantity, 1.5)
        self.assertEqual(rows[0].configuration["billing_usage"]["original_quantity"], 1.5)
        self.assertEqual(rows[0].usage_unit, "Hours")
        self.assertEqual(rows[0].currency, "INR")
        self.assertEqual(rows[0].cost, 12.75)
        self.assertEqual(rows[0].canonical_type, "compute_instance")

    def test_actual_azure_schema_is_detected(self):
        df = pd.DataFrame([{
            "SubscriptionGuid": "x",
            "ResourceGroup": "Internal-POC",
            "ResourceLocation": "US East 2",
            "UsageDateTime": "2026-09-10",
            "MeterCategory": "Storage",
            "MeterName": "Hot LRS Data Stored",
            "UsageQuantity": 0.000051,
            "ResourceRate": 1.530782,
            "PreTaxCost": 0.000078069882,
            "ConsumedService": "Microsoft.Storage",
            "ResourceType": "Microsoft.Storage/storageAccounts",
            "InstanceId": "/subscriptions/x/resourceGroups/poc/providers/Microsoft.Storage/storageAccounts/a",
            "Currency": "INR",
            "UnitOfMeasure": "100 GB/Month",
        }])
        self.assertEqual(detect(df), "Azure")
        rows, skipped = parse(df, "Azure")
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0].canonical_type, "object_storage")
        self.assertEqual(rows[0].configuration["billing_meter"]["raw_unit"], "100 GB/Month")
        self.assertEqual(rows[0].usage_quantity, 0.000051)

    def test_resource_type_wins_over_meter_description(self):
        rows, _ = parse(pd.DataFrame([{
            "InstanceId": "/subscriptions/x/resourceGroups/poc/providers/Microsoft.MachineLearningServices/workspaces/ws",
            "ResourceType": "Microsoft.MachineLearningServices/workspaces",
            "MeterCategory": "Virtual Network",
            "MeterName": "Standard IPv4 Static Public IP",
            "UsageQuantity": 1,
            "UnitOfMeasure": "200 Hours",
            "PreTaxCost": 1,
            "Currency": "INR",
        }]), "Azure")
        self.assertEqual(rows[0].canonical_type, "machine_learning")

    def test_resource_id_takes_precedence_and_usd_is_preserved(self):
        rows, _ = parse(pd.DataFrame([{
            "ResourceId": "primary",
            "InstanceId": "secondary",
            "CostUSD": 2,
            "PreTaxCost": 170,
            "Currency": "INR",
        }]), "Azure")
        self.assertEqual(rows[0].resource_id, "primary")
        self.assertEqual(rows[0].cost, 2)
        self.assertEqual(rows[0].currency, "USD")

    def test_billing_period_is_inclusive(self):
        rows, _ = parse(pd.DataFrame([
            {"InstanceId": "/subscriptions/x/a", "ResourceType": "Microsoft.Compute/virtualMachines", "UsageDateTime": "2026-09-01", "PreTaxCost": 1},
            {"InstanceId": "/subscriptions/x/b", "ResourceType": "Microsoft.Compute/virtualMachines", "UsageDateTime": "2026-09-10", "PreTaxCost": 1},
        ]), "Azure")
        self.assertEqual(billing_period(rows), {"start": "2026-09-01", "end": "2026-09-10", "days": 10})

    def test_read_table_is_independent_of_file_pointer(self):
        payload = b"InstanceId,ResourceType,PreTaxCost\n/subscriptions/x/a,Microsoft.Compute/virtualMachines,1\n"
        upload = NamedBytesIO(payload)
        upload.read()  # simulate a prior consumer moving the pointer to EOF
        frame = read_table(upload)
        self.assertEqual(len(frame), 1)
        self.assertIn("InstanceId", frame.columns)
