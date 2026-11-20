import json
import networkx as nx
import plotly.graph_objects as go


def build_graph(services):
    graph = nx.DiGraph()
    for service in services:
        graph.add_node(service['id'], **service)
    for service in services:
        for upstream in json.loads(service['dependencies']):
            graph.add_edge(upstream, service['id'])
    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError('Service dependencies must form a directed acyclic graph')
    return graph


def figure(services):
    graph = build_graph(services)
    domains = ['Shared Infrastructure', 'Payments', 'Reconciliation', 'Reporting', 'Customer Operations']
    positions = {}
    for column, domain in enumerate(domains):
        members = [s for s in services if s['domain'] == domain]
        for row, service in enumerate(members):
            positions[service['id']] = (column * 3, -row * 1.7)
    fig = go.Figure()
    for source, target in graph.edges:
        x0, y0 = positions[source]
        x1, y1 = positions[target]
        affected = graph.nodes[source]['status'] != 'HEALTHY'
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode='lines',
                                line=dict(color='#a34b59' if affected else '#344252', width=1),
                                hoverinfo='skip', showlegend=False))
    colors = {'HEALTHY':'#41be96','FAILED':'#ef5969','DEGRADED':'#e3b452','RECOVERING':'#62a8ef','UNKNOWN':'#94a3b8'}
    for status, color in colors.items():
        members = [s for s in services if s['status'] == status]
        if not members:
            continue
        fig.add_trace(go.Scatter(
            x=[positions[s['id']][0] for s in members], y=[positions[s['id']][1] for s in members],
            mode='markers+text', name=status,
            marker=dict(color=color, size=[24 if s['id']=='datahub' else 13 for s in members], line=dict(width=2,color='#111827')),
            text=[s['name'].replace(' ', '<br>', 1) for s in members], textposition='bottom center',
            textfont=dict(size=10), customdata=[s['id'] for s in members],
            hovertext=[f"{s['name']}<br>{status}<br>Upstream: {', '.join(graph.predecessors(s['id'])) or 'None'}<br>Downstream: {', '.join(graph.successors(s['id'])) or 'None'}" for s in members],
            hoverinfo='text'))
    fig.update_layout(template='plotly_dark', height=620, paper_bgcolor='#101722', plot_bgcolor='#101722',
                      margin=dict(l=30,r=30,t=45,b=30), legend=dict(orientation='h',y=-.04),
                      xaxis=dict(visible=False,range=[-1.2,13.5]), yaxis=dict(visible=False,range=[-14,1.5]),
                      uirevision='service-topology', annotations=[dict(x=i*3,y=1,text=d,showarrow=False,font=dict(size=11)) for i,d in enumerate(domains)])
    return fig


def analytical_figure(services, root_candidate):
    graph = build_graph(services)
    generations = list(nx.topological_generations(graph))
    positions = {node:((index-(len(layer)-1)/2)*2,-depth*3)
                 for depth,layer in enumerate(generations) for index,node in enumerate(sorted(layer))}
    fig = go.Figure()
    for source,target in graph.edges:
        x0,y0 = positions[source]
        x1,y1 = positions[target]
        fig.add_annotation(x=x1,y=y1,ax=x0,ay=y0,xref='x',yref='y',axref='x',ayref='y',
                           showarrow=True,arrowhead=2,arrowsize=1,arrowwidth=1,arrowcolor='#53647a',standoff=12)
    categories = [('ROOT CAUSE CANDIDATE','#ef5969'),('AFFECTED SERVICE','#e3b452'),('UNAFFECTED SERVICE','#41be96')]
    for category,color in categories:
        members = [s for s in services if ('ROOT CAUSE CANDIDATE' if s['id']==root_candidate else 'UNAFFECTED SERVICE' if s['status']=='HEALTHY' else 'AFFECTED SERVICE')==category]
        fig.add_trace(go.Scatter(x=[positions[s['id']][0] for s in members],y=[positions[s['id']][1] for s in members],
                      text=[s['name'].replace(' ','<br>',1) for s in members],mode='markers+text',name=category,
                      textposition='bottom center',textfont=dict(size=10),
                      marker=dict(size=28 if category=='ROOT CAUSE CANDIDATE' else 13,color=color),
                      hovertext=[s['name']+' | '+s['status'] for s in members],hoverinfo='text'))
    fig.update_layout(template='plotly_dark',height=720,xaxis=dict(visible=False),yaxis=dict(visible=False),
                      legend=dict(orientation='h',y=1.1),margin=dict(t=70,b=60),
                      title='Causal direction: upstream → downstream')
    return fig
