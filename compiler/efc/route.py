"""PathFinder-style negotiated-congestion routing on the CLB grid graph.

Nodes are CLB coordinates; edges between 4-neighbours have capacity = tracks.
IO pads attach to their perimeter coordinate. Multi-pin nets route as a tree:
sinks in order of distance to the already-routed partial tree.
"""
from collections import deque

def _neigh(p, n):
    x, y = p
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        q = (x + dx, y + dy)
        if 0 <= q[0] < n and 0 <= q[1] < n:
            yield q

def route(nets, cells, cell_at, io_pos, n, tracks, max_iter=12):
    # terminal positions
    def tpos(term):
        kind, ref = term
        return io_pos[ref] if kind == "io" else cell_at[ref]

    # build routing demands: net -> (src_pos, [sink_pos,...])
    demands = {}
    for net, terms in nets.items():
        srcs = [t for t in terms if _is_driver(net, t, cells, cell_at, io_pos)]
        sinks = [t for t in terms if t not in srcs]
        if not srcs:                       # undriven net (e.g. PI->PO pass)
            srcs, sinks = terms[:1], terms[1:]
        demands[net] = ([tpos(srcs[0])], [tpos(t) for t in sinks])

    hist = {}                              # edge -> history penalty
    pres_fac = 1.0
    final = None
    for it in range(max_iter):
        occ = {}
        routes = {}
        for net, (srcs, sinks) in demands.items():
            tree = set(srcs)
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

def _is_driver(net, term, cells, cell_at, io_pos):
    kind, ref = term
    if kind == "io":
        # an IO is a driver iff the net is a PI (we can't tell here; caller
        # puts PIs first). Heuristic: treat io as driver when no cell drives.
        return not any(c.out == net for c in cells)
    return cells[ref].out == net

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
                e = (p, nb) if p <= nb else (nb, p)
                o = occ.get(e, 0)
                _cost = 1 + hist.get(e, 0) + (pres_fac * max(0, o + 1 - tracks))
                seen[nb] = p
                q.append(nb)
    return None
