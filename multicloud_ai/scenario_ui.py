"""Interactive estimates for resources whose target deployment needs a decision."""
import json
import streamlit as st
from .core.catalog_scenarios import SERVICES, catalog_page, calculate, billing_window_hours, scenario_defaults


def render_scenarios(rows, make_provider, sanitize, billing_period=None):
    if not rows:
        return
    with st.expander("Resolve missing AWS prices: choose a target and calculate a scenario"):
        st.write("Choose a target catalog item and enter usage in its stated unit. You can add multiple components per resource. These scenarios are separate from verified comparisons and do not change savings or migration recommendations.")
        by_id = {r["Resource ID"]: r for r in rows if r.get("Resource ID")}
        if not by_id:
            return
        rid = st.selectbox("Source resource", list(by_id), format_func=lambda k: f"{by_id[k].get('Resource', k)} ? {by_id[k].get('Type', '')}", key="scenario_resource")
        recommended, mapped_region = scenario_defaults(by_id[rid])
        if st.session_state.get("scenario_selected_resource") != rid:
            st.session_state.scenario_selected_resource = rid
            st.session_state.scenario_service = recommended or list(SERVICES)[0]
            st.session_state.scenario_region = mapped_region
            st.session_state.scenario_instance = ""
            st.session_state.scenario_filter = ""
        reason = by_id[rid].get("AWS Pricing reason")
        if reason:
            st.info(str(reason))
        service = st.selectbox("AWS target service", list(SERVICES), key="scenario_service")
        region = st.text_input("AWS region (leave blank for global services)", key="scenario_region")
        size = st.text_input("Instance type, if applicable", placeholder="For example: ml.m5.large or t3.small.search", key="scenario_instance")
        query = (SERVICES[service], region.strip(), size.strip())
        state = st.session_state.get("scenario_catalog", {})
        load = st.button("Find live AWS catalog rates", key="scenario_find")
        more = False
        if state.get("query") == query and state.get("token"):
            more = st.button("Load next catalog page", key="scenario_more")
        if load or more:
            try:
                provider = make_provider()
                if not provider.enabled or provider.client is None:
                    raise ValueError(provider.init_error or "AWS credentials unavailable.")
                with st.spinner("Reading AWS catalog rates..."):
                    rates, token = catalog_page(provider.client, *query, token=state.get("token") if more else None)
                old = state.get("rates", []) if more else []
                unique = {r["rate_id"]: r for r in old + rates}
                st.session_state.scenario_catalog = {"query": query, "rates": list(unique.values()), "token": token}
                st.rerun()
            except Exception as exc:
                st.error(sanitize(exc))
        state = st.session_state.get("scenario_catalog", {})
        if state.get("query") == query:
            rates = state.get("rates", [])
            st.caption("Only flat on-demand USD dimensions are offered. Tiered and conditional rates require a separate calculation. Catalog pages are loaded on demand; this list may be incomplete.")
            search = st.text_input("Filter loaded rates by model, instance or description", key="scenario_filter")
            matches = [r for r in rates if search.casefold() in json.dumps(r).casefold()]
            if matches:
                index = st.selectbox("AWS price component", range(len(matches)), format_func=lambda i: f"{matches[i]['instance_type']} | {matches[i]['description']} | ${matches[i]['rate_usd']:g}/{matches[i]['unit']} | {matches[i]['sku']}")
                rate = matches[index]
                st.json({k: rate[k] for k in ("sku", "region", "unit", "rate_usd", "effective_date", "attributes")}, expanded=False)
                window = billing_period or {}
                hours = billing_window_hours(window)
                hourly = rate["unit"].lower() in {"hrs", "hours", "hour", "hr"}
                full_month = st.checkbox("Full-month planning scenario (730 hours for hourly components)", key=f"scenario_month_{rid}")
                use_window = False
                if hourly and hours is not None and not full_month:
                    use_window = st.checkbox(f"Estimate one selected component running continuously for the billing window ({hours} hours)", key="scenario_use_window")
                    st.caption("This is assumed target runtime, not measured source runtime. Other components, replica counts and usage charges remain separate.")
                if full_month and hourly:
                    hours, use_window = 730, True
                with st.form("scenario_usage"):
                    qty = st.number_input(f"Usage quantity ({rate['unit']})", min_value=0.0, value=float(hours) if use_window else 0.0, format="%.6f", disabled=use_window, key=f"scenario_quantity_{rate['rate_id']}_{use_window}_{hours}")
                    period = st.text_input("Usage period", value="Full month (730 hours)" if full_month else f"{window['start']} through {window['end']}" if hours is not None else "", placeholder="For example: 2026-09-01 through 2026-09-10")
                    assumptions = st.text_input("Target configuration and usage assumptions", placeholder="Explain the selected size, deployment and usage quantity")
                    submitted = st.form_submit_button("Calculate and save component scenario")
                if submitted:
                    try:
                        item = calculate(rate, float(hours) if use_window else qty, rid, period, assumptions + ("; assumes one selected component running continuously for the selected period" if use_window else ""))
                        item["Resource"] = by_id[rid].get("Resource", rid)
                        existing = st.session_state.get("aws_component_scenarios", [])
                        existing = [x for x in existing if (x["Resource ID"], x["Rate ID"], x["Period"]) != (rid, item["Rate ID"], item["Period"])]
                        st.session_state.aws_component_scenarios = existing + [item]
                        st.success(f"Saved component scenario: ${item['Scenario cost (USD)']:.6f}. Add other required components to complete your target design.")
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.info("No matching flat rates loaded. Check the region/instance filter, load the next page, or change the description filter.")
        saved = st.session_state.get("aws_component_scenarios", [])
        if saved:
            st.dataframe([{k: v for k, v in x.items() if k != "Resource ID"} for x in saved], hide_index=True, use_container_width=True)
            st.download_button("Download AWS component scenarios", json.dumps(saved, indent=2), "aws_component_scenarios.json", "application/json")
            if st.button("Clear saved scenarios"):
                st.session_state.pop("aws_component_scenarios", None)
                st.rerun()
