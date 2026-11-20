import streamlit as st
from core.database import snapshot
from core.analysis import load
from core.service_graph import analytical_figure
from ui.components import analysis_control, summary, scores, root_evidence

def render():
    state,analysis = snapshot(),load()
    incident_ids = [row['id'] for row in state['incidents']]
    if not incident_ids:
        st.header('Exception Genome')
        st.info('Start a scenario in Command Centre.')
        return
    incident_id = st.selectbox('Incident', incident_ids)
    analysis = load(incident_id=incident_id)
    exceptions = [row for row in state['exceptions'] if row['incident_id'] == incident_id]
    services = {s['id']:s for s in state['services']}
    st.header('Exception Genome')
    st.metric('Exceptions detected',len(exceptions))
    st.subheader('Different symptoms')
    domains = list(dict.fromkeys(s['domain'] for s in state['services']))
    for col,domain in zip(st.columns(len(domains)),domains):
        with col:
            with st.container(border=True):
                st.caption(domain)
                example = next((e for e in exceptions if services[e['service_id']]['domain']==domain),None)
                if example:
                    st.markdown('**'+services[example['service_id']]['name']+'**')
                    st.code(example['error_code'])
                    st.write(example['error_message'])
                else:
                    st.write('No failures observed')
    analysis_control(state, incident_id)
    if not analysis['root_cause_analyses']:
        st.info('Raw symptoms are available. No diagnosis has been computed.')
        return
    st.subheader('Shared operational fingerprint')
    cluster = st.selectbox('Assignment', analysis['correlation_clusters'],
                           format_func=lambda row: f"{row['id']} · {row.get('assignment_status', row['status'])} · {len(row['members'])} exceptions")
    root = next(row for row in analysis['root_cause_analyses'] if row['cluster_id'] == cluster['id'])
    if cluster.get('assignment_status') == 'SINGLETON':
        st.info('NO SHARED ROOT CAUSE DETECTED · Isolated operational exception')
    if root.get('diagnosis_outcome') == 'NO_CONFIDENT_ROOT_CAUSE':
        st.warning('NO CONFIDENT ROOT CAUSE · Human review required')
    for match in root.get('historical_matches', []):
        if match['historical_outcome'] == 'VERIFIED SUCCESS':
            st.success(f"Similar verified incident found · {match['similarity_score']:g}%")
        else:
            st.warning(f"Historical warning · Similar remediation failed verification · {match['similarity_score']:g}%")
        st.caption(f"{match['memory_id']} · {match['previous_action']} · {match['previous_verification_result']}")
    a,b,c = st.columns(3)
    a.metric('Shared dependency',root['root_cause_service'])
    b.metric('Different error codes',cluster['different_error_codes'])
    c.metric('Operational domains',cluster['domains'])
    st.write(cluster['common_change'].get('description','No shared recorded change'))
    st.caption(f"First observed: {services[cluster['first_failure']]['name']} | Span: {cluster['time_span_seconds']:g} simulated seconds")
    genomes = [g for g in analysis['exception_genomes'] if g['exception_id'] in cluster['members']]
    selected = st.selectbox('Inspect operational fingerprint',genomes,format_func=lambda g:g['service_name'])
    with st.expander('Genome fields',expanded=True):
        st.json(selected,expanded=False)
    st.subheader(cluster['id'] + ' · ' + cluster['status'])
    scores(cluster)
    summary(analysis)
    st.plotly_chart(analytical_figure(state['services'],root['root_cause_service_id']),width='stretch')
    root_evidence(root)


