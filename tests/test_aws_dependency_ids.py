from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.dependencies import build


def resource(service, kind, name, cfg=None, region="us-east-1", account="123456789012"):
    return NormalizedResource(f"arn:aws:{service}:{region}:{account}:{kind}/{name}",name,"AWS",kind,
                              region=region,configuration=cfg or {})


def test_aws_short_ids_resolve_from_lambda_and_subnet_to_vpc():
    vpc=resource("ec2","vpc","vpc-ab12")
    subnet=resource("ec2","subnet","subnet-cd34",{"network":{"vpc_id":"vpc-ab12"}})
    fn=resource("lambda","function","fn",{"serverless":{"vpc_config":{"SubnetIds":["subnet-cd34"]}}})
    edges=build([vpc,subnet,fn])
    assert {(e.source_id,e.target_id) for e in edges}=={(fn.resource_id,subnet.resource_id),(subnet.resource_id,vpc.resource_id)}


def test_short_ids_cannot_cross_region_or_account_or_match_self():
    ref=resource("ec2","subnet","subnet-ab12",{"network":{"vpc_id":"vpc-cd34","subnet_id":"subnet-ab12"}})
    other_region=resource("ec2","vpc","vpc-cd34",region="us-west-2")
    other_account=resource("ec2","vpc","vpc-cd34",account="999999999999")
    assert build([ref,other_region,other_account])==[]


def test_plain_names_do_not_create_edges():
    a=resource("ec2","instance","i-ab12",{"tags":{"Name":"myserver"}})
    b=resource("ec2","instance","i-cd34")
    b.name="myserver"
    assert build([a,b])==[]
