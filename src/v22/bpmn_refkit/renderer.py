"""Standalone SVG preview (DI remains the authoritative editable output)."""
from __future__ import annotations
import textwrap
from pathlib import Path
from .model import TAG_EVENT, TAG_GATE, TAG_DOC

def svg_render(path, root, shape_bounds, nodes, docs, seq, assocs, paths, lane_names, lane_bands, profile):
    """Self contained SVG preview, not a substitute for opening BPMN in a BPMN viewer."""
    import html
    bx = max(max((x + w for x, y, w, h in shape_bounds.values())), max((x for ps in paths.values() for x, y in ps), default=0)) + 170
    by = max(max((y + h for x, y, w, h in shape_bounds.values())), max((y for ps in paths.values() for x, y in ps), default=0)) + 95

    def esc(x):
        return html.escape(str(x or ''))
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {bx:.0f} {by:.0f}" width="{bx:.0f}" height="{by:.0f}">', '<defs><marker id="arr" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto-start-reverse"><path d="M0 0 L8 4.5 L0 9" fill="none" stroke="#364556" stroke-width="1.2"/></marker><marker id="assocArr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0 L7 4 L0 8" fill="none" stroke="#5995b9" stroke-width="1"/></marker></defs>', f'<rect x="0" y="0" width="{bx}" height="{by}" fill="#ffffff"/>', f"""<text x="84" y="57" font-size="25" font-family="Arial,sans-serif" font-weight="bold" fill="#233850">{esc(profile.get('title', 'BPMN — автоматическая и ручная компоновка'))}</text>"""]
    palette = ['#eff6ff', '#fff', '#f0faf5', '#fff9f2']
    for i, (lane, (y1, y2)) in enumerate(lane_bands.items()):
        lines.append(f'<rect x="70" y="{y1}" width="{bx - 120}" height="{y2 - y1}" fill="{palette[i % 4]}" stroke="#d3dfe8" stroke-width="2"/>')
        lname = lane_names.get(lane, lane)
        mid = (y1 + y2) / 2
        lines.append(f'<text x="94" y="{mid:.1f}" transform="rotate(-90 94 {mid:.1f})" text-anchor="middle" font-size="22" font-family="Arial" fill="#43586d" font-weight="bold">{esc(lname)}</text>')
    seq_lookup = {n: name for n, u, v, name in seq}
    for eid, u, v, d in assocs:
        p = paths.get(eid)
        if not p:
            continue
        points = ' '.join((f'{x},{y}' for x, y in p))
        lines.append(f'<polyline points="{points}" stroke="#6aa1c3" stroke-width="2" stroke-dasharray="6,5" fill="none"' + (' marker-end="url(#assocArr)"' if d != 'None' else '') + '/>')
    for eid, u, v, name in seq:
        p = paths.get(eid)
        if not p:
            continue
        points = ' '.join((f'{x},{y}' for x, y in p))
        lines.append(f'<polyline points="{points}" stroke="#33495c" stroke-width="2.3" fill="none" marker-end="url(#arr)"/>')
        if name and len(name) < 25 and (len(p) >= 2):
            a, b = (p[0], p[1])
            xx = (a[0] + b[0]) / 2
            yy = (a[1] + b[1]) / 2
            lines.append(f'<text x="{xx + 4}" y="{yy - 6}" font-size="12" font-family="Arial" fill="#9b5b2d">{esc(name)}</text>')
    for nid, o in nodes.items():
        if nid not in shape_bounds:
            continue
        x, y, w, h = shape_bounds[nid]
        kind = o['kind']
        name = o.get('name', '')
        if kind in TAG_GATE:
            cx = x + w / 2
            cy = y + h / 2
            lines.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" fill="#fff8e8" stroke="#a8762e" stroke-width="2"/>')
            lines.append(f'<text x="{cx}" y="{cy + 7}" text-anchor="middle" font-family="Arial" font-size="25" fill="#a8762e">×</text>')
            if name:
                chunks = textwrap.wrap(name, 26)
                for k, t in enumerate(chunks[:3]):
                    lines.append(f'<text x="{cx}" y="{y - 8 - (len(chunks) - k - 1) * 14}" text-anchor="middle" font-family="Arial" font-size="13" fill="#825b36">{esc(t)}</text>')
        elif kind in TAG_EVENT:
            cx = x + w / 2
            cy = y + h / 2
            color = '#3e9870' if kind == 'startEvent' else '#cc655a'
            lines.append(f'<circle cx="{cx}" cy="{cy}" r="{min(w, h) / 2 - 2}" fill="white" stroke="{color}" stroke-width="3"/>')
            if name:
                for k, t in enumerate(textwrap.wrap(name, 25)[:3]):
                    lines.append(f'<text x="{x + w + 8}" y="{y + 15 + k * 14}" font-size="12" font-family="Arial" fill="#43586d">{esc(t)}</text>')
        else:
            lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="white" stroke="#33556b" stroke-width="2"/>')
            if kind in ['callActivity', 'subProcess']:
                lines.append(f'<rect x="{x + 5}" y="{y + 5}" width="{w - 10}" height="{h - 10}" rx="9" fill="none" stroke="#33556b" stroke-width="1"/>')
            chars = int(max(16, (w - 12) / 8.7))
            chunks = textwrap.wrap(name, chars, break_long_words=False, break_on_hyphens=False)
            fs = 14 if len(chunks) <= 3 else 12
            for k, t in enumerate(chunks[:5]):
                ty = y + h / 2 - (len(chunks) - 1) * fs * 0.54 + k * fs * 1.12 + 4
                lines.append(f'<text x="{x + w / 2}" y="{ty:.1f}" text-anchor="middle" font-size="{fs}" font-family="Arial" fill="#20384b">{esc(t)}</text>')
    for nid, o in docs.items():
        if nid not in shape_bounds:
            continue
        x, y, w, h = shape_bounds[nid]
        if o['kind'] == 'dataStoreReference':
            lines.append(f'<ellipse cx="{x + w / 2}" cy="{y + 8}" rx="{w / 2}" ry="7" stroke="#4c98bc" fill="#e6f7ff"/><rect x="{x}" y="{y + 8}" width="{w}" height="{h - 16}" fill="#e6f7ff" stroke="#4c98bc"/><ellipse cx="{x + w / 2}" cy="{y + h - 8}" rx="{w / 2}" ry="7" stroke="#4c98bc" fill="#e6f7ff"/>')
        else:
            lines.append(f'<path d="M{x} {y} H{x + w - 12} L{x + w} {y + 12} V{y + h} H{x} Z" fill="#ffffff" stroke="#5a98b9" stroke-width="2"/><path d="M{x + w - 12} {y} V{y + 12} H{x + w}" fill="none" stroke="#5a98b9" stroke-width="1.7"/>')
        nm = o.get('name', '')
        s = textwrap.wrap(nm, 23)[:2]
        for k, t in enumerate(s):
            lines.append(f'<text x="{x + w / 2}" y="{y + h + 13 + k * 12}" text-anchor="middle" font-size="10.5" font-family="Arial" fill="#426a81">{esc(t)}</text>')
    lines.append('</svg>')
    Path(path).write_text('\n'.join(lines), encoding='utf-8')
