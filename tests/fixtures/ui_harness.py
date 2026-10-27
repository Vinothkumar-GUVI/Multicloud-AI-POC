
import io
import runpy
from unittest.mock import patch, Mock
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.pricing import PriceResult
class Upload(io.BytesIO):
    name='synthetic_azure.csv'
rid='/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test-rg/providers/Microsoft.Network/publicIPAddresses/ip'
payload=('InstanceId,ResourceType,UsageQuantity,UnitOfMeasure,PreTaxCost,Currency,UsageDateTime\n'+rid+',Microsoft.Network/publicIPAddresses,24,Hours,1,USD,2026-09-01\n').encode()
def upload(*args,**kwargs):
    return Upload(payload) if kwargs.get('key')=='billing_upload' else None
live=[NormalizedResource(rid,'ip','Azure','public_ip',region='eastus',configuration={'network':{'allocation_method':'Static'}})]
provider=Mock(enabled=True)
provider.price.return_value=PriceResult(.12,confidence='Live catalog + billed usage',source='Synthetic test',sku='Test')
with patch('streamlit.file_uploader',side_effect=upload), patch('multicloud_ai.cloud_adapters.azure.AzureAdapter',return_value=Mock(discover=Mock(return_value=live))), patch('multicloud_ai.core.pricing.AWSPriceProvider',return_value=provider), patch('multicloud_ai.core.pricing.GCPPriceProvider',return_value=provider):
    runpy.run_path('app.py',run_name='__main__')
