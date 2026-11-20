import streamlit as st
from core.database import snapshot, reset, connect
from core.service_graph import figure, build_graph
from simulator.incident_scenarios import start, advance, SCENARIOS, DATAHUB, get_scenario
from simulator.engine import propagation_order
from core.operational_memory import history, patterns
from core.analysis import ready
from core.analysis import load
from core.execution_readiness import READY, execution_readiness
from core.recovery_engine import advance_recovery
from ui.components import analysis_control, summary

@st.fragment(run_every=0.7)
def command_centre():
    if st.session_state.running:
        running_scenario = get_scenario(st.session_state.get('running_incident', DATAHUB.incident_id))
        if not advance(scenario=running_scenario):
            st.session_state.running = False
    state = snapshot()
    analysis = load()
    services, incidents, exceptions = state['services'], state['incidents'], state['exceptions']
    with connect() as db:
        memories = history(db)
    live_unresolved = {row['id'] for row in incidents if row['status'] != 'RESOLVED'}
    resolved_by_incident = {}
    for row in memories:
        if row['verification_result'] == 'VERIFIED' and row['source_incident_id'] not in live_unresolved:
            resolved_by_incident[row['source_incident_id']] = row
    resolved_cases = list(resolved_by_incident.values())
    autonomous = sum(not r['human_review_required'] for r in resolved_cases)
    healthy = sum(s['status']=='HEALTHY' for s in services)
    active = sum(e['status'] in ('ACTIVE', 'RECOVERING', 'REOPENED', 'ESCALATED') for e in exceptions)
    cols = st.columns(6)
    for col, label, value in zip(cols,
        ['Active exceptions','Active incidents','Healthy services','Root causes identified','Auto-resolved','Mean resolution time'],
        [active,sum(row['status'] != 'RESOLVED' for row in incidents),f'{healthy}/24',len(analysis['root_cause_analyses']),'0','—']):
        col.metric(label,value)
    st.caption(f"System health: {'HEALTHY' if healthy==24 else 'DEGRADED'} · Human escalations: 0 · Graph connections run from upstream dependencies to downstream consumers.")
    choices = {sc.title: sc for sc in SCENARIOS.values()}
    choice = st.selectbox('Demo scenario', [*choices, 'DataHub recurrence'])
    if choice == 'DataHub recurrence':
        ids = {row['source_incident_id'] for row in memories} | {row['id'] for row in incidents}
        sequence = 5
        while f'INC-REC-{sequence:03d}' in ids:
            sequence += 1
        scenario = get_scenario(f'INC-REC-{sequence:03d}')
    else:
        scenario = choices[choice]
    active_services = {row['service_id'] for row in exceptions if row['status'] != 'RESOLVED'}
    affected = set(propagation_order(build_graph(services), scenario))
    cannot_start = (st.session_state.running or bool(affected & active_services)
                    or any(row['id'] == scenario.incident_id for row in incidents))
    a,b,c = st.columns([1,1,3])
    if a.button('Simulate Incident',type='primary',disabled=cannot_start,width='stretch'):
        start(scenario=scenario)
        st.session_state.running_incident = scenario.incident_id
        st.session_state.running = True
        st.rerun()
    if b.button('Pause' if st.session_state.running else 'Resume', disabled=not incidents or incidents[0]['status'] != 'ACTIVE' or active>=23,width='stretch'):
        st.session_state.running = not st.session_state.running
        st.rerun()
    if c.button('Reset synthetic demo'):
        reset()
        st.session_state.running = False
        st.rerun()
    if c.button('Reset current scenario and keep memory'):
        reset(preserve_memory=True)
        st.session_state.running = False
        st.rerun()
    if incidents:
        selected = st.selectbox('Incident', [row['id'] for row in incidents])
        incident = next(row for row in incidents if row['id'] == selected)
        status = incident['status']
        if status == 'ACTIVE':
            total = len(propagation_order(build_graph(services), get_scenario(incident['id'])))
            st.progress(incident['simulation_step']/total, text=f"Incident propagation · {incident['simulation_step']}/{total}")
        st.write(f"**{incident['id']} · {status.replace('_', ' ')}**")
        if status in ('ACTIVE', 'DIAGNOSED') and ready(state, incident['id']):
            analysis_control(state, incident['id'])
            summary(load(incident_id=incident['id']))
            decision = execution_readiness(incident['id'])
            if decision['status'] == READY:
                projected = len(decision['simulation']['projected_recoveries'])
                st.success(f'READY FOR CONTROLLED EXECUTION | Safety APPROVED | {projected}/{active} projected recovery')
                st.caption(f'1 validated remediation | {active} live exceptions ACTIVE | Live service failures remain open.')
        if status == 'RECOVERING':
            advance_recovery(incident['id'])
        if status == 'RESOLVED':
            st.success('RESOLUTION VERIFIED')
    else:
        st.success('All 24 services healthy. No active incidents.')
    with st.expander('Operations analytics'):
        from core.review import cases
        from core.prevention_engine import recommendations
        with connect() as db:
            review_queue = sum(r['current_status'] in ('OPEN', 'REQUEST MORE EVIDENCE') for r in cases(db))
        human_resolved = len(resolved_cases) - autonomous
        open_ids = {row['id'] for row in incidents if row['status'] != 'RESOLVED'}
        failed_ids = {r['source_incident_id'] for r in memories if r['failure_count']}
        unresolved = len(open_ids | failed_ids)
        total_cases = len(resolved_cases) + unresolved
        groups = patterns(memories)
        rows = [
            ('Verified resolved incidents', len(resolved_cases)),
            ('Human-reviewed verified resolutions', human_resolved),
            ('Open review cases', review_queue),
            ('Failed or inconclusive verification', sum(r['failure_count'] for r in memories)),
            ('Completed rollbacks', sum(r['rollback_result'] == 'ROLLBACK_COMPLETED' for r in memories)),
            ('Recurring patterns', sum(r['occurrences'] > 1 for r in groups)),
            ('Preventive recommendations', len(recommendations(groups))),
        ]
        if total_cases:
            rows.extend((label, f'{count / total_cases:.1%}') for label, count in (
                ('Autonomous resolution rate', autonomous), ('Human-reviewed resolution rate', human_resolved),
                ('Unresolved rate', unresolved)))
        st.dataframe([{'Metric': label, 'Value': str(value)} for label, value in rows], hide_index=True)
        assignments = analysis['correlation_clusters']
        if assignments:
            grouped = [c for c in assignments if len(c['members']) > 1]
            open_assignments = len(assignments) - len(grouped)
            exception_count = sum(len(c['members']) for c in assignments)
            st.write(f'Exception compression · {exception_count} exceptions → {len(grouped)} shared clusters '
                     f'and {open_assignments} individual assignments')
    st.subheader('Service dependency map')
    st.plotly_chart(figure(services),width='stretch',key='dependency-map')
    st.subheader('Service health')
    graph = build_graph(services)
    rows = [{'Service':s['name'],'Domain':s['domain'],'Status':s['status'],
             'Upstream':', '.join(graph.nodes[n]['name'] for n in graph.predecessors(s['id'])) or 'None',
             'Downstream':', '.join(graph.nodes[n]['name'] for n in graph.successors(s['id'])) or 'None',
             'Last successful run':s['last_success'], 'Recent change':s['recent_change'] or 'None',
             'Error':s['error_state'] or 'None',
             'Current incident': ', '.join(sorted({e['incident_id'] for e in exceptions if e['service_id']==s['id']})) or 'None'} for s in services]
    st.dataframe(rows,width='stretch',hide_index=True)
    st.subheader('Exception activity')
    if exceptions:
        names = {s['id']:s['name'] for s in services}
        st.dataframe([{'Time':e['timestamp'],'Exception':e['id'],'Status':e['status'],'Service':names[e['service_id']],
                       'Error':e['error_code'],'Message':e['error_message'],'Severity':e['severity'],
                       'Business impact':e['business_impact']} for e in reversed(exceptions)],width='stretch',hide_index=True)
    else:
        st.caption('No exceptions detected.')











