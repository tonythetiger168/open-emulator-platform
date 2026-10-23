"""PathFinder-style negotiated-congestion routing on the CLB grid graph.

Input demands: net -> (src_xy, [sink_xy, ...]); grid nodes are CLB coords,
4-neighbour edges with capacity = tracks. Rip-up & re-route all nets per
iteration with history penalties until no overuse (or max_iter).
"""
from collections import deque

def _neigh(p, n):
    x, y = p
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        q = (x + dx, y + dy)
        if 0 <= q[0] < n and 0 <= q[1] < n:
            yield q

def route(demands, n, tracks, max_iter=12):
    hist = {}
    pres_fac = 1.0
    final = None
    for _ in range(max_iter):
        occ = {}
        routes = {}
        for net, (src, sinks) in demands.items():
            tree = {src}
            edges_used = []
            for sink in sinks:
                path = _bfs(tree, sink, n, occ, hist, tracks, pres_fac)
                if path is None:
                    path = _bfs(tree, sink, n, {}, {}, tracks, 0.0)  # fallback
                for a, b in zip(path, path[1:]):
                    e = (a, b) if a <= b else (b, a)
                    edges_used.append(e)
                    occ[e] = occ.get(e, 0) + 1
                tree.update(path)
            routes[net] = edges_used
        over = {e: o - tracks for e, o in occ.items() if o > tracks}
        final = (routes, occ, len(over))
        if not over:
            break
        for e in over:
            hist[e] = hist.get(e, 0) + over[e]
        pres_fac *= 1.6
    total_wl = sum(len(v) for v in final[0].values())
    return {"routes": final[0], "max_channel": max(final[1].values(), default=0),
            "tracks": tracks, "overused": final[2], "wirelength": total_wl}

def _bfs(tree, sink, n, occ, hist, tracks, pres_fac):
    seen = {p: None for p in tree}
    q = deque(tree)
    while q:
        p = q.popleft()
        if p == sink:
            path = []
            while p is not None:
                path.append(p)
                p = seen[p]
            return path[::-1]
        for nb in _neigh(p, n):
            if nb not in seen:
                seen[nb] = p
                q.append(nb)
    return None
