import json
import unittest
from unittest.mock import Mock, patch

from multicloud_ai.core import pricing
from multicloud_ai.core.models import NormalizedResource


def provider(client):
    result = pricing.AWSPriceProvider.__new__(pricing.AWSPriceProvider)
    result.enabled = True
    result.client = client
    result.init_error = ""
    return result


def product():
    return {"product": {"attributes": {"instanceType": "t3.small"}},
            "terms": {"OnDemand": {"term": {"priceDimensions": {
                "hourly": {"unit": "Hrs", "description": "per hour",
                           "pricePerUnit": {"USD": "0.02"}}
            }}}}}


class AWSPriceTests(unittest.TestCase):
    def test_compute_price_on_later_page_and_success_cache(self):
        client = Mock()
        client.get_products.side_effect = [
            {"PriceList": [], "NextToken": "page2"},
            {"PriceList": [json.dumps(product())]},
        ]
        aws = provider(client)
        resource = NormalizedResource(
            "vm", "vm", "Azure", "compute_instance", region="eastus",
            usage_quantity=10, usage_unit="Hours",
            configuration={"target_region": "us-east-1",
                           "target_instance_type": "t3.small"})
        result = aws.price(resource)
        self.assertAlmostEqual(result.monthly_cost, 0.2)
        self.assertEqual(client.get_products.call_args.kwargs["NextToken"], "page2")
        aws.price(resource)
        self.assertEqual(client.get_products.call_count, 2)

    def test_transient_failure_is_retried(self):
        client = Mock()
        client.get_products.side_effect = [RuntimeError("temporary outage"),
                                          {"PriceList": [product()]}]
        aws = provider(client)
        self.assertIn("temporary outage", aws._products("AmazonEC2", "[]")[1])
        products, error = aws._products("AmazonEC2", "[]")
        self.assertEqual(error, "")
        self.assertEqual(len(products), 1)

    def test_failed_later_page_does_not_cache_partial_catalog(self):
        client = Mock()
        client.get_products.side_effect = [
            {"PriceList": [product()], "NextToken": "page2"},
            RuntimeError("temporary outage"),
            {"PriceList": [product()]},
        ]
        aws = provider(client)
        self.assertEqual(aws._products("AmazonEC2", "[]")[0], ())
        self.assertEqual(len(aws._products("AmazonEC2", "[]")[0]), 1)
        self.assertNotIn("NextToken", client.get_products.call_args.kwargs)

    def test_repeated_token_reports_incomplete_catalog(self):
        client = Mock()
        client.get_products.return_value = {"PriceList": [], "NextToken": "same"}
        products, error = provider(client)._products("AmazonEC2", "[]")
        self.assertEqual(products, ())
        self.assertIn("repeated pagination token", error)
        self.assertEqual(client.get_products.call_count, 2)

    def test_public_ip_billed_hours_use_vpc_catalog(self):
        client = Mock()
        client.get_products.return_value = {"PriceList": [product()]}
        resource = NormalizedResource("ip", "ip", "Azure", "public_ip",
                                      region="us-east-1", usage_quantity=5, usage_unit="Hours")
        result = provider(client).price(resource)
        self.assertAlmostEqual(result.monthly_cost, 5 * 0.02)
        self.assertEqual(client.get_products.call_args.kwargs["ServiceCode"], "AmazonVPC")
        self.assertNotEqual(pricing._pricing_reliability(result), "Baseline / assumption")

    def test_public_ip_catalog_error_is_not_hidden_by_missing_hours(self):
        client = Mock()
        client.get_products.side_effect = RuntimeError("catalog denied")
        resource = NormalizedResource("ip", "ip", "Azure", "public_ip", usage_quantity=5, usage_unit="Hours")
        result = provider(client).price(resource)
        self.assertIn("catalog denied", result.reason)
        self.assertEqual(client.get_products.call_count, 1)

    def test_missing_database_size_does_not_select_cheapest_instance(self):
        client = Mock()
        resource = NormalizedResource("db", "db", "Azure", "relational_database", usage_quantity=5, usage_unit="Hours")
        result = provider(client).price(resource)
        self.assertIsNone(result.monthly_cost)
        self.assertIn("instance class", result.reason)
        client.get_products.assert_not_called()

    def test_vault_and_control_plane_are_not_priced_as_workloads(self):
        for kind in ("secrets_manager", "machine_learning", "data_pipeline"):
            with self.subTest(kind=kind):
                client = Mock()
                resource = NormalizedResource("id", "name", "Azure", kind)
                self.assertIsNone(provider(client).price(resource).monthly_cost)
                client.get_products.assert_not_called()

    def test_dns_selects_starting_tier(self):
        catalog = product()
        catalog["product"]["attributes"] = {"groupDescription": "Hosted zone"}
        catalog["terms"]["OnDemand"]["term"]["priceDimensions"] = {
            "first": {"beginRange": "0", "unit": "HostedZone",
                      "description": "$0.50 per Hosted Zone for the first 25 Hosted Zones",
                      "pricePerUnit": {"USD": "0.50"}},
            "later": {"beginRange": "25", "unit": "HostedZone",
                      "description": "$0.10 per Hosted Zone for additional Hosted Zones",
                      "pricePerUnit": {"USD": "0.10"}},
        }
        client = Mock()
        client.get_products.return_value = {"PriceList": [catalog]}
        resource = NormalizedResource("zone", "zone", "Azure", "dns")
        self.assertEqual(provider(client).price(resource).monthly_cost, 0.5)

    def test_partial_and_baseline_rows_have_no_savings(self):
        resource = NormalizedResource("vm", "vm", "Azure", "compute_instance")
        for confidence, coverage, reason in (
            ("Live catalog + configured baseline usage", "Full", ""),
            ("Live catalog + billed usage", "Instance only", ""),
            ("Live catalog + billed/configured usage", "Full", "Live configured storage capacity"),
        ):
            result = pricing.PriceResult(10, confidence=confidence,
                                         coverage=coverage, reason=reason)
            row = pricing._enhanced_row(resource, resource, "AWS", 20, result)
            self.assertIsNone(row["Savings (USD)"])
            self.assertIsNone(row["Savings %"])
            self.assertFalse(pricing.summarize([row], "Azure")["reliable"])

    def test_unpriced_row_never_reports_full_coverage(self):
        resource = NormalizedResource("id", "name", "Azure", "object_storage")
        row = pricing._enhanced_row(resource, resource, "AWS", 20,
                                    pricing.PriceResult(None, reason="Missing usage"))
        self.assertEqual(row["Pricing Coverage"], "Unavailable")

    def test_low_confidence_compute_mapping_does_not_query_catalog(self):
        resource = NormalizedResource("vm", "mlops", "Azure", "compute_instance",
            region="eastus", usage_quantity=5, usage_unit="Hours", configuration={"compute": {"vm_size": "Standard_NV999_unknown"}})
        aws = Mock()
        with patch.object(pricing, "_provider", return_value=aws):
            result = pricing.price_resource(resource, "AWS")
        self.assertIsNone(result.monthly_cost)
        self.assertIn("Standard_NV999_unknown", result.reason)
        aws.price.assert_not_called()

    def test_database_mapping_does_not_invent_default_size(self):
        from multicloud_ai.core.migration_mapper import _map_db_final
        resource = NormalizedResource("db", "db", "Azure", "relational_database",
            configuration={"database": {"engine": "postgresql", "storage_gb": 32}})
        description, confidence = _map_db_final(resource, "AWS")
        self.assertNotIn("db.t3.medium", description)
        self.assertEqual(confidence, "Low")

    def test_inr_source_can_be_priced_without_claiming_usd_savings(self):
        source = NormalizedResource("vm", "vm", "Azure", "compute_instance",
            currency="INR", cost=100, usage_quantity=10, usage_unit="Hours")
        result = pricing.PriceResult(2, confidence="Live catalog + billed usage")
        with patch.object(pricing, "price_resource", return_value=result) as lookup:
            rows = pricing.compare_billing_to_target([source], [source], "AWS")
        lookup.assert_called_once()
        self.assertEqual(rows[0]["Target Monthly Cost (USD)"], 2)
        self.assertEqual(rows[0]["Source Billed Cost"], 100)
        self.assertEqual(rows[0]["Source Currency"], "INR")
        self.assertIsNone(rows[0]["Source Billed Cost (USD)"])
        self.assertIsNone(rows[0]["Savings (USD)"])
        summary = pricing.summarize(rows, "Azure")
        self.assertEqual(summary["source_total"], 100)
        self.assertEqual(summary["target_total"], 2)
        self.assertFalse(summary["reliable"])
        self.assertIsNone(summary["savings"])

    def test_initialization_failure_can_recover(self):
        failed = Mock(enabled=False)
        with patch.object(pricing, "_AWS_PROVIDER", failed), patch.object(
            pricing, "AWSPriceProvider"
        ) as factory:
            self.assertIs(pricing._provider("AWS"), factory.return_value)
            factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
