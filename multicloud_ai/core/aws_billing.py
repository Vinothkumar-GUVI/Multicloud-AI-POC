"""Separate AWS usage-type identifiers from consumed billing units."""
import re

from .classification import classify


def billing_kind(product, service, usage_type):
    meter = str(usage_type).lower()
    if 'publicipv4' in meter:
        return 'public_ip'
    if 'ebsoptimized' in meter:
        return 'other'  # Instance feature charge, not provisioned disk capacity.
    if 'volumeusage' in meter or ('amazonrds' in str(product).lower() and 'storage' in meter):
        return 'block_storage'
    if 'datatransfer' in meter or 'aws-in-bytes' in meter or 'aws-out-bytes' in meter:
        return 'other'
    # Region prefixes such as APS3 must never participate in service matching.
    return classify(product, service)


def consumed_unit(explicit_unit, description, usage_type):
    if explicit_unit:
        return explicit_unit
    desc = str(description).lower()
    meter = str(usage_type).lower()
    if 'request' in meter:
        return 'requests'
    if re.search(r'\b(?:gb|gib)[- /]?month\b', desc) or 'gb-mo' in desc:
        return 'GB-month'
    if re.search(r'\b(?:gb|gib)\b', desc) and ('per gb' in desc or 'per gib' in desc):
        return 'GB'
    if re.search(r'\b(?:hours?|hrs?)\b', desc) or any(s in meter for s in ('boxusage:', 'instanceusage:', 'publicipv4:')):
        return 'Hours'
    return usage_type  # Unknown dimensions remain explicit; never infer from cost.
