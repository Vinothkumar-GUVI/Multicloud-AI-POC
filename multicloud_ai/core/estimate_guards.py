"""Validate workload equivalence before accepting AI price arithmetic."""
import re


def validate_cost_outlier(source_cost, target_cost, resource_id, cloud):
    """Block suspicious AI totals for correction, never fabricate a capped price.

    The absolute floor handles free/zero-cost source services. This is a
    plausibility gate, not a claim that providers cannot have higher prices.
    """
    limit = max(100.0, float(source_cost) * 10.0)
    if target_cost > limit:
        raise ValueError(
            f'Target cost outlier: {cloud} resource {resource_id} calculated USD {target_cost:.2f} '
            f'vs source USD {source_cost:.2f}, exceeding the plausibility threshold USD {limit:.2f}. '
            'Recheck per-million/per-thousand request rates, measured usage, runtime, currency and service tier. '
            'Do not invent usage to match a source price or cap the total. Return corrected quantity x rate '
            'components; if the higher price is genuine it requires independent pricing review.')


def workload_contract(resource, configuration):
    cfg = resource.configuration or {}
    components = cfg.get('billing_components', [])
    raw = str(resource.raw_type or '').lower()
    cosmos = 'microsoft.documentdb/databaseaccounts' in raw or '/microsoft.documentdb/databaseaccounts/' in resource.resource_id.lower()
    descriptions = ' '.join(str(c.get('meter', {})) for c in components).lower()
    # Only explicit engine/kind fields establish the source API. Resource names
    # such as "mongo-test" are not evidence of the database engine.
    def engine_values(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {'engine', 'kind', 'api', 'database_api'} and isinstance(child, str):
                    yield child.lower()
                else:
                    yield from engine_values(child)
        elif isinstance(value, list):
            for child in value:
                yield from engine_values(child)
    engines = list(engine_values(cfg)) + list(engine_values(configuration))
    mongo = any('mongo' in engine for engine in engines)
    contract = {'cosmos_account': cosmos,
                'mongo_api': mongo,
                'serverless_source': bool(re.search(r'\bserverless\b', descriptions))}
    if cosmos or mongo:
        contract['target_service_constraints'] = {
            'prohibited': ['Google Cloud Bigtable'],
            'instructions': 'Preserve the discovered database API; do not turn Cosmos request units into target operations. Disclose target minimum tier charges and use explicit quantity x unit-rate components.'}
    if mongo:
        contract['target_service_constraints'].update({
            'GCP': 'MongoDB Atlas on GCP; use a stated deployment tier, not Bigtable or Firestore.',
            'AWS': 'MongoDB-compatible service: MongoDB Atlas on AWS or Amazon DocumentDB, with compatibility and minimum-tier assumptions.'})
    return contract


def validate_service_mapping(contract, detail, cloud):
    service = detail['service'].lower()
    if contract.get('cosmos_account') and 'bigtable' in service:
        raise ValueError(
            'Incompatible target service: Cosmos DB account mapped to Bigtable. '
            'Do not add an always-on Bigtable node for Cosmos serverless requests. '
            'Use the discovered database API and a compatible target, with a disclosed deployment tier. '
            'For MongoDB use MongoDB Atlas on GCP; supply published tier pricing and assumptions. '
            'Do not convert request units directly into target read/write operations.')
    if contract.get('mongo_api') and any(name in service for name in ('dynamodb', 'firestore', 'bigtable')):
        raise ValueError(
            'Incompatible target service: MongoDB API workload requires a MongoDB-compatible target '
            '(for example MongoDB Atlas or Amazon DocumentDB), not a key-value or wide-column database. '
            'Do not price an application rewrite as an equivalent database migration.')
    for part in detail.get('components', []):
        if not isinstance(part, dict):
            continue
        unit = str(part.get('unit', '')).lower()
        basis = str(part.get('rate_basis', '')).lower()
        if contract.get('resource_type') == 'container_registry' and re.search(r'\b(?:gb|gib|tb|tib)[ -]?(?:month|hour)', unit):
            index = part.get('meter_index')
            meters = contract.get('meters', [])
            if type(index) is int and 0 <= index < len(meters) and re.search(r'\bregistry unit\b', str(meters[index].get('name', '')), re.I):
                raise ValueError('Incompatible target usage: registry tier-days cannot be used as stored image bytes. Supply measured image storage or an explicitly disclosed storage allowance without a tier-day meter_index.')
        if 'hour' in unit and re.search(r'\bper\s+(?:gb|gib|tb|tib)[ -]?month\b', basis):
            raise ValueError('Incompatible target usage: hourly quantity paired with a monthly storage rate. Express storage in GB-month or GiB-month, and compute runtime in hours with an hourly rate.')
