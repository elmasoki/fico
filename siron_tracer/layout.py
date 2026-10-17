"""Deterministic force-directed layout for the ER diagram (no JS libraries)."""
from __future__ import annotations

import math
from typing import Dict, Hashable, List, Tuple

Node = Tuple[Hashable, float, float]  # (id, width, height)


def layout(nodes: List[Node], edges: List[Tuple[Hashable, Hashable]], margin: int = 24,
           max_width: int = 1500):
    """Return ({id: (x, y)} top-left positions, width, height).

    Connected groups of tables are laid out separately and packed in rows;
    tables without relations are placed in a grid after them.
    """
    if not nodes:
        return {}, 400, 200
    size = {nd[0]: (nd[1], nd[2]) for nd in nodes}
    parent = {nd[0]: nd[0] for nd in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = [(a, b) for a, b in edges if a in size and b in size and a != b]
    for a, b in edges:
        parent[find(a)] = find(b)
    groups: Dict[Hashable, List[Node]] = {}
    for nd in nodes:
        groups.setdefault(find(nd[0]), []).append(nd)
    blocks = []  # (positions, width, height)
    singles = []
    for members in groups.values():
        if len(members) == 1:
            singles.append(members[0])
            continue
        ids = {m[0] for m in members}
        blocks.append(_force(members, [e for e in edges if e[0] in ids], 0))
    blocks.sort(key=lambda b: -b[2])
    if singles:
        cell_w = max(w for _, w, _ in singles) + 24
        cols = max(1, min(len(singles), int(max(max_width, cell_w) // cell_w)))
        pos = {nd[0]: ((i % cols) * cell_w, (i // cols) * (nd[2] + 24)) for i, nd in enumerate(singles)}
        rows = (len(singles) + cols - 1) // cols
        blocks.append((pos, cols * cell_w - 24, rows * (max(h for _, _, h in singles) + 24) - 24))

    out: Dict[Hashable, Tuple[float, float]] = {}
    x = y = row_h = 0.0
    width = 0.0
    for pos, w, h in blocks:
        if x > 0 and x + w > max_width:
            x, y, row_h = 0.0, y + row_h + 48, 0.0
        for nid, (px, py) in pos.items():
            out[nid] = (round(px + x + margin, 1), round(py + y + margin, 1))
        x += w + 48
        row_h = max(row_h, h)
        width = max(width, x - 48)
    return out, int(width + 2 * margin), int(y + row_h + 2 * margin)


def _force(nodes: List[Node], edges, margin: int):
    n = len(nodes)
    ids = [nd[0] for nd in nodes]
    size = {nd[0]: (nd[1], nd[2]) for nd in nodes}
    if n > 150:  # too many for O(n^2) iterations in Python: simple grid
        cols = int(math.ceil(math.sqrt(n)))
        cell_w = max(w for _, w, _ in nodes) + 30
        pos = {nid: ((i % cols) * cell_w + margin, (i // cols) * 80 + margin) for i, nid in enumerate(ids)}
        return pos, cols * cell_w + 2 * margin, (n // cols + 1) * 80 + 2 * margin

    avg_w = sum(w for _, w, _ in nodes) / n
    area = (avg_w + 40) * 95 * n
    k = math.sqrt(area / n)
    radius = k * math.sqrt(n) / 2
    pos = {nid: [radius * math.cos(2 * math.pi * i / n), radius * math.sin(2 * math.pi * i / n)]
           for i, nid in enumerate(ids)}
    edge_list = [(a, b) for a, b in edges if a in pos and b in pos and a != b]
    iterations = 300 if n < 40 else 150 if n < 100 else 80
    temp = k * 2
    for _ in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in ids}
        for i in range(n):
            a = ids[i]
            ax, ay = pos[a]
            for j in range(i + 1, n):
                b = ids[j]
                dx, dy = ax - pos[b][0], ay - pos[b][1]
                d2 = dx * dx + dy * dy or 0.01
                f = k * k / d2
                disp[a][0] += dx * f
                disp[a][1] += dy * f
                disp[b][0] -= dx * f
                disp[b][1] -= dy * f
        for a, b in edge_list:
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) or 0.01
            f = d / k
            disp[a][0] -= dx * f
            disp[a][1] -= dy * f
            disp[b][0] += dx * f
            disp[b][1] += dy * f
        for nid in ids:
            x, y = pos[nid]
            disp[nid][0] -= x * 0.03  # gravity keeps unconnected tables close
            disp[nid][1] -= y * 0.03
            dx, dy = disp[nid]
            d = math.sqrt(dx * dx + dy * dy) or 0.01
            step = min(d, temp)
            pos[nid][0] += dx / d * step
            pos[nid][1] += dy / d * step
        temp = max(temp * 0.97, k * 0.02)

    # rotate so the longest spread is horizontal (screens are wider than tall)
    cx = sum(pos[i][0] for i in ids) / n
    cy = sum(pos[i][1] for i in ids) / n
    sxx = sum((pos[i][0] - cx) ** 2 for i in ids)
    syy = sum((pos[i][1] - cy) ** 2 for i in ids)
    sxy = sum((pos[i][0] - cx) * (pos[i][1] - cy) for i in ids)
    angle = -0.5 * math.atan2(2 * sxy, sxx - syy)
    ca, sa = math.cos(angle), math.sin(angle)
    for i in ids:
        x, y = pos[i][0] - cx, pos[i][1] - cy
        pos[i] = [x * ca - y * sa, (x * sa + y * ca) * 0.8]

    # remove overlaps between boxes
    for _ in range(60):
        moved = False
        for i in range(n):
            a = ids[i]
            for j in range(i + 1, n):
                b = ids[j]
                (wa, ha), (wb, hb) = size[a], size[b]
                dx = pos[b][0] - pos[a][0]
                dy = pos[b][1] - pos[a][1]
                ox = (wa + wb) / 2 + 24 - abs(dx)
                oy = (ha + hb) / 2 + 24 - abs(dy)
                if ox > 0 and oy > 0:
                    moved = True
                    if ox / (wa + wb) < oy / (ha + hb):
                        shift = ox / 2 * (1 if dx >= 0 else -1)
                        pos[a][0] -= shift
                        pos[b][0] += shift
                    else:
                        shift = oy / 2 * (1 if dy >= 0 else -1)
                        pos[a][1] -= shift
                        pos[b][1] += shift
        if not moved:
            break

    min_x = min(pos[i][0] - size[i][0] / 2 for i in ids)
    min_y = min(pos[i][1] - size[i][1] / 2 for i in ids)
    out = {i: (round(pos[i][0] - size[i][0] / 2 - min_x + margin, 1),
               round(pos[i][1] - size[i][1] / 2 - min_y + margin, 1)) for i in ids}
    width = max(out[i][0] + size[i][0] for i in ids) + margin
    height = max(out[i][1] + size[i][1] for i in ids) + margin
    return out, int(width), int(height)
