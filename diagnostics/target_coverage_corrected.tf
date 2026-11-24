terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Multi-Cloud AI — AZURE -> AWS
# Default-network fallbacks used only when the source did not expose a target subnet/VPC mapping.
data "aws_vpc" "default" { default = true }
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
# Generated from live resource discovery. Source configuration is used when exposed by the provider API.
# Target-cloud defaults are used only where the source API does not expose an equivalent setting.




resource "aws_vpc" "migrated" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}





resource "aws_ebs_volume" "devtest_osdisk_1_5827615136b14430a96272e649c97cb9" {
  availability_zone = "${var.aws_region}a"
  size              = 30
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  snapshot_id       = var.target_devtest_osdisk_1_5827615136b14430a96272e649c97cb9_snapshot_id
}

resource "aws_ebs_volume" "dwh_platform_datadisk_0" {
  availability_zone = "${var.aws_region}a"
  size              = 16
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  snapshot_id       = var.target_dwh_platform_datadisk_0_snapshot_id
}

resource "aws_ebs_volume" "dwh_platform_osdisk_1_56264da4f2c445dd8ed73482c9744f2c" {
  availability_zone = "${var.aws_region}a"
  size              = 64
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  snapshot_id       = var.target_dwh_platform_osdisk_1_56264da4f2c445dd8ed73482c9744f2c_snapshot_id
}

resource "aws_ebs_volume" "mlops_osdisk_1_716c68c32b6a42898a98d5769187eaa6" {
  availability_zone = "${var.aws_region}a"
  size              = 64
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  snapshot_id       = var.target_mlops_osdisk_1_716c68c32b6a42898a98d5769187eaa6_snapshot_id
}

resource "aws_ebs_volume" "nacmachinea_osdisk_1_d5dfeca78f194c008358d0a753ae185b" {
  availability_zone = "${var.aws_region}a"
  size              = 64
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  snapshot_id       = var.target_nacmachinea_osdisk_1_d5dfeca78f194c008358d0a753ae185b_snapshot_id
}

resource "aws_ebs_volume" "practice1_osdisk_1_066fab3369ef40ff9a9695257fd1155f" {
  availability_zone = "${var.aws_region}a"
  size              = 30
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  snapshot_id       = var.target_practice1_osdisk_1_066fab3369ef40ff9a9695257fd1155f_snapshot_id
}

data "aws_ami" "mlops_ami" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
resource "aws_instance" "mlops" {
  ami = var.target_mlops_ami_id
  instance_type = "g4ad.2xlarge"
  subnet_id     = data.aws_subnets.default.ids[0]
  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }
  tags = merge(var.default_tags, {
    Name = "mlops"
  })
}

resource "aws_ecr_repository" "acrsbzuciaipoc" {
  name = "acrsbzuciaipoc"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "datamigrationagent" {
  name = "datamigrationagent"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "sqlbot1" {
  name = "sqlbot1"
  image_scanning_configuration { scan_on_push = true }
}



resource "aws_route53_zone" "privatelink_mysql_database_azure_com" {
  name = "privatelink.mysql.database.azure.com"
}

resource "aws_route53_zone" "privatelink_redis_cache_windows_net" {
  name = "privatelink.redis.cache.windows.net"
}

resource "aws_eip" "devtest_ip" { domain = "vpc" }

resource "aws_eip" "dwh_platform_ip" { domain = "vpc" }

resource "aws_eip" "mlops_ip" { domain = "vpc" }

resource "aws_eip" "mlopsip616" { domain = "vpc" }

resource "aws_eip" "mlopsip847" { domain = "vpc" }

resource "aws_eip" "nacmachinea_ip_cca5941d" { domain = "vpc" }



resource "aws_s3_bucket" "centerofexcell5982957371" {
  bucket = "centerofexcell5982957371"
}

resource "aws_s3_bucket_public_access_block" "centerofexcell5982957371" {
  bucket                  = aws_s3_bucket.centerofexcell5982957371.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "coe4360812019" {
  bucket = "coe4360812019"
}

resource "aws_s3_bucket_public_access_block" "coe4360812019" {
  bucket                  = aws_s3_bucket.coe4360812019.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "dataiqaihub4393665029" {
  bucket = "dataiqaihub4393665029"
}

resource "aws_s3_bucket_public_access_block" "dataiqaihub4393665029" {
  bucket                  = aws_s3_bucket.dataiqaihub4393665029.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "docinteltestresult" {
  bucket = "docinteltestresult"
}

resource "aws_s3_bucket_public_access_block" "docinteltestresult" {
  bucket                  = aws_s3_bucket.docinteltestresult.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "internalpoc9dc1" {
  bucket = "internalpoc9dc1"
}

resource "aws_s3_bucket_public_access_block" "internalpoc9dc1" {
  bucket                  = aws_s3_bucket.internalpoc9dc1.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "macanpocstorageaccount" {
  bucket = "macanpocstorageaccount"
}

resource "aws_s3_bucket_public_access_block" "macanpocstorageaccount" {
  bucket                  = aws_s3_bucket.macanpocstorageaccount.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "mlopsdvcstore" {
  bucket = "mlopsdvcstore"
}

resource "aws_s3_bucket_public_access_block" "mlopsdvcstore" {
  bucket                  = aws_s3_bucket.mlopsdvcstore.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "nkusml0423074054" {
  bucket = "nkusml0423074054"
}

resource "aws_s3_bucket_public_access_block" "nkusml0423074054" {
  bucket                  = aws_s3_bucket.nkusml0423074054.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "nkusml9639037362" {
  bucket = "nkusml9639037362"
}

resource "aws_s3_bucket_public_access_block" "nkusml9639037362" {
  bucket                  = aws_s3_bucket.nkusml9639037362.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "npaml7729019114" {
  bucket = "npaml7729019114"
}

resource "aws_s3_bucket_public_access_block" "npaml7729019114" {
  bucket                  = aws_s3_bucket.npaml7729019114.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "stdataiq1515008267882418" {
  bucket = "stdataiq1515008267882418"
}

resource "aws_s3_bucket_public_access_block" "stdataiq1515008267882418" {
  bucket                  = aws_s3_bucket.stdataiq1515008267882418.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "tfstorageaccountrasi" {
  bucket = "tfstorageaccountrasi"
}

resource "aws_s3_bucket_public_access_block" "tfstorageaccountrasi" {
  bucket                  = aws_s3_bucket.tfstorageaccountrasi.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}







resource "aws_secretsmanager_secret" "coe0795089701" {
  name = "coe0795089701"
}

resource "aws_secretsmanager_secret" "nkusml1649788538" {
  name = "nkusml1649788538"
}


resource "aws_security_group" "mlopsnsg372" {
  name        = "mlopsnsg372"
  description = "Migrated security group"
  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol    = "tcp"
    from_port   = 22
    to_port     = 22
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol    = "tcp"
    from_port   = 8501
    to_port     = 8501
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol    = "tcp"
    from_port   = 9001
    to_port     = 9001
    cidr_blocks = ["0.0.0.0/0"]
  }
}


# ============================================================
# Migration warnings / review items
# ============================================================
# - data-migration-agent: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - centofexcelai: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - mlops-ai-api: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - Multicloud-AI: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - datafactorydocintellpoc: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - creditmlops21823: Database engine or instance sizing requires an explicit target design; no PostgreSQL default was substituted.
# - coepocmongo: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - COE_1: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - NKusml: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - law-sb-zuci-poc: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - dataiq-search: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - dataiq-server: Database engine or instance sizing requires an explicit target design; no PostgreSQL default was substituted.
# - azureblob: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - data-migration-agent: No safe provider-specific Terraform 1:1 mapping is available for this managed application service from the discovered metadata.
# - sb-zuci-ai-poc: No safe provider-specific Terraform 1:1 mapping is available for this managed application service from the discovered metadata.
# - sqlbot: No safe provider-specific Terraform 1:1 mapping is available for this managed application service from the discovered metadata.
# - nkusml8541076082: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - sb-zuci-ai-poc: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - coe0795089701: secret values are not exposed by discovery and are not copied.
# - nkusml1649788538: secret values are not exposed by discovery and are not copied.
# - COE: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - mlops404_z1: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - ASP-InternalPOC-9da0: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - DefaultWorkspace-2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7-EUS2: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - mlopsnsg372: security rules require review before apply because source and target firewall semantics differ.
# - nkusml0872833282: The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.
# - master: Database engine or instance sizing requires an explicit target design; no PostgreSQL default was substituted.

# Terraform provisions infrastructure. It does not copy application binaries, database contents, container images, secrets, ML models, search indexes, or other data-plane contents.
# Dependency relationships discovered by the source adapter are listed below.
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Compute/virtualMachines/mlops -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/INTERNAL-POC/providers/Microsoft.Compute/disks/mlops_OsDisk_1_716c68c32b6a42898a98d5769187eaa6 | references | High | Explicit resource ID reference at configuration path 'raw_properties.storageProfile.osDisk.managedDisk.id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Compute/virtualMachines/mlops -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkInterfaces/mlops404_z1 | references | High | Explicit resource ID reference at configuration path 'raw_properties.networkProfile.networkInterfaces[0].id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE_1 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE | references | High | Explicit resource ID reference at configuration path 'raw_properties.hubResourceId' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE_1 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/coe4360812019 | references | High | Explicit resource ID reference at configuration path 'machine_learning.storage_account_id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE_1 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.KeyVault/vaults/coe0795089701 | references | High | Explicit resource ID reference at configuration path 'machine_learning.key_vault_id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/NKusml -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/nkusml0423074054 | references | High | Explicit resource ID reference at configuration path 'machine_learning.storage_account_id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/NKusml -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.KeyVault/vaults/nkusml1649788538 | references | High | Explicit resource ID reference at configuration path 'machine_learning.key_vault_id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/data-migration-agent -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/serverFarms/ASP-InternalPOC-9da0 | references | High | Explicit resource ID reference at configuration path 'raw_properties.serverFarmId' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sb-zuci-ai-poc -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/microsoft.insights/components/sb-zuci-ai-poc | references | High | Explicit resource ID reference at configuration path 'tags.hidden-link: /app-insights-resource-id' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sb-zuci-ai-poc -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/serverFarms/ASP-InternalPOC-9da0 | references | High | Explicit resource ID reference at configuration path 'raw_properties.serverFarmId' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sqlbot -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/serverFarms/ASP-InternalPOC-9da0 | references | High | Explicit resource ID reference at configuration path 'raw_properties.serverFarmId' (Azure Resource Graph)
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Insights/components/nkusml8541076082 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.OperationalInsights/workspaces/nkusml0872833282 | references | High | Explicit resource ID reference at configuration path 'raw_properties.WorkspaceResourceId' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/microsoft.insights/components/sb-zuci-ai-poc -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/DefaultResourceGroup-EUS2/providers/Microsoft.OperationalInsights/workspaces/DefaultWorkspace-2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7-EUS2 | references | High | Explicit resource ID reference at configuration path 'raw_properties.WorkspaceResourceId' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/coe4360812019 | references | High | Explicit resource ID reference at configuration path 'machine_learning.storage_account_id' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.KeyVault/vaults/coe0795089701 | references | High | Explicit resource ID reference at configuration path 'machine_learning.key_vault_id' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkInterfaces/mlops404_z1 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/mlopsip847 | references | High | Explicit resource ID reference at configuration path 'raw_properties.ipConfigurations[0].properties.publicIPAddress.id' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkInterfaces/mlops404_z1 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkSecurityGroups/mlopsnsg372 | references | High | Explicit resource ID reference at configuration path 'raw_properties.networkSecurityGroup.id' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkInterfaces/mlops404_z1 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Compute/virtualMachines/mlops | references | High | Explicit resource ID reference at configuration path 'raw_properties.virtualMachine.id' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkSecurityGroups/mlopsnsg372 -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkInterfaces/mlops404_z1 | references | High | Explicit resource ID reference at configuration path 'raw_properties.networkInterfaces[0].id' (Azure Resource Graph (related dependency))
# /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Sql/servers/dataiq-server/databases/master -> /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Sql/servers/dataiq-server | references | High | Explicit resource ID reference at configuration path 'parent_resource_id' (Azure Resource Graph (child configuration))

# ============================================================
# Supplemental AWS resources generated from live configuration
# ============================================================
resource "aws_network_interface" "mlops404_z1" {
  subnet_id       = data.aws_subnets.default.ids[0]
  security_groups = [aws_security_group.mlopsnsg372.id]
  tags = merge(var.default_tags, {
    Name = "mlops404_z1"
  })
}



resource "aws_sagemaker_domain" "coe_1" {
  domain_name = "coe-1"
  auth_mode   = "IAM"
  vpc_id      = data.aws_vpc.default.id
  subnet_ids  = [data.aws_subnets.default.ids[0]]
  default_user_settings {
    execution_role = var.sagemaker_execution_role_arn
  }
}

resource "aws_sagemaker_domain" "nkusml" {
  domain_name = "nkusml"
  auth_mode   = "IAM"
  vpc_id      = data.aws_vpc.default.id
  subnet_ids  = [data.aws_subnets.default.ids[0]]
  default_user_settings {
    execution_role = var.sagemaker_execution_role_arn
  }
}

resource "aws_sagemaker_domain" "coe" {
  domain_name = "coe"
  auth_mode   = "IAM"
  vpc_id      = data.aws_vpc.default.id
  subnet_ids  = [data.aws_subnets.default.ids[0]]
  default_user_settings {
    execution_role = var.sagemaker_execution_role_arn
  }
}

resource "aws_glue_workflow" "datafactorydocintellpoc" {
  name = "datafactorydocintellpoc"
}

resource "aws_cloudwatch_log_group" "law_sb_zuci_poc" {
  name = "/migrated/law-sb-zuci-poc"
}

resource "aws_cloudwatch_log_group" "defaultworkspace_2e64ac5c_bc96_4389_a5bb_fc1c2e7bf8d7_eus2" {
  name = "/migrated/defaultworkspace-2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7-eus2"
}

resource "aws_cloudwatch_log_group" "nkusml0872833282" {
  name = "/migrated/nkusml0872833282"
}

# Supplemental mapping review items:
# - data-migration-agent: CloudFront not emitted because live origin_host was not exposed by Azure discovery.
# - COE_1: SageMaker domain is a control-plane shell; attached training/endpoints/storage are not inferred from workspace metadata.
# - NKusml: SageMaker domain is a control-plane shell; attached training/endpoints/storage are not inferred from workspace metadata.
# - COE: SageMaker domain is a control-plane shell; attached training/endpoints/storage are not inferred from workspace metadata.
# - datafactorydocintellpoc: Glue workflow shell generated; source ADF activities, linked services and DPU/runtime usage are not exposed by the factory record.
# - law-sb-zuci-poc: CloudWatch log group shell generated; historical logs and retention/ingestion volumes require separate migration/usage data.
# - DefaultWorkspace-2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7-EUS2: CloudWatch log group shell generated; historical logs and retention/ingestion volumes require separate migration/usage data.
# - nkusml0872833282: CloudWatch log group shell generated; historical logs and retention/ingestion volumes require separate migration/usage data.
# - coepocmongo: DynamoDB was not emitted because a live partition/hash key was not exposed; creating a guessed schema would be unsafe.
# TARGET INPUTS REQUIRED: data-migration-agent
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Cdn/profiles/data-migration-agent
# Mapping assumption: Proposed CloudFront HTTPS custom origin; supply caching policies and migrate custom domains, certificates and routing rules separately.
resource "aws_cloudfront_distribution" "data_migration_agent" {
  enabled = true
  origin {
    domain_name = var.target_data_migration_agent_origin_domain_name
    origin_id   = "migration-origin"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  default_cache_behavior {
    target_origin_id         = "migration-origin"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = var.target_data_migration_agent_allowed_methods
    cached_methods           = var.target_data_migration_agent_cached_methods
    cache_policy_id          = var.target_data_migration_agent_cache_policy_id
    origin_request_policy_id = var.target_data_migration_agent_origin_request_policy_id
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}

# TARGET INPUTS REQUIRED: centofexcelai
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.CognitiveServices/accounts/centofexcelai
# Mapping assumption: Bedrock inference profile is a proposed OpenAI workload mapping; validate model access, region and application API compatibility.
resource "aws_bedrock_inference_profile" "centofexcelai" {
  name = "centofexcelai"
  model_source { copy_from = var.target_centofexcelai_model_source_arn }
}

# TARGET INPUTS REQUIRED: mlops-ai-api
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.CognitiveServices/accounts/mlops-ai-api
# Mapping assumption: Bedrock inference profile is a proposed OpenAI workload mapping; validate model access, region and application API compatibility.
resource "aws_bedrock_inference_profile" "mlops_ai_api" {
  name = "mlops_ai_api"
  model_source { copy_from = var.target_mlops_ai_api_model_source_arn }
}

# TARGET INPUTS REQUIRED: Multicloud-AI
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.CognitiveServices/accounts/Multicloud-AI
# Mapping assumption: Bedrock inference profile is a proposed OpenAI workload mapping; validate model access, region and application API compatibility.
resource "aws_bedrock_inference_profile" "multicloud_ai" {
  name = "multicloud_ai"
  model_source { copy_from = var.target_multicloud_ai_model_source_arn }
}

# TARGET INPUTS REQUIRED: creditmlops21823
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.DBforPostgreSQL/flexibleServers/creditmlops21823
# Mapping assumption: RDS is a proposed database-engine mapping; migrate data separately and validate engine, licensing and availability requirements.
resource "aws_db_instance" "creditmlops21823" {
  identifier                = "creditmlops21823"
  engine                    = "postgres"
  engine_version            = var.target_creditmlops21823_engine_version
  instance_class            = var.target_creditmlops21823_instance_class
  allocated_storage         = var.target_creditmlops21823_allocated_storage_gb
  username                  = var.target_creditmlops21823_administrator_login
  password                  = var.target_creditmlops21823_administrator_password
  db_subnet_group_name      = var.target_creditmlops21823_db_subnet_group_name
  vpc_security_group_ids    = var.target_creditmlops21823_security_group_ids
  publicly_accessible       = false
  skip_final_snapshot       = false
  final_snapshot_identifier = var.target_creditmlops21823_final_snapshot_identifier
}

resource "aws_docdb_cluster_instance" "coepocmongo_instance" {
  identifier         = "coepocmongo-instance"
  cluster_identifier = aws_docdb_cluster.coepocmongo.id
  instance_class     = var.target_coepocmongo_instance_class
}

# TARGET INPUTS REQUIRED: coepocmongo
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.DocumentDb/databaseAccounts/coepocmongo
# Mapping assumption: DocumentDB is a proposed MongoDB-compatible destination; verify supported commands, indexes and consistency, then migrate data separately.
resource "aws_docdb_cluster" "coepocmongo" {
  cluster_identifier        = "coepocmongo"
  engine                    = "docdb"
  engine_version            = var.target_coepocmongo_engine_version
  master_username           = var.target_coepocmongo_administrator_login
  master_password           = var.target_coepocmongo_administrator_password
  db_subnet_group_name      = var.target_coepocmongo_db_subnet_group_name
  vpc_security_group_ids    = var.target_coepocmongo_security_group_ids
  skip_final_snapshot       = false
  final_snapshot_identifier = var.target_coepocmongo_final_snapshot_identifier
}

# TARGET INPUTS REQUIRED: dataiq-search
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Search/searchServices/dataiq-search
# Mapping assumption: OpenSearch is a proposed search destination; rebuild indexes and validate analyzer, query and vector-search compatibility.
resource "aws_opensearch_domain" "dataiq_search" {
  domain_name     = "dataiq-search"
  engine_version  = var.target_dataiq_search_engine_version
  access_policies = var.target_dataiq_search_access_policies_json
  cluster_config {
    instance_type  = var.target_dataiq_search_instance_type
    instance_count = var.target_dataiq_search_instance_count
  }
  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.target_dataiq_search_volume_size_gb
  }
  vpc_options {
    subnet_ids         = var.target_dataiq_search_subnet_ids
    security_group_ids = var.target_dataiq_search_security_group_ids
  }
  encrypt_at_rest { enabled = true }
  node_to_node_encryption { enabled = true }
  domain_endpoint_options { enforce_https = true }
}

# TARGET INPUTS REQUIRED: dataiq-server
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Sql/servers/dataiq-server
# Mapping assumption: RDS is a proposed database-engine mapping; migrate data separately and validate engine, licensing and availability requirements.
resource "aws_db_instance" "dataiq_server" {
  identifier                = "dataiq-server"
  engine                    = var.target_dataiq_server_sqlserver_engine
  engine_version            = var.target_dataiq_server_engine_version
  instance_class            = var.target_dataiq_server_instance_class
  allocated_storage         = var.target_dataiq_server_allocated_storage_gb
  username                  = var.target_dataiq_server_administrator_login
  password                  = var.target_dataiq_server_administrator_password
  db_subnet_group_name      = var.target_dataiq_server_db_subnet_group_name
  vpc_security_group_ids    = var.target_dataiq_server_security_group_ids
  publicly_accessible       = false
  skip_final_snapshot       = false
  final_snapshot_identifier = var.target_dataiq_server_final_snapshot_identifier
}

# TARGET INPUTS REQUIRED: azureblob
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/connections/azureblob
# Mapping assumption: Connector access policy only; attach it to the application role and implement the target integration.
resource "aws_iam_policy" "azureblob" {
  name   = "azureblob"
  policy = var.target_azureblob_connector_policy_json
}

# TARGET INPUTS REQUIRED: data-migration-agent
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/data-migration-agent
# Mapping assumption: App Runner container deployment requires a compatible image, access roles and application migration.
resource "aws_apprunner_service" "data_migration_agent_2" {
  service_name                   = "data-migration-agent-2"
  auto_scaling_configuration_arn = var.target_data_migration_agent_2_auto_scaling_configuration_arn
  source_configuration {
    auto_deployments_enabled = false
    authentication_configuration { access_role_arn = var.target_data_migration_agent_2_image_access_role_arn }
    image_repository {
      image_identifier      = var.target_data_migration_agent_2_image_identifier
      image_repository_type = "ECR"
      image_configuration { port = var.target_data_migration_agent_2_container_port }
    }
  }
  instance_configuration {
    cpu               = var.target_data_migration_agent_2_cpu
    memory            = var.target_data_migration_agent_2_memory
    instance_role_arn = var.target_data_migration_agent_2_instance_role_arn
  }
}

# TARGET INPUTS REQUIRED: sb-zuci-ai-poc
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sb-zuci-ai-poc
# Mapping assumption: App Runner container deployment requires a compatible image, access roles and application migration.
resource "aws_apprunner_service" "sb_zuci_ai_poc" {
  service_name                   = "sb-zuci-ai-poc"
  auto_scaling_configuration_arn = var.target_sb_zuci_ai_poc_auto_scaling_configuration_arn
  source_configuration {
    auto_deployments_enabled = false
    authentication_configuration { access_role_arn = var.target_sb_zuci_ai_poc_image_access_role_arn }
    image_repository {
      image_identifier      = var.target_sb_zuci_ai_poc_image_identifier
      image_repository_type = "ECR"
      image_configuration { port = var.target_sb_zuci_ai_poc_container_port }
    }
  }
  instance_configuration {
    cpu               = var.target_sb_zuci_ai_poc_cpu
    memory            = var.target_sb_zuci_ai_poc_memory
    instance_role_arn = var.target_sb_zuci_ai_poc_instance_role_arn
  }
}

# TARGET INPUTS REQUIRED: sqlbot
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sqlbot
# Mapping assumption: App Runner container deployment requires a compatible image, access roles and application migration.
resource "aws_apprunner_service" "sqlbot" {
  service_name                   = "sqlbot"
  auto_scaling_configuration_arn = var.target_sqlbot_auto_scaling_configuration_arn
  source_configuration {
    auto_deployments_enabled = false
    authentication_configuration { access_role_arn = var.target_sqlbot_image_access_role_arn }
    image_repository {
      image_identifier      = var.target_sqlbot_image_identifier
      image_repository_type = "ECR"
      image_configuration { port = var.target_sqlbot_container_port }
    }
  }
  instance_configuration {
    cpu               = var.target_sqlbot_cpu
    memory            = var.target_sqlbot_memory
    instance_role_arn = var.target_sqlbot_instance_role_arn
  }
}

# TARGET INPUTS REQUIRED: nkusml8541076082
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Insights/components/nkusml8541076082
# Mapping assumption: CloudWatch log destination only; application instrumentation and telemetry migration remain required.
resource "aws_cloudwatch_log_group" "nkusml8541076082" {
  name              = "/migration/nkusml8541076082"
  retention_in_days = var.target_nkusml8541076082_retention_days
}

# TARGET INPUTS REQUIRED: sb-zuci-ai-poc
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/microsoft.insights/components/sb-zuci-ai-poc
# Mapping assumption: CloudWatch log destination only; application instrumentation and telemetry migration remain required.
resource "aws_cloudwatch_log_group" "sb_zuci_ai_poc_2" {
  name              = "/migration/sb_zuci_ai_poc_2"
  retention_in_days = var.target_sb_zuci_ai_poc_2_retention_days
}

# TARGET INPUTS REQUIRED: ASP-InternalPOC-9da0
# Source ID: /subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/serverFarms/ASP-InternalPOC-9da0
# Mapping assumption: Proposed App Runner scaling configuration; associate its ARN with migrated application services.
resource "aws_apprunner_auto_scaling_configuration_version" "asp_internalpoc_9da0" {
  auto_scaling_configuration_name = "asp-internalpoc-9da0"
  max_concurrency                 = var.target_asp_internalpoc_9da0_max_concurrency
  min_size                        = var.target_asp_internalpoc_9da0_min_size
  max_size                        = var.target_asp_internalpoc_9da0_max_size
}




















































































































































variable "target_mlops_ami_id" {
  type = string
  sensitive = false
  description = "Required target configuration: mlops ami_id. Supply a validated value."
}

# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Cdn/profiles/data-migration-agent","target_addresses":["aws_cloudfront_distribution.data_migration_agent"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.CognitiveServices/accounts/centofexcelai","target_addresses":["aws_bedrock_inference_profile.centofexcelai"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.CognitiveServices/accounts/mlops-ai-api","target_addresses":["aws_bedrock_inference_profile.mlops_ai_api"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.CognitiveServices/accounts/Multicloud-AI","target_addresses":["aws_bedrock_inference_profile.multicloud_ai"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/INTERNAL-POC/providers/Microsoft.Compute/disks/DevTest_OsDisk_1_5827615136b14430a96272e649c97cb9","target_addresses":["aws_ebs_volume.devtest_osdisk_1_5827615136b14430a96272e649c97cb9"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Compute/disks/dwh-platform_DataDisk_0","target_addresses":["aws_ebs_volume.dwh_platform_datadisk_0"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/INTERNAL-POC/providers/Microsoft.Compute/disks/dwh-platform_OsDisk_1_56264da4f2c445dd8ed73482c9744f2c","target_addresses":["aws_ebs_volume.dwh_platform_osdisk_1_56264da4f2c445dd8ed73482c9744f2c"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/INTERNAL-POC/providers/Microsoft.Compute/disks/mlops_OsDisk_1_716c68c32b6a42898a98d5769187eaa6","target_addresses":["aws_ebs_volume.mlops_osdisk_1_716c68c32b6a42898a98d5769187eaa6"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/INTERNAL-POC/providers/Microsoft.Compute/disks/nacmachineA_OsDisk_1_d5dfeca78f194c008358d0a753ae185b","target_addresses":["aws_ebs_volume.nacmachinea_osdisk_1_d5dfeca78f194c008358d0a753ae185b"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/INTERNAL-POC/providers/Microsoft.Compute/disks/practice1_OsDisk_1_066fab3369ef40ff9a9695257fd1155f","target_addresses":["aws_ebs_volume.practice1_osdisk_1_066fab3369ef40ff9a9695257fd1155f"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Compute/virtualMachines/mlops","target_addresses":["aws_instance.mlops"],"required_variables":["target_mlops_ami_id"],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.ContainerRegistry/registries/acrsbzuciaipoc","target_addresses":["aws_ecr_repository.acrsbzuciaipoc"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.ContainerRegistry/registries/datamigrationagent","target_addresses":["aws_ecr_repository.datamigrationagent"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.ContainerRegistry/registries/sqlbot1","target_addresses":["aws_ecr_repository.sqlbot1"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.DataFactory/factories/datafactorydocintellpoc","target_addresses":["aws_glue_workflow.datafactorydocintellpoc"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.DBforPostgreSQL/flexibleServers/creditmlops21823","target_addresses":["aws_db_instance.creditmlops21823"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.DocumentDb/databaseAccounts/coepocmongo","target_addresses":["aws_docdb_cluster_instance.coepocmongo_instance","aws_docdb_cluster.coepocmongo"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE_1","target_addresses":["aws_sagemaker_domain.coe_1"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/NKusml","target_addresses":["aws_sagemaker_domain.nkusml"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/privateDnsZones/privatelink.mysql.database.azure.com","target_addresses":["aws_route53_zone.privatelink_mysql_database_azure_com"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/privateDnsZones/privatelink.redis.cache.windows.net","target_addresses":["aws_route53_zone.privatelink_redis_cache_windows_net"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/DevTest-ip","target_addresses":["aws_eip.devtest_ip"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/dwh-platform-ip","target_addresses":["aws_eip.dwh_platform_ip"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/mlops-ip","target_addresses":["aws_eip.mlops_ip"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/mlopsip616","target_addresses":["aws_eip.mlopsip616"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/mlopsip847","target_addresses":["aws_eip.mlopsip847"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/publicIPAddresses/nacmachineA-ip-cca5941d","target_addresses":["aws_eip.nacmachinea_ip_cca5941d"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.OperationalInsights/workspaces/law-sb-zuci-poc","target_addresses":["aws_cloudwatch_log_group.law_sb_zuci_poc"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Search/searchServices/dataiq-search","target_addresses":["aws_opensearch_domain.dataiq_search"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Sql/servers/dataiq-server","target_addresses":["aws_db_instance.dataiq_server"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/centerofexcell5982957371","target_addresses":["aws_s3_bucket.centerofexcell5982957371","aws_s3_bucket_public_access_block.centerofexcell5982957371"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/coe4360812019","target_addresses":["aws_s3_bucket.coe4360812019","aws_s3_bucket_public_access_block.coe4360812019"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/dataiqaihub4393665029","target_addresses":["aws_s3_bucket.dataiqaihub4393665029","aws_s3_bucket_public_access_block.dataiqaihub4393665029"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/docinteltestresult","target_addresses":["aws_s3_bucket.docinteltestresult","aws_s3_bucket_public_access_block.docinteltestresult"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/internalpoc9dc1","target_addresses":["aws_s3_bucket.internalpoc9dc1","aws_s3_bucket_public_access_block.internalpoc9dc1"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/macanpocstorageaccount","target_addresses":["aws_s3_bucket.macanpocstorageaccount","aws_s3_bucket_public_access_block.macanpocstorageaccount"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/mlopsdvcstore","target_addresses":["aws_s3_bucket.mlopsdvcstore","aws_s3_bucket_public_access_block.mlopsdvcstore"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/nkusml0423074054","target_addresses":["aws_s3_bucket.nkusml0423074054","aws_s3_bucket_public_access_block.nkusml0423074054"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/nkusml9639037362","target_addresses":["aws_s3_bucket.nkusml9639037362","aws_s3_bucket_public_access_block.nkusml9639037362"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/npaml7729019114","target_addresses":["aws_s3_bucket.npaml7729019114","aws_s3_bucket_public_access_block.npaml7729019114"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/stdataiq1515008267882418","target_addresses":["aws_s3_bucket.stdataiq1515008267882418","aws_s3_bucket_public_access_block.stdataiq1515008267882418"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Storage/storageAccounts/tfstorageaccountrasi","target_addresses":["aws_s3_bucket.tfstorageaccountrasi","aws_s3_bucket_public_access_block.tfstorageaccountrasi"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/connections/azureblob","target_addresses":["aws_iam_policy.azureblob"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/data-migration-agent","target_addresses":["aws_apprunner_service.data_migration_agent_2"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sb-zuci-ai-poc","target_addresses":["aws_apprunner_service.sb_zuci_ai_poc"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/sites/sqlbot","target_addresses":["aws_apprunner_service.sqlbot"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Insights/components/nkusml8541076082","target_addresses":["aws_cloudwatch_log_group.nkusml8541076082"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/microsoft.insights/components/sb-zuci-ai-poc","target_addresses":["aws_cloudwatch_log_group.sb_zuci_ai_poc_2"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.KeyVault/vaults/coe0795089701","target_addresses":["aws_secretsmanager_secret.coe0795089701"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.KeyVault/vaults/nkusml1649788538","target_addresses":["aws_secretsmanager_secret.nkusml1649788538"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.MachineLearningServices/workspaces/COE","target_addresses":["aws_sagemaker_domain.coe"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkInterfaces/mlops404_z1","target_addresses":["aws_network_interface.mlops404_z1"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Web/serverFarms/ASP-InternalPOC-9da0","target_addresses":["aws_apprunner_auto_scaling_configuration_version.asp_internalpoc_9da0"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/DefaultResourceGroup-EUS2/providers/Microsoft.OperationalInsights/workspaces/DefaultWorkspace-2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7-EUS2","target_addresses":["aws_cloudwatch_log_group.defaultworkspace_2e64ac5c_bc96_4389_a5bb_fc1c2e7bf8d7_eus2"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Network/networkSecurityGroups/mlopsnsg372","target_addresses":["aws_security_group.mlopsnsg372"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.OperationalInsights/workspaces/nkusml0872833282","target_addresses":["aws_cloudwatch_log_group.nkusml0872833282"],"required_variables":[],"mapping_note":""}
# RESOURCE COVERAGE: {"source_id":"/subscriptions/2e64ac5c-bc96-4389-a5bb-fc1c2e7bf8d7/resourceGroups/Internal-POC/providers/Microsoft.Sql/servers/dataiq-server/databases/master","target_addresses":["aws_db_instance.dataiq_server"],"required_variables":[],"mapping_note":"System master database is provided by its SQL Server instance; it is not recreated as an application database."}
