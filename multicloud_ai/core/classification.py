PATTERNS = [
    ("kubernetes_cluster", ["eks", "gke", "aks", "managedclusters", "kubernetes"]),
    ("serverless_function", ["lambda", "cloud functions", "cloudfunctions", "functionapp"]),
    ("container_service", ["containerapps", "container app", "cloud run", "apprunner", "ecs", "fargate"]),
    ("nosql_database", ["dynamodb", "cosmosdb", "documentdb", "firestore", "bigtable"]),
    ("data_warehouse", ["redshift", "bigquery", "synapse", "athena"]),
    ("relational_database", ["rds", "cloud sql", "sql/servers", "sql database", "postgres", "mysql", "aurora"]),
    ("cache", ["elasticache", "memorystore", "redis", "memcached"]),
    ("nat_gateway", ["natgateway", "nat gateway", "cloud nat"]),
    ("load_balancer", ["loadbalancer", "load balancer", "application gateway", "alb", "nlb", "elb"]),
    ("cdn", ["cloudfront", "cdn", "frontdoor"]),
    ("dns", ["route53", "route 53", "cloud dns", "dnszone", "dns zone", "privatednszones", "private dns"]),
    ("secrets_manager", ["keyvault", "key vault", "secretsmanager", "secretmanager"]),
    ("container_registry", ["ecr", "artifactregistry", "artifact registry", "containerregistry"]),
    ("public_ip", ["publicip", "public ip", "elastic ip", "compute/addresses"]),
    ("block_storage", ["ebs", "managed disk", "manageddisk", "persistent disk", "compute/disks"]),
    ("object_storage", ["s3", "storageaccounts", "storage account", "cloud storage", "gcs", "bucket"]),
    ("compute_instance", ["ec2", "virtualmachines", "virtual machine", "compute instance", "compute.googleapis.com/instance", "compute engine"]),
    ("virtual_network", ["vpc", "virtualnetwork", "virtual network", "vnet", "compute.googleapis.com/network"]),
    ("subnet", ["subnetwork", "subnet"]),
    ("network_interface", ["networkinterfaces", "network interface", "nic", "compute.googleapis.com/instancegroup"]),
    ("security_group", ["networksecuritygroups", "security group", "securitygroup", "firewall"]),
    ("generative_ai", ["azure openai", "openai", "foundry models", "foundry model", "amazon bedrock", "bedrock", "generative ai", "generativeai"]),
    ("machine_learning", ["machinelearningservices", "vertex ai", "aiplatform"]),
    ("data_pipeline", ["datafactory", "data fusion", "dataproc", "dataflow", "aws glue", "glue"]),
    ("logging", ["operationalinsights", "log analytics", "logging.googleapis.com", "cloudwatch logs", "cloudwatch"]),
    ("search", ["microsoft.search", "searchservices", "azure search", "vertex ai search"]),
    ("identity", ["managedidentity", "iam/serviceaccounts", "serviceaccount"]),
    ("database_mongo", ["documentdb/databaseaccounts", "cosmosdb", "mongodb"]),
    ("app_service", ["microsoft.web/sites", "app service", "webapp"]),
    ("app_service_plan", ["microsoft.web/serverfarms", "app service plan", "serverfarm"]),
]

def classify(raw_type: str, service: str = "") -> str:
    text = f"{raw_type} {service}".lower()
    # More specific types must win over generic words such as 'redis' or 'bucket'.
    for kind, words in PATTERNS:
        if any(w in text for w in words):
            return kind
    return "other"
