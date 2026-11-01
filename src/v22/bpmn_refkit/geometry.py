"""Single source of truth for geometry metrics and collision detection."""
from __future__ import annotations
from collections import Counter, defaultdict

def segment_intersection(a, b, c, d):
    (x1, y1), (x2, y2) = (a, b)
    (u1, v1), (u2, v2) = (c, d)
    if abs(y1 - y2) < 1e-05 and abs(u1 - u2) < 1e-05:
        return min(x1, x2) + 0.5 < u1 < max(x1, x2) - 0.5 and min(v1, v2) + 0.5 < y1 < max(v1, v2) - 0.5
    if abs(x1 - x2) < 1e-05 and abs(v1 - v2) < 1e-05:
        return min(u1, u2) + 0.5 < x1 < max(u1, u2) - 0.5 and min(y1, y2) + 0.5 < v1 < max(y1, y2) - 0.5
    return False

def segment_overlap(a, b, c, d):
    (x1, y1), (x2, y2) = (a, b)
    (u1, v1), (u2, v2) = (c, d)
    if x1 == x2 == u1 == u2:
        return max(0, min(max(y1, y2), max(v1, v2)) - max(min(y1, y2), min(v1, v2)))
    if y1 == y2 == v1 == v2:
        return max(0, min(max(x1, x2), max(u1, u2)) - max(min(x1, x2), min(u1, u2)))
    return 0.0

def point_port(src, tgt):
    x, y, w, h = src
    tx, ty, tw, th = tgt
    dx = tx + tw / 2 - (x + w / 2)
    dy = ty + th / 2 - (y + h / 2)
    if abs(dx) > abs(dy) * 0.66:
        if dx >= 0:
            return ((x + w, y + h / 2), (tx, ty + th / 2))
        else:
            return ((x, y + h / 2), (tx + tw, ty + th / 2))
    if dy >= 0:
        return ((x + w / 2, y + h), (tx + tw / 2, ty))
    return ((x + w / 2, y), (tx + tw / 2, ty + th))

def compress(pts):
    out = []
    for p in pts:
        p = (round(float(p[0]), 2), round(float(p[1]), 2))
        if not out or p != out[-1]:
            out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1:i + 2]
        if a[0] == b[0] == c[0] or a[1] == b[1] == c[1]:
            out.pop(i)
        else:
            i += 1
    return out

def geometry_audit(boxes, paths, seq, assocs, nodes, docs):
    shape_ov = []
    shape_items = [(k, v) for k, v in boxes.items() if k in nodes or k in docs]
    for i, (a, (x, y, w, h)) in enumerate(shape_items):
        for b, (xx, yy, ww, hh) in shape_items[i + 1:]:
            if min(x + w, xx + ww) - max(x, xx) > 0.01 and min(y + h, yy + hh) - max(y, yy) > 0.01:
                shape_ov.append((a, b))
    flow_ids = {a for a, _, _, _ in seq}
    assoc_ids = {a for a, _, _, _ in assocs}
    c = Counter()
    examples = defaultdict(list)
    edge_list = [(k, v) for k, v in paths.items() if len(v) > 1]
    for i, (a, pa) in enumerate(edge_list):
        for b, pb in edge_list[i + 1:]:
            for s, t in zip(pa, pa[1:]):
                for q, r in zip(pb, pb[1:]):
                    if segment_intersection(s, t, q, r):
                        if a in flow_ids and b in flow_ids:
                            kind = 'flow_flow'
                        elif a in assoc_ids and b in assoc_ids:
                            kind = 'association_association'
                        else:
                            kind = 'flow_association'
                        c[kind] += 1
                        if len(examples[kind]) < 20:
                            examples[kind].append([a, b])
                    if segment_overlap(s, t, q, r) > 2:
                        c['overlapping_segments'] += 1
                        if len(examples['overlapping_segments']) < 20:
                            examples['overlapping_segments'].append([a, b])
    through = []
    id_to_uv = {id: (u, v) for id, u, v, _ in seq + assocs}
    for a, pa in edge_list:
        u, v = id_to_uv[a]
        for ob, box in shape_items:
            if ob in (u, v):
                continue
            if any((bbox_intersect_seg(box, s, t, clearance=1) for s, t in zip(pa, pa[1:]))):
                through.append((a, ob))
    bends = sum((max(0, len(p) - 2) for p in paths.values()))
    main_lengths = [sum((abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(paths[id], paths[id][1:]))) for id in flow_ids if id in paths]
    doc_lengths = [sum((abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(paths[id], paths[id][1:]))) for id in assoc_ids if id in paths]
    return {'shape_overlaps': len(shape_ov), 'shape_overlap_examples': shape_ov[:30], 'line_through_shapes': len(through), 'line_through_examples': through[:25], 'crossings': dict(c), 'crossing_examples': dict(examples), 'total_bends': bends, 'avg_flow_length': round(sum(main_lengths) / len(main_lengths), 2) if main_lengths else 0, 'avg_document_length': round(sum(doc_lengths) / len(doc_lengths), 2) if doc_lengths else 0, 'document_references': len(docs), 'flow_count': len(flow_ids), 'association_count': len(assoc_ids)}

def bbox_intersect_seg(box, a, b, clearance=0):
    """Correct segment-rectangle geometry for reference diagrams with diagonal associations.

    The v16 helper assumed that every non-orthogonal line intersects EVERY box,
    causing false-positive 'edge through node' diagnostics in real references.
    Liang-Barsky clipping with interior-midpoint test fixes that bias without
    requiring optional geometric packages.
    """
    x, y, w, h = box
    l = x + clearance
    r = x + w - clearance
    t = y + clearance
    bot = y + h - clearance
    if l >= r or t >= bot:
        return False
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if abs(dx) < 1e-08 and abs(dy) < 1e-08:
        return l < a[0] < r and t < a[1] < bot
    p = (-dx, dx, -dy, dy)
    q = (a[0] - l, r - a[0], a[1] - t, bot - a[1])
    enter = 0.0
    leave = 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return False
            continue
        val = qi / pi
        if pi < 0:
            enter = max(enter, val)
        else:
            leave = min(leave, val)
        if enter > leave:
            return False
    if leave - enter <= 1e-09:
        return False
    middle = (enter + leave) / 2.0
    px = a[0] + dx * middle
    py = a[1] + dy * middle
    return l + 1e-08 < px < r - 1e-08 and t + 1e-08 < py < bot - 1e-08

def metric_length(path):
    return sum((abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(path, path[1:])))
