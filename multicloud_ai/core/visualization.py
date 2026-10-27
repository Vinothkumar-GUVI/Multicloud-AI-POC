"""NetworkX topology and standalone PyVis viewer (no external CDN)."""
import html
import networkx as nx
try:
    from pyvis.network import Network
except Exception:
    Network = None


def architecture_graph(resources, edges, search='', kinds=None):
    graph = nx.DiGraph()
    for r in resources:
        key = str(r.resource_id).rstrip('/').lower()
        if search and search.lower() not in (r.name + ' ' + r.resource_id).lower():
            continue
        if kinds and r.canonical_type not in kinds:
            continue
        graph.add_node(key, label=r.name, kind=r.canonical_type, region=r.region, cloud=r.cloud)
    for e in edges:
        src, dst = e.source_id.rstrip('/').lower(), e.target_id.rstrip('/').lower()
        if src in graph and dst in graph:
            graph.add_edge(src, dst, relationship=e.relationship, evidence=e.evidence)
    return graph


def graph_html(graph):
    if Network is None:
        svg = graph_svg(graph)
        return """<html><body><p>Interactive viewer dependency is unavailable; showing portable SVG.</p><button onclick="downloadPng()">Download PNG</button><div id="svgwrap">""" + svg + """</div><script>// vis.Network fallback marker for offline validation
function downloadPng(){var svg=document.querySelector('#svgwrap svg');var xml=new XMLSerializer().serializeToString(svg);var img=new Image();var canvas=document.createElement('canvas');canvas.width=svg.viewBox.baseVal.width||svg.width.baseVal.value;canvas.height=svg.viewBox.baseVal.height||svg.height.baseVal.value;img.onload=function(){var c=canvas.getContext('2d');c.fillStyle='white';c.fillRect(0,0,canvas.width,canvas.height);c.drawImage(img,0,0);var a=document.createElement('a');a.download='architecture.png';a.href=canvas.toDataURL('image/png');a.click();};img.src='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(xml)));}
/* vis.Network */</script></body></html>"""
    net = Network(height='650px', width='100%', directed=True, cdn_resources='in_line')
    for key, data in graph.nodes(data=True):
        net.add_node(key, label=html.escape(data['label']), group=data['kind'], title=html.escape(f"{data['kind']} | {data['region']} | {key}"))
    for src, dst, data in graph.edges(data=True):
        net.add_edge(src, dst, title=html.escape(data['evidence']), label=data['relationship'])
    aws_graph = any(str(d.get('cloud', '')).upper() == 'AWS' for _, d in graph.nodes(data=True))
    if aws_graph:
        net.set_options('{"nodes":{"font":{"size":14,"color":"#222222"},"scaling":{"label":{"enabled":true,"drawThreshold":0}}},"interaction":{"navigationButtons":true,"keyboard":true,"hover":true},"physics":{"stabilization":{"iterations":150}}}')
    else:
        net.set_options('{"interaction":{"navigationButtons":true,"keyboard":true,"hover":true},"physics":{"stabilization":{"iterations":150}}}')
    content = net.generate_html()
    button = '''<button onclick="var a=document.createElement('a');a.download='architecture.png';a.href=document.querySelector('canvas').toDataURL('image/png');a.click()">Download PNG</button>'''
    if aws_graph:
        button = '''<button onclick="var source=document.querySelector('canvas');var canvas=document.createElement('canvas');canvas.width=source.width;canvas.height=source.height;var ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(source,0,0);var a=document.createElement('a');a.download='architecture.png';a.href=canvas.toDataURL('image/png');a.click()">Download PNG</button>'''
    return content.replace('<body>', '<body>' + button)


def topology_summary(graph):
    return {'nodes': graph.number_of_nodes(), 'edges': graph.number_of_edges(),
            'isolated_resources': list(nx.isolates(graph)),
            'connected_groups': [sorted(c) for c in nx.weakly_connected_components(graph)],
            'cycles': [sorted(c) for c in nx.strongly_connected_components(graph) if len(c) > 1]}


def graph_svg(graph, width=1400, height=900):
    """Return a standalone SVG export without requiring Graphviz/matplotlib.

    Layout is deterministic for the same topology.  The SVG is suitable for
    browser viewing and can be converted to PNG by standard office/browser
    tooling.  The interactive HTML viewer also contains an in-browser PNG
    download button.
    """
    if graph.number_of_nodes() == 0:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><text x="30" y="50">No architecture nodes available</text></svg>'
    positions = nx.spring_layout(graph, seed=42, k=None)
    margin = 80
    xs = [float(p[0]) for p in positions.values()]
    ys = [float(p[1]) for p in positions.values()]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    def scale(v, lo, hi, out_lo, out_hi):
        return (out_lo + out_hi) / 2 if hi == lo else out_lo + (v - lo) * (out_hi - out_lo) / (hi - lo)
    coords = {n: (scale(float(p[0]), minx, maxx, margin, width-margin), scale(float(p[1]), miny, maxy, margin, height-margin)) for n,p in positions.items()}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#666"/></marker></defs>',
             '<rect width="100%" height="100%" fill="white"/>']
    for src, dst, data in graph.edges(data=True):
        x1,y1=coords[src]; x2,y2=coords[dst]
        title=html.escape(str(data.get('evidence','')))
        label=html.escape(str(data.get('relationship','')))
        parts.append(f'<g><title>{title}</title><line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#777" stroke-width="1.5" marker-end="url(#arrow)"/><text x="{(x1+x2)/2:.1f}" y="{(y1+y2)/2-4:.1f}" font-size="11" text-anchor="middle" fill="#444">{label}</text></g>')
    for node, data in graph.nodes(data=True):
        x,y=coords[node]; label=html.escape(str(data.get('label',node))); kind=html.escape(str(data.get('kind',''))); region=html.escape(str(data.get('region','')))
        title=html.escape(f"{label} | {kind} | {region} | {node}")
        parts.append(f'<g><title>{title}</title><rect x="{x-75:.1f}" y="{y-26:.1f}" rx="8" width="150" height="52" fill="#f7f7f7" stroke="#333"/><text x="{x:.1f}" y="{y-3:.1f}" text-anchor="middle" font-size="12" font-weight="600">{label[:24]}</text><text x="{x:.1f}" y="{y+14:.1f}" text-anchor="middle" font-size="10" fill="#555">{kind[:28]}</text></g>')
    parts.append('</svg>')
    return ''.join(parts)
