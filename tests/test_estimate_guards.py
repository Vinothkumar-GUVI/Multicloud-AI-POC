from types import SimpleNamespace
import pytest
from multicloud_ai.core.estimate_guards import workload_contract, validate_service_mapping


def resource(configuration=None):
    return SimpleNamespace(raw_type='Microsoft.DocumentDB/databaseAccounts',
                           resource_id='/subscriptions/s/providers/Microsoft.DocumentDB/databaseAccounts/db',
                           configuration=configuration or {})


def test_workload_evidence_detects_serverless_but_does_not_infer_mongo_from_name():
    r = resource({'billing_components': [{'meter': {'subcategory': 'serverless'}}]})
    c = workload_contract(r, {})
    assert c['cosmos_account'] and c['serverless_source']
    assert not c['mongo_api']
    assert workload_contract(r, {'Configuration': {'engine':'MongoDB'}})['mongo_api']


@pytest.mark.parametrize('cloud', ['AWS','Azure','GCP'])
def test_incompatible_mongo_mappings_are_rejected_in_every_target(cloud):
    for service in ['Amazon DynamoDB', 'Google Cloud Bigtable', 'Firestore']:
        with pytest.raises(ValueError, match='Incompatible target service'):
            validate_service_mapping({'mongo_api':True}, {'service':service}, cloud)


def test_legitimate_expensive_mongo_target_is_not_capped():
    detail = {'service':'Amazon DocumentDB', 'monthly_cost_usd':5000, 'components':[]}
    validate_service_mapping({'mongo_api':True}, detail, 'AWS')
    assert detail['monthly_cost_usd'] == 5000


def test_cosmos_bigtable_is_rejected_even_without_explicit_mongo_engine():
    with pytest.raises(ValueError, match='Incompatible target service'):
        validate_service_mapping({'cosmos_account':True}, {'service':'Google Cloud Bigtable'}, 'GCP')


@pytest.mark.parametrize('cloud', ['AWS','Azure','GCP'])
def test_hourly_storage_multiplier_is_rejected_for_all_clouds(cloud):
    with pytest.raises(ValueError, match='Incompatible target usage'):
        validate_service_mapping({}, {'service':'Storage', 'components':[
            {'unit':'Hours','rate_basis':'USD 0.10 per GB-month'}]}, cloud)


def test_registry_tier_meter_cannot_be_used_for_storage():
    with pytest.raises(ValueError, match='Incompatible target usage'):
        validate_service_mapping({'resource_type':'container_registry','meters':[{'name':'Basic Registry Unit'}]},
                                 {'service':'ECR','components':[{'unit':'GB-month','meter_index':0}]}, 'AWS')


@pytest.mark.parametrize('invalid_cache', [False, True])
def test_invalid_service_response_is_corrected_instead_of_entering_totals(monkeypatch, invalid_cache):
    from multicloud_ai.core.models import NormalizedResource
    from multicloud_ai.core import ai_comparison as comparison
    from copy import deepcopy
    r = NormalizedResource('/subscriptions/s/providers/Microsoft.DocumentDB/databaseAccounts/db','db',
                           'Azure','nosql_database',raw_type='Microsoft.DocumentDB/databaseAccounts',cost=.003)
    calls = []
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        targets = {c:{'monthly_cost_usd':8,'service':'MongoDB Atlas', 'assumptions':'Small paid tier; no free tier assumed',
                      'components':[{'quantity':1,'unit':'month','rate_unit':'month','unit_price_usd':8,
                                     'description':'Tier minimum','rate_basis':'USD 8 per month'}]} for c in ['AWS','GCP']}
        if len(calls)==1 and not invalid_cache:
            targets['GCP']['service'] = 'Google Cloud Bigtable'
            targets['GCP']['components'][0]['unit_price_usd'] = 468
        return {'report':{'estimates':[{'resource_id':r.resource_id.lower(),'targets':targets}]}}
    monkeypatch.setattr(comparison,'run_agent',agent)
    cache = {}
    if invalid_cache:
        cache[(r.resource_id.lower(),)] = [{'resource_id':r.resource_id.lower(),'targets':{
            c: {'service':'Bigtable','monthly_cost_usd':468,'assumptions':'Invalid cached mapping','components':[]}
            for c in ['AWS','GCP']}}]
    result = comparison.estimate_comparison(object(),[r],'Azure',None,[],[],estimate_cache=cache)
    assert len(calls)==(1 if invalid_cache else 2)
    assert 'Incompatible target service' in calls[0 if invalid_cache else 1]['validation_feedback']['error']
    assert result['totals']['GCP']==8
    assert cache[(r.resource_id.lower(),)][0]['targets']['GCP']['service'] == 'MongoDB Atlas'


def test_mongo_target_guidance_is_explicit_and_unknown_api_is_not_assumed():
    contract = workload_contract(resource({'database': {'engine': 'MongoDB'}}), {})
    assert 'MongoDB Atlas on GCP' in contract['target_service_constraints']['GCP']
    assert 'GCP' not in workload_contract(resource(), {})['target_service_constraints']
