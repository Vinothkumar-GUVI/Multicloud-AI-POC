"""Terraform generation for Multi-Cloud AI.

Phase 6A/6B: Azure -> AWS configuration-preserving migration.
The generator uses live Azure configuration when available and only falls back
to billing metadata when a live value is genuinely unavailable.
"""

import re
import hashlib
from typing import Dict, Iterable, List, Tuple

from .migration_mapper import (
    aws_instance_type_for_azure,
    aws_region_for_azure,
    azure_resource_kind,
)


def tf_name(value):
    s = re.sub(r"[^A-Za-z0-9_]", "_", value or "resource").strip("_").lower()[:60] or "resource"
    return s if s[0].isalpha() else "r_" + s


def hyphen_safe(value, max_len=63):
    base = re.sub(r"[^a-z0-9-]", "-", (value or "").lower())
    base = re.sub(r"-+", "-", base).strip("-")
    return base[:max_len] or "resource"


def aws_security_group_name(value):
    name = hyphen_safe(value, 255)
    return ('migrated-' + name)[:255] if name.startswith('sg-') else name


def normalize_aws_security_group_names(text):
    """Fix reserved AWS group names without changing Terraform addresses/IDs."""
    def block(match):
        return re.sub(r'(?m)^(\s*name(?:_prefix)?\s*=\s*)"(sg-[^"\n]*)"',
                      lambda m: m[1] + hcl_string(aws_security_group_name(m[2])), match[0])
    return re.sub(r'^resource "aws_security_group" "[^"]+" \{.*?^\}', block, text, flags=re.M | re.S)


def hcl_string(value):
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def hcl_bool(value, default=False):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "true" if default else "false"
    return "true" if str(value).strip().lower() in {"true", "1", "yes", "enabled"} else "false"


def provider(cloud):
    cloud = str(cloud).strip().upper()
    if cloud not in {"AWS", "AZURE", "GCP"}:
        raise ValueError("Unsupported Terraform cloud: " + cloud)
    if cloud == "AWS":
        return '''terraform {
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
'''
    if cloud == "AZURE":
        return '''terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}
provider "azurerm" {
  features {}
}
'''
    return '''terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}
provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
'''


def _rid(resource):
    return str(resource.resource_id or "").rstrip("/").lower()


def _kind(resource):
    raw = str(getattr(resource, "raw_type", "") or "").strip().lower()
    if raw:
        return raw
    return azure_resource_kind(_rid(resource))


def _is_kind(resource, suffix):
    return _kind(resource).endswith(str(suffix or "").lower().lstrip("/"))


def _config(resource):
    return resource.configuration if isinstance(resource.configuration, dict) else {}


def _tags(resource):
    tags = _config(resource).get("tags")
    if isinstance(tags, dict):
        return tags
    if isinstance(resource.tags, dict):
        return resource.tags
    return {}


def _tag_lines(tags, indent="  "):
    if not tags:
        return []
    lines = [f"{indent}tags = {{"]
    for key, value in sorted(tags.items(), key=lambda x: str(x[0])):
        safe_key = str(key).replace('"', '\\"')
        lines.append(f"{indent}  {hcl_string(safe_key)} = {hcl_string(value)}")
    lines.append(f"{indent}}}")
    return lines


def _unique_resources(resources):
    result = {}
    for resource in resources:
        result[_rid(resource)] = resource
    return list(result.values())


def _resource_maps(resources):
    by_id = {_rid(r): r for r in resources}
    tf = {}
    used = {}
    for r in resources:
        base = tf_name(r.name or _rid(r).split("/")[-1])
        count = used.get(base, 0) + 1
        used[base] = count
        tf[_rid(r)] = base if count == 1 else f"{base}_{count}"
    return by_id, tf


def _azure_disk_type_to_aws(value):
    text = str(value or "").upper()
    if "ULTRA" in text:
        return "gp3"  # closest broadly deployable managed block-storage class
    if "PREMIUM" in text:
        return "gp3"
    if "STANDARDSSD" in text:
        return "gp3"
    return "st1" if "STANDARD" in text and "HDD" in text else "gp3"


def _azure_os_to_aws_ssm_path(os_type, image_sku=""):
    text = f"{os_type} {image_sku}".lower()
    if "windows" in text:
        return "/aws/service/ami-windows-latest/Windows_Server-2022-English-Full-Base"
    # Ubuntu is the safest automatic Linux default when the Azure image is not
    # a Marketplace image that AWS has an exact counterpart for.
    if "ubuntu" in text or not text.strip():
        return "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
    return "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp3/ami-id"


def _vpc_resources(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.network/virtualnetworks"):
            continue
        n = tf[_rid(r)]
        cfg = _config(r).get("network", {})
        cidrs = cfg.get("address_spaces") or []
        cidr = cidrs[0] if cidrs else "10.0.0.0/16"
        lines += [
            f'resource "aws_vpc" "{n}" {{',
            f'  cidr_block           = {hcl_string(cidr)}',
            '  enable_dns_support   = true',
            '  enable_dns_hostnames = true',
        ]
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','']
        handled.add(_rid(r))


def _subnet_parent_vpc(r, by_id, tf):
    cfg = _config(r).get("network", {})
    vnet_id = str(cfg.get("vnet_id") or "").rstrip("/").lower()
    if vnet_id and vnet_id in tf:
        return f'aws_vpc.{tf[vnet_id]}.id'
    # Derive parent VNet from the Azure resource ID.
    rid = _rid(r)
    marker = "/virtualnetworks/"
    if marker in rid:
        prefix = rid.split("/subnets/")[0]
        if prefix in tf:
            return f'aws_vpc.{tf[prefix]}.id'
    return None


def _subnet_resources(resources, by_id, tf, lines, handled, warnings):
    index = 0
    for r in resources:
        if not _is_kind(r, "/microsoft.network/virtualnetworks/subnets"):
            continue
        n = tf[_rid(r)]
        cfg = _config(r).get("network", {})
        cidrs = cfg.get("address_prefixes") or []
        cidr = cidrs[0] if cidrs else "10.0.1.0/24"
        vpc_ref = _subnet_parent_vpc(r, by_id, tf)
        if not vpc_ref:
            # A standalone subnet is not useful in AWS without a VPC. Create a
            # deterministic VPC only when the source VNet was not discovered.
            fallback = f"aws_vpc.generated_{index}.id"
            lines += [
                f'resource "aws_vpc" "generated_{index}" {{',
                '  cidr_block = "10.0.0.0/16"',
                '  enable_dns_support = true',
                '  enable_dns_hostnames = true',
                '}',
                '',
            ]
            vpc_ref = fallback
            warnings.append(f"{r.name}: source VNet was not discovered; generated a fallback 10.0.0.0/16 VPC.")
            index += 1
        lines += [
            f'resource "aws_subnet" "{n}" {{',
            f'  vpc_id     = {vpc_ref}',
            f'  cidr_block = {hcl_string(cidr)}',
            f'  availability_zone = "${{var.aws_region}}a"',
        ]
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','']
        handled.add(_rid(r))


def _security_groups(resources, by_id, tf, lines, handled, warnings):
    # Map each Azure NSG to the VPC containing a subnet/NIC that references it.
    for r in resources:
        if not _is_kind(r, "/microsoft.network/networksecuritygroups"):
            continue
        n = tf[_rid(r)]
        vpc_ref = None
        for candidate in resources:
            cfg = _config(candidate).get("network", {}) or {}
            nsg_id = str(cfg.get("network_security_group_id") or "").rstrip("/").lower()
            if nsg_id == _rid(r):
                vpc_ref = _subnet_parent_vpc(candidate, by_id, tf) if _is_kind(candidate, "/microsoft.network/virtualnetworks/subnets") else None
                if not vpc_ref and _is_kind(candidate, "/microsoft.network/networkinterfaces"):
                    ip = (cfg.get("ip_configurations") or [{}])[0]
                    sid = str(ip.get("subnet_id") or "").rstrip("/").lower()
                    if sid in tf:
                        parent = by_id.get(sid)
                        vpc_ref = _subnet_parent_vpc(parent, by_id, tf) if parent else None
                if vpc_ref:
                    break
        if not vpc_ref:
            vpcs = [x for x in resources if _is_kind(x, "/microsoft.network/virtualnetworks")]
            if vpcs:
                vpc_ref = f'aws_vpc.{tf[_rid(vpcs[0])]}.id'
            else:
                vpc_ref = 'data.aws_vpc.default.id'
                warnings.append(f"{r.name}: no source VNet was discovered; NSG is attached to the AWS default VPC.")
        lines += [
            f'resource "aws_security_group" "{n}" {{',
            f'  name        = {hcl_string(aws_security_group_name(r.name))}',
            '  description = "Migrated from Azure Network Security Group"',
            f'  vpc_id      = {vpc_ref}',
            '}',
            '',
        ]
        rules = (_config(r).get("network_security", {}) or {}).get("rules", [])
        for rule in rules:
            direction = str(rule.get("direction", "Inbound")).lower()
            access = str(rule.get("access", "Allow")).lower()
            if access != "allow" or direction != "inbound":
                continue
            direction=str(rule.get('direction') or '').lower()
            proto=str(rule.get('protocol') or '').lower()
            prefix = rule.get('source_address_prefix') if direction == 'inbound' else rule.get('destination_address_prefix')
            ports = rule.get('destination_port_range')
            # Never widen unsupported Azure selectors into permissive AWS rules.
            if (direction not in {'inbound', 'outbound'} or proto not in {'tcp', 'udp', '*', 'any', 'all'}
                or rule.get('source_port_range') != '*' or not ports or not prefix
                or any(rule.get(k) for k in ('source_port_ranges', 'destination_port_ranges',
                    'source_address_prefixes', 'destination_address_prefixes',
                    'source_application_security_groups', 'destination_application_security_groups'))):
                warnings.append(f'{r.name}: rule {rule.get("name", "rule")} requires manual firewall mapping; no permissive substitute emitted.')
                continue
            try:
                import ipaddress
                network = ipaddress.ip_network('0.0.0.0/0' if prefix == '*' else prefix, strict=False)
                if network.version != 4:
                    raise ValueError('IPv6 needs explicit mapping')
                cidr = str(network)
                proto = '-1' if proto in {'*', 'any', 'all'} else proto
                if proto == '-1':
                    if ports != '*':
                        raise ValueError('Protocol and port mismatch')
                    from_port = to_port = '0'
                elif ports == '*':
                    from_port, to_port = '0', '65535'
                else:
                    parts = str(ports).split('-')
                    low, high = int(parts[0]), int(parts[-1])
                    if len(parts) > 2 or not 0 <= low <= high <= 65535:
                        raise ValueError('Invalid ports')
                    from_port, to_port = str(low), str(high)
            except (ValueError, TypeError):
                warnings.append(f'{r.name}: rule {rule.get("name", "rule")} requires manual address/port mapping; no permissive substitute emitted.')
                continue
            rule_name = tf_name(rule.get("name", "rule"))
            lines += [
                f'resource "aws_vpc_security_group_ingress_rule" "{n}_{rule_name}" {{',
                f'  security_group_id = aws_security_group.{n}.id',
                f'  cidr_ipv4         = {hcl_string(cidr)}',
                f'  from_port         = {int(from_port) if str(from_port).isdigit() else 0}',
                f'  to_port           = {int(to_port) if str(to_port).isdigit() else 0}',
                f'  ip_protocol       = {hcl_string(proto)}',
                '}',
                '',
            ]
        handled.add(_rid(r))

def _public_ips(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.network/publicipaddresses"):
            continue
        n = tf[_rid(r)]
        cfg = _config(r).get("network", {})
        lines += [
            f'resource "aws_eip" "{n}" {{',
            '  domain = "vpc"',
        ]
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','']
        handled.add(_rid(r))


def _nics(resources, by_id, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.network/networkinterfaces"):
            continue
        n = tf[_rid(r)]
        cfg = _config(r).get("network", {})
        ip = (cfg.get("ip_configurations") or [{}])[0]
        subnet_id = str(ip.get("subnet_id") or "").rstrip("/").lower()
        subnet_ref = f'aws_subnet.{tf[subnet_id]}.id' if subnet_id in tf else None
        if not subnet_ref:
            warnings.append(f"{r.name}: source subnet was not discovered; NIC generation skipped.")
            continue
        lines += [
            f'resource "aws_network_interface" "{n}" {{',
            f'  subnet_id = {subnet_ref}',
        ]
        private_ip = ip.get("private_ip")
        if private_ip and str(ip.get("private_ip_allocation", "")).lower() == "static":
            lines.append(f'  private_ips = [{hcl_string(private_ip)}]')
        nsg_id = str(cfg.get("network_security_group_id") or "").rstrip("/").lower()
        if nsg_id in tf:
            lines.append(f'  security_groups = [aws_security_group.{tf[nsg_id]}.id]')
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','']
        public_ip_id = str(ip.get("public_ip_id") or "").rstrip("/").lower()
        if public_ip_id in tf:
            lines += [
                f'resource "aws_eip_association" "{n}" {{',
                f'  allocation_id = aws_eip.{tf[public_ip_id]}.id',
                f'  network_interface_id = aws_network_interface.{n}.id',
                '}',
                '',
            ]
        handled.add(_rid(r))


def _disk_resources(resources, by_id, tf, lines, handled, warnings):
    attachment_index = 0
    for r in resources:
        if not _is_kind(r, "/microsoft.compute/disks"):
            continue
        n = tf[_rid(r)]
        cfg = _config(r).get("storage", {})
        size = cfg.get("size_gb") or 1
        disk_type = _azure_disk_type_to_aws(cfg.get("storage_type"))
        managed_by = str(_config(r).get("raw_properties", {}).get("managedBy") or "").rstrip("/").lower()
        availability = '"${var.aws_region}a"'
        if managed_by and managed_by in tf:
            availability = f'aws_instance.{tf[managed_by]}.availability_zone'
        lines += [
            f'resource "aws_ebs_volume" "{n}" {{',
            f'  availability_zone = {availability}',
            f'  size              = {int(size)}',
            f'  type              = {hcl_string(disk_type)}',
        ]
        if cfg.get("disk_iops") and disk_type == "gp3":
            lines.append(f'  iops = {int(cfg["disk_iops"])}')
        if cfg.get("disk_mbps") and disk_type == "gp3":
            lines.append(f'  throughput = {int(cfg["disk_mbps"])}')
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','']
        if managed_by and managed_by in tf:
            vmn = tf[managed_by]
            device_letter = chr(ord("f") + (attachment_index % 20))
            attachment_index += 1
            lines += [
                f'resource "aws_volume_attachment" "attach_{n}" {{',
                f'  device_name = "/dev/sd{device_letter}"',
                f'  volume_id   = aws_ebs_volume.{n}.id',
                f'  instance_id = aws_instance.{vmn}.id',
                '}',
                '',
            ]
        else:
            warnings.append(f"{r.name}: Azure disk has no discovered VM attachment; EBS volume will be created unattached.")
        handled.add(_rid(r))


def _vm_resources(resources, by_id, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.compute/virtualmachines"):
            continue
        n = tf[_rid(r)]
        cfg = _config(r)
        compute = cfg.get("compute", {}) or {}
        vm_size = compute.get("vm_size") or r.sku
        instance_type, confidence = aws_instance_type_for_azure(vm_size)
        image_sku = compute.get("image_sku", "")
        os_type = compute.get("os_type", "Linux")
        ssm_path = _azure_os_to_aws_ssm_path(os_type, image_sku)
        ami_data = f"ami_{n}"
        if "windows" in f"{os_type} {image_sku}".lower():
            lines += [
                f'data "aws_ssm_parameter" "{ami_data}" {{',
                f'  name = {hcl_string(ssm_path)}',
                '}',
            ]
        else:
            lines += [
                f'data "aws_ssm_parameter" "{ami_data}" {{',
                f'  name = {hcl_string(ssm_path)}',
            ]
        lines += ['}','']
        root_size = compute.get("os_disk_size_gb")
        nic_ids = compute.get("network_interface_ids") or []
        nic_ref = None
        for nid in nic_ids:
            key = str(nid).rstrip("/").lower()
            if key in tf:
                nic_ref = f'aws_network_interface.{tf[key]}.id'
                break
        lines += [
            f'resource "aws_instance" "{n}" {{',
            f'  ami           = data.aws_ssm_parameter.{ami_data}.value',
            f'  instance_type = {hcl_string(instance_type)}',
        ]
        if nic_ref:
            lines += [
                '  network_interface {',
                f'    network_interface_id = {nic_ref}',
                '    device_index         = 0',
                '  }',
            ]
        else:
            # Use the first discovered subnet as a deterministic fallback.
            subnet_refs = [tf[_rid(x)] for x in resources if _is_kind(x, "/microsoft.network/virtualnetworks/subnets") and _rid(x) in tf]
            if subnet_refs:
                lines.append(f'  subnet_id = aws_subnet.{subnet_refs[0]}.id')
            else:
                warnings.append(f"{r.name}: no discovered subnet/NIC; instance may require target-network review.")
        if root_size:
            root_type = _azure_disk_type_to_aws((compute.get("os_disk_managed") or {}).get("storageAccountType"))
            lines += [
                '  root_block_device {',
                f'    volume_size = {int(root_size)}',
                f'    volume_type = {hcl_string(root_type)}',
                '    delete_on_termination = true',
                '  }',
            ]
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','']
        if confidence != "High":
            warnings.append(f"{r.name}: Azure VM size {vm_size!r} mapped to AWS {instance_type} with {confidence} confidence.")
        handled.add(_rid(r))


def _s3_resources(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.storage/storageaccounts") and r.canonical_type != "object_storage":
            continue
        n = tf[_rid(r)]
        suffix = hashlib.sha1(_rid(r).encode("utf-8")).hexdigest()[:8]
        bucket = hyphen_safe(f"{r.name}-{suffix}")
        cfg = _config(r).get("object_storage", {})
        lines += [
            f'resource "aws_s3_bucket" "{n}" {{',
            f'  bucket = {hcl_string(bucket)}',
        ]
        lines += _tag_lines(_tags(r))
        lines += ['  tags = merge(var.default_tags, {', f'    Name = {hcl_string(r.name)}', '  })', '}','',
                  f'resource "aws_s3_bucket_public_access_block" "{n}" {{',
                  f'  bucket = aws_s3_bucket.{n}.id',
                  '  block_public_acls       = true',
                  '  block_public_policy     = true',
                  '  ignore_public_acls      = true',
                  '  restrict_public_buckets = true',
                  '}',
                  '',
                  f'resource "aws_s3_bucket_versioning" "{n}" {{',
                  f'  bucket = aws_s3_bucket.{n}.id',
                  '  versioning_configuration { status = "Enabled" }',
                  '}',
                  '']
        handled.add(_rid(r))


def _ecr_resources(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.containerregistry/registries"):
            continue
        n = tf[_rid(r)]
        lines += [
            f'resource "aws_ecr_repository" "{n}" {{',
            f'  name                 = {hcl_string(hyphen_safe(r.name, 256))}',
            '  image_tag_mutability = "MUTABLE"',
            '  image_scanning_configuration { scan_on_push = true }',
            '}','']
        handled.add(_rid(r))


def _secrets(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.keyvault/vaults"):
            continue
        n = tf[_rid(r)]
        lines += [
            f'resource "aws_secretsmanager_secret" "{n}" {{',
            f'  name = {hcl_string(hyphen_safe(r.name, 512))}',
            '}','',
            f'# Azure Key Vault secret values were intentionally not copied because Azure Resource Graph does not expose secret material.',
            f'# Add secret values to AWS after deployment; the vault itself is provisioned automatically.',
            '']
        handled.add(_rid(r))
        warnings.append(f"{r.name}: Key Vault metadata is migrated, but secret values cannot be exported/read by Resource Graph and are not copied.")


def _route53(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.network/privatednszones"):
            continue
        n = tf[_rid(r)]
        zone = r.name
        lines += [
            f'resource "aws_route53_zone" "{n}" {{',
            f'  name = {hcl_string(zone)}',
            '}',
            '',
        ]
        handled.add(_rid(r))


def _postgres(resources, tf, lines, handled, warnings):
    for r in resources:
        if not _is_kind(r, "/microsoft.dbforpostgresql/flexibleservers"):
            continue
        n = tf[_rid(r)]
        db = _config(r).get("database", {}) or {}
        version = str(db.get("version") or "15")
        # RDS version availability varies by region. Keep major version when possible.
        version_match = re.match(r"(\d+)(?:\.\d+)?", version)
        engine_version = version_match.group(1) if version_match else "15"
        storage = int(db.get("storage_gb") or 32)
        source_class, class_confidence = aws_instance_type_for_azure(db.get("sku_name") or "")
        db_class = f"db.{source_class}" if source_class else "db.m5.large"
        if source_class.startswith("t3."):
            db_class = f"db.{source_class}"
        elif not db_class.startswith("db."):
            db_class = "db.m5.large"
        multi_az = str(db.get("high_availability") or "").lower() in {"zone_redundant", "zonal", "enabled"}
        lines += [
            f'resource "random_password" "{n}" {{',
            '  length  = 24',
            '  special = true',
            '}',
            '',
            f'resource "aws_db_instance" "{n}" {{',
            '  identifier = ' + hcl_string(hyphen_safe(r.name, 63)),
            '  engine = "postgres"',
            f'  engine_version = {hcl_string(engine_version)}',
            f'  instance_class = {hcl_string(db_class)}',
            f'  allocated_storage = {storage}',
            '  storage_type = "gp3"',
            '  username = "migration_admin"',
            f'  password = random_password.{n}.result',
            f'  multi_az = {str(multi_az).lower()}',
            '  publicly_accessible = false',
            '  skip_final_snapshot = true',
            '  deletion_protection = false',
            '}',
            '',
        ]
        if class_confidence != "High":
            warnings.append(f"{r.name}: Azure PostgreSQL SKU {db.get('sku_name')!r} mapped to AWS {db_class} with {class_confidence} confidence.")
        warnings.append(f"{r.name}: PostgreSQL server configuration is mapped, but Azure-to-AWS data migration is not performed by Terraform.")
        handled.add(_rid(r))


def _unsupported(resources, handled, lines, warnings):
    for r in resources:
        key = _rid(r)
        if key in handled:
            continue
        lines += [
            f'# UNSUPPORTED AUTOMATIC CONVERSION: {r.name}',
            f'# Azure resource type: {r.raw_type or r.canonical_type}',
            f'# Source ID: {r.resource_id}',
            '# The source configuration was discovered, but no safe 1:1 AWS Terraform mapping is implemented in Phase 6B.',
            '# No fake/default AWS resource was generated.',
            '',
        ]
        warnings.append(f"{r.name}: {r.raw_type or r.canonical_type} has no safe automatic AWS mapping in Phase 6B; Terraform intentionally does not invent one.")


def _aws_generate(resources, edges):
    resources = _unique_resources(resources)
    by_id, tf = _resource_maps(resources)
    source_region = next((r.region for r in resources if r.region and r.region != "unknown"), "eastus")
    aws_region = aws_region_for_azure(source_region)
    lines: List[str] = [
        provider("AWS"),
        '# ============================================================',
        '# Multi-Cloud AI — Phase 6B Azure -> AWS',
        '# Configuration-preserving Terraform generated from live Azure discovery.',
        '# Billing provides cost; Azure Resource Graph provides source configuration.',
        '# ============================================================',
        '',
        'variable "aws_region" {',
        f'  type    = string',
        f'  default = {hcl_string(aws_region)}',
        '  description = "AWS region mapped from the discovered Azure region. Override only if your target placement requires another AWS region."',
        '}',
        '',
        'variable "default_tags" {',
        '  type    = map(string)',
        '  default = {}',
        '}',
        '',
        'data "aws_availability_zones" "available" { state = "available" }',
        'data "aws_vpc" "default" { default = true }',
        '',
    ]
    handled = set()
    warnings: List[str] = []

    _vpc_resources(resources, tf, lines, handled, warnings)
    _subnet_resources(resources, by_id, tf, lines, handled, warnings)
    _security_groups(resources, by_id, tf, lines, handled, warnings)
    _public_ips(resources, tf, lines, handled, warnings)
    _nics(resources, by_id, tf, lines, handled, warnings)
    _disk_resources(resources, by_id, tf, lines, handled, warnings)
    _vm_resources(resources, by_id, tf, lines, handled, warnings)
    _s3_resources(resources, tf, lines, handled, warnings)
    _ecr_resources(resources, tf, lines, handled, warnings)
    _secrets(resources, tf, lines, handled, warnings)
    _route53(resources, tf, lines, handled, warnings)
    _postgres(resources, tf, lines, handled, warnings)
    _unsupported(resources, handled, lines, warnings)

    lines += ['# ============================================================', '# Discovered dependency relationships', '# ============================================================']
    if edges:
        for e in edges:
            lines.append(f'# {e.source_id} -> {e.target_id} | {e.relationship} | {e.confidence} | {e.evidence}')
    else:
        lines.append('# No explicit dependency relationships were discovered.')

    lines += ['', '# ============================================================', '# Migration notes', '# ============================================================']
    if warnings:
        for item in warnings:
            lines.append(f'# - {item}')
    else:
        lines.append('# No migration warnings were generated.')
    lines += [
        '#',
        '# Important: Terraform creates infrastructure. It does not copy application/data contents',
        '# from Azure to AWS. Data replication, image conversion, DNS cutover, and application',
        '# validation remain separate migration activities where applicable.',
        '',
    ]
    return "\n".join(lines)


def _legacy_generate(resources, edges, target):
    """Keep existing behavior for non-Azure->AWS paths until their phases are implemented."""
    lines = [
        provider(target),
        '# Generated from normalized billing + live-cloud discovery.',
        '# Phase 6 configuration-preserving generation is currently implemented for Azure -> AWS.',
        '',
    ]
    for r in resources:
        n = tf_name(r.name)
        c = r.canonical_type
        lines += [f'# Source: {r.cloud} | {r.resource_id}', f'# Configuration source: {r.configuration_source} | confidence: {r.configuration_confidence}']
        if c == "compute_instance":
            if target == "AWS":
                lines += [f'resource "aws_instance" "{n}" {{', '  # Azure -> AWS path should use the Phase 6 generator.', '}', '']
            elif target == "Azure":
                lines += [f'resource "azurerm_linux_virtual_machine" "{n}" {{', f'  name = {hcl_string(r.name)}', '}', '']
            else:
                lines += [f'resource "google_compute_instance" "{n}" {{', f'  name = {hcl_string(r.name)}', '}', '']
        elif c == "block_storage":
            lines += [f'# Block storage: {r.name} — target-specific implementation pending.', '']
        elif c == "object_storage":
            lines += [f'# Object storage: {r.name} — target-specific implementation pending.', '']
        else:
            lines += [f'# {c}: {r.name} — target-specific implementation pending.', '']
    lines += ['# Dependencies discovered from explicit live-cloud references:']
    for e in edges:
        lines.append(f'# {e.source_id} -> {e.target_id} | {e.relationship} | {e.evidence}')
    return "\n".join(lines)


def generate(resources, edges, target):
    if target == "AWS" and any(getattr(r, "cloud", "") == "Azure" for r in resources):
        return _aws_generate(resources, edges)
    return _legacy_generate(resources, edges, target)


# ============================================================
# All-cloud Terraform generation
# ============================================================

def _generic_source_value(r, *keys, default=""):
    cfg = _config(r)
    for key in keys:
        value = cfg.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _generic_machine_type(r, target):
    c = _config(r).get("compute", {}) or {}
    src = str(getattr(r, "cloud", "")).upper()
    if src == "AWS":
        value = c.get("instance_type") or getattr(r, "sku", "") or "t3.micro"
        if target == "GCP": return "e2-medium"
        if target == "Azure": return "Standard_B2s"
        return value
    if src == "GCP":
        value = c.get("machine_type") or getattr(r, "sku", "") or "e2-medium"
        if target == "AWS": return "t3.medium"
        if target == "Azure": return "Standard_B2s"
        return value
    value = c.get("vm_size") or getattr(r, "sku", "") or "Standard_B2s"
    if target == "AWS": return aws_instance_type_for_azure(value)[0]
    if target == "GCP": return "e2-medium"
    return value


def _generic_region(r, target):
    region = str(getattr(r, "region", "") or "")
    src = str(getattr(r, "cloud", "") or "").upper()
    if target == "AWS" and src == "AZURE": return aws_region_for_azure(region)
    if target == "GCP":
        # Azure/AWS region names are not interchangeable with GCP locations.
        return "us-east1" if region.lower() in {"eastus", "us-east-1", "us-east-2"} else (region or "us-central1")
    if target == "Azure":
        return "East US" if region.lower() in {"us-east-1", "us-east1", "eastus"} else (region or "East US")
    return region or "us-east-1"


def _generic_cidr(r, subnet=False):
    n = _config(r).get("network", {}) or {}
    vals = n.get("address_prefixes") or n.get("address_spaces") or n.get("cidrs") or n.get("ip_cidr_range")
    if isinstance(vals, list) and vals: return vals[0]
    if isinstance(vals, str) and vals: return vals
    return "10.0.1.0/24" if subnet else "10.0.0.0/16"


def _generic_disk_size(r):
    st = _config(r).get("storage", {}) or {}
    c = _config(r).get("compute", {}) or {}
    return int(st.get("size_gb") or st.get("disk_size_gb") or c.get("os_disk_size_gb") or c.get("boot_disk_size_gb") or 30)


def _generic_tags(r):
    return _tags(r)


def _generate_generic(resources, edges, target):
    resources = _unique_resources(resources)
    by_id, tf = _resource_maps(resources)
    target = str(target).upper()
    source = str(getattr(resources[0], "cloud", "") if resources else "").upper()
    region = _generic_region(next((r for r in resources if getattr(r, "region", "")), resources[0] if resources else None), target) if resources else ("us-east-1" if target == "AWS" else "us-central1")
    lines = [provider(target), f'# Multi-Cloud AI — {source} -> {target}', '# Generated from live discovery when available. Values are mapped from discovered configuration.', '']
    if target == "AWS":
        lines += ['variable "aws_region" {', '  type = string', f'  default = {hcl_string(region)}', '}', 'variable "default_tags" {\n  type = map(string)\n  default = {}\n}', 'data "aws_availability_zones" "available" { state = "available" }', '']
    elif target == "GCP":
        project = next((str(getattr(r, "group", "") or "") for r in resources if getattr(r, "group", "") and getattr(r, "group", "") != "default"), "")
        lines += ['variable "gcp_project_id" { type = string }', 'variable "gcp_region" {', '  type = string', f'  default = {hcl_string(region)}', '}', '']
    elif target == "Azure":
        lines += ['variable "azure_location" {\n  type = string', f'  default = {hcl_string(region)}', '}', 'variable "azure_resource_group" {\n  type = string\n  default = "migrated-resources"\n}', '']
    handled=set(); warnings=[]

    for r in resources:
        n=tf[_rid(r)]; c=str(getattr(r,"canonical_type","") or "").lower(); raw=str(getattr(r,"raw_type","") or "").lower(); tags=_generic_tags(r)
        if c == "compute_instance":
            size=_generic_machine_type(r,target); disk=_generic_disk_size(r)
            if target=="AWS":
                lines += [f'resource "aws_instance" "{n}" {{', f'  ami = data.aws_ssm_parameter.ubuntu.value', f'  instance_type = {hcl_string(size)}', f'  root_block_device {{ volume_size = {disk} volume_type = "gp3" }}', '  tags = merge(var.default_tags, {', f'    Name = {hcl_string(getattr(r,"name","instance"))}', '  })', '}','']
            elif target=="GCP":
                lines += [f'resource "google_compute_instance" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","instance"))}', '  machine_type = ' + hcl_string(size), '  zone = ' + hcl_string(region + '-a'), '  boot_disk {', '    initialize_params {', f'      size = {disk}', '      image = "ubuntu-os-cloud/ubuntu-2204-lts"', '    }', '  }', '  network_interface {', '    network = google_compute_network.migrated.id', '  }', '}','']
            else:
                os_type=str((_config(r).get("compute",{}) or {}).get("os_type") or "Linux").lower()
                vmres="azurerm_windows_virtual_machine" if "windows" in os_type else "azurerm_linux_virtual_machine"
                lines += [f'resource "{vmres}" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","vm"))}', '  resource_group_name = var.azure_resource_group', '  location = var.azure_location', f'  size = {hcl_string(size)}', '  admin_username = "migration_admin"', '  disable_password_authentication = false' if "windows" not in os_type else '  admin_password = var.azure_admin_password', f'  os_disk {{ caching = "ReadWrite" storage_account_type = "Premium_LRS" disk_size_gb = {disk} }}', '  source_image_reference { publisher = "Canonical" offer = "0001-com-ubuntu-server-jammy" sku = "22_04-lts-gen2" version = "latest" }' if "windows" not in os_type else '  source_image_reference { publisher = "MicrosoftWindowsServer" offer = "WindowsServer" sku = "2022-datacenter-azure-edition" version = "latest" }', '}','']
            handled.add(_rid(r))
        elif c == "block_storage":
            size=_generic_disk_size(r)
            if target=="AWS": lines += [f'resource "aws_ebs_volume" "{n}" {{', f'  availability_zone = "${{var.aws_region}}a"', f'  size = {size}', '  type = "gp3"', '}','']
            elif target=="GCP": lines += [f'resource "google_compute_disk" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","disk"))}', f'  size = {size}', '  type = "pd-balanced"', '  zone = ' + hcl_string(region+'-a'), '}','']
            else: lines += [f'resource "azurerm_managed_disk" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","disk"))}', '  location = var.azure_location', '  resource_group_name = var.azure_resource_group', f'  storage_account_type = "Premium_LRS"', f'  disk_size_gb = {size}', '  create_option = "Empty"', '}','']
            handled.add(_rid(r))
        elif c == "object_storage":
            if target=="AWS":
                lines += [f'resource "aws_s3_bucket" "{n}" {{', f'  bucket = {hcl_string(hyphen_safe(getattr(r,"name","bucket")))}', '}', '', f'resource "aws_s3_bucket_public_access_block" "{n}" {{', f'  bucket = aws_s3_bucket.{n}.id', '  block_public_acls = true', '  block_public_policy = true', '  ignore_public_acls = true', '  restrict_public_buckets = true', '}','']
            elif target=="GCP": lines += [f'resource "google_storage_bucket" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","bucket")))}', '  location = ' + hcl_string(region.upper()), '  uniform_bucket_level_access = true', '}','']
            else: lines += [f'resource "azurerm_storage_account" "{n}" {{', f'  name = {hcl_string(re.sub("[^a-z0-9]", "", getattr(r,"name","storage").lower())[:24] or "migratedstorage")}', '  resource_group_name = var.azure_resource_group', '  location = var.azure_location', '  account_tier = "Standard"', '  account_replication_type = "LRS"', '  https_traffic_only_enabled = true', '}','']
            handled.add(_rid(r))
        elif c == "container_registry":
            if target=="AWS": lines += [f'resource "aws_ecr_repository" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","repository")))}', '  image_scanning_configuration { scan_on_push = true }', '}','']
            elif target=="GCP": lines += [f'resource "google_artifact_registry_repository" "{n}" {{', f'  repository_id = {hcl_string(hyphen_safe(getattr(r,"name","repository")))}', '  format = "DOCKER"', '  location = ' + hcl_string(region), '}','']
            else: lines += [f'resource "azurerm_container_registry" "{n}" {{', f'  name = {hcl_string(re.sub("[^a-zA-Z0-9]", "", getattr(r,"name","registry"))[:50] or "migratedregistry")}', '  resource_group_name = var.azure_resource_group', '  location = var.azure_location', '  sku = "Standard"', '  admin_enabled = false', '}','']
            handled.add(_rid(r))
        elif c in {"relational_database","postgresql"}:
            d=_config(r).get("database",{}) or {}; version=str(d.get("version") or d.get("engine_version") or "15"); storage=int(d.get("storage_gb") or d.get("allocated_storage") or 32)
            if target=="AWS": lines += [f'resource "random_password" "{n}" {{ length = 24 special = true }}','',f'resource "aws_db_instance" "{n}" {{', f'  identifier = {hcl_string(hyphen_safe(getattr(r,"name","postgres"),63))}', '  engine = "postgres"', f'  engine_version = {hcl_string(re.match(r"\\d+(?:\\.\\d+)?",version).group(0) if re.match(r"\\d+(?:\\.\\d+)?",version) else "15")}', '  instance_class = "db.t3.medium"', f'  allocated_storage = {storage}', '  storage_type = "gp3"', '  username = "migration_admin"', f'  password = random_password.{n}.result', '  publicly_accessible = false', '  skip_final_snapshot = true', '}','']
            elif target=="GCP": lines += [f'resource "google_sql_database_instance" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","postgres")))}', '  database_version = "POSTGRES_15"', '  region = var.gcp_region', '  settings { tier = "db-custom-2-7680" disk_type = "PD_SSD" disk_size = ' + str(storage) + ' availability_type = "ZONAL" }', '}','']
            else: lines += [f'resource "azurerm_postgresql_flexible_server" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","postgres")))}', '  resource_group_name = var.azure_resource_group', '  location = var.azure_location', '  version = ' + hcl_string(re.match(r"\\d+",version).group(0) if re.match(r"\\d+",version) else "15"), '  administrator_login = "migration_admin"', '  administrator_password = var.azure_admin_password', '  storage_mb = ' + str(storage*1024), '  sku_name = "GP_Standard_D2s_v5"', '}','']
            handled.add(_rid(r)); warnings.append(f"{getattr(r,'name','database')}: database data is not copied by Terraform; perform data replication separately.")
        elif c == "virtual_network":
            if "subnet" in raw: continue
            cidr=_generic_cidr(r)
            if target=="AWS": lines += [f'resource "aws_vpc" "{n}" {{', f'  cidr_block = {hcl_string(cidr)}', '  enable_dns_support = true', '  enable_dns_hostnames = true', '}','']
            elif target=="GCP": lines += [f'resource "google_compute_network" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","network")))}', '  auto_create_subnetworks = false', '}','']
            else: lines += [f'resource "azurerm_virtual_network" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","vnet"))}', '  location = var.azure_location', '  resource_group_name = var.azure_resource_group', f'  address_space = [{hcl_string(cidr)}]', '}','']
            handled.add(_rid(r))
        elif c == "public_ip":
            if target=="AWS": lines += [f'resource "aws_eip" "{n}" {{ domain = "vpc" }}','']
            elif target=="GCP": lines += [f'resource "google_compute_address" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","address")))}', '  region = var.gcp_region', '}','']
            else: lines += [f'resource "azurerm_public_ip" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","public-ip"))}', '  location = var.azure_location', '  resource_group_name = var.azure_resource_group', '  allocation_method = "Static"', '}','']
            handled.add(_rid(r))
        elif c == "security_group":
            if target=="AWS": lines += [f'resource "aws_security_group" "{n}" {{', f'  name = {hcl_string(aws_security_group_name(getattr(r,"name","security-group")))}', '  description = "Migrated security group"', '}','']
            elif target=="GCP": lines += [f'resource "google_compute_firewall" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","firewall")))}', '  network = google_compute_network.migrated.id', '  allow {', '    protocol = "tcp"', '    ports = ["0-65535"]', '  }', '  source_ranges = ["0.0.0.0/0"]', '}','']
            else: lines += [f'resource "azurerm_network_security_group" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","nsg"))}', '  location = var.azure_location', '  resource_group_name = var.azure_resource_group', '}','']
            warnings.append(f"{getattr(r,'name','security-group')}: security rules should be reviewed against target-cloud semantics before apply.")
            handled.add(_rid(r))
        elif c == "dns":
            if target=="AWS": lines += [f'resource "aws_route53_zone" "{n}" {{ name = {hcl_string(getattr(r,"name","zone"))} }}','']
            elif target=="GCP": lines += [f'resource "google_dns_managed_zone" "{n}" {{', f'  name = {hcl_string(tf_name(getattr(r,"name","zone")))}', f'  dns_name = {hcl_string(getattr(r,"name","example.com"))}', '  visibility = "public"', '}','']
            else: lines += [f'resource "azurerm_private_dns_zone" "{n}" {{', f'  name = {hcl_string(getattr(r,"name","zone"))}', '  resource_group_name = var.azure_resource_group', '}','']
            handled.add(_rid(r))
        elif c == "secrets_manager":
            if target=="AWS": lines += [f'resource "aws_secretsmanager_secret" "{n}" {{ name = {hcl_string(hyphen_safe(getattr(r,"name","secret")))} }}','']
            elif target=="GCP": lines += [f'resource "google_secret_manager_secret" "{n}" {{', f'  secret_id = {hcl_string(hyphen_safe(getattr(r,"name","secret")))}', '  replication {', '    auto {}', '  }', '}','']
            else: lines += [f'resource "azurerm_key_vault" "{n}" {{', f'  name = {hcl_string(hyphen_safe(getattr(r,"name","vault")))}', '  location = var.azure_location', '  resource_group_name = var.azure_resource_group', '  tenant_id = var.azure_tenant_id', '  sku_name = "standard"', '  purge_protection_enabled = false', '}','']
            warnings.append(f"{getattr(r,'name','secret')}: secret values are not copied automatically.")
            handled.add(_rid(r))
        else:
            lines += [f'# REVIEW REQUIRED: {getattr(r,"name","resource")}', f'# Source type: {getattr(r,"raw_type","") or c}', f'# Source ID: {getattr(r,"resource_id","")}', '# No safe provider-specific Terraform was generated for this resource type.', '']
            warnings.append(f"{getattr(r,'name','resource')}: provider-specific mapping requires manual review.")

    lines += ['# ============================================================', '# Migration warnings / review items', '# ============================================================']
    for w in warnings: lines.append('# - ' + w)
    if not warnings: lines.append('# No warnings generated.')
    lines += ['', '# Terraform provisions infrastructure; it does not migrate application/data contents.', '']
    return "\n".join(lines)


def generate(resources, edges, target):
    target = str(target or "").upper()
    resources = list(resources or [])
    if target == "AWS" and any(str(getattr(r, "cloud", "")).upper() == "AZURE" for r in resources):
        return _aws_generate(resources, edges)
    return _generate_generic(resources, edges, target)

# ============================================================
# Final all-cloud Terraform generator
# ============================================================

def _gcp_disk_type(value):
    t=str(value or '').upper()
    if 'PREMIUM' in t or t in {'SSD','PD-SSD'}: return 'pd-ssd'
    if 'STANDARDSSD' in t or 'BALANCED' in t: return 'pd-balanced'
    return 'pd-standard'


def _gcp_machine(source, r):
    c=_config(r).get('compute',{}) or {}
    src=str(getattr(r,'cloud','')).upper()
    if src=='GCP': return c.get('machine_type') or 'e2-standard-2'
    if src=='Azure':
        v=str(c.get('vm_size') or getattr(r,'sku','') or '').lower().replace('_','-')
        table={'standard-b2ms':'e2-standard-2','standard-b2s':'e2-standard-2','standard-d2s-v5':'n2-standard-2','standard-d4s-v5':'n2-standard-4','standard-d8s-v5':'n2-standard-8','standard-nv8as-v4':'g2-standard-8'}
        return table.get(v,'e2-standard-2')
    v=str(c.get('instance_type') or getattr(r,'sku','') or '').lower()
    table={'t3.micro':'e2-small','t3.small':'e2-medium','t3.medium':'e2-standard-2','t3.large':'e2-standard-2','m5.large':'n2-standard-2','m5.xlarge':'n2-standard-4','m5.2xlarge':'n2-standard-8','c5.large':'c2-standard-2'}
    return table.get(v,'e2-standard-2')


def _aws_machine(source, r):
    approved = _config(r).get("approved_aws_compute", {})
    if approved.get("instance_type"):
        return approved["instance_type"]
    from .pricing import _target_sku
    mapping = _target_sku(r, "AWS")
    value = mapping.get("target_instance_type")
    if mapping.get("pricing_mapping_error") or not value:
        raise ValueError(f"{r.name}: select a validated target compute configuration before generating Terraform.")
    return value


def _target_region_generic(r,target):
    from .migration_mapper import _target_region
    return _target_region(getattr(r,'cloud',''),getattr(r,'region',''),target)


def _source_image_for_gcp(r):
    c=_config(r).get('compute',{}) or {}
    pub=str(c.get('image_publisher') or '').lower(); offer=str(c.get('image_offer') or '').lower(); sku=str(c.get('image_sku') or '').lower(); os_type=str(c.get('os_type') or '').lower()
    if 'redhat' in pub or 'rhel' in offer or 'rhel' in sku or 'rhel' in os_type: return 'rhel-cloud/rhel-9'
    if 'windows' in os_type or 'microsoft' in pub: return 'windows-cloud/windows-server-2022'
    return 'ubuntu-os-cloud/ubuntu-2204-lts'


def _gcp_storage_class(r):
    o=_config(r).get('object_storage',{}) or {}; access=str(o.get('access_tier') or '').lower()
    return 'NEARLINE' if access=='cool' else 'COLDLINE' if access=='archive' else 'STANDARD'


def _gcp_sql_version(r):
    d=_config(r).get('database',{}) or {}; v=str(d.get('version') or d.get('engine_version') or '15')
    m=re.search(r'(\d+)',v); major=m.group(1) if m else '15'
    engine=str(d.get('engine') or 'postgresql').lower()
    return ('MYSQL_' if 'mysql' in engine else 'SQLSERVER_' if 'sqlserver' in engine or 'sql-server' in engine else 'POSTGRES_') + major


def _emit_review(lines, r, target, reason, warnings):
    lines += [f'# REVIEW REQUIRED: {getattr(r,"name","resource")}', f'# Source type: {getattr(r,"raw_type","") or getattr(r,"canonical_type","")}', f'# Source ID: {getattr(r,"resource_id","")}', f'# Target: {target}', f'# Reason: {reason}', '']
    warnings.append(f'{getattr(r,"name","resource")}: {reason}')


def _generate_generic_final(resources, edges, target):
    resources=_unique_resources(resources); target=str(target or '').upper(); source=str(getattr(resources[0],'cloud','') if resources else '').upper()
    if not resources:
        return provider(target) + '# No resources were available for Terraform generation.\n'
    by_id,tf=_resource_maps(resources)
    region=_target_region_generic(next((r for r in resources if getattr(r,'region','')),resources[0]),target)
    lines=[provider(target), f'# Multi-Cloud AI — {source} -> {target}', '# Generated from live resource discovery. Source configuration is used when exposed by the provider API.', '# Target-cloud defaults are used only where the source API does not expose an equivalent setting.', '']
    if target=='AWS':
        lines += ['variable "aws_region" {', '  type = string', f'  default = {hcl_string(region or "us-east-1")}', '}', 'variable "default_tags" {\n  type = map(string)\n  default = {}\n}', '']
    elif target=='GCP':
        project=next((str(getattr(r,'group','') or '') for r in resources if getattr(r,'group','') and getattr(r,'group','')!='default'),'')
        lines += ['variable "gcp_project_id" { type = string }', 'variable "gcp_region" {', '  type = string', f'  default = {hcl_string(region or "us-central1")}', '}', '']
    else:
        lines += ['variable "azure_location" {\n  type = string', f'  default = {hcl_string(region or "East US")}', '}', 'variable "azure_resource_group" {\n  type = string\n  default = "migrated-resources"\n}', 'variable "azure_admin_password" {\n  type = string\n  sensitive = true\n  default = null\n}', '']
    handled=set(); warnings=[]

    # Networks first so compute/NIC resources can reference them.
    network_refs=[]
    for r in resources:
        kind=str(getattr(r,'canonical_type','') or '').lower(); raw=str(getattr(r,'raw_type','') or '').lower(); n=tf[_rid(r)]
        if kind!='virtual_network' or 'subnet' in raw: continue
        cfg=_config(r).get('network',{}) or {}; cidr=(cfg.get('address_spaces') or cfg.get('address_prefixes') or cfg.get('cidr') or ['10.0.0.0/16']); cidr=cidr[0] if isinstance(cidr,list) else cidr
        if target=='AWS': lines += [f'resource "aws_vpc" "{n}" {{',f'  cidr_block = {hcl_string(cidr)}','  enable_dns_support = true','  enable_dns_hostnames = true','  tags = merge(var.default_tags, {',f'    Name = {hcl_string(r.name)}','  })','}','']; network_refs.append(('AWS',n)); handled.add(_rid(r))
        elif target=='GCP': lines += [f'resource "google_compute_network" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}','  auto_create_subnetworks = false','}','']; network_refs.append(('GCP',n)); handled.add(_rid(r))
        else: lines += [f'resource "azurerm_virtual_network" "{n}" {{',f'  name = {hcl_string(r.name)}','  location = var.azure_location','  resource_group_name = var.azure_resource_group',f'  address_space = [{hcl_string(cidr)}]','}','']; network_refs.append(('Azure',n)); handled.add(_rid(r))
    if target=='GCP' and not network_refs:
        lines += ['resource "google_compute_network" "migrated" {','  name = "migrated-network"','  auto_create_subnetworks = false','}','']; network_refs=[('GCP','migrated')]
    if target=='AWS' and not network_refs:
        lines += ['resource "aws_vpc" "migrated" {','  cidr_block = "10.0.0.0/16"','  enable_dns_support = true','  enable_dns_hostnames = true','}','']; network_refs=[('AWS','migrated')]

    for r in resources:
        rid=_rid(r)
        if rid in handled: continue
        n=tf[rid]; kind=str(getattr(r,'canonical_type','') or '').lower(); raw=str(getattr(r,'raw_type','') or '').lower(); cfg=_config(r)
        try:
            if kind=='subnet':
                net=cfg.get('network',{}) or {}; cidr=net.get('address_prefix') or (net.get('address_prefixes') or ['10.0.1.0/24']); cidr=cidr[0] if isinstance(cidr,list) else cidr
                if target=='AWS':
                    vpc=network_refs[0][1]; lines += [f'resource "aws_subnet" "{n}" {{',f'  vpc_id = aws_vpc.{vpc}.id',f'  cidr_block = {hcl_string(cidr)}',f'  availability_zone = "${{var.aws_region}}a"','}','']
                elif target=='GCP': lines += [f'resource "google_compute_subnetwork" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  ip_cidr_range = {hcl_string(cidr)}',f'  region = var.gcp_region',f'  network = google_compute_network.{network_refs[0][1]}.id','}','']
                else: lines += [f'resource "azurerm_subnet" "{n}" {{',f'  name = {hcl_string(r.name)}',f'  resource_group_name = var.azure_resource_group',f'  virtual_network_name = azurerm_virtual_network.{network_refs[0][1]}.name',f'  address_prefixes = [{hcl_string(cidr)}]','}','']
                handled.add(rid)
            elif kind=='compute_instance':
                c=cfg.get('compute',{}) or {}
                size=_aws_machine(source,r) if target=='AWS' else _gcp_machine(source,r) if target=='GCP' else (c.get('vm_size') or 'Standard_B2s')
                disk=c.get('os_disk_size_gb') or c.get('boot_disk_size_gb') or 30
                if target=='AWS':
                    # Preserve the discovered source OS family.  The AMI ID is
                    # still resolved by AWS at apply time, but the parameter path
                    # is selected from the live source configuration.
                    os_type=str(c.get('os_type') or 'Linux').lower()
                    if 'windows' in os_type:
                        ami_owner='801119661308'
                        ami_pattern='Windows_Server-2022-English-Full-Base-*'
                    elif 'rhel' in os_type or 'redhat' in os_type:
                        ami_owner='309956199498'
                        ami_pattern='RHEL-9*'
                    else:
                        ami_owner='099720109477'
                        ami_pattern='ubuntu/images/hvm-ssd-gp3/ubuntu-jammy-22.04-amd64-server-*'

                    # Prefer the subnet reached through the VM's live NIC
                    # configuration.  Only fall back to the first discovered
                    # subnet when the provider did not expose that relationship.
                    subnet_ref=''
                    nic_ids=[str(x).rstrip('/').lower() for x in (c.get('network_interface_ids') or []) if x]
                    for nr in resources:
                        if str(getattr(nr,'canonical_type','') or '').lower() != 'network_interface':
                            continue
                        if _rid(nr) not in nic_ids:
                            continue
                        ips=(_config(nr).get('network',{}) or {}).get('ip_configurations') or []
                        if ips and ips[0].get('subnet_id'):
                            sid=str(ips[0].get('subnet_id')).rstrip('/').lower()
                            if any(str(getattr(sr,'canonical_type','') or '').lower()=='subnet' and _rid(sr)==sid for sr in resources):
                                subnet_ref=f'aws_subnet.{tf[sid]}.id'
                                break
                    if not subnet_ref:
                        first_subnet=next((x for x in resources if str(getattr(x,'canonical_type','') or '').lower()=='subnet' and _rid(x) in tf),None)
                        subnet_ref=f'aws_subnet.{tf[_rid(first_subnet)]}.id' if first_subnet else 'data.aws_subnets.default.ids[0]'

                    # Preserve the discovered managed-disk size and use gp3 as
                    # the target EBS type.  Target IOPS/throughput are handled by
                    # standalone disk resources when those source values exist.
                    lines += [
                        f'data "aws_ami" "{n}_ami" {{',
                        '  most_recent = true',
                        f'  owners = [{hcl_string(ami_owner)}]',
                        f'  filter {{\n    name = "name"\n    values = [{hcl_string(ami_pattern)}]\n  }}',
                        '  filter {\n    name = "virtualization-type"\n    values = ["hvm"]\n  }',
                        '}',
                        f'resource "aws_instance" "{n}" {{',
                        f'  ami = data.aws_ami.{n}_ami.id',
                        f'  instance_type = {hcl_string(size)}',
                        f'  subnet_id = {subnet_ref}',
                        f'  root_block_device {{',
                        f'    volume_size = {int(disk)}',
                        '    volume_type = "gp3"',
                        '  }',
                        '  tags = merge(var.default_tags, {',
                        f'    Name = {hcl_string(r.name)}',
                        '  })',
                        '}',
                        '',
                    ]
                elif target=='GCP':
                    image=_source_image_for_gcp(r); zone=str(c.get('zone') or '').strip(); zone=(zone if zone and zone.count('-')>=2 else region+'-a')
                    netref=network_refs[0][1]
                    lines += [f'resource "google_compute_instance" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  machine_type = {hcl_string(size)}',f'  zone = {hcl_string(zone)}','  boot_disk {','    initialize_params {',f'      size = {int(disk)}',f'      image = {hcl_string(image)}','    }','  }','  network_interface {', f'    network = google_compute_network.{netref}.id', '  }','  labels = {}','}','']
                    lines.append('')
                else:
                    vmres='azurerm_windows_virtual_machine' if 'windows' in str(c.get('os_type','')).lower() else 'azurerm_linux_virtual_machine'
                    lines += [f'resource "{vmres}" "{n}" {{',f'  name = {hcl_string(r.name)}','  location = var.azure_location','  resource_group_name = var.azure_resource_group',f'  size = {hcl_string(size)}','  admin_username = "migration_admin"',f'  admin_password = var.azure_admin_password', '  disable_password_authentication = false', '  os_disk {', '    caching = "ReadWrite"', '    storage_account_type = "Premium_LRS"',f'    disk_size_gb = {int(disk)}','  }','}','']
                handled.add(rid)

            elif kind=='block_storage':
                s=cfg.get('storage',{}) or {}; size=int(s.get('size_gb') or s.get('disk_size_gb') or 30); stype=s.get('storage_type') or s.get('volume_type') or s.get('type')
                if target=='AWS': lines += [f'resource "aws_ebs_volume" "{n}" {{',f'  availability_zone = "${{var.aws_region}}a"',f'  size = {size}','  type = "gp3"',f'  iops = {max(3000, int(s.get("disk_iops") or 3000))}',f'  throughput = {max(125, int(s.get("disk_mbps") or 125))}','}','']
                elif target=='GCP': lines += [f'resource "google_compute_disk" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  size = {size}',f'  type = {hcl_string(_gcp_disk_type(stype))}',f'  zone = {hcl_string(region+"-a")}','}','']
                else: lines += [f'resource "azurerm_managed_disk" "{n}" {{',f'  name = {hcl_string(r.name)}','  location = var.azure_location','  resource_group_name = var.azure_resource_group',f'  disk_size_gb = {size}','  storage_account_type = "Premium_LRS"','  create_option = "Empty"','}','']
                handled.add(rid)
            elif kind=='object_storage':
                o=cfg.get('object_storage',{}) or {}; access=str(o.get('access_tier') or 'Hot').lower()
                if target=='AWS': lines += [f'resource "aws_s3_bucket" "{n}" {{',f'  bucket = {hcl_string(hyphen_safe(r.name))}','}','',f'resource "aws_s3_bucket_public_access_block" "{n}" {{',f'  bucket = aws_s3_bucket.{n}.id','  block_public_acls = true','  block_public_policy = true','  ignore_public_acls = true','  restrict_public_buckets = true','}','']
                elif target=='GCP': lines += [f'resource "google_storage_bucket" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  location = {hcl_string(region.upper())}',f'  storage_class = {hcl_string(_gcp_storage_class(r))}','  uniform_bucket_level_access = true','}','']
                else: lines += [f'resource "azurerm_storage_account" "{n}" {{',f'  name = {hcl_string(re.sub("[^a-z0-9]","",str(r.name).lower())[:24] or "migratedstorage")}', '  resource_group_name = var.azure_resource_group','  location = var.azure_location','  account_tier = "Standard"','  account_replication_type = "LRS"','  https_traffic_only_enabled = true','}','']
                handled.add(rid)
            elif kind=='container_registry':
                if target=='AWS': lines += [f'resource "aws_ecr_repository" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name,256))}','  image_scanning_configuration { scan_on_push = true }','}','']
                elif target=='GCP': lines += [f'resource "google_artifact_registry_repository" "{n}" {{',f'  repository_id = {hcl_string(hyphen_safe(r.name))}','  format = "DOCKER"',f'  location = {hcl_string(region)}','}','']
                else: lines += [f'resource "azurerm_container_registry" "{n}" {{',f'  name = {hcl_string(re.sub("[^A-Za-z0-9]","",str(r.name))[:50] or "migratedregistry")}', '  resource_group_name = var.azure_resource_group','  location = var.azure_location','  sku = "Standard"','  admin_enabled = false','}','']
                handled.add(rid)
            elif kind in {'relational_database','postgresql'}:
                d=cfg.get('database',{}) or {}; size=int(d.get('storage_gb') or d.get('allocated_storage') or 32); version=str(d.get('version') or d.get('engine_version') or '15'); engine=str(d.get('engine') or 'postgresql').lower()
                if target=='GCP' and ('sqlserver' in engine or 'sql-server' in engine):
                    _emit_review(lines,r,target,'Source is an Azure SQL Server logical server. Cloud SQL for SQL Server requires a target edition/version and database-level migration details that are not exposed by this discovery record.',warnings)
                elif target=='GCP': lines += [f'resource "google_sql_database_instance" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  database_version = {hcl_string(_gcp_sql_version(r))}','  region = var.gcp_region','  settings {',f'    tier = {hcl_string(d.get("instance_class") or "db-custom-2-7680")}',f'    disk_type = "PD_SSD"',f'    disk_size = {size}','    availability_type = "ZONAL"','  }','}','']
                elif target=='AWS':
                    from .pricing import _target_sku
                    db_class = _target_sku(r, 'AWS').get('target_instance_class')
                    if engine not in {'postgres', 'postgresql'} or not db_class:
                        _emit_review(lines, r, target, 'Database engine or instance sizing requires an explicit target design; no PostgreSQL default was substituted.', warnings)
                        continue
                    major=re.search(r'(\d+)',version); ev=major.group(1) if major else '15'; lines += [f'resource "random_password" "{n}" {{','  length = 24','  special = true','}', '',f'resource "aws_db_instance" "{n}" {{',f'  identifier = {hcl_string(hyphen_safe(r.name,63))}','  engine = "postgres"',f'  engine_version = {hcl_string(ev)}',f'  instance_class = {hcl_string(db_class)}',f'  allocated_storage = {size}','  storage_type = "gp3"','  username = "migration_admin"',f'  password = random_password.{n}.result','  publicly_accessible = false','  skip_final_snapshot = true','}','']
                else: lines += [f'resource "azurerm_postgresql_flexible_server" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}','  resource_group_name = var.azure_resource_group','  location = var.azure_location',f'  version = {hcl_string(re.search(r"(\\d+)",version).group(1) if re.search(r"(\\d+)",version) else "15")}', '  administrator_login = "migration_admin"','  administrator_password = var.azure_admin_password',f'  storage_mb = {size*1024}','  sku_name = "GP_Standard_D2s_v5"','}','']
                handled.add(rid); warnings.append(f'{r.name}: database schema/data are not copied by Terraform; perform data replication separately.')
            elif kind=='public_ip':
                if target=='AWS': lines += [f'resource "aws_eip" "{n}" {{ domain = "vpc" }}','']
                elif target=='GCP': lines += [f'resource "google_compute_address" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  region = var.gcp_region','}','']
                else: lines += [f'resource "azurerm_public_ip" "{n}" {{',f'  name = {hcl_string(r.name)}','  location = var.azure_location','  resource_group_name = var.azure_resource_group','  allocation_method = "Static"','  sku = "Standard"','}','']
                handled.add(rid)
            elif kind=='security_group':
                if target=='AWS':
                    sgcfg=_config(r).get('network_security',{}) or {}
                    rules=sgcfg.get('rules') or []
                    lines += [
                        f'resource "aws_security_group" "{n}" {{',
                        f'  name = {hcl_string(aws_security_group_name(r.name))}',
                        '  description = "Migrated security group"',
                    ]
                    emitted_rule_count=0
                    for rule in rules:
                        if str(rule.get('access','Allow')).lower() != 'allow':
                            warnings.append(f'{r.name}: Azure deny rule {rule.get("name","rule")} was not emitted because AWS security groups do not support explicit deny rules.')
                            continue
                        direction=str(rule.get('direction') or '').lower()
                        proto=str(rule.get('protocol') or '').lower()
                        prefix = rule.get('source_address_prefix') if direction == 'inbound' else rule.get('destination_address_prefix')
                        ports = rule.get('destination_port_range')
                        # Never widen unsupported Azure selectors into permissive AWS rules.
                        if (direction not in {'inbound', 'outbound'} or proto not in {'tcp', 'udp', '*', 'any', 'all'}
                            or rule.get('source_port_range') != '*' or not ports or not prefix
                            or any(rule.get(k) for k in ('source_port_ranges', 'destination_port_ranges',
                                'source_address_prefixes', 'destination_address_prefixes',
                                'source_application_security_groups', 'destination_application_security_groups'))):
                            warnings.append(f'{r.name}: rule {rule.get("name", "rule")} requires manual firewall mapping; no permissive substitute emitted.')
                            continue
                        try:
                            import ipaddress
                            network = ipaddress.ip_network('0.0.0.0/0' if prefix == '*' else prefix, strict=False)
                            if network.version != 4:
                                raise ValueError('IPv6 needs explicit mapping')
                            cidr = str(network)
                            proto = '-1' if proto in {'*', 'any', 'all'} else proto
                            if proto == '-1':
                                if ports != '*':
                                    raise ValueError('Protocol and port mismatch')
                                from_port = to_port = '0'
                            elif ports == '*':
                                from_port, to_port = '0', '65535'
                            else:
                                parts = str(ports).split('-')
                                low, high = int(parts[0]), int(parts[-1])
                                if len(parts) > 2 or not 0 <= low <= high <= 65535:
                                    raise ValueError('Invalid ports')
                                from_port, to_port = str(low), str(high)
                        except (ValueError, TypeError):
                            warnings.append(f'{r.name}: rule {rule.get("name", "rule")} requires manual address/port mapping; no permissive substitute emitted.')
                            continue
                        block='  ingress {' if direction == 'inbound' else '  egress {'
                        lines += [
                            block,
                            f'    protocol = {hcl_string(proto)}',
                            f'    from_port = {from_port}',
                            f'    to_port = {to_port}',
                            f'    cidr_blocks = [{hcl_string(cidr)}]',
                            '  }',
                        ]
                        emitted_rule_count += 1
                    if emitted_rule_count == 0:
                        warnings.append(f'{r.name}: no validated rules emitted; review required.')
                    lines += ['}','']
                elif target=='GCP':
                    lines += [f'resource "google_compute_firewall" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}',f'  network = google_compute_network.{network_refs[0][1]}.id','  allow {', '    protocol = "tcp"', '    ports = ["0-65535"]', '  }','  source_ranges = ["0.0.0.0/0"]','}','']
                else:
                    lines += [f'resource "azurerm_network_security_group" "{n}" {{',f'  name = {hcl_string(r.name)}','  location = var.azure_location','  resource_group_name = var.azure_resource_group','}','']
                warnings.append(f'{r.name}: security rules require review before apply because source and target firewall semantics differ.'); handled.add(rid)

            elif kind=='dns':
                dns=cfg.get('dns',{}) or {}; zone=str(dns.get('dns_name') or r.name)
                if target=='AWS': lines += [f'resource "aws_route53_zone" "{n}" {{',f'  name = {hcl_string(zone)}','}','']
                elif target=='GCP': lines += [f'resource "google_dns_managed_zone" "{n}" {{',f'  name = {hcl_string(tf_name(r.name))}',f'  dns_name = {hcl_string(zone if zone.endswith(".") else zone+".")}',f'  visibility = "{str(dns.get("visibility") or "public").lower()}"','}','']
                else: lines += [f'resource "azurerm_private_dns_zone" "{n}" {{',f'  name = {hcl_string(zone)}','  resource_group_name = var.azure_resource_group','}','']
                handled.add(rid)
            elif kind=='secrets_manager':
                if target=='AWS': lines += [f'resource "aws_secretsmanager_secret" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name,512))}','}','']
                elif target=='GCP': lines += [f'resource "google_secret_manager_secret" "{n}" {{',f'  secret_id = {hcl_string(hyphen_safe(r.name))}','  replication {', '    auto {}', '  }','}','']
                else: lines += [f'resource "azurerm_key_vault" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}','  location = var.azure_location','  resource_group_name = var.azure_resource_group','  tenant_id = "00000000-0000-0000-0000-000000000000"','  sku_name = "standard"','}','']
                warnings.append(f'{r.name}: secret values are not exposed by discovery and are not copied.'); handled.add(rid)
            elif kind in {'container_service','app_service','serverless_function'}:
                c=cfg.get('container_service',{}) or {}; image=c.get('image') or ((cfg.get('site_config') or {}).get('linuxFxVersion') if isinstance(cfg.get('site_config'),dict) else None) or 'us-docker.pkg.dev/cloudrun/container/hello'
                if target=='GCP': lines += [f'resource "google_cloud_run_v2_service" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name))}','  location = var.gcp_region','  template {','    containers {',f'      image = {hcl_string(image)}','    }','  }','}','']
                else: _emit_review(lines,r,target,'No safe provider-specific Terraform 1:1 mapping is available for this managed application service from the discovered metadata.',warnings)
                handled.add(rid)
            elif kind=='identity':
                if str(r.cloud).upper() == 'AWS':
                    _emit_review(lines,r,target,'AWS IAM users, groups and roles require their actual policies and trust relationships; inventory metadata alone cannot reconstruct an identity.',warnings)
                    handled.add(rid)
                    continue
                if target=='GCP': lines += [f'resource "google_service_account" "{n}" {{',f'  account_id = {hcl_string(hyphen_safe(r.name,30))}',f'  display_name = {hcl_string(r.name)}','}','']
                elif target=='AWS': lines += [f'resource "aws_iam_role" "{n}" {{',f'  name = {hcl_string(hyphen_safe(r.name,64))}','  assume_role_policy = jsonencode({Version = "2012-10-17", Statement = [{Effect = "Allow", Principal = {Service = "ec2.amazonaws.com"}, Action = "sts:AssumeRole"}]})','}','']
                else: lines += [f'resource "azurerm_user_assigned_identity" "{n}" {{',f'  name = {hcl_string(r.name)}','  location = var.azure_location','  resource_group_name = var.azure_resource_group','}','']
                warnings.append(f'{r.name}: identity permissions are not copied 1:1; review target IAM bindings.'); handled.add(rid)
            else:
                _emit_review(lines,r,target,'The source service has no safe generic Terraform equivalent in this version. Source configuration is retained in the UI mapping, and a manual target-service design is required.',warnings)
        except Exception as exc:
            _emit_review(lines,r,target,f'Generation error was prevented: {exc}',warnings)

    lines += ['# ============================================================','# Migration warnings / review items','# ============================================================']
    for w in warnings: lines.append('# - '+w)
    if not warnings: lines.append('# No warnings generated.')
    lines += ['','# Terraform provisions infrastructure. It does not copy application binaries, database contents, container images, secrets, ML models, search indexes, or other data-plane contents.','# Dependency relationships discovered by the source adapter are listed below.']
    for e in edges or []:
        lines.append(f'# {getattr(e,"source_id","")} -> {getattr(e,"target_id","")} | {getattr(e,"relationship","")} | {getattr(e,"confidence","")} | {getattr(e,"evidence","")}')
    lines.append('')
    return '\n'.join(lines)


def generate(resources, edges, target):
    target=str(target or '').upper(); resources=list(resources or [])
    # Keep the previously validated, configuration-preserving Azure -> AWS path.
    if target=='AWS' and any(str(getattr(r,'cloud','')).upper()=='AZURE' for r in resources):
        return _aws_generate(resources, edges)
    return _generate_generic_final(resources, edges, target)


# ======================================================================
# Supplemental configuration-preserving AWS Terraform
# ======================================================================
# The final generator above intentionally emits conservative review
# blocks for services that cannot be mapped 1:1.  The supplemental layer
# below adds concrete AWS resources whenever the source configuration
# contains enough information, while retaining review comments for
# workload/data-plane items that cannot be safely inferred.
#
# This wrapper is deliberately additive: no source resource is dropped.

def _aws_supplemental_terraform(resources, target):
    if str(target or "").upper() != "AWS":
        return []

    resources = list(resources or [])
    by_id = {_rid(r): r for r in resources}
    name_by_id = {rid: tf_name(getattr(r, "name", "resource")) for rid, r in by_id.items()}

    lines = [
        "# ============================================================",
        "# Supplemental AWS resources generated from live configuration",
        "# ============================================================",
    ]
    warnings = []

    # Build a deterministic lookup for target subnet/security-group names.
    subnet_tf = {}
    sg_tf = {}
    vpc_tf = {}
    eip_tf = {}
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind == "subnet":
            subnet_tf[rid] = name_by_id[rid]
        elif kind == "security_group":
            sg_tf[rid] = name_by_id[rid]
        elif kind == "virtual_network":
            vpc_tf[rid] = name_by_id[rid]
        elif kind == "public_ip":
            eip_tf[rid] = name_by_id[rid]

    emitted = set()

    # --------------------------------------------------------------
    # Azure NIC -> AWS ENI, preserving IP configuration, subnet and
    # security-group association where those IDs were discovered.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind != "network_interface":
            continue
        n = name_by_id[rid]
        net = _config(r).get("network", {}) or {}
        ips = net.get("ip_configurations") or []
        first = ips[0] if ips else {}
        subnet_id = str(first.get("subnet_id") or "").rstrip("/").lower()
        sg_id = str(net.get("network_security_group_id") or "").rstrip("/").lower()
        subnet_ref = (
            f"aws_subnet.{subnet_tf[subnet_id]}.id"
            if subnet_id in subnet_tf
            else 'data.aws_subnets.default.ids[0]'
        )
        attrs = [
            f'resource "aws_network_interface" "{n}" {{',
            f'  subnet_id = {subnet_ref}',
        ]
        private_ip = first.get("private_ip")
        if private_ip:
            attrs.append(f'  private_ips = [{hcl_string(private_ip)}]')
        if sg_id in sg_tf:
            attrs.append(f'  security_groups = [aws_security_group.{sg_tf[sg_id]}.id]')
        attrs += [
            '  tags = merge(var.default_tags, {',
            f'    Name = {hcl_string(getattr(r, "name", "network-interface"))}',
            '  })',
            '}',
            '',
        ]
        lines += attrs
        emitted.add(rid)

        public_id = str(first.get("public_ip_id") or "").rstrip("/").lower()
        if public_id in eip_tf:
            lines += [
                f'resource "aws_eip_association" "{n}_public_ip" {{',
                f'  allocation_id = aws_eip.{eip_tf[public_id]}.id',
                f'  network_interface_id = aws_network_interface.{n}.id',
                '}',
                '',
            ]

    # --------------------------------------------------------------
    # Azure Container Apps -> ECS/Fargate.  CPU, memory, image and
    # minimum replica count are taken from live Azure configuration.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind != "container_service":
            continue
        n = name_by_id[rid]
        c = _config(r).get("container_service", {}) or {}
        cpu = c.get("cpu_vcpu")
        memory = c.get("memory_gb")
        image = c.get("image")
        replicas = int(c.get("min_replicas") or 1)
        if not cpu or not memory or not image:
            warnings.append(
                f'{getattr(r, "name", "container service")}: ECS/Fargate was not emitted because live CPU, memory, or image configuration is incomplete.'
            )
            continue

        cpu_units = max(256, int(round(float(cpu) * 1024)))
        memory_mib = max(512, int(round(float(memory) * 1024)))
        lines += [
            f'resource "aws_ecs_cluster" "{n}" {{',
            f'  name = {hcl_string(hyphen_safe(getattr(r, "name", "ecs-cluster")))}',
            '}',
            '',
            f'resource "aws_iam_role" "{n}_execution" {{',
            f'  name = {hcl_string(hyphen_safe(getattr(r, "name", "ecs") + "-execution", 64))}',
            '  assume_role_policy = jsonencode({',
            '    Version = "2012-10-17"',
            '    Statement = [{',
            '      Effect = "Allow"',
            '      Principal = { Service = "ecs-tasks.amazonaws.com" }',
            '      Action = "sts:AssumeRole"',
            '    }]',
            '  })',
            '}',
            '',
            f'resource "aws_iam_role_policy_attachment" "{n}_execution_policy" {{',
            f'  role       = aws_iam_role.{n}_execution.name',
            '  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"',
            '}',
            '',
            f'resource "aws_ecs_task_definition" "{n}" {{',
            f'  family                   = {hcl_string(hyphen_safe(getattr(r, "name", "task")))}',
            '  requires_compatibilities = ["FARGATE"]',
            '  network_mode             = "awsvpc"',
            '  cpu                      = ' + hcl_string(str(cpu_units)),
            '  memory                   = ' + hcl_string(str(memory_mib)),
            f'  execution_role_arn       = aws_iam_role.{n}_execution.arn',
            '  container_definitions = jsonencode([{',
            f'    name  = {hcl_string(hyphen_safe(getattr(r, "name", "container"), 64))}',
            f'    image = {hcl_string(str(image))}',
            f'    cpu   = {cpu_units}',
            f'    memory = {memory_mib}',
            '    essential = true',
            '  }])',
            '}',
            '',
        ]

        subnet_exprs = []
        for sr in resources:
            sid = _rid(sr)
            if str(getattr(sr, "canonical_type", "") or "").lower() == "subnet":
                subnet_exprs.append(f'aws_subnet.{name_by_id[sid]}.id')
        if not subnet_exprs:
            subnet_exprs = ['data.aws_subnets.default.ids[0]']

        lines += [
            f'resource "aws_security_group" "{n}_service" {{',
            f'  name = {hcl_string(hyphen_safe(getattr(r, "name", "service") + "-ecs-sg", 255))}',
            '  description = "Security group for migrated Fargate service"',
            '  egress {',
            '    protocol = "-1"',
            '    from_port = 0',
            '    to_port = 0',
            '    cidr_blocks = ["0.0.0.0/0"]',
            '  }',
            '}',
            '',
            f'resource "aws_ecs_service" "{n}" {{',
            f'  name            = {hcl_string(hyphen_safe(getattr(r, "name", "ecs-service"), 255))}',
            f'  cluster         = aws_ecs_cluster.{n}.id',
            f'  task_definition = aws_ecs_task_definition.{n}.arn',
            f'  desired_count   = {replicas}',
            '  launch_type     = "FARGATE"',
            '  network_configuration {',
            f'    subnets         = [{", ".join(subnet_exprs[:3])}]',
            f'    security_groups = [aws_security_group.{n}_service.id]',
            '    assign_public_ip = false',
            '  }',
            '}',
            '',
        ]
        warnings.append(
            f'{getattr(r, "name", "container service")}: ECS image is taken from live Azure configuration; private ACR authentication/image replication is not performed by Terraform.'
        )
        emitted.add(rid)

    # --------------------------------------------------------------
    # Azure CDN profile/endpoint -> CloudFront.  An origin hostname
    # is mandatory; if it was not exposed, do not invent one.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind != "cdn":
            continue
        n = name_by_id[rid]
        cdn = _config(r).get("cdn", {}) or {}
        origin = str(cdn.get("origin_host") or "").strip()
        if not origin:
            warnings.append(
                f'{getattr(r, "name", "CDN")}: CloudFront not emitted because live origin_host was not exposed by Azure discovery.'
            )
            continue
        lines += [
            f'resource "aws_cloudfront_distribution" "{n}" {{',
            '  enabled = true',
            f'  origin {{',
            f'    domain_name = {hcl_string(origin)}',
            f'    origin_id   = {hcl_string("azure-origin-" + n)}',
            '  }',
            '  default_cache_behavior {',
            f'    target_origin_id       = {hcl_string("azure-origin-" + n)}',
            '    viewer_protocol_policy = "redirect-to-https"',
            '    allowed_methods         = ["GET", "HEAD", "OPTIONS"]',
            '    cached_methods          = ["GET", "HEAD"]',
            '    forwarded_values {',
            '      query_string = false',
            '      cookies { forward = "none" }',
            '    }',
            '  }',
            '  restrictions {',
            '    geo_restriction { restriction_type = "none" }',
            '  }',
            '  viewer_certificate { cloudfront_default_certificate = true }',
            f'  tags = merge(var.default_tags, {{ Name = {hcl_string(getattr(r, "name", "cdn"))} }})',
            '}',
            '',
        ]
        warnings.append(
            f'{getattr(r, "name", "CDN")}: CloudFront request/data-transfer charges require actual traffic usage; no traffic is inferred from source spend.'
        )
        emitted.add(rid)

    # --------------------------------------------------------------
    # Azure Redis -> ElastiCache replication group.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind != "cache":
            continue
        n = name_by_id[rid]
        c = _config(r).get("cache", {}) or {}
        node_type = str(c.get("target_node_type") or c.get("node_type") or "cache.t3.micro")
        count = int(c.get("num_cache_clusters") or 1)
        lines += [
            f'resource "aws_elasticache_replication_group" "{n}" {{',
            f'  replication_group_id = {hcl_string(hyphen_safe(getattr(r, "name", "redis"), 40))}',
            '  description = "Migrated Redis cache"',
            '  engine = "redis"',
            f'  node_type = {hcl_string(node_type)}',
            f'  num_cache_clusters = {max(1, count)}',
            '  automatic_failover_enabled = false',
            '}',
            '',
        ]
        warnings.append(
            f'{getattr(r, "name", "cache")}: Redis node type is a migration mapping; validate engine version, subnet group, encryption and failover before apply.'
        )
        emitted.add(rid)

    # --------------------------------------------------------------
    # Azure ML workspace -> SageMaker domain shell.  The execution
    # role is intentionally a variable; credentials are never copied.
    # --------------------------------------------------------------
    ml_resources = [
        r for r in resources
        if str(getattr(r, "canonical_type", "") or "").lower() == "machine_learning"
    ]
    if ml_resources:
        lines += [
            'variable "sagemaker_execution_role_arn" {',
            '  type = string',
            '  description = "IAM execution role ARN for the migrated SageMaker domain"',
            '}',
            '',
        ]
        for r in ml_resources:
            rid = _rid(r); n = name_by_id[rid]
            subnet_exprs = [
                f'aws_subnet.{name_by_id[_rid(sr)]}.id'
                for sr in resources
                if str(getattr(sr, "canonical_type", "") or "").lower() == "subnet"
            ]
            if not subnet_exprs:
                subnet_exprs = ['data.aws_subnets.default.ids[0]']
            lines += [
                f'resource "aws_sagemaker_domain" "{n}" {{',
                f'  domain_name = {hcl_string(hyphen_safe(getattr(r, "name", "sagemaker"), 63))}',
                '  auth_mode = "IAM"',
                f'  vpc_id = {("aws_vpc." + vpc_tf[next(iter(vpc_tf))] + ".id") if vpc_tf else "data.aws_vpc.default.id"}',
                f'  subnet_ids = [{", ".join(subnet_exprs[:5])}]',
                '  default_user_settings {',
                '    execution_role = var.sagemaker_execution_role_arn',
                '  }',
                '}',
                '',
            ]
            warnings.append(
                f'{getattr(r, "name", "ML workspace")}: SageMaker domain is a control-plane shell; attached training/endpoints/storage are not inferred from workspace metadata.'
            )
            emitted.add(rid)

    # --------------------------------------------------------------
    # Azure Data Factory -> Glue workflow shell.  Activity scripts,
    # connections and DPU runtime are data/workload-plane details.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind != "data_pipeline":
            continue
        n = name_by_id[rid]
        lines += [
            f'resource "aws_glue_workflow" "{n}" {{',
            f'  name = {hcl_string(hyphen_safe(getattr(r, "name", "glue-workflow"), 255))}',
            '}',
            '',
        ]
        warnings.append(
            f'{getattr(r, "name", "data pipeline")}: Glue workflow shell generated; source ADF activities, linked services and DPU/runtime usage are not exposed by the factory record.'
        )
        emitted.add(rid)

    # --------------------------------------------------------------
    # Azure Log Analytics/logging -> CloudWatch log group shell.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind != "logging":
            continue
        n = name_by_id[rid]
        lines += [
            f'resource "aws_cloudwatch_log_group" "{n}" {{',
            f'  name = {hcl_string("/migrated/" + hyphen_safe(getattr(r, "name", "log-group")))}',
            '}',
            '',
        ]
        warnings.append(
            f'{getattr(r, "name", "logging")}: CloudWatch log group shell generated; historical logs and retention/ingestion volumes require separate migration/usage data.'
        )
        emitted.add(rid)

    # --------------------------------------------------------------
    # Azure Cosmos/DocumentDB -> DynamoDB only when a partition key is
    # actually present.  Otherwise retain the source resource in the
    # main generator's review section instead of inventing a schema.
    # --------------------------------------------------------------
    for r in resources:
        rid = _rid(r)
        kind = str(getattr(r, "canonical_type", "") or "").lower()
        if kind not in {"nosql_database", "database_mongo"}:
            continue
        n = name_by_id[rid]
        d = _config(r).get("database", {}) or {}
        key = d.get("partition_key") or d.get("hash_key")
        if not key:
            warnings.append(
                f'{getattr(r, "name", "NoSQL database")}: DynamoDB was not emitted because a live partition/hash key was not exposed; creating a guessed schema would be unsafe.'
            )
            continue
        lines += [
            f'resource "aws_dynamodb_table" "{n}" {{',
            f'  name = {hcl_string(hyphen_safe(getattr(r, "name", "dynamodb"), 255))}',
            '  billing_mode = "PAY_PER_REQUEST"',
            '  hash_key = ' + hcl_string(str(key)),
            '  attribute {',
            f'    name = {hcl_string(str(key))}',
            '    type = "S"',
            '  }',
            '}',
            '',
        ]
        emitted.add(rid)

    if warnings:
        lines += [
            "# Supplemental mapping review items:",
        ]
        lines += [f"# - {w}" for w in warnings]
        lines += ['']

    return lines, warnings, emitted


def _generate_with_supplemental_aws(resources, edges, target):
    base = _generate_generic_final(resources, edges, target)
    if str(target or "").upper() != "AWS":
        return base

    extra, warnings, emitted = _aws_supplemental_terraform(resources, target)

    # Add AWS data sources once when supplemental resources may need a
    # default subnet/VPC.  Existing generated resources remain untouched.
    need_default_network = 'data.aws_subnets.default' in base or any(
        str(getattr(r, "canonical_type", "") or "").lower()
        in {"network_interface", "container_service", "machine_learning"}
        for r in resources
    )
    if need_default_network:
        data = [
            '# Default-network fallbacks used only when the source did not expose a target subnet/VPC mapping.',
            'data "aws_vpc" "default" { default = true }',
            'data "aws_subnets" "default" {',
            '  filter {',
            '    name   = "vpc-id"',
            '    values = [data.aws_vpc.default.id]',
            '  }',
            '}',
            '',
        ]
        # Insert after provider/variable header rather than after resources.
        marker = '# Multi-Cloud AI'
        pos = base.find(marker)
        if pos >= 0:
            line_end = base.find('\n', pos)
            base = base[:line_end+1] + '\n'.join(data) + base[line_end+1:]
        else:
            base = '\n'.join(data) + base

    # Remove the conservative review block emitted by the generic generator
    # for resources for which the supplemental layer produced concrete AWS
    # Terraform.  Keep the supplemental review/warning items (for example,
    # private ACR image replication) because those are genuine limitations.
    for rid in emitted:
        r = next((x for x in resources if _rid(x) == rid), None)
        if r is None:
            continue
        name = re.escape(str(getattr(r, "name", "resource")))
        base = re.sub(
            rf'(?ms)^# REVIEW REQUIRED: {name}\n'
            rf'# Source type: .*?\n'
            rf'# Source ID: .*?\n'
            rf'# Target: AWS\n'
            rf'# Reason: .*?\n\n',
            '',
            base,
            count=1,
        )
        base = re.sub(
            rf'(?m)^# - {name}: No safe provider-specific Terraform 1:1 mapping is available for this managed application service from the discovered metadata\\.\n',
            '',
            base,
            count=1,
        )
        base = re.sub(
            rf'(?m)^# - {name}: The source service has no safe generic Terraform equivalent in this version\\. Source configuration is retained in the UI mapping, and a manual target-service design is required\\.\n',
            '',
            base,
            count=1,
        )

    return base + "\n" + "\n".join(extra)


# Final override: use the configuration-preserving all-cloud generator
# for AWS as well, then add concrete supplemental resources.
generate = _generate_with_supplemental_aws


_generate_before_placement = generate

def generate(resources, edges, target, target_configurations=None):
    resources = list(resources)
    from .placement import terraform_region
    region = terraform_region(resources) if str(target).upper() == "AWS" else None
    if str(target).upper() == "AWS":
        from copy import deepcopy
        from .equivalence import equivalent_configuration_rows
        rows = target_configurations if target_configurations is not None else equivalent_configuration_rows(resources, "AWS")
        by_id = {str(row.get("Resource ID", "")).rstrip("/").lower(): row for row in rows}
        resources = deepcopy(resources)
        for resource in resources:
            if resource.canonical_type != "compute_instance":
                continue
            row = by_id.get(str(resource.resource_id).rstrip("/").lower())
            if not row or (region and row.get("Target Region") != region):
                raise ValueError(f"{resource.name}: approved target configuration is missing or its region differs from Terraform placement.")
            sku = str(row.get("Target SKU") or "")
            if not re.fullmatch(r"[a-z][a-z0-9-]*\.[a-z0-9]+", sku):
                raise ValueError(f"{resource.name}: target instance sizing must be resolved before Terraform generation.")
            resource.configuration = dict(resource.configuration or {})
            resource.configuration["approved_aws_compute"] = {"instance_type": sku}
    text = _generate_before_placement(resources, edges, target)
    if region:
        text, count = re.subn(r'(variable "aws_region" \{.*?default\s*=\s*)"[^"]*"',
            lambda m: m.group(1) + hcl_string(region), text, count=1, flags=re.S)
        if count != 1:
            raise ValueError("Generated Terraform does not expose the expected AWS region variable.")
    if str(target).upper() == "AZURE" and all(str(r.cloud).upper() == "AZURE" for r in resources):
        text = _preserve_azure_source(text, resources)
    return text


def _preserve_azure_source(text, resources):
    """Preserve source identities; do not turn logical SQL servers into PostgreSQL."""
    _, names = _resource_maps(resources)
    by_name = {names[_rid(r)]: r for r in resources}
    def replace_block(match):
        kind, name, block = match.group(1), match.group(2), match.group(0)
        r = by_name.get(name)
        if r is None:
            return block
        raw = str(r.raw_type).lower()
        if kind == "azurerm_postgresql_flexible_server" and (raw.startswith("microsoft.sql/") or "postgres" not in (raw + str(r.configuration.get("database", {}).get("engine", ""))).lower()):
            return f"# REVIEW REQUIRED: {r.name}\n# Source ID: {r.resource_id}\n# SQL logical server/system database is not a PostgreSQL instance; no substitute database emitted.\n"
        group_match = re.search(r"/resourcegroups/([^/]+)", r.resource_id, re.I)
        group = group_match.group(1) if group_match else r.group
        location = str(r.region or "").strip()
        if "location = var.azure_location" in block and location.lower() in {"", "global", "unknown"}:
            return f"# REVIEW REQUIRED: {r.name}\n# Source ID: {r.resource_id}\n# A regional location was not discovered; resource omitted rather than placed in global.\n"
        block = block.replace("location = var.azure_location", "location = " + hcl_string(location))
        if group and group != "default":
            block = block.replace("resource_group_name = var.azure_resource_group", "resource_group_name = " + hcl_string(group))
        if kind == "azurerm_postgresql_flexible_server":
            db = r.configuration.get("database", {}) or {}
            from .equivalence import source_configuration_fields
            discovered = source_configuration_fields(r)
            version = str(discovered.get("version") or "")
            sku = discovered.get("sku") or r.sku
            tier = ""
            if isinstance(sku, dict):
                tier, sku = sku.get("tier", ""), sku.get("name", "")
            sku = str(sku or "")
            if not re.match(r"^(B|GP|MO)_Standard_", sku):
                prefix = {"Burstable": "B", "GeneralPurpose": "GP", "MemoryOptimized": "MO"}.get(tier)
                if not prefix and sku.startswith("Standard_B"):
                    prefix = "B"
                sku = prefix + "_" + sku if prefix else ""
            storage = discovered.get("storage_gb")
            if not re.fullmatch(r"\d+(?:\.\d+)?", version) or not sku or not storage:
                return f"# REVIEW REQUIRED: {r.name}\n# Source ID: {r.resource_id}\n# PostgreSQL version, SKU tier or storage is unresolved; no substitute database configuration emitted.\n"
            block = re.sub(r'(?m)^  version = .*$', '  version = ' + hcl_string(version.split(".")[0]), block)
            block = re.sub(r'(?m)^  sku_name = .*$', '  sku_name = ' + hcl_string(sku), block)
            block = re.sub(r'(?m)^  storage_mb = .*$', '  storage_mb = ' + str(int(float(storage) * 1024)), block)
            admin = db.get("administrator_login") or r.configuration.get("raw_properties", {}).get("administratorLogin")
            if admin:
                block = re.sub(r'(?m)^  administrator_login = .*$', '  administrator_login = ' + hcl_string(str(admin)), block)
            else:
                block = re.sub(r'(?m)^  administrator_login = .*\n', '', block)
            note = "  # SOURCE DRAFT: Review database authentication, networking, backups and HA before use."
            if note not in block:
                block = block.replace("{\n", "{\n" + note + "\n", 1)
        if kind == "azurerm_managed_disk":
            storage = r.configuration.get("storage", {})
            sku = storage.get("storage_type") or storage.get("type") or r.sku
            if sku in {"Standard_LRS", "StandardSSD_LRS", "Premium_LRS", "StandardSSD_ZRS", "Premium_ZRS", "UltraSSD_LRS", "PremiumV2_LRS"}:
                block = re.sub(r'storage_account_type = "[^"]+"', 'storage_account_type = ' + hcl_string(sku), block)
        if kind == "azurerm_container_registry":
            registry = r.configuration.get("registry", {})
            sku = registry.get("sku") or registry.get("tier") or r.sku
            if isinstance(sku, dict):
                sku = sku.get("name")
            if sku in {"Basic", "Standard", "Premium"}:
                block = re.sub(r'sku = "[^"]+"', 'sku = ' + hcl_string(sku), block)
        if kind in {"azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine"}:
            return f"# REVIEW REQUIRED: {r.name}\n# Source ID: {r.resource_id}\n# Reconstruct VM image, existing OS disk and NIC attachments before generating a deployable VM; no replacement boot disk or credentials invented.\n"
        return block
    text = re.sub(r'^resource "(azurerm_[^"]+)" "([^"]+)" \{.*?^\}', replace_block, text, flags=re.M | re.S)
    # Source resources carry their own location/group, not migration defaults.
    text = re.sub(r'variable "azure_location" \{.*?^\}\n', '', text, flags=re.M | re.S)
    text = re.sub(r'variable "azure_resource_group" \{.*?^\}\n', '', text, flags=re.M | re.S)
    return text
