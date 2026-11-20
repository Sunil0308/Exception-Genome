import streamlit as st

from core.database import connect
from core.operational_memory import history, patterns
from core.prevention_engine import recommendations


def render():
    st.header('Operational Memory')
    with connect() as db:
        records = history(db)
    if not records:
        st.info('Complete verification to build operational history.')
        return
    st.dataframe([{'Incident': r['source_incident_id'], 'Root cause': r['root_cause'],
                   'Outcome': r['final_outcome'], 'Verification': r['verification_result'],
                   'Rollback': r['rollback_result'], 'Memory': r['memory_id']} for r in records], hide_index=True)
    st.subheader('Recurring patterns')
    groups = patterns(records)
    st.dataframe([{k: v for k, v in group.items() if k != 'records'} for group in groups], hide_index=True)
    for insight in recommendations(groups):
        st.subheader('Preventive recommendation')
        st.write(insight['recommended_control'])
        st.caption(f"{insight['recurrence_count']} verified occurrences · {insight['pattern_id']}")

