import streamlit as st

from core.audit import timeline
from core.database import connect


def render():
    st.header('Audit Trail')
    with connect() as db:
        events = timeline(db)
    for field in ('incident_id', 'cluster_id', 'actor', 'action', 'decision', 'result', 'contract_hash'):
        choices = sorted({row[field] for row in events if row.get(field)})
        selected = st.multiselect(field.replace('_', ' ').title(), choices)
        if selected:
            events = [row for row in events if row.get(field) in selected]
    if events:
        dates = sorted({row['timestamp'][:10] for row in events})
        first, last = st.select_slider('Date range', options=dates, value=(dates[0], dates[-1])) if len(dates) > 1 else (dates[0], dates[0])
        events = [row for row in events if first <= row['timestamp'][:10] <= last]
    if not events:
        st.info('No matching events.')
        return
    st.dataframe([{key: val for key, val in row.items() if key != 'evidence'} for row in events], hide_index=True)
    selected = st.selectbox('Event detail', range(len(events)),
                            format_func=lambda n: f"{events[n]['timestamp']} · {events[n]['action']}")
    with st.expander('Evidence'):
        st.write(events[selected].get('evidence', {}))


