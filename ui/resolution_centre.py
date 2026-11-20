import streamlit as st

from core.action_registry import AUTONOMY_CLASSES, RESTART
from core.analysis import load
from core.database import snapshot
from core.execution_readiness import READY, execution_readiness
from services.workflow import create_contract, evaluate_safety_gate, record_readiness, run_impact_simulation


from ui.controlled_execution import execution_view, render_execution


def render():
    st.header('Resolution Centre')
    state = snapshot()
    names = {service['id']: service['name'] for service in state['services']}
    incident_ids = [row['id'] for row in state['incidents'] if row['status'] != 'ACTIVE']
    if not incident_ids:
        st.info('Complete analysis in the Command Centre to open the Resolution Centre.')
        return
    incident_id = st.selectbox('Diagnosed incident', incident_ids)
    incident = next(row for row in state['incidents'] if row['id'] == incident_id)
    analysis = load(incident_id=incident_id)
    roots = analysis['root_cause_analyses']
    if not roots:
        st.info('Resolution planning requires one identified root cause.')
        return
    roots_by_cluster = {item['cluster_id']: item for item in roots}
    cluster = st.selectbox('Resolution assignment', analysis['correlation_clusters'],
                           format_func=lambda item: item['id']) if len(roots) > 1 else analysis['correlation_clusters'][0]
    cluster_id = cluster['id']
    record, verification = execution_view(incident_id, cluster_id)
    historical = bool(record and record['action_applied'])
    root = roots_by_cluster[cluster_id]
    decision = execution_readiness(incident_id, cluster_id=cluster_id)
    contract = decision['contract']
    safety_label = ('HUMAN_REVIEW_REQUIRED' if record.get('review_decision_id') else 'APPROVED') if historical else decision.get('safety_status', 'PENDING')
    simulation_label = 'PASS' if historical else decision.get('simulation_status', 'PENDING')

    with st.container(border=True):
        st.subheader('Trust chain')
        stages = (
            ('Diagnosis', 'Verified evidence', bool(root)),
            ('Resolution contract', f'Version {contract.contract_version}' if contract else 'Pending',
             bool(decision.get('integrity'))),
            ('Safety Gate', decision.get('safety_status', 'PENDING'), decision.get('safety_status') == 'APPROVED'),
            ('Impact Sandbox', decision.get('simulation_status', 'PENDING'), decision.get('simulation_status') == 'PASS'),
            ('Ready', 'Validated at execution' if historical else decision['status'].replace('_', ' '), historical or decision['status'] == READY),
        )
        for column, (label, status, complete) in zip(st.columns(5), stages):
            column.markdown(f"**{'✓' if complete else '○'} {label}**")
            column.caption(status)

        if record:
            outcome = incident['status'].replace('_', ' ')
            execution_stage = 'COMPLETED' if verification else record['status'].replace('_', ' ')
            phase5_stages = [('Execution', execution_stage),
                             ('Verification', verification['status'] if verification else 'PENDING')]
            if record['rollback_status']:
                phase5_stages.append(('Rollback', record['rollback_status'].removeprefix('ROLLBACK_')))
            phase5_stages.append(('Final status', outcome))
            for column, (label, stage) in zip(st.columns(len(phase5_stages)), phase5_stages):
                column.markdown(f'**{label}**')
                column.caption(stage)

    st.subheader('1. Diagnosis Snapshot')
    for column, (label, value) in zip(st.columns(5), (
        ('Exceptions', len(cluster['members'])), ('Correlated clusters', len(analysis['correlation_clusters'])),
        ('Root causes', len(roots)), ('Root-cause evidence', f"{root['confidence'] * 100:.1f}/100"),
        ('Correlation', f"{cluster['score']:.1f}/100"),
    )):
        column.metric(label, value)
    st.write(root['root_cause_service'])
    if cluster.get('assignment_status') == 'SINGLETON':
        st.info('NO SHARED ROOT CAUSE DETECTED · Isolated operational exception')
    if root.get('diagnosis_outcome') == 'NO_CONFIDENT_ROOT_CAUSE':
        st.warning('NO CONFIDENT ROOT CAUSE · Human review required')

    st.subheader('2. Proposed Remediation')
    left, right = st.columns(2)
    left.markdown('**Analysis recommendation**')
    left.write(root['recommended_action'])
    right.markdown('**Allowlisted controlled action**')
    if contract:
        right.code(contract.action_type)
        right.write(f"Target · {names.get(contract.target_service, contract.target_service)}")
        if contract.action_parameters:
            right.json(contract.action_parameters)
        right.write(f'{contract.autonomy_class} · {AUTONOMY_CLASSES[contract.autonomy_class]}')
    else:
        right.caption('Generate a contract to see the proposed controlled action.')

    st.subheader('3. Resolution Contract')
    candidate = st.radio('Remediation candidate', ['Approved reference activation', 'Aggressive shared authentication restart'], horizontal=True)
    if st.button('Generate Resolution Contract', type='primary', disabled=bool(record)):
        create_contract(incident_id, unsafe_demo=candidate.startswith('Aggressive'), cluster_id=cluster_id)
        record_readiness(incident_id, cluster_id=cluster_id)
        st.rerun()
    if not contract:
        return
    st.write(f'Version {contract.contract_version} · SHA-256')
    st.code(contract.contract_hash)
    st.write(contract.root_cause)
    for title, value in (
        ('Frozen evidence snapshot', contract.evidence_snapshot),
        ('Required preconditions', contract.required_preconditions),
        ('Expected postconditions', contract.expected_postconditions),
        ('Rollback plan', contract.rollback_plan),
        ('Authority scope', {**contract.authority_scope, 'maximum_blast_radius': contract.maximum_blast_radius}),
    ):
        with st.expander(title):
            st.json(value)

    st.subheader('4. Safety Gate')
    if st.button('Evaluate Safety Gate', disabled=bool(record)):
        evaluate_safety_gate(incident_id, cluster_id=cluster_id)
        record_readiness(incident_id, cluster_id=cluster_id)
        st.rerun()
    safety = decision['safety']
    if safety:
        status = safety_label
        st.markdown(f"**{status.replace('_', ' ')}**")
        passed = sum(rule['result'] == 'PASS' for rule in safety['rules'])
        st.caption(f'{passed} / {len(safety["rules"])} rules passed')
        st.dataframe([
            {'Rule': r['rule_id'], 'Name': r['name'], 'Result': r['result'],
             'Evidence': str(r['evidence']), 'Failure reason': r['failure_reason']} for r in safety['rules']
        ], hide_index=True)
        if status == 'APPROVED':
            st.success('Approved for impact simulation')
        elif status in ('BLOCKED', 'HUMAN_REVIEW_REQUIRED'):
            st.warning('Autonomous remediation blocked. Human review required.')

    st.subheader('5. Impact Sandbox')
    st.caption('Synthetic state-based projection. Live service and exception states are displayed in Command Centre.')
    if st.button('Run Impact Simulation', disabled=bool(record) or not (safety_label == 'APPROVED' or (safety_label == 'HUMAN_REVIEW_REQUIRED' and contract.target_service in ('merchant', 'scheduler', 'event_bus')))):
        run_impact_simulation(incident_id, cluster_id=cluster_id)
        record_readiness(incident_id, cluster_id=cluster_id)
        st.rerun()
    if contract.action_type == RESTART and decision['safety_status'] == 'BLOCKED':
        st.caption('This preset can be projected for the demonstration after the Safety Gate blocks it.')
        if st.button('Run isolated unsafe demonstration'):
            run_impact_simulation(incident_id, unsafe_demo=True, cluster_id=cluster_id)
            record_readiness(incident_id, cluster_id=cluster_id)
            st.rerun()
    simulation = decision['simulation']
    if simulation:
        recovered = len(simulation['projected_recoveries'])
        unresolved = len(simulation['projected_unresolved'])
        st.markdown(f'### {recovered} / {recovered + unresolved} projected recovery')
        for column, (label, count) in zip(st.columns(5), (
            ('Affected services', recovered + unresolved), ('Projected unresolved', unresolved),
            ('New failures', len(simulation['new_failures'])), ('Policy violations', len(simulation['policy_violations'])),
            ('Unexpected impacts', len(simulation['unexpected_impacts'])),
        )):
            column.metric(label, count)
        st.write(f"**{simulation_label}** · {simulation['reason']}")
        st.write('Root cause projected resolved · ' + ('Yes' if simulation['root_cause_resolved'] else 'No'))
        st.dataframe([{'Service': key, **value} for key, value in simulation['projected_service_states'].items()],
                     hide_index=True)

    st.subheader('6. Execution Readiness')
    for column, (label, value) in zip(st.columns(4), (
        ('Contract', 'VALID' if decision['integrity'] else 'INVALID'),
        ('Safety Gate', safety_label), ('Impact Sandbox', simulation_label),
        ('State', 'AT EXECUTION' if historical else 'STALE' if 'STALE' in (decision['safety_status'], decision['simulation_status'])
         or not decision['diagnosis_current'] else 'CURRENT'),
    )):
        column.metric(label, value)
    if historical:
        st.markdown('### Readiness validated at execution')
    else:
        st.markdown(f"### {decision['status'].replace('_', ' ')}")
        st.write(decision['reason'])
    if decision['status'] == READY:
        st.write(f'{contract.proposed_action} · {len(simulation["projected_recoveries"])} projected recoveries')
        st.code(contract.contract_hash)
        if contract.rollback_plan:
            st.write('Rollback · Restore ' + contract.rollback_plan['credential_version'] + ' and escalate.')
        else:
            st.write('Authority · Synthetic reviewer approval')
    if historical:
        st.caption('Approval and simulation above are the records used when this execution started.')
    render_execution(incident, decision, record, verification, names, cluster_id)








