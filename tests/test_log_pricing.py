from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from multicloud_ai.core.log_pricing import price_logs
from multicloud_ai.core.pricing import PriceResult


def test_billed_log_quantity_uses_regional_rate_without_free_tier():
    resource=SimpleNamespace(region="eastus",configuration={"target_region":"us-east-1","billing_components":[{"meter":{"name":"Analytics Logs Data Ingestion"},"quantity":.000017397,"unit":"1 GB"}]})
    provider=Mock();provider._region_filters.return_value=[]
    product={"product":{"attributes":{"operation":"PutLogEvents","usagetype":"USE1-DataProcessing-Bytes","regionCode":"us-east-1"}},"terms":{"OnDemand":{"term":{"priceDimensions":{"rate":{"unit":"GB","beginRange":"0","endRange":"Inf","pricePerUnit":{"USD":"0.5"}}}}}}}
    provider._query.return_value=([product],"")
    result=price_logs(provider,resource,PriceResult)
    assert result.monthly_cost==pytest.approx(.0000086985)
    assert result.coverage=="Ingestion only"
    provider._query.return_value=([product,product],"")
    assert price_logs(provider,resource,PriceResult).monthly_cost is None
    provider._query.return_value=([],"AccessDenied")
    assert price_logs(provider,resource,PriceResult).reason=="AccessDenied"
    provider._query.return_value=([product],"")
    resource.configuration["billing_components"][0]["unit"]="Requests"
    assert price_logs(provider,resource,PriceResult).monthly_cost is None
