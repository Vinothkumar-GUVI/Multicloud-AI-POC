import json

import pandas as pd
import pytest

from multicloud_ai.core.billing import parse
from multicloud_ai.core.ai_comparison import apply_estimates
from multicloud_ai.core.comparison_model import compare_model


@pytest.mark.parametrize('product,meter,desc,qty,kind,unit', [
    ('AmazonSQS', 'USE2-Requests-Tier1', '$0.40 per million Amazon SQS standard requests', 6, 'other', 'requests'),
    ('awskms', 'us-east-2-KMS-Requests', '$0.03 per 10000 KMS requests', 28, 'other', 'requests'),
    ('AmazonS3', 'APS3-Requests-Tier1', '$0.005 per 1,000 PUT, COPY, POST, or LIST requests', 1, 'object_storage', 'requests'),
    ('AWSDataTransfer', 'APS3-DataTransfer-Out-Bytes', '$0.09 per GB - first 10 TB / month', 261, 'other', 'GB'),
    ('AmazonEC2', 'APS3-BoxUsage:t2.xlarge', '$0.2 per On Demand Linux t2.xlarge Instance Hour', 730, 'compute_instance', 'Hours'),
    ('AmazonEC2', 'USE2-EBS:VolumeUsage.gp3', '$0.08 per GB-month of provisioned gp3 storage', 750, 'block_storage', 'GB-month'),
])
def test_invoice_meter_names_are_not_units_or_service_patterns(product,meter,desc,qty,kind,unit):
    rows, skipped = parse(pd.DataFrame([{'ProductCode':product, 'UsageType':meter,
        'ItemDescription':desc, 'UsageQuantity':qty, 'Actual Cost':1, 'CurrencyCode':'USD',
        'RecordID':'1'}]), 'AWS')
    assert skipped == 0
    resource = rows[0]
    assert (resource.canonical_type, resource.usage_unit, resource.usage_quantity) == (kind, unit, qty)
    assert resource.configuration['billing_meter']['name'] == meter


@pytest.mark.parametrize('unit,qty,ai_qty,rate,expected', [
    ('requests', 6, 5774675000000, .0000004, .0000024),
    ('GB', 261.1128642, 261112.8642, .09, 23.500157778),
])
def test_aws_single_meter_quantities_override_invented_ai_usage(unit,qty,ai_qty,rate,expected):
    from multicloud_ai.core.models import NormalizedResource
    baseline = compare_model([NormalizedResource('r','r','AWS','other',cost=1)], 'AWS', {'Azure':1,'GCP':1})
    baseline.update(require_components=True,usage_contracts={'r':{'meters':[{'quantity':qty,'unit':unit}]}})
    entries = [{'resource_id':'r','targets':{cloud:{'monthly_cost_usd':ai_qty*rate,
        'service':'Example', 'assumptions':'same usage', 'components':[{'quantity':ai_qty,
        'unit':unit,'rate_unit':unit,'unit_price_usd':rate,'description':'usage','rate_basis':'test'}]}
        for cloud in ['Azure','GCP']}}]
    result = apply_estimates(baseline, entries)
    assert result['totals']['GCP'] == pytest.approx(expected)
    assert json.loads(result['rows'][0]['GCP Calculation'])[0]['quantity'] == qty


def test_aws_target_quote_per_million_is_normalized_to_single_request():
    from multicloud_ai.core.models import NormalizedResource
    baseline = compare_model([NormalizedResource('r','r','AWS','other',cost=1)], 'AWS', {'Azure':1,'GCP':1})
    baseline.update(require_components=True,usage_contracts={'r':{'meters':[{'quantity':6,'unit':'requests'}]}})
    entries = [{'resource_id':'r','targets':{cloud:{'monthly_cost_usd':2.4,
        'service':'Example', 'assumptions':'same requests', 'components':[{'quantity':6,
        'unit':'requests','rate_unit':'requests','unit_price_usd':.4,
        'description':'Requests','rate_basis':'$0.40 per million requests'}]} for cloud in ['Azure','GCP']}}]
    assert apply_estimates(baseline,entries)['totals']['GCP'] == pytest.approx(.0000024)
