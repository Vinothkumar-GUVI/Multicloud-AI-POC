from __future__ import annotations

import hashlib
import json
from collections import Counter
from time import monotonic

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from multicloud_ai.login import require_login
from multicloud_ai.phase_ui import ai_settings, migration_advisory_panel
from multicloud_ai.cloud_adapters.aws import AWSAdapter
from multicloud_ai.cloud_adapters.azure import AzureAdapter, extract_subscription_id
from multicloud_ai.cloud_adapters.gcp import GCPAdapter
from multicloud_ai.core.auth import (
    AWSCredentials,
    AzureCredentials,
    GCPCredentials,
    CredentialBundle,
    sanitize_exception,
    validate_bundle,
)
from multicloud_ai.core.billing import CLOUDS, billing_period, detect, parse, read_table
from multicloud_ai.core.config import load_settings, configure_logging
from multicloud_ai.core.currency import fetch_usd_rate, convert_billing
from multicloud_ai.core.dependencies import build as build_dependencies
from multicloud_ai.core.equivalence import (
    equivalent_configuration_rows,
    pricing_comparison_rows,
    pricing_display_rows,
    client_pricing_rows,
    pricing_target_summary,
    service_equivalent,
)
from multicloud_ai.core.package import build_migration_package
from multicloud_ai.core.phase_artifacts import build_common_ir, build_architecture_artifact
from multicloud_ai.core.planner import create_discovery_plan
from multicloud_ai.core.pricing import (
    AWSPriceProvider,
    AzurePriceProvider,
    GCPPriceProvider,
    compare_billing_to_target,
)
from multicloud_ai.core.strategy import build_migration_plan
from multicloud_ai.core.terraform import generate
from multicloud_ai.core.terraform_runner import validate_cli
from multicloud_ai.core.validation import validate_terraform_text
from multicloud_ai.core.visualization import architecture_graph, graph_html, graph_svg, topology_summary


SETTINGS = load_settings()
LOGGER = configure_logging(SETTINGS)
st.set_page_config(page_title="Multi-Cloud AI", page_icon="☁️", layout="wide")
require_login()

st.title("☁️ Multi-Cloud AI — Migration")
st.caption(
    "Understand the current estate, visualize dependencies, compare both alternative clouds, "
    "generate a source Terraform draft, compare modeled costs, confirm the recommendation, and generate target Terraform."
)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def cached_usd_rate(currency: str):
    return fetch_usd_rate(currency)


def _json(data) -> str:
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def _billing_signature(upload, cloud: str) -> str:
    return f"migration-workbench-v1:{hashlib.sha256(upload.getvalue()).hexdigest()}:{cloud}"


def _credential_bundle() -> CredentialBundle:
    gcp_info = st.session_state.get("cred_gcp_service_account_info") or {}
    bundle = CredentialBundle(
        aws=AWSCredentials(
            access_key_id=str(st.session_state.get("cred_aws_access_key", "") or "").strip(),
            secret_access_key=str(st.session_state.get("cred_aws_secret_key", "") or "").strip(),
            session_token=str(st.session_state.get("cred_aws_session_token", "") or "").strip(),
            region=str(st.session_state.get("cred_aws_region", "") or "").strip(),
        ),
        azure=AzureCredentials(
            tenant_id=str(st.session_state.get("cred_azure_tenant", "") or "").strip(),
            client_id=str(st.session_state.get("cred_azure_client", "") or "").strip(),
            client_secret=str(st.session_state.get("cred_azure_secret", "") or "").strip(),
            subscription_id=str(st.session_state.get("cred_azure_subscription", "") or "").strip(),
        ),
        gcp=GCPCredentials(
            project_id=str(st.session_state.get("cred_gcp_project", "") or "").strip(),
            service_account_info=gcp_info if isinstance(gcp_info, dict) else {},
            billing_api_key=str(st.session_state.get("cred_gcp_billing_api_key", "") or "").strip(),
        ),
    )
    active_source = st.session_state.get("source")
    return CredentialBundle(
        aws=bundle.aws if active_source == "AWS" else AWSCredentials(),
        azure=bundle.azure if active_source == "Azure" else AzureCredentials(),
        gcp=bundle.gcp if active_source == "GCP" else GCPCredentials(),
    )



def _source_scope(source: str, billing, credentials: CredentialBundle) -> str:
    if source == "Azure":
        ids = sorted({extract_subscription_id(r.resource_id) for r in billing if extract_subscription_id(r.resource_id)})
        if credentials.azure.subscription_id:
            ids = [credentials.azure.subscription_id]
        return ", ".join(ids) if ids else "Not detected"
    if source == "GCP":
        project = credentials.gcp.project_id or next((r.group for r in billing if r.group and r.group != "default"), "")
        return project or "Not detected"
    return credentials.aws.region or next((r.region for r in billing if r.region and r.region != "unknown"), "us-east-1")


def _discover(source: str, billing, credentials: CredentialBundle):
    """Create a bounded billing-driven plan internally and execute source discovery."""
    plan = create_discovery_plan(billing, source)
    st.session_state.discovery_plan = plan.to_dict()  # internal audit evidence; intentionally not a UI section
    resource_ids = plan.resource_ids
    if len(resource_ids) > SETTINGS.max_discovery_resources:
        raise RuntimeError(
            f"Discovery scope contains {len(resource_ids):,} exact resources, above the configured safety limit "
            f"of {SETTINGS.max_discovery_resources:,}. Narrow the billing export or raise MULTICLOUD_MAX_DISCOVERY_RESOURCES after capacity review."
        )

    if source == "Azure":
        if not resource_ids:
            raise RuntimeError("Azure discovery needs resource-level ARM IDs in the billing export.")
        subscriptions = sorted({extract_subscription_id(x) for x in resource_ids if extract_subscription_id(x)})
        if credentials.azure.subscription_id:
            subscriptions = [credentials.azure.subscription_id]
        if not subscriptions:
            raise RuntimeError("No Azure subscription GUID was found. Enter Subscription ID under Cloud Access.")
        return AzureAdapter(
            subscriptions,
            tenant_id=credentials.azure.tenant_id or None,
            client_id=credentials.azure.client_id or None,
            client_secret=credentials.azure.client_secret or None,
        ).discover(resource_ids)

    if source == "GCP":
        project = credentials.gcp.project_id or next((r.group for r in billing if r.group and r.group != "default"), "")
        if not project:
            raise RuntimeError("No GCP project ID was found. Enter Project ID under Cloud Access.")
        return GCPAdapter(project, service_account_info=credentials.gcp.service_account_info or None).discover(resource_ids)

    region = credentials.aws.region or next((r.region for r in billing if r.region and r.region != "unknown"), "us-east-1")
    return AWSAdapter(
        region=region,
        access_key_id=credentials.aws.access_key_id or None,
        secret_access_key=credentials.aws.secret_access_key or None,
        session_token=credentials.aws.session_token or None,
    ).discover(resource_ids)


def _provider(target: str, credentials: CredentialBundle):
    if target == "AWS":
        return AWSPriceProvider(
            access_key_id=credentials.aws.access_key_id or None,
            secret_access_key=credentials.aws.secret_access_key or None,
            session_token=credentials.aws.session_token or None,
        )
    if target == "GCP":
        return GCPPriceProvider(
            api_key=credentials.gcp.billing_api_key or None,
            service_account_info=credentials.gcp.service_account_info or None,
        )
    return AzurePriceProvider()


def _clear_after_discovery():
    for key in (
        "monthly_capacity", "aws_component_scenarios", "scenario_catalog", "pricing", "pricing_errors", "pricing_elapsed", "final_target", "migration_advisory",
        "terraform", "validation", "cli_validation", "builder_reports", "equivalent_rows", "client_terraform_approval",
    ):
        st.session_state.pop(key, None)


def _clear_analysis():
    for key in (
        "monthly_capacity", "aws_component_scenarios", "scenario_catalog", "live", "edges", "discovery_error", "discovery_plan", "pricing", "pricing_errors",
        "pricing_elapsed", "final_target", "migration_advisory", "terraform", "validation",
        "cli_validation", "builder_reports", "equivalent_rows", "client_terraform_approval",
    ):
        st.session_state.pop(key, None)


def _pricing_row_by_id(rows):
    return {
        str(r.get("Resource ID") or "").rstrip("/").lower(): r
        for r in (rows or [])
        if r.get("Resource ID")
    }


def _format_money(value):
    return "Unavailable" if value is None else f"${float(value):,.2f}"


if st.session_state.get("application_revision") != "migration-workbench-v1":
    _clear_analysis()
    st.session_state.application_revision = "migration-workbench-v1"

ai_settings()


CREDENTIAL_WIDGET_KEYS = (
    "cred_aws_access_key", "cred_aws_secret_key", "cred_aws_session_token", "cred_aws_region",
    "cred_azure_tenant", "cred_azure_client", "cred_azure_secret", "cred_azure_subscription",
    "cred_gcp_project", "cred_gcp_billing_api_key", "cred_gcp_sa_file", "cred_gcp_sa_json",
    "cred_gcp_service_account_info", "cred_gcp_sa_signature",
)

with st.sidebar:
    st.header("Billing & Cloud Access")
    upload = st.file_uploader(
        "Upload AWS, Azure, or GCP billing export",
        type=["csv", "xlsx", "xls"],
        key="billing_upload",
    )
    st.caption("Cloud and billing currency are detected automatically. Cross-cloud comparisons use normalized USD values.")

    if upload is not None:
        if len(upload.getvalue()) > SETTINGS.max_upload_mb * 1024 * 1024:
            st.error(f"File exceeds the configured {SETTINGS.max_upload_mb} MB upload limit.")
            st.stop()
        try:
            raw_df = read_table(upload)
            detected = detect(raw_df)
        except Exception as exc:
            st.error(f"Billing file could not be read: {exc}")
            st.stop()

        if detected == "Unknown":
            st.warning("Cloud schema was not recognized automatically.")
            source = st.selectbox("Cloud override", CLOUDS, key="cloud_override")
        else:
            source = detected
            st.success(f"Detected current cloud: {source}")

        signature = _billing_signature(upload, source)
        if st.session_state.get("billing_signature") != signature:
            resources, skipped = parse(raw_df, source)
            if not resources:
                st.error(f"No billing rows could be parsed as {source} data.")
                st.stop()
            _clear_analysis()
            st.session_state.billing_signature = signature
            st.session_state.source = source
            st.session_state.billing_original = resources
            st.session_state.billing_skipped = skipped
            st.session_state.billing_input_rows = len(raw_df)

        if st.button("Clear entered credentials", use_container_width=True, key="clear_credentials"):
            for key in CREDENTIAL_WIDGET_KEYS:
                st.session_state.pop(key, None)
            _clear_analysis()
            st.rerun()

        if source == "AWS":
            with st.expander("AWS credentials", expanded=(source == "AWS")):
                st.text_input("Access Key ID", type="password", key="cred_aws_access_key")
                st.text_input("Secret Access Key", type="password", key="cred_aws_secret_key")
                st.text_input("Session Token (optional)", type="password", key="cred_aws_session_token")
                st.text_input("AWS Region (optional override)", key="cred_aws_region", placeholder="Auto-detect; fallback us-east-1")

        if source == "Azure":
            with st.expander("Azure credentials", expanded=(source == "Azure")):
                st.text_input("Tenant ID", type="password", key="cred_azure_tenant")
                st.text_input("Client ID", type="password", key="cred_azure_client")
                st.text_input("Client Secret", type="password", key="cred_azure_secret")
                st.text_input("Subscription ID (optional override)", key="cred_azure_subscription")

        if source == "GCP":
            with st.expander("GCP credentials", expanded=(source == "GCP")):
                st.text_input("Project ID", key="cred_gcp_project")
                gcp_sa_file = st.file_uploader("Service Account JSON file", type=["json"], key="cred_gcp_sa_file")
                gcp_sa_json = st.text_input("Or paste Service Account JSON", type="password", key="cred_gcp_sa_json")
                st.text_input("Cloud Billing Catalog API Key (optional)", type="password", key="cred_gcp_billing_api_key")
                payload = None
                signature_value = ""
                if gcp_sa_file is not None:
                    raw = gcp_sa_file.getvalue()
                    signature_value = hashlib.sha256(raw).hexdigest()
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except Exception:
                        st.error("The uploaded GCP service account file is not valid JSON.")
                elif gcp_sa_json.strip():
                    signature_value = hashlib.sha256(gcp_sa_json.encode()).hexdigest()
                    try:
                        payload = json.loads(gcp_sa_json)
                    except Exception:
                        st.error("The pasted GCP service account value is not valid JSON.")
                if isinstance(payload, dict):
                    st.session_state.cred_gcp_service_account_info = payload
                    st.session_state.cred_gcp_sa_signature = signature_value
                elif not gcp_sa_file and not gcp_sa_json.strip():
                    st.session_state.pop("cred_gcp_service_account_info", None)
                    st.session_state.pop("cred_gcp_sa_signature", None)

        credentials = _credential_bundle()
        input_errors = validate_bundle(credentials)
        for message in input_errors:
            st.error(message)
        st.caption(f"Detected source scope: {_source_scope(source, st.session_state.billing_original, credentials)}")

        if st.button("🔎 Discover current environment", type="primary", use_container_width=True, key="run_discovery"):
            if input_errors:
                st.error("Correct the credential input errors before running discovery.")
            else:
                _clear_analysis()
                try:
                    with st.spinner(f"Discovering {source} resources and explicit dependencies..."):
                        live = _discover(source, st.session_state.billing_original, credentials)
                        edges = build_dependencies(live)
                    st.session_state.live = live
                    st.session_state.edges = edges
                    st.session_state.pop("discovery_error", None)
                except Exception as exc:
                    st.session_state.live = []
                    st.session_state.edges = []
                    st.session_state.discovery_error = sanitize_exception(exc, credentials)
                st.rerun()


if upload is None or "billing_original" not in st.session_state:
    st.info("Upload a billing export in the sidebar to start the migration assessment.")
    st.markdown(
        "**Workflow:** current cloud inventory → dependency architecture → cloud-neutral model → "
        "two-cloud price comparison → target confirmation → equivalent configuration → migration strategy → "
        "optional AI advisory → Terraform generation and validation."
    )
    st.stop()

source = st.session_state.source
billing_original = st.session_state.billing_original
credentials = _credential_bundle()


# -----------------------------------------------------------------------------
# Current cloud overview
# -----------------------------------------------------------------------------
st.header("Current Cloud Overview")
fx_rates, fx_sources = {}, []
try:
    for currency in sorted({str(r.currency or "USD").upper() for r in billing_original} - {"USD"}):
        rate, rate_source = cached_usd_rate(currency)
        fx_rates[currency] = rate
        fx_sources.append({"currency": currency, "usd_rate": rate, "source": rate_source})
    billing = convert_billing(billing_original, fx_rates)
except Exception as exc:
    st.error(f"Automatic currency normalization failed: {exc}")
    st.stop()

period = billing_period(billing_original)
unique_resources = len({str(r.resource_id).rstrip("/").lower() for r in billing if str(r.resource_id or "").strip()})
current_total = sum(float(r.cost or 0.0) for r in billing)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current cloud", source)
c2.metric("Billing rows", f"{len(billing):,}")
c3.metric("Billed resource IDs", f"{unique_resources:,}")
c4.metric("Observed cost (USD)", f"${current_total:,.2f}")
if period.get("start"):
    st.caption(f"Observed billing period: {period['start']} → {period['end']} ({period['days']} day(s)). All savings below refer to comparable usage evidence from this period unless explicitly stated otherwise.")
if fx_sources:
    st.caption("Currency normalization: " + "; ".join(f"{x['currency']}→USD {x['usd_rate']:.8f} ({x['source']})" for x in fx_sources))

with st.expander("Billing resource inventory", expanded=False):
    st.dataframe(
        pd.DataFrame([
            {
                "Resource": r.name,
                "Type": r.canonical_type,
                "Resource ID": r.resource_id,
                "Usage": f"{r.usage_quantity:g} {r.usage_unit}" if r.usage_unit else "Not exposed",
                "Cost (USD)": round(float(r.cost or 0), 6),
                "Region": r.region,
            }
            for r in billing
        ]),
        use_container_width=True,
        hide_index=True,
    )

live = st.session_state.get("live", [])
if source != "AWS":
    from multicloud_ai.core.placement import place_resources
    placement_selection = st.session_state.get("aws_region_selection", {})
    # Use the applied placement for both pricing and deployment.
    live = place_resources(live, placement_selection.get("override", ""), placement_selection.get("confirmed", False))

# Billing can identify generative-AI accounts that discovery labels generically.
from copy import deepcopy
live = deepcopy(live)
ai_billed_ids = {r.resource_id.rstrip("/").lower() for r in billing if r.canonical_type == "generative_ai"}
for resource in live:
    if resource.canonical_type == "other" and resource.resource_id.rstrip("/").lower() in ai_billed_ids:
        resource.canonical_type = "generative_ai"
edges = st.session_state.get("edges", [])
if st.session_state.get("discovery_error"):
    st.error("Live discovery failed: " + st.session_state.discovery_error)
    st.info("Correct cloud permissions/credentials and rerun **Discover current environment**. Architecture, configuration-equivalence and Terraform intentionally require live configuration.")
    st.stop()
if not live:
    st.info("Enter the current-cloud credentials in the sidebar and click **Discover current environment** to continue.")
    st.stop()

st.success(f"Live discovery completed: {len(live):,} resources and {len(edges):,} explicit dependency relationships.")


# -----------------------------------------------------------------------------
# Dependency architecture
# -----------------------------------------------------------------------------
st.header("Dependency Architecture")
st.write("Each circle represents a resource discovered in your current cloud. A line connects resources when the cloud configuration explicitly says that one uses or belongs to another, for example, a server using a disk or network.")
st.write("These connections come from live configuration records, not billing amounts. Resources without a line may still have application-level connections that the cloud records do not expose.")
graph = architecture_graph(live, edges)
summary = topology_summary(graph)
a1, a2, a3, a4 = st.columns(4)
a1.metric("Resources", summary.get("nodes", graph.number_of_nodes()))
a2.metric("Relationships", summary.get("edges", graph.number_of_edges()))
a3.metric("Resource types", len({r.canonical_type for r in live}))
a4.metric("Connected resources", sum(1 for n in graph.nodes if graph.degree(n) > 0))

architecture_html = graph_html(graph)
architecture_svg = graph_svg(graph)
components.html(architecture_html, height=690, scrolling=True)
st.caption("Drag nodes, zoom, hover for details, and use the controls in the graph. Only dependencies supported by provider metadata are shown; missing metadata is not guessed.")

with st.expander("Dependency evidence", expanded=False):
    if edges:
        st.dataframe(
            pd.DataFrame([
                {
                    "From": e.source_id,
                    "To": e.target_id,
                    "Relationship": e.relationship,
                    "Evidence": e.evidence,
                    "Confidence": e.confidence,
                }
                for e in edges
            ]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No directly resolvable dependency edges were found in provider metadata.")

ad1, ad2 = st.columns(2)
ad1.download_button("Download architecture HTML", architecture_html, "architecture.html", "text/html", key="download_architecture_html")
ad2.download_button("Download architecture SVG", architecture_svg, "architecture.svg", "image/svg+xml", key="download_architecture_svg")


# -----------------------------------------------------------------------------
# Cloud-neutral model
# -----------------------------------------------------------------------------
st.header("Cloud-Neutral Resource Model")
common_ir = build_common_ir(live, edges)
ir1, ir2, ir3 = st.columns(3)
ir1.metric("Normalized resources", common_ir.get("resource_count", 0))
ir2.metric("Normalized relationships", common_ir.get("relationship_count", 0))
ir3.metric("Model status", common_ir.get("status", "Unknown"))

neutral_rows = [
    {
        "Resource": r.get("name"),
        "Neutral Type": r.get("resource_type"),
        "Source Cloud": str(r.get("cloud", "")).upper(),
        "Region": r.get("region"),
    }
    for r in common_ir.get("resources", [])
]
st.dataframe(pd.DataFrame(neutral_rows), use_container_width=True, hide_index=True)
st.caption("This common model removes provider-specific naming from the decision flow so the same resource can be compared consistently across AWS, Azure and GCP.")
st.download_button("Download cloud-neutral model", _json(common_ir), "cloud_neutral_ir.json", "application/json", key="download_common_ir")


from multicloud_ai.review_workflow import render_workflow
render_workflow(source, billing, live, edges, period)
