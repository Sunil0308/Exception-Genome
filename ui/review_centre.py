import streamlit as st

from core.database import connect
from services.workflow import inject_probe
from core.review import APPROVE, DECISIONS, REVIEWERS, cases, decide, technical_review, append_diagnostic_record


from core.execution_readiness import record_readiness
from core.resolution_contract import current_contract


def render():
    st.header('Review Centre')
    with connect() as db:
        rows = cases(db)
    if not rows:
        st.info('No cases currently require review.')
        return
    selected = st.selectbox('Review case', rows, format_func=lambda row: row['review_id'])
    st.write(selected['reason'])
    st.caption(selected['current_status'])
    diagnosis = selected['diagnosis']
    st.write(diagnosis['root_cause'])
    with st.expander('Evidence and alternatives'):
        st.write(diagnosis['supporting_evidence'])
        st.write(diagnosis['conflicting_evidence'])
        st.write(diagnosis['alternative_hypotheses'])
    with connect() as db:
        contract = current_contract(db, selected['incident_id'], selected['cluster_id'])
        allow_approval = bool(technical_review(db, contract))
    if selected['current_status'] in ('OPEN', 'REQUEST MORE EVIDENCE'):
        with st.form('review-decision'):
            reviewer = st.selectbox('Simulated reviewer identity', REVIEWERS)
            disposition = st.selectbox('Decision', (*DECISIONS, APPROVE) if allow_approval else DECISIONS)
            reason = st.text_area('Rationale')
            if st.form_submit_button('Record decision'):
                try:
                    with connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        decide(db, selected['review_id'], reviewer, disposition, reason)
                except ValueError as error:
                    st.error(str(error))
                else:
                    if disposition == APPROVE:
                        record_readiness(selected['incident_id'], cluster_id=selected['cluster_id'])
                    st.rerun()

    if selected['current_status'] == 'REQUEST MORE EVIDENCE' and st.button('Simulate diagnostic evidence arriving'):
        try:
            change = inject_probe(selected['incident_id'], selected['cluster_id'])
        except ValueError as error:
            st.error(str(error))
        else:
            st.write('Previous diagnosis · ' + change['previous_diagnosis']['diagnosis_outcome'])
            st.success('New diagnosis · ' + change['diagnosis']['root_cause'])


