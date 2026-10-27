"""Registry storage planning estimates; Azure tier-days are not image GB."""
import re


def registry_estimate(resource_id, contract, monthly):
    if not monthly or contract.get('resource_type') != 'container_registry':
        return None
    meters = contract.get('meters', [])
    if not meters:
        return None
    tiers = []
    for meter in meters:
        match = re.fullmatch(r'(Basic|Standard|Premium) Registry Unit', str(meter.get('name', '')).strip(), re.I)
        if not match:
            return None  # Do not silently omit excess storage, build or transfer meters.
        tiers.append(match[1].lower())
    if len(set(tiers)) != 1:
        return None
    size = {'basic': 10., 'standard': 100., 'premium': 500.}[tiers[0]]
    assumption = (f'Measured image storage unavailable. Planning allowance uses the {size:g} GiB '
                  f'included in the Azure {tiers[0]} tier, not actual consumed storage or a maximum. '
                  'Registry-day quantities are not storage quantities. Transfer, builds and scanning are excluded; '
                  'no account-wide free allowance assumed.')
    targets = {}
    for cloud, service, unit, quantity, url in [
        ('AWS', 'Amazon ECR private image storage', 'GB-month', size * 2**30 / 10**9,
         'https://aws.amazon.com/ecr/pricing/'),
        ('GCP', 'Google Artifact Registry storage', 'GiB-month', size,
         'https://cloud.google.com/artifact-registry/pricing'),
    ]:
        part = {'quantity': quantity, 'unit': unit, 'rate_unit': unit, 'unit_price_usd': .10,
                'description': 'Stored container images, one monthly period',
                'rate_basis': f'USD 0.10 per {unit}; excludes transfer, scanning and builds',
                'rate_source': url, 'rate_checked': '2026-10-10',
                'usage_review': assumption}
        targets[cloud] = {'service': service, 'monthly_cost_usd': quantity * .10,
                          'pricing_status': 'estimated', 'assumptions': assumption, 'components': [part]}
    return {'resource_id': resource_id, 'targets': targets}
