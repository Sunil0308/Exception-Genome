import streamlit as st
from services.workflow import analyse, ready
from core.correlation_engine import WEIGHTS

def analysis_control(state, incident_id=None):
    from core.analysis import load
    incident_id = incident_id or state['incidents'][0]['id']
    roots = load(incident_id=incident_id)['root_cause_analyses']
    if roots and all(root.get('analysis_id') for root in roots):
        return
    if st.button('Analyse Exception Genomes',type='primary',disabled=not ready(state, incident_id)):
        with st.status('Analysing operational evidence...',expanded=True) as status:
            analyse(incident_id, progress=st.write)
            status.update(label='Analysis complete',state='complete')
        st.rerun()
    if not ready(state, incident_id):
        st.caption('Complete propagation in Command Centre before running analysis.')

def summary(analysis):
    clusters = analysis['correlation_clusters']
    roots = analysis['root_cause_analyses']
    if not roots:
        return
    with st.container(border=True):
        columns = st.columns([3,1,3,1,3])
        columns[0].metric('OPERATIONAL EXCEPTIONS',sum(len(c['members']) for c in clusters))
        columns[1].markdown('## →')
        columns[2].metric('CORRELATED CLUSTERS',len(clusters))
        columns[3].markdown('## →')
        columns[4].metric('ROOT CAUSE CANDIDATES',len(roots))
        st.markdown('**' + roots[0]['root_cause_service'] + '** · ' + roots[0]['root_cause'])
        st.caption(f"{roots[0].get('incident_id', 'Incident')} | DIAGNOSED | Correlation {clusters[0]['score']:.1f}/100 | Operationally unresolved")

def scores(cluster):
    st.caption('Deterministic evidence score; not a calibrated statistical probability. History: NO_HISTORY.')
    st.dataframe([{'Signal':key.replace('_',' ').title(),'Points':round(value,2),'Maximum':WEIGHTS[key]}
                  for key,value in cluster['signals'].items()],hide_index=True,width='stretch')
    st.metric('Correlation',f"{cluster['score']:.1f} / 100")
    with st.expander('Inspect member-to-first-failure comparisons'):
        st.dataframe([{'Exception':p['b'],'Seconds apart':p['gap_seconds'],**p['signals'],'Total':p['score']}
                      for p in cluster['pair_evidence']],hide_index=True,width='stretch')

def root_evidence(root):
    st.subheader(root['root_cause_service'])
    st.write(root['root_cause'])
    st.metric('Root-cause evidence score',f"{root['confidence']*100:.1f} / 100")
    st.dataframe([{'Evidence':k,'Points':round(v,2),'Maximum':m} for (k,v),m in zip(root['confidence_breakdown'].items(),[35,20,20,15,10])],hide_index=True)
    st.caption('Contradictions awards at most 8/10: absence of observed contradiction is not proof. Scores are heuristic, not probabilities.')
    left,right = st.columns(2)
    with left:
        st.markdown('**Supporting evidence**')
        for evidence in root['supporting_evidence']:
            st.write('• ' + evidence)
    with right:
        st.markdown('**Conflicting evidence**')
        for evidence in root['conflicting_evidence']:
            st.write('• ' + evidence)
        if not root['conflicting_evidence']:
            st.write('No contradictions observed in the available synthetic evidence.')
        st.markdown('**Alternative hypotheses**')
        for alternative in root['alternative_hypotheses']:
            st.markdown('**' + alternative['hypothesis'] + '**')
            st.write(alternative['evidence_against'])
    with st.expander('Candidate ranking and causal chains'):
        st.dataframe([{'Service':r['service'],'Score':round(r['score'],2),'Counter-evidence':'; '.join(r['conflicts'])} for r in root['candidate_ranking']],hide_index=True)
        for chain in root['causal_chain']:
            st.write(' → '.join(chain['path']) + ' | ' + chain['timestamp'][11:])
    st.warning('RECOMMENDATION ONLY — NOT AUTHORISED FOR EXECUTION')
    st.write(root['recommended_action'])
    st.caption('Risk: NOT ASSESSED · DETERMINISTIC DEMO MODE')






