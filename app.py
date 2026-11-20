import streamlit as st
from ui.audit_view import render as audit
from ui.memory_view import render as memory
from ui.review_centre import render as review
from core.database import initialize
from ui.command_centre import command_centre
from ui.genome_view import render as genome_view
from ui.incident_investigation import render as investigation
from ui.resolution_centre import render as resolution_centre

st.set_page_config(page_title='Exception Genome', layout='wide')
initialize()
st.session_state.setdefault('running', False)
st.title('Exception Genome')
st.caption('Verified Autonomous Operations | Synthetic proof of concept | Phase 7')
st.sidebar.caption('Synthetic services and evidence. No banking systems connected.')
page = st.sidebar.radio('Workspace', ['Command Centre', 'Exception Genome', 'Incident Investigation', 'Resolution Centre', 'Review Centre', 'Operational Memory', 'Audit Trail'])
st.sidebar.caption('Diagnose → Contract → Govern → Simulate')
{'Command Centre': command_centre, 'Exception Genome': genome_view,
 'Incident Investigation': investigation, 'Resolution Centre': resolution_centre, 'Review Centre': review, 'Operational Memory': memory, 'Audit Trail': audit}[page]()





