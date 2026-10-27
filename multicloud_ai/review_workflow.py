"""Manager-requested configuration, source Terraform, modeled pricing, target flow."""
import hashlib
import json
import re
from time import monotonic
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict
import pandas as pd
import streamlit as st
from .core.comparison_model import compare_model, DEFAULT_FACTORS, CLOUDS
from .core.equivalence import source_configuration_fields, equivalent_configuration_rows
from .core.agents import redact, run_agent
from .core.terraform import generate
from .core.validation import validate_terraform_text
from .core.terraform_runner import validate_cli
from .phase_ui import client


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def draft_mappings(live, cloud, source_stage=False):
    mappings = equivalent_configuration_rows(live, cloud)
    if source_stage and cloud == "AWS":
        by_id = {r.resource_id.rstrip("/").lower(): r for r in live}
        for mapping in mappings:
            resource = by_id.get(str(mapping.get("Resource ID", "")).rstrip("/").lower())
            if resource is None or resource.canonical_type != "compute_instance":
                continue
            compute = resource.configuration.get("compute", {})
            sku = compute.get("instance_type") or resource.sku
            if re.fullmatch(r"[a-z][a-z0-9-]*\.[a-z0-9]+", str(sku)):
                mapping["Target SKU"] = sku
                mapping["Target Region"] = resource.region
    return mappings


def source_candidate_preserves_identity(candidate, live):
    from .core.terraform import _preserve_azure_source
    return _preserve_azure_source(candidate, live) == candidate


def tf_panel(label, cloud, live, edges, billing, configurations, key, evidence_signature):
    st.header(label)
    native_source = key == "current_cloud_tf" and cloud == "Azure"
    if native_source:
        st.caption("AzureRM reads existing resources using your current-cloud credentials and generates native Terraform configuration with import mappings. Generation checks resource coverage and provider validation. SQL passwords are represented by sensitive variables; plan verification is deferred when their values are unavailable. Nothing is deployed or imported into persistent state.")
    else:
        st.caption("AI uses the billing summary, discovered configurations and dependency evidence. Generated code is a reconstruction/migration draft, not imported Terraform state; review before use. Nothing is deployed.")
    evidence_signature = fingerprint(["native-source-canonical-imports-v12" if native_source else "target-input-coverage-v21" if key == 'confirmed_target_tf' else "source-reconstruction-v10", evidence_signature, cloud])
    saved_key = key + "_result"
    saved = st.session_state.get(saved_key)
    if saved and saved["signature"] != evidence_signature:
        st.session_state.pop(saved_key, None)
        saved = None
    use_ai = False if native_source else st.checkbox("Use configured AI for this Terraform draft", value=True, key=key + "_ai")
    regenerate = st.checkbox("Regenerate Terraform draft", value=False, key=key + "_refresh") if saved else False
    requested = st.button("Generate " + cloud + " Terraform draft", key=key + "_generate")
    if requested and saved and not regenerate and saved.get("use_ai") == use_ai:
        st.info("Using the saved Terraform draft. Select Regenerate Terraform draft to request a new one.")
    if requested and (not saved or regenerate or saved.get("use_ai") != use_ai):
        try:
            with st.spinner("Generating Terraform draft..."):
                if native_source:
                    from .core.source_terraform import reconstruct_azure
                    environment = {name: st.session_state.get(setting, '') for name, setting in {
                        'ARM_TENANT_ID': 'cred_azure_tenant', 'ARM_CLIENT_ID': 'cred_azure_client',
                        'ARM_CLIENT_SECRET': 'cred_azure_secret', 'ARM_SUBSCRIPTION_ID': 'cred_azure_subscription'}.items()}
                    status = ['Reading Azure provider configuration']
                    elapsed_display = st.empty()
                    resource_display = st.empty()
                    started = monotonic()
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(reconstruct_azure, live, environment, lambda stage: status.__setitem__(0, stage))
                        try:
                            while True:
                                snapshot = status[0]
                                if isinstance(snapshot, dict):
                                    elapsed_display.caption(f"{snapshot['stage']} · {snapshot['completed']}/{snapshot['total']} resources read · {int(monotonic() - started)}s elapsed")
                                    active = snapshot.get('active', [])
                                    resource_display.table([{'Resource': item['name'], 'Status': 'Reading configuration',
                                        'Elapsed (s)': int(monotonic() - item['started'])} for item in active]) if active else resource_display.empty()
                                else:
                                    elapsed_display.caption(f'{snapshot} · {int(monotonic() - started)}s elapsed')
                                    resource_display.empty()
                                try:
                                    draft = future.result(timeout=1)
                                    break
                                except FutureTimeout:
                                    if future.done():
                                        raise
                        finally:
                            elapsed_display.empty()
                            resource_display.empty()
                    origin = ('Source configuration with permission-limited templates; manual values and plan verification pending'
                              if '# PERMISSION FALLBACK:' in draft else
                              'AzureRM-generated source configuration; provider validation passed; SQL plan verification pending'
                              if '# SOURCE PLAN PENDING:' in draft else
                              'AzureRM-generated source configuration; complete import coverage and no-change plan verified')
                else:
                    mappings = draft_mappings(live, cloud, source_stage=(key == "current_cloud_tf"))
                    draft = generate(live, edges, cloud, target_configurations=mappings)
                    origin = "Deterministic draft"
                ai_notice = ""
                if use_ai:
                    try:
                        ai = client()
                        evidence = {"purpose": {"cloud": cloud, "stage": label, "requirements": "Return the complete Terraform draft in the terraform field, including when no corrections are needed. Preserve all discovered resources or explicit review markers. Do not invent source configuration or copy credentials."},
                                    "billing": billing, "configurations": configurations,
                                    "dependencies": [asdict(e) for e in edges], "draft": {"terraform": draft}}
                        elapsed_display = st.empty()
                        ai_started = monotonic()
                        with ThreadPoolExecutor(max_workers=1) as builder_pool:
                            future = builder_pool.submit(run_agent, "Builder", ai, redact(evidence), max_turns=3, inline_evidence=True)
                            try:
                                while True:
                                    elapsed_display.caption(f"Generating AI Terraform draft · {int(monotonic() - ai_started)}s elapsed")
                                    try:
                                        report = future.result(timeout=1)
                                        break
                                    except FutureTimeout:
                                        if future.done():
                                            raise
                            finally:
                                elapsed_display.empty()
                        candidate = report["report"].get("terraform", "").strip()
                        candidate = re.sub(r"^```(?:hcl|terraform|tf)?\s*|\s*```$", "", candidate).strip()
                        if candidate and str(cloud).upper() == 'AWS':
                            from .core.terraform import normalize_aws_security_group_names
                            candidate = normalize_aws_security_group_names(candidate)
                        candidate_validation = validate_terraform_text(candidate, cloud).to_dict() if candidate else None
                        if not candidate:
                            ai_notice = "AI returned no Terraform code. The deterministic draft is retained below; it has not been AI-validated. You can continue to pricing or retry AI generation."
                        elif not candidate_validation.get("valid"):
                            diagnostics = str(redact('; '.join(candidate_validation.get('errors', []))))
                            ai_notice = "AI output rejected: " + diagnostics + ". Using the deterministic draft, which undergoes Terraform provider validation."
                        elif key == "current_cloud_tf" and cloud == "Azure" and not source_candidate_preserves_identity(candidate, live):
                            ai_notice = "AI draft changed source resource identity, region or type. The source-preserving deterministic draft is retained."
                        else:
                            draft = candidate
                            origin = "AI-generated draft"
                    except Exception as exc:
                        ai_notice = "AI generation unavailable; deterministic draft retained. " + str(redact(str(exc)))
                if key == 'confirmed_target_tf':
                    from .core.target_terraform import complete_target
                    draft = complete_target(draft, live, cloud, edges,
                                            st.session_state.get('current_cloud_tf_result', {}).get('text', ''))
                if str(cloud).upper() == 'AWS':
                    from .core.terraform import normalize_aws_security_group_names
                    draft = normalize_aws_security_group_names(draft)
                validation = validate_terraform_text(draft, cloud).to_dict()
                candidate_saved = {"signature": evidence_signature, "text": draft, "validation": validation, "origin": origin, "ai_notice": ai_notice, "use_ai": use_ai}
                if not native_source:
                    st.caption('Checking Terraform syntax and provider schema…')
                    check = validate_cli(draft, cloud)
                    if check.get('status') == 'failed':
                        diagnostics = '; '.join(str(item.get('summary', '')) + ': ' + str(item.get('detail', ''))
                                                if isinstance(item, dict) else str(item) for item in check.get('diagnostics', []))
                        raise RuntimeError('Generated Terraform failed provider validation. ' + str(redact(diagnostics)))
                    candidate_saved['cli'] = check
                    if check.get('valid') and check.get('formatted_terraform'):
                        candidate_saved['text'] = check['formatted_terraform']
                saved = candidate_saved
                st.session_state[saved_key] = saved
        except Exception as exc:
            st.error("Terraform generation failed: " + str(redact(str(exc))))
    if saved:
        if saved.get("ai_notice"):
            st.warning(saved["ai_notice"])
        st.caption(saved["origin"] + "; static validation: " + ("PASS" if saved["validation"].get("valid") else "FAIL"))
        for message in saved["validation"].get("errors", []):
            st.error(message)
        for message in saved["validation"].get("warnings", []):
            st.warning(message)
        blocks = len(re.findall(r'^resource "', saved["text"], re.M))
        reviews = saved["text"].count("# REVIEW REQUIRED:")
        if native_source:
            if '# SYSTEM RESOURCE:' in saved['text']:
                st.caption('SQL master is retained as an existing system database ID; it is not recreated as an application database.')
            if '# PERMISSION FALLBACK:' in saved['text']:
                st.caption(f'Source coverage: {blocks} resource blocks. Resources marked PERMISSION FALLBACK require the listed values and configuration checks. Plan verification is pending.')
            elif '# SOURCE PLAN PENDING:' in saved['text']:
                st.caption(f'Source coverage: {blocks} native Terraform resource blocks. Provider validation passed. SQL plan verification is pending until the sensitive password variables are supplied privately.')
            else:
                st.caption(f'Source coverage: {blocks} native Terraform resource blocks. Provider validation and the source import plan passed without infrastructure changes.')
        else:
            st.caption(f"Draft coverage: {blocks} Terraform resource blocks; {reviews} review markers. Static validation does not establish deployment readiness.")
        st.code(saved["text"], language="hcl")
        st.download_button("Download " + cloud + " Terraform draft", saved["text"], key + ".tf", key=key + "_download")
        if key == 'confirmed_target_tf':
            from .core.target_terraform import required_inputs
            inputs = sorted(required_inputs(saved['text']))
            if inputs:
                st.caption('Required target inputs: ' + ', '.join(inputs) + '. Replace every null in the input template with your configuration; keep secrets private.')
                st.download_button('Download required target input template',
                                   json.dumps(dict.fromkeys(inputs), indent=2),
                                   'target.required.tfvars.json', key=key + '_inputs_download')
        if st.button("Validate with Terraform CLI", key=key + "_validate"):
            saved["cli"] = validate_cli(saved["text"], cloud)
        if saved.get("cli"):
            st.json(saved["cli"], expanded=False)
    return saved


def configuration_table_html(configurations):
    """Escaped, wrapping cells keep full configuration visible without copying."""
    rows = []
    for r in configurations:
        fields = r.get("Configuration") or {}
        details = "; ".join(f"{name.replace('_', ' ')}: {json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}"
                            for name, value in fields.items()) or "Configuration not exposed by discovery"
        rows.append({"Resource": r.get("Resource", ""), "Service": r.get("Service", ""),
                     "Configuration": "Region: " + str(r.get("Region", "")) + "; " + details})
    table = pd.DataFrame(rows, columns=["Resource", "Service", "Configuration"]).to_html(index=False, escape=True)
    return ('<style>.current-config-table table{width:100%;table-layout:fixed;border-collapse:collapse;}'
            '.current-config-table th,.current-config-table td{text-align:left;vertical-align:top;'
            'white-space:normal;overflow-wrap:anywhere;padding:10px;border:1px solid #8884;}'
            '.current-config-table th:nth-child(1){width:24%;}'
            '.current-config-table th:nth-child(2){width:22%;}'
            '.current-config-table th:nth-child(3){width:54%;}</style>'
            '<div class="current-config-table">' + table + '</div>')


def render_workflow(source, billing, live, edges, period):
    st.header("Current resource configurations")
    configurations = redact([{"Resource": r.name, "Resource ID": r.resource_id, "Service": r.service or r.raw_type,
                              "Region": r.region, "Raw type": r.raw_type, "Configuration": source_configuration_fields(r)} for r in live])
    st.html(configuration_table_html(configurations))
    billing_evidence = [{"Resource ID": r.resource_id, "Cost USD": r.cost, "Usage": r.usage_quantity,
                         "Unit": r.usage_unit, "Service": r.service} for r in billing]
    sig = fingerprint([source, configurations, billing_evidence, [asdict(e) for e in edges]])
    draft = tf_panel("Current cloud Terraform", source, live, edges, billing_evidence, configurations, "current_cloud_tf", sig)
    if not draft:
        st.info("Generate the current-cloud Terraform draft to continue to pricing comparison.")
        return
    targets = [c for c in CLOUDS if c != source]
    st.header(f"Pricing Comparison \u2014 {source} \u2192 {' & '.join(targets)}")
    st.caption("Resource-wise estimated cost comparison based on the uploaded billing. This scenario model requires no target-cloud credentials.")
    method = st.radio("Pricing method", ["AI resource estimates", "Manual factor scenario"], key="pricing_method")
    if method == "AI resource estimates":
        from .core.ai_comparison import estimate_comparison
        monthly = st.checkbox("Project billing period to a 730-hour month", value=bool(period.get("days")), key="ai_monthly_" + source)
        usage_overrides = {}
        price_sig = fingerprint(["aws-consumed-meter-units-v25" if source == "AWS" else "registry-storage-period-v26", sig, monthly, period])
        stored = st.session_state.get("ai_pricing_comparison", {})
        refresh = st.checkbox("Request new AI estimates", value=False, key="refresh_ai_pricing")
        if st.button("Generate AI pricing comparison", key="generate_ai_pricing"):
            if stored.get("signature") == price_sig and not refresh:
                st.info("Using the saved estimates for this assessment. Select Request new AI estimates to recalculate.")
            else:
                cache_record = st.session_state.get("ai_pricing_batch_cache", {})
                if cache_record.get("signature") != price_sig or refresh:
                    cache_record = {"signature": price_sig, "batches": {}}
                    st.session_state.ai_pricing_batch_cache = cache_record
                try:
                    with st.spinner("AI is estimating both target clouds in resource batches..."):
                        meter = st.progress(0, text="Starting pricing batches...")
                        pricing_detail = st.empty()
                        pricing_started = monotonic()
                        def pricing_progress(done, total):
                            elapsed = int(monotonic() - pricing_started)
                            meter.progress(done / total, text=f"Pricing batches completed: {done}/{total} · {elapsed}s elapsed · waiting for AI responses" if done < total else f"Pricing batches completed: {done}/{total} · {elapsed}s elapsed")
                        model = estimate_comparison(client(), billing, source, period.get("days") if monthly else None,
                                                    configurations, [asdict(e) for e in edges], progress=pricing_progress,
                                                    estimate_cache=cache_record["batches"], usage_overrides=usage_overrides,
                                                    status=pricing_detail.caption)
                        meter.empty()
                        pricing_detail.empty()
                        st.session_state.ai_pricing_comparison = {"signature": price_sig, "model": model}
                except Exception as exc:
                    if 'meter' in locals():
                        meter.empty()
                    if 'pricing_detail' in locals():
                        pricing_detail.empty()
                    st.error("AI pricing failed: " + str(redact(str(exc))))
                    if cache_record["batches"]:
                        saved_count = sum(len(key) == 1 for key in cache_record["batches"])
                        st.info(f"Saved estimates for {saved_count} resources. Click Generate AI pricing comparison again with Request new AI estimates unchecked to resume.")
        stored = st.session_state.get("ai_pricing_comparison", {})
        if stored.get("signature") != price_sig:
            st.info("Generate the AI pricing comparison to see estimates and a recommendation. Target-cloud credentials are not required.")
            return
        model = stored["model"]
        st.caption("AI estimates use per-resource configurations and disclosed assumptions, not fixed discount factors. These are planning estimates, not verified provider quotes. Totals and the lowest-cost recommendation are calculated by the application.")
    else:
        factors = {source: 1.0}
        for target in targets:
            factors[target] = DEFAULT_FACTORS[target] / DEFAULT_FACTORS[source]
        monthly = st.checkbox("Project billing period to a 730-hour month", value=bool(period.get("days")), key="model_monthly_" + source)
        model = compare_model(billing, source, factors, period.get("days") if monthly else None)
    scope = "monthly projection" if model["monthly"] else "uploaded billing period"
    st.caption(f"Period basis: {scope}. Live-only resources without billing are outside this comparison.")
    if model.get("excluded_resources"):
        st.caption(f"Matching comparison scope: {model['comparable_resources']}/{len(model['rows'])} resources. Source cost for the full billing scope: USD {model['observed_source_total']:,.2f}. Blank costs require review.")
    for col, cloud in zip(st.columns(3), [source] + targets):
        label = " Current Total" if cloud == source else (" Unvalidated Estimate" if not model.get("recommendation_ready", True) else " Estimated Total")
        col.metric(cloud + label, f"${model['totals'][cloud]:,.2f}")
    winner = model["recommended"]
    if not model.get("recommendation_ready", True):
        pct = model["savings"] / model["totals"][source] * 100 if model["totals"][source] > 0 else 0
        st.info(f"Provisional recommendation under the current assumptions: {winner} — USD {model['totals'][winner]:,.2f}. Estimated difference vs {source}: USD {model['savings']:,.2f} ({pct:.2f}%). Usage, rates and service equivalence still require review.")
    elif winner == source:
        st.success(f"Model recommendation: stay with {source}; it has the lowest estimated cost (or ties for lowest).")
    else:
        pct = model["savings"] / model["totals"][source] * 100 if model["totals"][source] > 0 else 0
        st.success(f"Recommended lower-cost target under these assumptions: {winner} \u2014 USD {model['totals'][winner]:,.2f}. Estimated difference: USD {model['savings']:,.2f} ({pct:.2f}%).")
    st.subheader("Resource-wise Cost Comparison")
    st.caption("Equivalent services are proposed mappings. The detailed download includes target quantities, unit rates, calculation components and assumptions requiring review.")
    money_cols = [c + " Cost" for c in CLOUDS] + ["Lowest Cost"]
    display_rows = []
    for row in model["rows"]:
        display = {key: row.get(key) for key in
                   ["Resource", "Type", "Azure Cost", "AWS Cost", "GCP Cost", "Lowest Cost", "Recommended Cloud"]}
        for target in targets:
            service = row.get(target + " Service") or "Not specified"
            display[target + " Equivalent Service"] = "Equivalent service pending review" if "planning allowance" in service.lower() else service
            display[target + " Estimate Basis"] = row.get(target + " Estimate Basis", "AI estimate requires review" if method == "AI resource estimates" else "Manual factor scenario")
        display["Lowest Estimated Cost Cloud"] = row.get("Lowest Estimated Cost Cloud", display.pop("Recommended Cloud", ""))
        display.pop("Recommended Cloud", None)
        display_rows.append(display)
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, use_container_width=True,
                 column_config={k: st.column_config.NumberColumn(format="$%.2f") for k in money_cols})
    st.subheader("Overall Cloud Cost Comparison")
    st.dataframe(pd.DataFrame([{"Cloud": c, "Estimated Cost (USD)": v, "Difference vs " + source: model["totals"][source] - v}
                              for c, v in model["totals"].items()]), hide_index=True, use_container_width=True)
    st.caption("Target values use AI assumptions or the selected manual model, not live provider prices. Duplicate resource billing rows are aggregated before calculation. A lower estimated cost is not guaranteed migration savings.")
    if st.button("Generate AI explanation of recommendation", key="model_ai_explanation"):
        try:
            st.session_state.model_explanation = {"signature": fingerprint(model), "report": run_agent("FinOps", client(), {"scenario_model": model}, max_turns=8)}
        except Exception as exc:
            st.error(str(redact(str(exc))))
    explanation = st.session_state.get("model_explanation", {})
    if explanation.get("signature") == fingerprint(model):
        st.write(explanation["report"]["report"]["summary"].replace("$", "USD "))
    st.download_button("Download pricing comparison", pd.DataFrame(model["rows"]).to_csv(index=False), "pricing_comparison.csv", key="model_download")
    st.header("Target Cloud Decision")
    decision_sig = fingerprint([sig, model, draft["text"]])
    if st.button("Accept recommendation: " + winner, key="accept_model_target"):
        st.session_state.model_decision = {"signature": decision_sig, "cloud": winner}
    if st.session_state.get("model_decision") != {"signature": decision_sig, "cloud": winner}:
        st.info("Accept the recommendation to continue. Changing the assessment or model requires a new confirmation.")
        return
    if winner == source:
        st.success("Current cloud retained. No target migration Terraform is required; the source draft is available above.")
        return
    st.success("Confirmed migration target: " + winner)
    target_live = live
    if winner == "AWS":
        from .core.placement import place_resources
        region = st.text_input("AWS deployment region", value="us-east-1", key="model_aws_deployment_region")
        try:
            target_live = place_resources(live, region, True)
        except ValueError as exc:
            st.error(str(exc))
            return
        decision_sig = fingerprint([decision_sig, region])
        st.caption("Deployment region affects the Terraform draft. Model cost factors are regional assumptions, not regional catalog quotes.")
    target_draft = tf_panel("Target cloud Terraform", winner, target_live, edges, billing_evidence, configurations, "confirmed_target_tf", decision_sig)
    if target_draft:
        from .core.target_terraform import coverage_rows
        st.subheader('Source and target Terraform resource coverage')
        st.caption('Matched by source resource ID. Green: generated with no missing inputs detected. Amber: enter variables or check the proposed mapping. Red: no safe target mapping. One source resource can require several target blocks; block counts do not establish equivalence or deployment readiness.')
        rows = coverage_rows(target_live, draft['text'], target_draft['text'])
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        covered = sum(not row['Status'].startswith('🔴') for row in rows)
        st.caption(f'{covered}/{len(rows)} source resources have mapped target Terraform blocks.')
        st.download_button('Download Terraform resource coverage', pd.DataFrame(rows).to_csv(index=False),
                           'terraform_resource_coverage.csv', key='terraform_coverage_download')
