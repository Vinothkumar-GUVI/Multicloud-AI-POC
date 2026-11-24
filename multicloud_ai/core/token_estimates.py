"""Explicit planning alternatives for supported model token workloads."""
import re


def mini_token_estimate(resource_id, contract):
    meters = contract.get("meters", [])
    if contract.get("resource_type") != "generative_ai" or not meters:
        return None
    directions = []
    model_classes = set()
    for meter in meters:
        name = str(meter.get("name", "")).lower()
        mini = bool(re.search(r"gpt\s*4(?:[. ]1|o)?\s*mini", name))
        standard = bool(re.search(r"\bgpt\s*4o\b", name)) and not mini
        if not (mini or standard) or meter.get("unit") != "tokens":
            return None
        if any(word in name for word in ('batch', 'audio', 'image', 'provisioned', 'realtime')):
            return None
        model_classes.add('mini' if mini else 'standard')
        direction = "input" if re.search(r"\binp(?:ut)?\b", name) else "output" if re.search(r"\boutp(?:ut)?\b", name) else None
        if not direction:
            return None
        directions.append(direction)
    if len(model_classes) != 1:
        return None
    standard = model_classes == {'standard'}
    profiles = [
        ('AWS', 'Amazon Bedrock - Amazon Nova Pro', 'amazon.nova-pro-v1:0', {'input': .80, 'output': 3.20},
         'https://aws.amazon.com/blogs/machine-learning/prompting-for-the-best-price-performance/', 'us-east-1 planning reference'),
        ('GCP', 'Vertex AI - Gemini 2.5 Flash', 'gemini-2.5-flash', {'input': .30, 'output': 2.50},
         'https://cloud.google.com/vertex-ai/generative-ai/pricing', 'standard text-token pricing reference'),
    ] if standard else [
        ('AWS', 'Amazon Bedrock - Amazon Nova Lite', 'amazon.nova-lite-v1:0', {'input': .06, 'output': .24},
         'https://aws.amazon.com/blogs/migration-and-modernization/migrate-your-ai-workloads-to-amazon-bedrock-with-aws-transform/', 'us-east-1 planning reference'),
        ('GCP', 'Vertex AI - Gemini 2.5 Flash-Lite', 'gemini-2.5-flash-lite', {'input': .10, 'output': .40},
         'https://cloud.google.com/vertex-ai/generative-ai/pricing', 'standard pricing reference'),
    ]
    targets = {}
    for cloud, service, model, rates, source, region in profiles:
        parts = [{"quantity": meter["quantity"], "unit": "tokens", "rate_unit": "tokens",
                  "unit_price_usd": rates[direction] / 1000000, "meter_index": index,
                  "description": direction + " tokens", "rate_basis": f"USD {rates[direction]} per million {direction} tokens, standard on-demand pricing",
                  "rate_source": source, "rate_checked": "2026-11-20" if standard else "2026-10-06", "region": region}
                 for index, (meter, direction) in enumerate(zip(meters, directions))]
        targets[cloud] = {"monthly_cost_usd": sum(p["quantity"] * p["unit_price_usd"] for p in parts),
            "service": service, "model_id": model, "inference_mode": "standard on-demand",
            "assumptions": ("Proposed general-purpose model alternative, not identical to GPT-4o. " if standard else "Proposed lightweight model alternative, not identical to GPT-4.1 mini/GPT-4o mini. ") + "Same source token quantities used for planning; target tokenization, capabilities and regional availability require review. Numeric Azure meter labels are interpreted as pricing metadata; inferred thousand-token source units are disclosed in the components. No provisioned capacity, grounding, caching or ancillary services assumed.",
            "components": parts}
        if any('cache' in str(m.get('name', '')).lower() for m in meters):
            targets[cloud]['assumptions'] += ' Azure cached input tokens are priced as ordinary target input tokens; no matching target cache reuse or cache discount is assumed.'
    return {"resource_id": resource_id, "targets": targets}
