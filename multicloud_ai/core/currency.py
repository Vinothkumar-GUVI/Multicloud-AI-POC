"""Explicit display conversion; original billing objects remain unchanged."""
from dataclasses import replace
from math import isfinite
import requests
import json
import ssl
import urllib.request
try:
    import truststore
except Exception:  # optional on minimal/test environments
    truststore = None


def _primary_usd_rate(currency):
    try:
        response = requests.get(f"https://api.frankfurter.dev/v2/rate/{currency}/USD", timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.SSLError as exc:
        raise ValueError("HTTPS certificate verification failed. If your network inspects HTTPS, configure REQUESTS_CA_BUNDLE with your IT-approved PEM certificate bundle and restart Streamlit.") from exc
    except requests.exceptions.ProxyError as exc:
        raise ValueError("The configured network proxy could not reach the exchange-rate service. Check the approved proxy/network settings and retry.") from exc
    except requests.exceptions.JSONDecodeError as exc:
        raise ValueError("The exchange-rate service returned non-JSON content. A network filter or sign-in page may be intercepting the request.") from exc
    except requests.RequestException as exc:
        raise ValueError("The exchange-rate service could not be reached or returned an HTTP error. Retry after network access is restored.") from exc
    rate = float(data["rate"])
    if data.get("base") != currency or data.get("quote") != "USD" or not isfinite(rate) or rate <= 0:
        raise ValueError("Invalid exchange-rate response")
    return rate, data["date"]


def fetch_usd_rate(currency):
    currency = currency.upper().strip()
    if currency == "USD":
        return 1.0, "Already USD"
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("Invalid currency code")
    try:
        rate, date = _primary_usd_rate(currency)
        return rate, f"{date} (Frankfurter)"
    except (ValueError, KeyError, TypeError):
        pass
    try:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if truststore is not None else ssl.create_default_context()
        with urllib.request.urlopen(
            f"https://www.floatrates.com/daily/{currency.lower()}.json",
            context=context, timeout=10,
        ) as response:
            data = json.load(response)["usd"]
        rate = float(data["rate"])
        if data.get("code") != "USD" or not isfinite(rate) or rate <= 0:
            raise ValueError("Invalid fallback rate")
        return rate, f"{data['date']} (FloatRates)"
    except Exception as exc:
        raise ValueError("Automatic USD conversion is temporarily unavailable. Check network access to the exchange-rate services and retry. HTTPS certificate verification remains enabled.") from exc


def convert_billing(resources, rates):
    result = []
    for resource in resources:
        currency = resource.currency.upper()
        if currency == "USD":
            result.append(replace(resource))
            continue
        rate = rates.get(currency)
        if rate is None:
            result.append(replace(resource))
            continue
        if not isfinite(rate) or rate <= 0:
            raise ValueError("Exchange rates must be positive finite numbers")
        converted = replace(resource, cost=resource.cost * rate, currency="USD")
        converted.fx_converted = True
        converted.configuration = dict(getattr(converted, "configuration", {}) or {})
        converted.configuration["fx_normalization"] = {
            "original_currency": currency,
            "original_cost": resource.cost,
            "usd_rate": rate,
            "normalized_currency": "USD",
        }
        result.append(converted)
    return result
