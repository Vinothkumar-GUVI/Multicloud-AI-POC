"""AI resource estimates with locally checked coverage, arithmetic and recommendation."""
import math
import re
from copy import deepcopy
from .agents import run_agent
from .comparison_model import CLOUDS, compare_model


def apply_estimates(baseline, estimates):
    source = baseline["source"]
    targets = [c for c in CLOUDS if c != source]
    contracts = baseline.get("usage_contracts", {})
    by_id = {}
    expected = {row["Resource ID"] for row in baseline["rows"]}
    if not isinstance(estimates, list):
        raise ValueError("AI pricing report has no estimates array")
    for entry in deepcopy(estimates):
        rid = str(entry.get("resource_id", "")).strip().rstrip("/").lower()
        if rid not in expected or rid in by_id:
            raise ValueError("AI pricing returned an unknown or duplicate resource ID: " + rid + ". Return exactly one estimate for each requested ID, and no other IDs.")
        if set(entry.get("targets", {})) != set(targets):
            raise ValueError("AI pricing must include both target clouds")
        entry["targets"] = {cloud: deepcopy(detail) for cloud, detail in entry["targets"].items()}
        for cloud, detail in entry["targets"].items():
            value = detail.get("monthly_cost_usd")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("AI pricing contains an invalid cost")
            if not isinstance(detail.get("assumptions"), str) or not detail["assumptions"].strip():
                raise ValueError("AI pricing must disclose assumptions")
            if not isinstance(detail.get("service"), str) or not detail["service"].strip():
                raise ValueError("AI pricing must identify a target service")
            if "planning allowance" in detail["service"].lower():
                raise ValueError("Source-cost planning allowance is not a target estimate; provide target quantity x unit-rate components for every target")
        if baseline.get("require_components"):
            contract = contracts.get(rid, {})
            for cloud, detail in entry["targets"].items():
                parts = detail.get("components")
                if not isinstance(parts, list) or not parts:
                    raise ValueError(f"AI pricing must provide quantity x unit-rate components for every target; missing components for {cloud} resource {rid}")
                if contract.get("enforce_meter_units") and any(m.get("name") for m in contract.get("meters", [])) and not contract.get("logical_sql"):
                    for component in parts:
                        index = component.get("meter_index") if isinstance(component, dict) else None
                        if isinstance(component, dict) and not (type(index) is int and 0 <= index < len(contract["meters"])):
                            component["usage_review"] = "Source-meter reference unavailable; target quantity is an AI assumption requiring review"
                calculated = 0.0
                hourly_parts = []
                for part in parts:
                    if not isinstance(part, dict):
                        raise ValueError("AI pricing component must be an object")
                    if source == "AWS" and len(contract.get("meters", [])) == 1:
                        part["meter_index"] = 0
                    q, rate = part.get("quantity"), part.get("unit_price_usd")
                    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in [q, rate]):
                        raise ValueError("AI pricing component has invalid quantity or rate")
                    if not isinstance(part.get("unit"), str) or not part["unit"].strip():
                        raise ValueError("AI pricing component is missing its quantity unit; supply an explicit unit")
                    if baseline.get("require_canonical_target_units"):
                        for field in ("unit", "rate_unit"):
                            unit = str(part.get(field, "")).strip()
                            if not unit or (re.match(r"^\d", unit) and unit.lower() not in {"1/month", "1 /month"}):
                                raise ValueError(
                                    "Ambiguous packed target pricing unit: use GB-month, TB-month, Hours, requests, "
                                    "operations or tokens with an explicit per-unit target rate. "
                                    "Do not copy Azure pricing-unit denominators into target rates."
                                )
                    for field, placeholder in (("description", "Component description not supplied"),
                                               ("rate_basis", "Rate basis not supplied; unverified AI assumption")):
                        if not isinstance(part.get(field), str) or not part[field].strip():
                            part.setdefault("missing_metadata", []).append(field)
                            part[field] = placeholder
                    meters = contract.get("meters", [])
                    index = part.get("meter_index")
                    if meters and type(index) is int and 0 <= index < len(meters) and not (contract.get("private_zone_only") and part.get("fixed_zone_fee")):
                        from .pricing_audit import unit_key
                        meter = meters[index]
                        if meter.get("unit_assumption"):
                            part["source_usage_interpretation"] = meter["unit_assumption"]
                        packed_source = bool(re.match(r"^\d", str(meter["unit"]).strip()))
                        # AI is not allowed to replace authoritative quantities in identical units.
                        if packed_source:
                            # Export price-unit labels do not establish consumed
                            # packs. Never turn them into a quantity multiplier.
                            part["usage_review"] = (
                                f"Source export unit {meter['unit']} requires meter/schema validation; "
                                "AI quantity retained without automatic pack multiplication"
                            )
                            part["source_usage"] = {"quantity": meter["quantity"], "unit": meter["unit"]}
                        elif unit_key(part["unit"]) == unit_key(meter["unit"]):
                            part.setdefault("ai_reported_quantity", q)
                            q = meter["quantity"]
                            part["quantity"] = q
                        elif contract.get("resource_type") != "nosql_database":
                            from .pricing_units import convert
                            converted = convert(meter["quantity"], meter["unit"], part["unit"], allow_data=source == "AWS")
                            if converted is None:
                                part["usage_review"] = f"Unvalidated conversion from {meter['unit']} to {part['unit']}; AI quantity retained as an assumption"
                            else:
                                part.setdefault("ai_reported_quantity", q)
                                q = converted
                                part["quantity"] = q
                                part["usage_conversion"] = {"source_quantity": meter["quantity"], "source_unit": meter["unit"], "target_unit": part["unit"]}
                        else:
                            part["usage_review"] = "Database request-unit to operation conversion is unvalidated; AI quantity retained as an assumption"
                    # A textual quote in the same declared rate unit must agree with the numeric rate.
                    quote_text = part["rate_basis"] + " " + part["description"]
                    if source == "AWS":
                        quote_text = re.sub(r"\bper\s+(million|thousand)\b", r"per 1 \1", quote_text, flags=re.I)
                    canonical_quote = re.search(
                        r"\$([0-9]+(?:\.[0-9]+)?)\s*(?:per|/)\s*([0-9,]+)\s*(million\s+|thousand\s+)?(tokens?|requests?|operations?|ops)\b",
                        quote_text, re.I)
                    if canonical_quote and part["unit"].lower() in {"token", "tokens", "request", "requests", "operation", "operations", "ops"} and str(part.get("rate_unit", "")).lower() == part["unit"].lower():
                        family = "tokens" if part["unit"].lower().startswith("token") else "requests"
                        quote_family = "tokens" if canonical_quote[4].lower().startswith("token") else "requests"
                        denominator = float(canonical_quote[2].replace(",", "")) * ({"million": 1000000, "thousand": 1000}.get((canonical_quote[3] or "").strip().lower(), 1))
                        if family == quote_family and denominator > 0:
                            expected_rate = float(canonical_quote[1]) / denominator
                            if math.isclose(rate, float(canonical_quote[1]), rel_tol=1e-6, abs_tol=1e-12):
                                part["original_unit_price_usd"] = rate
                                rate = expected_rate
                                part["unit_price_usd"] = rate
                                part["rate_correction"] = "Normalized the declared quote to the single-unit rate"
                            elif not math.isclose(rate, expected_rate, rel_tol=1e-6, abs_tol=1e-12):
                                raise ValueError("Contradictory pricing component: numeric per-unit rate disagrees with quoted price denominator")
                    quoted = re.search(r"\$([0-9]+(?:\.[0-9]+)?)\s+per\s+([0-9,]+)\s+(requests?|ops|operations?)", part["rate_basis"], re.I)
                    declared = re.fullmatch(r"([0-9,]+)\s+(requests?|ops|operations?)", str(part.get("rate_unit", "")).strip(), re.I)
                    if quoted and declared and quoted[2].replace(",", "") == declared[1].replace(",", ""):
                        if not math.isclose(rate, float(quoted[1]), rel_tol=1e-6, abs_tol=1e-12):
                            raise ValueError("Contradictory pricing component: numeric rate disagrees with quoted rate basis; return consistent quantity, unit, rate_unit and price")
                    if re.search(r"operations?\s*\(\d+\)", part["unit"], re.I) and declared:
                        raise ValueError("Contradictory pricing component: packed operation quantity must be expressed explicitly in the same unit as the rate")
                    # Convert explicit request-price denominators, not ambiguous source export units.
                    rate_unit = str(part.get("rate_unit", "")).lower().replace(",", "").strip()
                    denominator = re.fullmatch(r"(\d+(?:\.\d+)?)\s+(?:requests?|operations?)", rate_unit)
                    if part["unit"].strip().lower() in {"request", "requests", "operation", "operations"} and denominator:
                        pack = float(denominator[1])
                        if pack <= 0:
                            raise ValueError("Request rate denominator must be positive")
                        part["original_unit_price_usd"] = rate
                        part["original_rate_unit"] = part["rate_unit"]
                        rate = rate / pack
                        part["unit_price_usd"] = rate
                        part["rate_unit"] = part["unit"]
                        part["rate_basis"] += f"; normalized from price per {pack:g} requests/operations"
                    if part.get("rate_unit"):
                        from .pricing_units import convert
                        priced_units = convert(1, part["unit"], part["rate_unit"], allow_data=source == "AWS")
                        if priced_units is not None and priced_units != 1:
                            part.setdefault("original_unit_price_usd", rate)
                            part.setdefault("original_rate_unit", part["rate_unit"])
                            rate *= priced_units
                            part["unit_price_usd"] = rate
                            part["rate_unit"] = part["unit"]
                    calculated += q * rate
                    if part["unit"].strip().lower() in {"hour", "hours", "instance-hour", "instance-hours", "hr", "hrs"}:
                        hourly_parts.append(part)
                if "runtime_hours" in contract:
                    runtime = contract["runtime_hours"]
                    if isinstance(runtime, bool) or not isinstance(runtime, (int, float)) or not math.isfinite(runtime) or runtime < 0:
                        raise ValueError("Invalid billed VM runtime")
                    if len(hourly_parts) != 1:
                        detail["runtime_review"] = (
                            "VM runtime mapping requires review: multiple hourly components may represent "
                            "compute, GPU, licensing or unrelated charges; bundled/non-hourly components "
                            "cannot be normalized automatically. AI quantities retained, not usage-validated."
                        )
                    else:
                        compute = hourly_parts[0]
                        if not math.isclose(compute["quantity"], runtime, rel_tol=1e-5, abs_tol=.001):
                            compute["ai_reported_quantity"] = compute["quantity"]
                            compute["quantity"] = runtime
                            detail["assumptions"] += (
                                f" Runtime correction: compute uses {runtime:g} billed/projected instance-hours; "
                                "this overrides any AI runtime assumption above. Other components are unchanged."
                            )
                    calculated = sum(p["quantity"] * p["unit_price_usd"] for p in parts)
                if not math.isfinite(calculated):
                    raise ValueError("AI pricing component total is not finite")
                detail.setdefault("ai_reported_cost_usd", detail["monthly_cost_usd"])
                detail["monthly_cost_usd"] = calculated
                if contract.get("logical_sql") and any(x in detail["service"].lower() for x in ["rds", "cloud sql", "postgres"]):
                    raise ValueError(
                        f"SQL logical server/security charges cannot be mapped to a database instance: resource {rid}, target {cloud}. "
                        "Estimate the billed security/control-plane workload only using target security services and quantity x rate components. "
                        "Do not provision or price RDS, Cloud SQL or PostgreSQL database instances without discovered database evidence."
                    )
        by_id[rid] = entry["targets"]
    if set(by_id) != expected:
        raise ValueError("AI pricing omitted resources; incomplete totals were not accepted")
    result = deepcopy(baseline)
    totals = {c: 0.0 for c in [source] + targets}
    for row in result["rows"]:
        for cloud, detail in by_id[row["Resource ID"]].items():
            row[cloud + " Cost"] = float(detail["monthly_cost_usd"])
            if "ai_reported_cost_usd" in detail:
                row[cloud + " AI Reported Cost"] = detail["ai_reported_cost_usd"]
            row[cloud + " Service"] = detail["service"]
            row[cloud + " Assumptions"] = detail["assumptions"]
            import json
            row[cloud + " Excluded Components"] = json.dumps(detail.get("excluded_components", []))
            row[cloud + " Runtime Review"] = detail.get("runtime_review", "")
            row[cloud + " Model"] = detail.get("model_id", "")
            row[cloud + " Inference Mode"] = detail.get("inference_mode", "")
            if "components" in detail:
                import json
                row[cloud + " Calculation"] = json.dumps(detail["components"])
        values = {c: row[c + " Cost"] for c in totals}
        winner = min(values, key=lambda c: (round(values[c], 8), c != source))
        row.update({"Lowest Cost": values[winner], "Recommended Cloud": winner,
                    "Estimated Savings": values[source] - values[winner]})
        for c, value in values.items():
            totals[c] += value
            if not math.isfinite(totals[c]):
                raise ValueError("AI pricing aggregate total is not finite")
    winner = min(totals, key=lambda c: (round(totals[c], 8), c != source))
    result.update(totals=totals, recommended=winner, savings=totals[source]-totals[winner], method="AI resource estimates", recommendation_status="Provisional: AI rates and service equivalence require validation")
    result.pop("factors", None)
    return result


def estimate_comparison(client, billing, source, days, configurations, dependencies, progress=None, estimate_cache=None, usage_overrides=None, status=None):
    from .source_usage import automatic_overrides
    usage_overrides = {**automatic_overrides(billing), **(usage_overrides or {})}
    baseline = compare_model(billing, source, {c: 1.0 for c in CLOUDS if c != source}, days)
    targets = [c for c in CLOUDS if c != source]
    configs = {str(c["Resource ID"]).rstrip("/").lower(): c for c in configurations}
    from .pricing import _aggregate_billing
    grouped = {r.resource_id.rstrip("/").lower(): r for r in _aggregate_billing(billing)}
    from .usage import normalize_usage
    scale = (730 / 24) / days if days else 1.0
    contracts = {}
    for rid, r in grouped.items():
        components = r.configuration.get("billing_components", [])
        contract = {"logical_sql": "/microsoft.sql/servers/" in rid and "/databases/" not in rid,
                    "meters": [{"name": c.get("meter", {}).get("name"), "quantity": c.get("quantity", 0) * scale,
                                "unit": c.get("unit"), "raw_unit": c.get("meter", {}).get("raw_unit"), "category": c.get("meter", {}).get("category"),
                                "source_rate": c.get("meter", {}).get("rate"),
                                "source_rate_currency": r.configuration.get("fx_normalization", {}).get("original_currency", r.currency),
                                "source_meter_cost_usd": c.get("source_cost"),
                                "source_model": c.get("meter", {}).get("name")} for c in components]}
        for index, meter in enumerate(contract["meters"]):
            if source == "AWS":
                meter["source_description"] = components[index].get("meter", {}).get("description", "")
            meter["meter_index"] = index
            meter["quantity"], meter["unit"] = normalize_usage(meter["quantity"], meter["unit"])
            from .source_usage import meter_key
            override = (usage_overrides or {}).get(meter_key(r.canonical_type, meter.get("name"), meter["unit"]))
            if override:
                meter["export_quantity"] = meter["quantity"]
                meter["export_unit"] = meter["unit"]
                meter["quantity"] *= override["multiplier"]
                meter["unit"] = override["unit"]
                meter["source_unit_confirmed"] = not bool(override.get("assumption"))
                meter["unit_assumption"] = override.get("assumption", "")
        contract["resource_type"] = r.canonical_type
        contract["enforce_meter_units"] = True
        if r.canonical_type == "compute_instance":
            runtime = []
            for meter in contract["meters"]:
                unit = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*)?hours?", str(meter["unit"]).strip(), re.I)
                if unit and "virtual machines" in str(meter["category"]).lower():
                    runtime.append(meter["quantity"])
            if runtime:
                contract["runtime_hours"] = sum(runtime)
        contracts[rid] = contract
    baseline.update(require_components=True, require_canonical_target_units=True, usage_contracts=contracts)
    estimates = []
    from .dns_estimates import private_zone_estimate
    from .token_estimates import mini_token_estimate
    from .registry_estimates import registry_estimate
    ai_rows = []
    for row in baseline["rows"]:
        fixed = registry_estimate(row["Resource ID"], contracts.get(row["Resource ID"], {}), days is not None)
        if fixed:
            estimates.append(fixed)
            continue
        fixed = private_zone_estimate(row["Resource ID"], contracts.get(row["Resource ID"], {}), days is not None)
        if fixed:
            contracts[row["Resource ID"]]["private_zone_only"] = True
        else:
            fixed = mini_token_estimate(row["Resource ID"], contracts.get(row["Resource ID"], {}))
            if fixed:
                contracts[row["Resource ID"]]["published_token_rates"] = True
        if fixed:
            estimates.append(fixed)
        else:
            ai_rows.append(row)
    cache = estimate_cache if estimate_cache is not None else {}
    from threading import Lock
    status_lock = Lock()
    resource_status = {}
    def estimate_batch(batch, correction=None, correction_attempt=0, format_attempt=0):
        saved_rows = [row for row in batch if (row["Resource ID"],) in cache]
        if saved_rows:
            saved = [entry for row in saved_rows for entry in cache[(row["Resource ID"],)]]
            apply_estimates({**baseline, "rows": saved_rows}, saved)
            missing = [row for row in batch if (row["Resource ID"],) not in cache]
            return saved + (estimate_batch(missing, correction, correction_attempt) if missing else [])
        ids = {row["Resource ID"] for row in batch}
        with status_lock:
            for row in batch:
                resource_status[row["Resource ID"]] = (row["Resource"], "correcting estimate" if correction else "awaiting AI response")
        resources = [{"resource_id": row["Resource ID"], "name": row["Resource"], "type": row["Type"],
                      "source_monthly_usd": row[source + " Cost"], "configuration": configs.get(row["Resource ID"], {}), "usage_contract": contracts.get(row["Resource ID"], {})} for row in batch]
        from copy import copy
        worker_client = copy(client)
        if hasattr(worker_client, 'request'):
            worker_client.request_timeout = None
            worker_client.max_attempts = 1
        session = getattr(client, "session", None)
        if session is not None:
            from .http_session import system_trust_session
            worker_client.session = system_trust_session()
            if getattr(client.transport, "__self__", None) is session:
                worker_client.transport = worker_client.session.post
            if getattr(client.get_transport, "__self__", None) is session:
                worker_client.get_transport = worker_client.session.get
        try:
            report = run_agent("PricingEstimator", worker_client, {
                "scope": {"source": source, "targets": targets, "billing_days": days,
                          "period": "730-hour monthly projection" if days else "uploaded billing period"},
                "resources": resources,
                "target_unit_policy": (
                    "Use explicit target quantity units and rate_unit: GB-month, TB-month, Hours, requests, operations or tokens. "
                    "Express rates per single unit; convert published per-1000/per-million prices to per-request or per-token rates. "
                    "Never use bare numeric units or packed units such as 100 GB/Month. "
                    "Source export pricing-unit labels are not proof that usage_quantity counts packs. "
                    "Use configuration and documented usage semantics, disclose unresolved source conversions, "
                    "and supply the target region and rate source in each component. Do not claim rate verification."
                ),
                "validation_feedback": {"error": correction or "", "instruction": "Every requested resource and target must include a nonempty components array. Each component needs quantity, unit, unit_price_usd, meter_index, rate_unit, description and rate_basis. Estimate target-specific quantities and rates using discovered configuration and source usage. Disclose uncertain quantities, conversions and rates as assumptions; never copy source cost as a target allowance. Logical SQL servers require security/control-plane equivalents, not an invented database instance. A subtotal alone is insufficient; do not invent evidence."},
                "dependencies": [e for e in dependencies if str(e.get("source_id", "")).rstrip("/").lower() in ids]}, max_turns=3)
        except RuntimeError as exc:
            recoverable = any(message in str(exc) for message in (
                "invalid JSON or missing required report fields", "max_output_tokens", "before the read timeout"))
            if not recoverable:
                raise
            if len(batch) == 1:
                if "invalid JSON or missing required report fields" in str(exc) and format_attempt < 1:
                    return estimate_batch(batch, correction="Return one complete JSON object with an estimates array for this resource and both targets. Keep descriptions short and do not add prose.",
                                          correction_attempt=correction_attempt, format_attempt=format_attempt + 1)
                raise
            # Retry smaller independent batches; never accept truncated estimates.
            midpoint = len(batch) // 2
            return estimate_batch(batch[:midpoint], correction) + estimate_batch(batch[midpoint:], correction)
        batch_estimates = report["report"].get("estimates")
        # Preserve individually valid rows even when another row needs correction.
        # The next attempt then requests only the invalid/missing resources.
        if isinstance(batch_estimates, list):
            for row in batch:
                matches = [entry for entry in batch_estimates if isinstance(entry, dict)
                           and str(entry.get("resource_id", "")).strip().rstrip("/").lower() == row["Resource ID"]]
                if len(matches) > 1 and all(entry == matches[0] for entry in matches[1:]):
                    matches = matches[:1]  # Identical duplicates are safe; conflicting prices require correction.
                if len(matches) == 1:
                    try:
                        apply_estimates({**baseline, "rows": [row]}, matches)
                    except ValueError:
                        continue
                    cache[(row["Resource ID"],)] = matches
        try:
            apply_estimates({**baseline, "rows": batch}, batch_estimates)
        except ValueError as exc:
            if "AI pricing omitted resources" in str(exc) and len(batch) > 1:
                # Validation reached the coverage check, so returned entries have
                # valid IDs, target coverage and components. Keep them and recover
                # only absent rows, individually to avoid another partial batch.
                returned_ids = {str(entry["resource_id"]).strip().rstrip("/").lower()
                                for entry in batch_estimates}
                recovered = list(batch_estimates)
                for entry in recovered:
                    cache[(str(entry["resource_id"]).strip().rstrip("/").lower(),)] = [entry]
                for row in batch:
                    if row["Resource ID"] not in returned_ids:
                        recovered.extend(estimate_batch(
                            [row], correction="AI pricing omitted resource " + row["Resource ID"] +
                            "; return this exact resource ID with estimates for both target clouds."
                        ))
                apply_estimates({**baseline, "rows": batch}, recovered)
                return recovered
            recoverable = any(reason in str(exc) for reason in [
                "unknown or duplicate resource ID",
                "missing its quantity unit", "Contradictory pricing component", "Unvalidated usage conversion",
                "quantity x unit-rate components for every target", "SQL logical server/security charges",
                "Ambiguous packed target pricing unit",
                "AI pricing omitted resources",
            ])
            if not recoverable:
                raise
            if correction_attempt < 2:
                return estimate_batch(batch, correction=str(exc), correction_attempt=correction_attempt + 1)
            if len(batch) > 1:
                # Isolate the invalid mapping rather than repeatedly regenerating
                # unrelated resources together with the failing row.
                return [entry for row in batch for entry in estimate_batch([row], correction=str(exc))]
            raise
        for entry in batch_estimates:
            cache[(str(entry["resource_id"]).strip().rstrip("/").lower(),)] = [entry]
        return batch_estimates
    # Begin the likely expensive requests first and distribute work across batches
    # so a complex database/AI resource is not left until the final request.
    def complexity(row):
        contract = contracts.get(row["Resource ID"], {})
        return len(contract.get("meters", [])) * 2 + {
            "generative_ai": 8, "nosql_database": 6, "relational_database": 6,
            "machine_learning": 4, "compute_instance": 3,
        }.get(row["Type"], 0)
    batch_count = (len(ai_rows) + 3) // 4
    batches = [[] for _ in range(batch_count)]
    weights = [0] * batch_count
    for row in sorted(ai_rows, key=complexity, reverse=True):
        index = min((i for i in range(batch_count) if len(batches[i]) < 4),
                    key=lambda i: (weights[i], len(batches[i]), i))
        batches[index].append(row)
        weights[index] += complexity(row) + 1
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    completed = {}
    batch_keys = [tuple(row["Resource ID"] for row in batch) for batch in batches]
    for i, key in enumerate(batch_keys):
        if key in cache:
            apply_estimates({**baseline, "rows": batches[i]}, cache[key])
            completed[i] = cache[key]
    pool = ThreadPoolExecutor(max_workers=3)
    try:
        pending = {pool.submit(estimate_batch, batch): i for i, batch in enumerate(batches) if i not in completed}
        remaining = set(pending)
        while remaining:
            done, remaining = wait(remaining, timeout=1, return_when=FIRST_COMPLETED)
            failure = None
            for future in done:
                try:
                    index = pending[future]
                    completed[index] = future.result()
                    cache[batch_keys[index]] = completed[index]
                except Exception as exc:
                    failure = exc
            if progress:
                progress(len(completed), len(batches))
            if status:
                with status_lock:
                    outstanding = [resource_status.get(row["Resource ID"], (row["Resource"], "queued"))
                        for row in ai_rows if (row["Resource ID"],) not in cache]
                status("; ".join(f"{name}: {stage}" for name, stage in outstanding[:4]) +
                       (f"; +{len(outstanding) - 4} more" if len(outstanding) > 4 else ""))
            if failure is not None:
                raise failure
    finally:
        # Do not block the UI while other HTTP calls finish after a failure.
        # Running requests finish independently; queued requests are cancelled.
        pool.shutdown(wait=False, cancel_futures=True)
    for i in range(len(batches)):
        estimates.extend(completed[i])
    result = apply_estimates(baseline, estimates)
    from .pricing_audit import audit_comparison
    from .pricing_corrections import correct_comparison
    from .pricing_scope import enforce_scope
    return enforce_scope(correct_comparison(audit_comparison(result, contracts), contracts), contracts)
