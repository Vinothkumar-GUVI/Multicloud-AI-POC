"""Phase-plan UI components. Agent calls run only on explicit user action."""
import json
import os
from dataclasses import asdict
import streamlit as st
import streamlit.components.v1 as components
from .core.agents import AgentClient, run_agent
from .core.visualization import architecture_graph, graph_html, graph_svg, topology_summary
from .core.terraform_runner import validate_cli, repair_terraform


def _ai_client(require_consent=True):
    if require_consent and not st.session_state.get('ai_consent'):
        raise ValueError('Enable AI analysis in the sidebar before running an agent.')
    provider = st.session_state.get('ai_provider', 'OpenAI')
    base_url = (st.session_state.get('ai_base_url') or os.getenv('OPENAI_BASE_URL', '')).strip()
    if provider == 'OpenAI' and not base_url:
        base_url = 'https://api.openai.com/v1'
    return AgentClient(
        st.session_state.get('ai_api_key') or os.getenv('OPENAI_API_KEY', ''),
        st.session_state.get('ai_model', ''),
        provider=provider,
        base_url=base_url,
        proxy_url=st.session_state.get('ai_proxy_url', ''),
    )


def ai_settings():
    from .core.ai_settings import load_ai_defaults
    try:
        for key, value in load_ai_defaults().items():
            if key not in st.session_state:
                st.session_state[key] = value
    except ValueError as exc:
        st.sidebar.error(str(exc))
    with st.sidebar.expander('AI agents - connection settings'):
        st.caption('AI settings load automatically from .streamlit/ai.toml. Sidebar changes apply to this session only.')
        provider = st.selectbox(
            'AI provider', ['OpenAI', 'Azure OpenAI', 'OpenAI-compatible'],
            key='ai_provider',
            help='Azure OpenAI uses the GA OpenAI-compatible /openai/v1 Responses API.',
        )
        st.text_input(
            'AI API key', type='password', key='ai_api_key',
            help='Kept in Streamlit session memory and never included in assessment artifacts.',
        )
        st.text_input(
            'Responses-compatible model/deployment ID', key='ai_model',
            placeholder='Enter a model or Azure deployment available to this credential',
        )
        endpoint_placeholder = (
            'https://api.openai.com/v1' if provider == 'OpenAI'
            else 'https://YOUR-RESOURCE.openai.azure.com/openai/v1' if provider == 'Azure OpenAI'
            else 'https://approved-gateway.example/v1'
        )
        st.text_input(
            'AI API base URL', key='ai_base_url',
            placeholder=endpoint_placeholder,
            help='OpenAI defaults to https://api.openai.com/v1. For Azure OpenAI, you may enter either the resource root or the full /openai/v1 base URL.',
        )
        st.text_input(
            'HTTPS proxy (optional)', type='password', key='ai_proxy_url',
            placeholder='http://proxy.company:port',
            help='Leave blank to use the operating-system/environment proxy. Useful on managed corporate networks.',
        )
        if st.button('Test AI connection', key='test_ai_connection'):
            try:
                with st.spinner('Testing endpoint, credential and model access...'):
                    result = _ai_client(require_consent=False).test_connection()
                st.session_state.ai_connection_result = result
                st.session_state.pop('ai_connection_error', None)
            except (ValueError, RuntimeError) as exc:
                st.session_state.ai_connection_error = str(exc)
                st.session_state.pop('ai_connection_result', None)
        if st.session_state.get('ai_connection_result'):
            result = st.session_state.ai_connection_result
            st.success(
                f"AI connection verified: {result['provider']} / {result['model']} "
                f"({result['endpoint_host']}, {result['elapsed_seconds']}s)."
            )
        if st.session_state.get('ai_connection_error'):
            st.error(st.session_state.ai_connection_error)
            st.caption('The deterministic billing, discovery, IR, architecture, FinOps and Terraform workflow remains available even when external AI access is blocked.')
        st.checkbox('Allow AI analysis of the displayed resource metadata and assessment evidence', key='ai_consent')
        st.caption('Agent buttons send curated inventory, dependency, pricing and draft-code evidence to the configured Responses API. Cloud credentials are excluded. AI reports are advisory.')


def client():
    return _ai_client(require_consent=True)


def evidence_for(live, edges, assessments, recommendation):
    # Whitelist only non-secret resource metadata; raw configuration/tags are excluded.
    return {
        'inventory': [{'resource_id': r.resource_id, 'name': r.name, 'type': r.canonical_type, 'region': r.region} for r in live],
        'dependencies': [asdict(e) for e in edges],
        'topology': topology_summary(architecture_graph(live, edges)),
        'pricing': [a.to_dict() for a in assessments],
        'pricing_rows': [r for rows in st.session_state.get('pricing', {}).values() for r in rows],
        'mapping': st.session_state.get('mapping', {}),
        'recommendation': recommendation,
    }


def interactive_view(live, edges):
    with st.expander('Interactive architecture explorer', expanded=False):
        search = st.text_input('Find resource by name or ID', key='graph_search')
        kinds = st.multiselect('Resource types', sorted({r.canonical_type for r in live}), key='graph_types')
        graph = architecture_graph(live, edges, search, kinds)
        st.caption(f'{graph.number_of_nodes()} resources / {graph.number_of_edges()} visible relationships. Filtering hides unrelated endpoints. Drag nodes, zoom, and hover for evidence.')
        content = graph_html(graph)
        components.html(content, height=720, scrolling=True)
        st.download_button('Download filtered architecture HTML', content, 'architecture_filtered.html', 'text/html', key='download_interactive_architecture_html')
        st.download_button('Download filtered architecture SVG', graph_svg(graph), 'architecture_filtered.svg', 'image/svg+xml', key='download_interactive_architecture_svg')
        st.caption('The interactive HTML viewer also includes an in-browser PNG export control.')
        st.json(topology_summary(graph), expanded=False)


def agent_panel(live, edges, assessments, recommendation):
    st.subheader('Scout and FinOps AI agents')
    context = evidence_for(live, edges, assessments, recommendation)
    if not st.session_state.get('ai_model'):
        st.info('AI agents are not configured. Enter an API key and model in the sidebar. Deterministic assessment remains available.')
    for role in ('Scout', 'FinOps'):
        if st.button(f'Run {role} AI Agent', key='run_agent_' + role):
            try:
                with st.spinner(f'{role} is reviewing assessment evidence...'):
                    result = run_agent(role, client(), context)
                st.session_state.setdefault('agent_reports', {})[role] = result
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
        result = st.session_state.get('agent_reports', {}).get(role)
        if result:
            st.markdown(result['report']['summary'])
            st.json(result, expanded=False)
            st.download_button(f'Download {role} report', json.dumps(result, indent=2), role.lower() + '_report.json', key='download_agent_report_' + role.lower())


def builder_panel(target, live, edges, assessments, recommendation):
    text = st.session_state.terraform[target]
    if st.button('Run Terraform CLI validation', key='validate_cli_' + target):
        with st.spinner('Running Terraform fmt, init (backend disabled), and validate...'):
            st.session_state.setdefault('cli_validation', {})[target] = validate_cli(text, target)
    cli = st.session_state.get('cli_validation', {}).get(target)
    if cli:
        st.write('Terraform CLI status: ' + cli['status'])
        st.json(cli, expanded=False)
    else:
        st.caption('Terraform CLI validation: not run. Syntax checks alone do not establish deployability.')
    if st.button('Run Builder AI repair and revalidate', key='builder_' + target):
        try:
            ai = client()
            with st.spinner('Builder is validating and repairing the draft (at most two repair attempts)...'):
                result = repair_terraform(text, target, ai, evidence_for(live, edges, assessments, recommendation))
            st.session_state.setdefault('builder_reports', {})[target] = result
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
    result = st.session_state.get('builder_reports', {}).get(target)
    if result:
        st.write('Builder candidate validation: ' + result['validation']['status'])
        st.json(result['history'], expanded=False)
        st.download_button('Download Builder candidate Terraform', result['terraform'], f'builder_{target.lower()}.tf', key='candidate_' + target)
        st.caption('Candidate output is separate from the original assessment. Provider validation does not prove migration equivalence or deployability in your account.')


def effective_terraform(target: str):
    """Return an AI-repaired Terraform candidate only after successful validation."""
    result = st.session_state.get('builder_reports', {}).get(target)
    if result and (result.get('validation') or {}).get('valid') and result.get('terraform'):
        return result['terraform'], 'builder_validated'
    return st.session_state.get('terraform', {}).get(target, ''), 'generated'


def migration_advisory_panel(target, live, edges, pricing_rows, mapping_rows, migration_plan, cost_summary):
    """Run a single migration-focused AI advisory after the target is confirmed."""
    st.subheader('AI Migration Advisory')
    from .core.advisory_presentation import render_assessment
    render_assessment(target, live, mapping_rows, migration_plan, cost_summary)

    st.caption(
        'Optional AI review of the selected target. It uses curated migration evidence only; cloud credentials, secret values and raw tags are excluded.'
    )
    if not st.session_state.get('ai_model'):
        st.info('Configure an AI provider/model in the sidebar to enable the advisory. The deterministic migration workflow remains fully usable without AI.')

    evidence = {
        'selected_target': {'cloud': target, 'cost_summary': cost_summary},
        'inventory': [
            {
                'resource_id': r.resource_id,
                'name': r.name,
                'type': r.canonical_type,
                'region': r.region,
                'configuration_confidence': getattr(r, 'configuration_confidence', ''),
            }
            for r in (live or [])
        ],
        'dependencies': [asdict(e) for e in (edges or [])],
        'pricing': list(pricing_rows or []),
        'equivalent_configuration': list(mapping_rows or []),
        'migration_strategy': [p.to_dict() if hasattr(p, 'to_dict') else p for p in (migration_plan or [])],
    }
    if st.button('Generate AI migration advisory', key='run_migration_advisory'):
        try:
            with st.spinner('Reviewing migration evidence and preparing practical migration guidance...'):
                result = run_agent('MigrationAdvisor', client(), evidence)
            st.session_state['migration_advisory'] = result
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))

    result = st.session_state.get('migration_advisory')
    if result:
        report = result.get('report', {})
        with st.expander('Detailed AI findings and recommendations', expanded=False):
            st.caption('AI-generated advisory, not validated conclusions. The calculated assessment above is authoritative for counts and coverage; unsupported savings or readiness claims must be disregarded.')
            st.markdown(report.get('summary', ''))
            for item in report.get('findings') or []:
                st.markdown(f'- {item}')
            if report.get('next_steps'):
                st.write('Suggested actions')
                for index, item in enumerate(report['next_steps'], start=1):
                    st.markdown(f'{index}. {item}')
        st.download_button(
            'Download AI migration advisory',
            json.dumps(result, indent=2, default=str),
            'ai_migration_advisory.json',
            'application/json',
            key='download_migration_advisory',
        )
