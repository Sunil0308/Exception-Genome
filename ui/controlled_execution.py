import streamlit as st

from core.database import connect, snapshot
from core.execution_engine import DEMO_FAILURE
from core.execution_readiness import READY
from core.phase5_store import execution
from services.workflow import advance_recovery, execute_controlled, run_verification
from core.service_graph import figure
from core.verification_engine import read_verification


def execution_view(incident_id, cluster_id=None):
    with connect() as db:
        record = execution(db, incident_id, cluster_id)
        verification = read_verification(db, record['execution_id']) if record else None
    return record, verification


@st.fragment(run_every=1.2)
def recovery_progress(incident_id, cluster_id):
    record, _ = execution_view(incident_id, cluster_id)
    if not record or record['status'] != 'RECOVERING':
        st.rerun()
    state = snapshot()
    incidents = [row for row in state['exceptions'] if row['incident_id'] == incident_id and row['service_id'] in record['affected_services']]
    left, right = st.columns(2)
    left.metric('Active exceptions', sum(row['status'] != 'RESOLVED' for row in incidents))
    right.metric('Services recovered', sum(row['status'] == 'RESOLVED' for row in incidents))
    names = [row['name'] for row in state['services'] if row['status'] == 'RECOVERING'
             and row['id'] in record['affected_services']]
    st.write('Currently recovering · ' + (', '.join(names) or 'None'))
    st.plotly_chart(figure(state['services']), key='phase5-recovery-graph', width='stretch')
    result = advance_recovery(incident_id, cluster_id=cluster_id)
    if result and result['status'] != 'RECOVERING':
        st.rerun()


def render_execution(incident, decision, record, verification, names, cluster_id=None):
    incident_id = incident['id']
    st.subheader('7. Controlled Execution')
    message = st.session_state.pop(f'execution-message-{incident_id}', None)
    if message:
        st.warning(message)
    if not record and decision['status'] == READY:
        mode = st.radio('Execution mode', ['NORMAL', DEMO_FAILURE], format_func=lambda value: (
            'Normal' if value == 'NORMAL' else 'Synthetic verification-failure demonstration'))
        if st.button('Execute Controlled Remediation', type='primary'):
            result = execute_controlled(incident_id, expected_hash=decision['contract'].contract_hash, mode=mode, cluster_id=cluster_id)
            if result['status'] in ('BLOCKED', 'FAILED'):
                st.session_state[f'execution-message-{incident_id}'] = result['failure_reason']
            st.rerun()
    elif not record:
        st.caption('Execution requires a current approved and simulated contract.')
    if not record:
        return

    st.write(f"{record['action_type']} · {names.get(record['target_service'], record['target_service'])}")
    st.code(record['execution_id'])
    st.code(record['contract_hash'])
    st.write(f"Status · {record['status'].replace('_', ' ')}")
    if record['action_applied']:
        st.write('Controlled action applied')
        if record['action_parameters'].get('credential_version'):
            st.code(record['action_parameters']['credential_version'])
        if record.get('review_decision_id'):
            st.caption('Reviewer authorization · ' + record['review_decision_id'])
    if record['mode'] == DEMO_FAILURE:
        st.caption('Synthetic verification-failure demonstration')
    if record['status'] == 'FAILED':
        st.error(record['failure_reason'])

    st.subheader('8. Recovery')
    if record['status'] == 'RECOVERING':
        recovery_progress(incident_id, cluster_id)
    else:
        st.write(f"Persisted recovery waves · {record['recovery_step']}")
    st.subheader('9. Independent Verification')
    if record['status'] == 'AWAITING_VERIFICATION' and st.button('Run Independent Verification', type='primary'):
        run_verification(incident_id, cluster_id=cluster_id)
        st.rerun()
    if verification:
        st.dataframe([{
            'Check': row['verification_rule_id'], 'Name': row['name'], 'Expected': str(row['expected']),
            'Actual': str(row['actual']), 'Result': row['result'], 'Evidence': row['failure_reason'],
        } for row in verification['checks']], hide_index=True)
        passed = sum(row['result'] == 'PASS' for row in verification['checks'])
        st.write(f"{passed}/15 checks passed · {verification['recovered_count']}/{verification['affected_count']} "
                 "incident exceptions cleared at the verification checkpoint")
        st.subheader('10. Final Outcome')
        if verification['status'] == 'VERIFIED' and record.get('multi_assignment') and incident['status'] != 'RESOLVED':
            st.success('ASSIGNMENT VERIFIED · Other assignments remain open.')
        elif incident['status'] == 'RESOLVED':
            st.success('RESOLUTION VERIFIED')
        else:
            st.error(f"VERIFICATION {verification['status']}")
            if record['rollback_status']:
                st.write(record['rollback_status'].replace('_', ' '))
            st.warning(incident['status'].replace('_', ' '))
    elif record['status'] == 'AWAITING_VERIFICATION':
        st.info('Recovery has finished. The incident remains open pending independent verification.')



