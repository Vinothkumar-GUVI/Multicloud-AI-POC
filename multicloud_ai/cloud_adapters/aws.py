import boto3
import os
from contextlib import contextmanager
from .base import CloudAdapter
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.classification import classify


def _arn_id(arn):
    text=str(arn or "")
    return text.split("/")[-1].split(":")[-1]


def _plain(value):
    if isinstance(value, dict): return {str(k): _plain(v) for k,v in value.items()}
    if isinstance(value, list): return [_plain(v) for v in value]
    if hasattr(value, "isoformat"): return value.isoformat()
    return value


def aws_resource_kind(raw_type, service):
    """EC2 is a service namespace, not proof that a resource is an instance."""
    raw = str(raw_type or "").lower()
    if str(service).lower() == "ec2" or raw.startswith("ec2:"):
        subtype = raw.rsplit(":", 1)[-1].replace("_", "-")
        return {"instance": "compute_instance", "volume": "block_storage", "vpc": "virtual_network",
                "subnet": "subnet", "network-interface": "network_interface", "security-group": "security_group",
                "security-group-rule": "security_group_rule", "route-table": "route_table", "network-acl": "network_acl",
                "internet-gateway": "internet_gateway", "natgateway": "nat_gateway", "nat-gateway": "nat_gateway",
                "elastic-ip": "public_ip", "elastic-ip-address": "public_ip", "key-pair": "ssh_key",
                "dhcp-options": "dhcp_options", "vpc-endpoint": "private_endpoint"}.get(subtype, "other")
    if str(service).lower() == "iam":
        return "identity"
    if str(service).lower() == "elasticache":
        # Users, user groups and parameter groups are not provisioned caches.
        subtype = raw.rsplit(":", 1)[-1].replace("-", "")
        return "cache" if subtype in {"cluster", "replicationgroup", "serverlesscache"} else "other"
    return classify(raw_type, service)


@contextmanager
def _without_profile_environment(enabled=True):
    if not enabled:
        yield
        return
    saved_profile = os.environ.pop("AWS_PROFILE", None)
    saved_default_profile = os.environ.pop("AWS_DEFAULT_PROFILE", None)
    try:
        yield
    finally:
        if saved_profile is not None:
            os.environ["AWS_PROFILE"] = saved_profile
        if saved_default_profile is not None:
            os.environ["AWS_DEFAULT_PROFILE"] = saved_default_profile


class AWSAdapter(CloudAdapter):
    cloud="AWS"
    def __init__(self, region="us-east-1", access_key_id=None, secret_access_key=None, session_token=None):
        self.region=region
        # Empty AWS_PROFILE values break botocore profile resolution.
        if not str(os.getenv("AWS_PROFILE", "")).strip():
            os.environ.pop("AWS_PROFILE", None)
        if not str(os.getenv("AWS_DEFAULT_PROFILE", "")).strip():
            os.environ.pop("AWS_DEFAULT_PROFILE", None)
        kwargs={}
        explicit = bool(access_key_id and secret_access_key)
        if explicit:
            kwargs.update(aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key)
            if session_token:
                kwargs["aws_session_token"]=session_token

        # Explicit in-application credentials must not be blocked by machine-level
        # AWS profile selectors. The process environment is restored immediately.
        self._explicit_credentials = explicit
        with _without_profile_environment(explicit):
            self.session=boto3.Session(region_name=region, **kwargs)
            if self.session.get_credentials() is None:
                raise RuntimeError("AWS credentials could not be resolved. Enter Access Key ID and Secret Access Key under Cloud Access, or use a supported runtime identity.")
            self.explorer=self.session.client("resource-explorer-2",region_name=region)
        self._clients={}

    def _client(self, service, region=None):
        key=(service,region or self.region)
        if key not in self._clients:
            with _without_profile_environment(self._explicit_credentials):
                self._clients[key]=self.session.client(service,region_name=region or self.region)
        return self._clients[key]

    def _service_configuration(self, item):
        arn=item.get("Arn","")
        service=str(item.get("Service","")).lower()
        rtype=str(item.get("ResourceType","")).lower()
        rid=_arn_id(arn)
        def regional_client(service_name, region=None):
            item_region = item.get("Region") or self.region
            return self._client(service_name, region or (self.region if item_region == "global" else item_region))
        cfg={"resource_explorer": {k:_plain(v) for k,v in item.items() if k not in {"Arn","Region","Service","ResourceType"}}}
        try:
            network_lookups = {
                "route-table": ("describe_route_tables", "RouteTableIds", "RouteTables"),
                "internet-gateway": ("describe_internet_gateways", "InternetGatewayIds", "InternetGateways"),
                "network-acl": ("describe_network_acls", "NetworkAclIds", "NetworkAcls"),
                "security-group-rule": ("describe_security_group_rules", "SecurityGroupRuleIds", "SecurityGroupRules"),
                "network-interface": ("describe_network_interfaces", "NetworkInterfaceIds", "NetworkInterfaces"),
                "key-pair": ("describe_key_pairs", "KeyPairIds", "KeyPairs"),
                "dhcp-options": ("describe_dhcp_options", "DhcpOptionsIds", "DhcpOptions"),
            }
            subtype = rtype.rsplit(":", 1)[-1]
            if service == "ec2" and subtype in network_lookups:
                method, parameter, result = network_lookups[subtype]
                rows = getattr(regional_client("ec2", item.get("Region") or self.region), method)(**{parameter: [rid]}).get(result, [])
                if rows:
                    cfg["network" if subtype != "key-pair" else "ssh_key"] = _plain(rows[0])
            elif service=="ec2" and (rtype.rsplit(":", 1)[-1] == "instance" or ":instance/" in arn):
                d=regional_client("ec2").describe_instances(InstanceIds=[rid])
                if d.get("Reservations") and d["Reservations"][0].get("Instances"):
                    x=_plain(d["Reservations"][0]["Instances"][0])
                    b=x.get("BlockDeviceMappings",[])
                    root=next((m.get("Ebs",{}) for m in b if m.get("DeviceName")==x.get("RootDeviceName")),{})
                    cfg["compute"]={"instance_type":x.get("InstanceType"),"ami_id":x.get("ImageId"),"availability_zone":x.get("Placement",{}).get("AvailabilityZone"),"vpc_id":x.get("VpcId"),"subnet_id":x.get("SubnetId"),"private_ip":x.get("PrivateIpAddress"),"public_ip":x.get("PublicIpAddress"),"security_group_ids":[g.get("GroupId") for g in x.get("SecurityGroups",[])],"root_volume_id":root.get("VolumeId"),"root_volume_size_gb":None,"platform":x.get("Platform") or x.get("PlatformDetails") or "Linux/UNIX","architecture":x.get("Architecture"),"tags":{t.get("Key"):t.get("Value") for t in x.get("Tags",[])}}
                    try:
                        instance_type=x.get("InstanceType")
                        if instance_type:
                            info=regional_client("ec2").describe_instance_types(InstanceTypes=[instance_type]).get("InstanceTypes",[])
                            if info:
                                spec=_plain(info[0])
                                cfg["compute"]["vcpu"]=(spec.get("VCpuInfo") or {}).get("DefaultVCpus")
                                mem_mib=(spec.get("MemoryInfo") or {}).get("SizeInMiB")
                                cfg["compute"]["memory_gb"]=(float(mem_mib)/1024.0) if mem_mib else None
                    except Exception:
                        pass
                    if root.get("VolumeId"):
                        try:
                            vol=regional_client("ec2").describe_volumes(VolumeIds=[root["VolumeId"]]).get("Volumes",[])
                            if vol: cfg["compute"]["root_volume_size_gb"]=vol[0].get("Size")
                        except Exception: pass
            elif service=="ec2" and ("volume" in rtype or ":volume/" in arn):
                d=regional_client("ec2").describe_volumes(VolumeIds=[rid]).get("Volumes",[])
                if d:
                    x=_plain(d[0]); cfg["storage"]={"size_gb":x.get("Size"),"volume_type":x.get("VolumeType"),"iops":x.get("Iops"),"throughput":x.get("Throughput"),"encrypted":x.get("Encrypted"),"availability_zone":x.get("AvailabilityZone"),"snapshot_id":x.get("SnapshotId")}
            elif service=="ec2" and (subtype == "vpc" or ":vpc/" in arn):
                d=regional_client("ec2").describe_vpcs(VpcIds=[rid]).get("Vpcs",[])
                if d:
                    x=_plain(d[0]); cfg["network"]={"vpc_id":x.get("VpcId"),"cidr":x.get("CidrBlock"),"is_default":x.get("IsDefault"),"state":x.get("State"),"tags":{t.get("Key"):t.get("Value") for t in x.get("Tags",[])}}
            elif service=="ec2" and "subnet" in rtype:
                d=regional_client("ec2").describe_subnets(SubnetIds=[rid]).get("Subnets",[])
                if d:
                    x=_plain(d[0]); cfg["network"]={"subnet_id":x.get("SubnetId"),"vpc_id":x.get("VpcId"),"cidr":x.get("CidrBlock"),"availability_zone":x.get("AvailabilityZone"),"map_public_ip_on_launch":x.get("MapPublicIpOnLaunch")}
            elif service=="ec2" and (subtype == "security-group" or "securitygroup" == subtype):
                d=regional_client("ec2").describe_security_groups(GroupIds=[rid]).get("SecurityGroups",[])
                if d:
                    x=_plain(d[0]); cfg["security_group"]={"group_id":x.get("GroupId"),"vpc_id":x.get("VpcId"),"description":x.get("Description"),"ingress":x.get("IpPermissions",[]),"egress":x.get("IpPermissionsEgress",[])}
            elif service=="s3" and ("bucket" in rtype or ":s3:" in arn):
                name=rid; s3=regional_client("s3")
                cfg["object_storage"]={"bucket":name}
                try: cfg["object_storage"]["location"]=_plain(s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1")
                except Exception: pass
                try: cfg["object_storage"]["versioning"]=_plain(s3.get_bucket_versioning(Bucket=name).get("Status"))
                except Exception: pass
            elif service=="ecr" and "repository" in rtype:
                x=regional_client("ecr").describe_repositories(repositoryNames=[rid]).get("repositories",[])
                if x:
                    y=_plain(x[0]); cfg["registry"]={"repository_name":y.get("repositoryName"),"uri":y.get("repositoryUri"),"image_tag_mutability":y.get("imageTagMutability"),"scan_on_push":y.get("imageScanningConfiguration",{}).get("scanOnPush")}
            elif service=="rds" and ("db" in rtype or "cluster" in rtype):
                if "cluster" in rtype:
                    x=regional_client("rds").describe_db_clusters(DBClusterIdentifier=rid).get("DBClusters",[])
                    if x:
                        y=_plain(x[0]); cfg["database"]={"engine":y.get("Engine"),"engine_version":y.get("EngineVersion"),"instance_class":y.get("DBClusterMembers"),"storage_gb":y.get("AllocatedStorage"),"multi_az":y.get("MultiAZ")}
                else:
                    x=regional_client("rds").describe_db_instances(DBInstanceIdentifier=rid).get("DBInstances",[])
                    if x:
                        y=_plain(x[0]); cfg["database"]={"engine":y.get("Engine"),"engine_version":y.get("EngineVersion"),"instance_class":y.get("DBInstanceClass"),"storage_gb":y.get("AllocatedStorage"),"storage_type":y.get("StorageType"),"iops":y.get("Iops"),"multi_az":y.get("MultiAZ"),"publicly_accessible":y.get("PubliclyAccessible"),"vpc_id":y.get("DBSubnetGroup",{}).get("VpcId")}
            elif service in {"secretsmanager"} and "secret" in rtype:
                x=regional_client("secretsmanager").describe_secret(SecretId=arn); cfg["secrets"]={"name":x.get("Name"),"kms_key_id":x.get("KmsKeyId"),"rotation_enabled":x.get("RotationEnabled"),"rotation_lambda_arn":x.get("RotationLambdaARN")}; cfg["secret_value_exposed"]=False
            elif service=="elasticache" and ("cluster" in rtype or "replication-group" in rtype):
                if "replication-group" in rtype:
                    x=regional_client("elasticache").describe_replication_groups(ReplicationGroupId=rid).get("ReplicationGroups",[])
                    if x: y=_plain(x[0]); cfg["cache"]={"engine":y.get("Engine"),"node_type":y.get("CacheNodeType"),"num_cache_clusters":y.get("NumCacheClusters"),"status":y.get("Status")}
            elif service=="ec2" and ("elastic-ip" in rtype or "address" in rtype or "eip" in rtype):
                ec2=regional_client("ec2")
                rows=ec2.describe_addresses(AllocationIds=[rid]).get("Addresses",[]) if rid.startswith("eipalloc-") else []
                if rows:
                    y=_plain(rows[0]); cfg["network"]={"allocation_id":y.get("AllocationId"),"public_ip":y.get("PublicIp"),"domain":y.get("Domain"),"instance_id":y.get("InstanceId"),"network_interface_id":y.get("NetworkInterfaceId"),"private_ip":y.get("PrivateIpAddress"),"association_id":y.get("AssociationId")}
            elif service=="lambda" or "lambda" in rtype:
                y=_plain(regional_client("lambda").get_function(FunctionName=arn or rid))
                c=y.get("Configuration",{}) or {}
                cfg["serverless"]={"runtime":c.get("Runtime"),"handler":c.get("Handler"),"memory_mb":c.get("MemorySize"),"timeout_seconds":c.get("Timeout"),"architectures":c.get("Architectures") or [],"ephemeral_storage_mb":(c.get("EphemeralStorage") or {}).get("Size"),"role_arn":c.get("Role"),"vpc_config":c.get("VpcConfig") or {},"environment_keys":sorted(((c.get("Environment") or {}).get("Variables") or {}).keys()),"package_type":c.get("PackageType")}
            elif service in {"elasticloadbalancing","elbv2"} or "loadbalancer" in rtype.lower():
                elb=regional_client("elbv2")
                lbs=elb.describe_load_balancers(LoadBalancerArns=[arn]).get("LoadBalancers",[])
                if lbs:
                    y=_plain(lbs[0]); listeners=[]; targets=[]
                    try: listeners=_plain(elb.describe_listeners(LoadBalancerArn=arn).get("Listeners",[]))
                    except Exception: pass
                    try: targets=_plain(elb.describe_target_groups(LoadBalancerArn=arn).get("TargetGroups",[]))
                    except Exception: pass
                    cfg["load_balancer"]={"type":y.get("Type"),"scheme":y.get("Scheme"),"ip_address_type":y.get("IpAddressType"),"vpc_id":y.get("VpcId"),"availability_zones":y.get("AvailabilityZones") or [],"security_groups":y.get("SecurityGroups") or [],"listeners":listeners,"target_groups":targets}
            elif service=="cloudfront" or "distribution" in rtype.lower():
                y=_plain(regional_client("cloudfront",region="us-east-1").get_distribution(Id=rid).get("Distribution",{}))
                dcfg=y.get("DistributionConfig",{}) or {}
                cfg["cdn"]={"enabled":dcfg.get("Enabled"),"price_class":dcfg.get("PriceClass"),"http_version":dcfg.get("HttpVersion"),"ipv6_enabled":dcfg.get("IsIPV6Enabled"),"aliases":(dcfg.get("Aliases") or {}).get("Items") or [],"origins":(dcfg.get("Origins") or {}).get("Items") or [],"default_cache_behavior":dcfg.get("DefaultCacheBehavior") or {}}
            elif service=="glue" or "glue" in rtype.lower():
                glue=regional_client("glue")
                if "workflow" in rtype.lower():
                    y=_plain(glue.get_workflow(Name=rid,IncludeGraph=False).get("Workflow",{})); cfg["data_pipeline"]={"kind":"workflow","description":y.get("Description"),"default_run_properties":y.get("DefaultRunProperties") or {},"max_concurrent_runs":y.get("MaxConcurrentRuns")}
                elif "job" in rtype.lower():
                    y=_plain(glue.get_job(JobName=rid).get("Job",{})); cfg["data_pipeline"]={"kind":"job","role":y.get("Role"),"glue_version":y.get("GlueVersion"),"worker_type":y.get("WorkerType"),"number_of_workers":y.get("NumberOfWorkers"),"max_capacity":y.get("MaxCapacity"),"timeout":y.get("Timeout"),"command":y.get("Command") or {}}
            elif service=="ecs" or "ecs" in rtype.lower():
                ecs=regional_client("ecs")
                if "/service/" in arn:
                    tail=arn.split("/service/",1)[1].split("/")
                    cluster=tail[0] if len(tail)>1 else None
                    rows=ecs.describe_services(cluster=cluster,services=[arn]).get("services",[]) if cluster else []
                    if rows:
                        y=_plain(rows[0]); cfg["container_service"]={"launch_type":y.get("launchType"),"platform_version":y.get("platformVersion"),"desired_count":y.get("desiredCount"),"task_definition":y.get("taskDefinition"),"network_configuration":y.get("networkConfiguration") or {},"load_balancers":y.get("loadBalancers") or [],"capacity_provider_strategy":y.get("capacityProviderStrategy") or []}
                elif "/cluster/" in arn:
                    rows=ecs.describe_clusters(clusters=[arn],include=["SETTINGS","CONFIGURATIONS"]).get("clusters",[])
                    if rows:
                        y=_plain(rows[0]); cfg["container_service"]={"kind":"cluster","status":y.get("status"),"registered_container_instances":y.get("registeredContainerInstancesCount"),"running_tasks":y.get("runningTasksCount"),"active_services":y.get("activeServicesCount"),"settings":y.get("settings") or [],"configuration":y.get("configuration") or {}}
            elif service=="eks" or "eks" in rtype.lower():
                y=_plain(regional_client("eks").describe_cluster(name=rid).get("cluster",{})); cfg["kubernetes"]={"version":y.get("version"),"status":y.get("status"),"role_arn":y.get("roleArn"),"endpoint_public_access":(y.get("resourcesVpcConfig") or {}).get("endpointPublicAccess"),"endpoint_private_access":(y.get("resourcesVpcConfig") or {}).get("endpointPrivateAccess"),"vpc_id":(y.get("resourcesVpcConfig") or {}).get("vpcId"),"subnet_ids":(y.get("resourcesVpcConfig") or {}).get("subnetIds") or [],"security_group_ids":(y.get("resourcesVpcConfig") or {}).get("securityGroupIds") or [],"encryption_config":y.get("encryptionConfig") or []}
            elif service=="route53" or "hostedzone" in rtype.replace("-","").lower():
                y=_plain(regional_client("route53",region="us-east-1").get_hosted_zone(Id=rid)); z=y.get("HostedZone",{}) or {}; cfg["dns"]={"name":z.get("Name"),"private_zone":(z.get("Config") or {}).get("PrivateZone"),"comment":(z.get("Config") or {}).get("Comment"),"vpcs":y.get("VPCs") or []}
            elif service=="dynamodb" and "table" in rtype.lower():
                y=_plain(regional_client("dynamodb").describe_table(TableName=rid).get("Table",{})); cfg["database"]={"engine":"dynamodb","key_schema":y.get("KeySchema") or [],"attribute_definitions":y.get("AttributeDefinitions") or [],"billing_mode":(y.get("BillingModeSummary") or {}).get("BillingMode"),"provisioned_throughput":y.get("ProvisionedThroughput") or {},"sse":y.get("SSEDescription") or {},"global_secondary_indexes":y.get("GlobalSecondaryIndexes") or []}
        except Exception as exc:
            cfg["discovery_warning"]=f"Service-specific configuration could not be retrieved: {exc}"
        return cfg

    def discover(self, resource_ids):
        supplied={str(x).rstrip("/") for x in (resource_ids or []) if str(x).strip()}
        # Invoice/service-summary exports may contain synthetic billing:// IDs.
        # In that case discover the account inventory and keep cost correlation
        # explicitly separate instead of filtering every live resource out.
        wanted={x for x in supplied if not x.lower().startswith("billing://")}
        wanted_short={_arn_id(x) for x in wanted}; out=[]
        try:
            token=None
            while True:
                kwargs={"QueryString":"*"}
                if token: kwargs["NextToken"]=token
                resp=self.explorer.search(**kwargs)
                for item in resp.get("Resources",[]):
                    rid=item.get("Arn","")
                    if wanted and rid.rstrip("/") not in wanted and _arn_id(rid) not in wanted_short: continue
                    cfg=self._service_configuration(item)
                    props=cfg.get("resource_explorer",{})
                    out.append(NormalizedResource(rid,rid.split("/")[-1].split(":")[-1],"AWS",aws_resource_kind(item.get("ResourceType",""),item.get("Service","")),item.get("ResourceType",""),item.get("Service",""),item.get("Region",self.region),"",configuration=cfg,configuration_source="AWS Resource Explorer + service API",configuration_confidence="Partial" if cfg.get("discovery_warning") else "Confirmed" if any(k != "resource_explorer" for k in cfg) else "Inventory metadata only"))
                token=resp.get("NextToken")
                if not token: break
        except Exception as exc:
            raise RuntimeError("AWS discovery failed. Ensure Resource Explorer and read permissions for the discovered services are available.") from exc
        return out
