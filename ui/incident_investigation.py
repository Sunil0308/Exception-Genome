import json
import streamlit as st
from core.database import snapshot
from core.analysis import load
from ui.components import analysis_control,root_evidence,summary

def render():
    state,analysis = snapshot(),load()
    st.header('Incident Investigation')
    if not state['incidents']:
        st.info('No active incidents. Start the demo in Command Centre.')
        return
    incident_id = st.selectbox('Incident', [row['id'] for row in state['incidents']])
    incident = next(row for row in state['incidents'] if row['id'] == incident_id)
    state['exceptions'] = [row for row in state['exceptions'] if row['incident_id'] == incident_id]
    analysis = load(incident_id=incident_id)
    services = {s['id']:s for s in state['services']}
    st.subheader(incident['id'] + ' | ' + incident['status'])
    st.caption('Started: ' + incident['started_at'][11:] + ' | Synthetic scenario')
    for col,label,value in zip(st.columns(3),['Affected services','Exceptions','Domains affected'],
                              [len({e['service_id'] for e in state['exceptions']}),len(state['exceptions']),
                               len({services[e['service_id']]['domain'] for e in state['exceptions']})]):
        col.metric(label,value)
    st.subheader('Incident Timeline')
    events = []
    for service in state['services']:
        if service['recent_change']:
            try:
                change = json.loads(service['recent_change'])
                events.append({'Timestamp':change['timestamp'],'Event':change['description']})
            except (ValueError,KeyError,TypeError):
                st.caption('Legacy change record: '+service['recent_change'])
    events.extend({'Timestamp':e['timestamp'],'Event':services[e['service_id']]['name']+' — '+e['error_message']} for e in state['exceptions'])
    st.dataframe(sorted(events,key=lambda e:e['Timestamp']),hide_index=True,width='stretch')
    st.subheader('Evidence')
    st.caption('Source records remain inspectable before and after diagnosis.')
    with st.expander('Recorded exception context'):
        st.dataframe(state['exceptions'],hide_index=True,width='stretch')
    analysis_control(state, incident_id)
    if analysis['root_cause_analyses']:
        summary(analysis)
        st.subheader('Root Cause Analysis')
        for root in analysis['root_cause_analyses']:
            root_evidence(root)


