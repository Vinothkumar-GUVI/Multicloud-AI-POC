from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from multicloud_ai.core.workload_pricing import price_workload, catalog_component
from multicloud_ai.core.pricing import PriceResult


def product():
    return {"product":{"productFamily":"Database Storage","attributes":{"regionCode":"us-east-2","usagetype":"USE2-DocDB:StorageUsage"}},
            "terms":{"OnDemand":{"t":{"priceDimensions":{"a":{"unit":"GB-Mo","beginRange":"0","endRange":"10","pricePerUnit":{"USD":"0.1"}},
            "b":{"unit":"GB-Mo","beginRange":"10","endRange":"Inf","pricePerUnit":{"USD":"0.05"}}}}}}}


def test_storage_tiers_are_integrated_not_flattened():
    p=Mock();p._query.return_value=([product()],"")
    value,error=catalog_component(p,"AmazonDocDB","us-east-2",{"productFamily":"Database Storage"},{"GB-Mo"},15,r"(?:.*[-:])?StorageUsage")
    assert not error and value==pytest.approx(1.25)
    p._query.return_value=([product(),product()],"")
    assert catalog_component(p,"AmazonDocDB","us-east-2",{}, {"GB-Mo"},15)[0] is None
    p._query.return_value=([],"AccessDenied")
    assert catalog_component(p,"AmazonDocDB","us-east-2",{}, {"GB-Mo"},15)[1]=="AccessDenied"


def test_supplied_cosmos_storage_unit_has_numeric_partial_cost():
    p=Mock();p._query.return_value=([product()],"")
    r=SimpleNamespace(region="centralus",canonical_type="nosql_database",configuration={"target_region":"us-east-2","database":{"kind":"MongoDB"},"billing_components":[
        {"meter":{"category":"Azure Cosmos DB","name":"Data Stored"},"quantity":.007856,"unit":"10 GB/Month"},
        {"meter":{"category":"Azure Cosmos DB","name":"1M RUs"},"quantity":.000967,"unit":"100000000"}]})
    result=price_workload(p,r,PriceResult)
    assert result.monthly_cost==pytest.approx(.007856)
    assert result.usage==pytest.approx(.07856)
    assert result.coverage=="Storage only"
    r.configuration["database"]={"kind":"SQL"}
    assert price_workload(p,r,PriceResult) is None


def test_opensearch_uses_explicit_config_and_rejects_invalid_nodes():
    p=Mock();item=product()
    item["product"]={"attributes":{"regionCode":"us-east-2","instanceType":"t3.small.search"}}
    item["terms"]["OnDemand"]["t"]["priceDimensions"]={"a":{"unit":"Hrs","beginRange":"0","endRange":"Inf","pricePerUnit":{"USD":"0.1"}}}
    p._query.return_value=([item],"")
    r=SimpleNamespace(region="eastus2",canonical_type="search",configuration={"target_region":"us-east-2","target_instance_type":"t3.small.search","target_runtime_hours":489,"target_node_count":2})
    assert price_workload(p,r,PriceResult).monthly_cost==pytest.approx(97.8)
    r.configuration["target_node_count"]=-1
    assert price_workload(p,r,PriceResult).monthly_cost is None


def test_status_distinguishes_implementation_and_design():
    from multicloud_ai.core.equivalence import client_pricing_rows
    base={"Resource":"x","Type":"other","Current Cost (USD)":0,"AWS Cost (USD)":None}
    for reason,status in [("No safe AWS pricing rule is implemented", "Pricing mapping not implemented"),
                          ("Target design/usage mapping required, not an AWS permission failure", "Target design required"),
                          ("No catalog match", "Catalog match requires review")]:
        assert client_pricing_rows([dict(base, **{"AWS Pricing reason":reason})],["AWS"])[0]["AWS Cost status"]==status
