import unittest
from unittest.mock import Mock
from multicloud_ai.cloud_adapters.azure import AzureAdapter, extract_subscription_id

class AzureDiscoveryTests(unittest.TestCase):
    def test_uppercase_billing_id_reaches_resource_graph(self):
        sid = "2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7"
        rid = f"/subscriptions/{sid}/resourceGroups/poc/providers/Microsoft.DataFactory/factories/test".upper()
        self.assertEqual(extract_subscription_id(rid), sid)
        adapter = AzureAdapter.__new__(AzureAdapter)
        adapter.subscriptions = []
        adapter.client = Mock()
        adapter.client.resources.return_value = Mock(data=[])
        self.assertEqual(adapter.discover([rid]), [])
        adapter.client.resources.assert_called_once()
        request = adapter.client.resources.call_args.args[0]
        self.assertIn(rid, request.query)
        self.assertEqual(request.subscriptions, [sid])
        related = set()
        adapter._collect_resource_ids({"id": rid}, related)
        self.assertEqual(related, {rid})

class AzureDiscoveryBatchingTests(unittest.TestCase):
    def test_resource_ids_are_case_insensitively_deduplicated(self):
        sid = "2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7"
        rid = f"/subscriptions/{sid}/resourceGroups/poc/providers/Microsoft.Compute/virtualMachines/vm"
        deduped = AzureAdapter._dedupe_resource_ids([rid, rid.upper(), rid + "/", "not-an-arm-id"])
        self.assertEqual(deduped, [rid])

    def test_query_ids_batches_large_resource_sets(self):
        sid = "2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7"
        ids = [
            f"/subscriptions/{sid}/resourceGroups/poc/providers/Microsoft.Compute/virtualMachines/vm{i}"
            for i in range(205)
        ]
        adapter = AzureAdapter.__new__(AzureAdapter)
        adapter.client = Mock()
        adapter.client.resources.return_value = Mock(data=[])
        result = adapter._query_ids(ids, [sid], "Azure Resource Graph")
        self.assertEqual(result, {})
        self.assertEqual(adapter.client.resources.call_count, 3)
