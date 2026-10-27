import unittest
from unittest.mock import patch, Mock
from multicloud_ai.core.currency import convert_billing, fetch_usd_rate
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core import pricing
from multicloud_ai.core.billing import parse
import pandas as pd

class CurrencyTests(unittest.TestCase):
    def test_conversion_preserves_input_and_credits(self):
        rows = [NormalizedResource("id", "name", "Azure", "other", currency="INR", cost=n) for n in (100, -20)]
        converted = convert_billing(rows, {"INR": 0.01})
        self.assertAlmostEqual(sum(r.cost for r in converted), 0.8)
        self.assertEqual(rows[0].cost, 100)
        self.assertEqual(rows[0].currency, "INR")
        self.assertEqual(converted[0].currency, "USD")
        self.assertTrue(converted[0].fx_converted)
        self.assertEqual(len(pricing._aggregate_billing(converted)), 1)

    def test_missing_rate_does_not_relabel_inr(self):
        r = NormalizedResource("id", "n", "Azure", "other", currency="INR", cost=100)
        self.assertEqual(convert_billing([r], {})[0].currency, "INR")
        for rate in (0, -1, float("nan")):
            with self.assertRaises(ValueError): convert_billing([r], {"INR": rate})

    def test_reference_rate_validation(self):
        response = Mock()
        response.json.return_value = {"base":"INR", "quote":"USD", "rate":0.01, "date":"2026-09-10"}
        with patch("multicloud_ai.core.currency.requests.get", return_value=response):
            self.assertEqual(fetch_usd_rate("INR"), (0.01, "2026-09-10 (Frankfurter)"))

    def test_billed_database_meter_supplies_size(self):
        rows, _ = parse(pd.DataFrame([{"InstanceId":"db", "ResourceType":"Microsoft.DBforPostgreSQL/flexibleServers",
            "MeterName":"B1MS", "MeterSubCategory":"Burstable Compute", "UsageQuantity":10,
            "UnitOfMeasure":"Hours", "PreTaxCost":1, "Currency":"USD"}]), "Azure")
        live = NormalizedResource("db", "db", "Azure", "relational_database", configuration={"database":{"engine":"postgresql"}})
        with patch.object(pricing, "price_resource", return_value=pricing.PriceResult(None)) as call:
            pricing.compare_billing_to_target(rows, [live], "AWS")
        proxy = call.call_args.args[0]
        self.assertEqual(pricing._target_sku(proxy, "AWS")["target_instance_class"], "db.t3.small")

    def test_certificate_failure_has_actionable_message(self):
        import requests
        with patch("multicloud_ai.core.currency.requests.get", side_effect=requests.exceptions.SSLError("certificate failure")):
            with patch("multicloud_ai.core.currency.urllib.request.urlopen", side_effect=OSError("offline")), self.assertRaisesRegex(ValueError, "Automatic USD conversion") :
                fetch_usd_rate("INR")

    def test_automatic_fallback_uses_native_tls(self):
        import io
        import requests
        payload = b'{"usd":{"code":"USD","rate":0.01,"date":"test date"}}'
        with patch("multicloud_ai.core.currency.requests.get", side_effect=requests.exceptions.SSLError()), patch("multicloud_ai.core.currency.urllib.request.urlopen", return_value=io.BytesIO(payload)):
            self.assertEqual(fetch_usd_rate("INR"), (0.01, "test date (FloatRates)"))

    def test_usd_never_needs_network(self):
        with patch("multicloud_ai.core.currency.requests.get") as request:
            self.assertEqual(fetch_usd_rate("USD")[0], 1)
            request.assert_not_called()
