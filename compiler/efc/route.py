"""Timing-driven PathFinder routing: A* directed search with lookahead.

Improvement-plan Phase A item 3 (v0.5): the previous router expanded nodes in
pure BFS order (VTR 8 removed its BFS router entirely — breadth-first routing
is a proven dead end). This router is a VPR-style timing-driven PathFinder:

  edge_cost(e, net) = crit(net) * delay_norm(e)
                      + (1 - crit(net)) * base_cost * penalty(e)
  penalty(e)        = 1 + pres_fac * max(0, occ(e) + 1 - cap) + hist(e)

  - crit(net) in [0,1] comes from timing.sta() (VPR-style 1 - slack/T).
    Critical nets (crit -> 1) pay mostly the delay term: on the unit grid the
    per-hop delay is uniform, so they take minimum-hop paths and ignore
    congestion. Non-critical nets (crit -> 0) pay the congestion term and
    route around overused channels. This is exactly the VPR timing-driven
    trade-off.
  - A* lookahead = Manhattan distance to the sink x minimum possible per-hop
    cost (admissible: real per-hop cost >= lookahead rate), so the search is
    directed at the sink instead of expanding breadth-first.

Rip-up & re-route all nets per iteration; history penalties accumulate on
overused edges and pres_fac grows geometrically until no overuse (or
max_iter). Falls back to penalty-free A* for any sink that cannot reach its
target under congestion costs.

Input demands: net -> (src_xy, [sink_xy, ...]); grid nodes are CLB coords,
4-neighbour edges with capacity = tracks.
"""
import heapq

def _neigh(p, n):
    x, y = p
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        q = (x + dx, y + dy)
        if 0 <= q[0] < n and 0 <= q[1] < n:
            yield q

def _edge(a, b):
    return (a, b) if a <= b else (b, a)

def _delay_norm(arch):
    """Per-hop delay weight on the unit grid, normalized so L1 hop = 1.0.

    Edges are unit-length, so every hop uses the shortest segment; the value
    is kept arch-derived (not a magic constant) so future switch-block /
    segment-aware costs slot in here. Returns 1.0 when no arch is given.
    """
    if arch is None:
        return 1.0
    seg = arch.segment_for(1)
    e = seg.elmore_ns()
    return e / e if e > 0 else 1.0     # = 1.0, documented derivation point

def _astar(tree, sink, n, occ, hist, tracks, pres_fac, delay_w, crit_w):
    """A* from any node of `tree` (multi-source) to `sink`.

    Returns (path, expanded_count) or (None, expanded_count).
    Per-hop cost = crit_w * delay_w + (1 - crit_w) * penalty(edge);
    lookahead = manhattan * min_per_hop, min_per_hop = crit_w * delay_w
    (congestion penalty >= 0 keeps the heuristic admissible).
    """
    min_per_hop = crit_w * delay_w

    def h(p):
        return (abs(p[0] - sink[0]) + abs(p[1] - sink[1])) * min_per_hop

    g = {p: 0.0 for p in tree}
    came = {p: None for p in tree}
    heap = [(h(p), i, p) for i, p in enumerate(tree)]
    heapq.heapify(heap)
    cnt = len(tree)
    expanded = 0
    while heap:
        f, _, p = heapq.heappop(heap)
        if f > g[p] + h(p) + 1e-12:
            continue                              # stale heap entry
        expanded += 1
        if p == sink:
            path = []
            while p is not None:
                path.append(p)
                p = came[p]
            return path[::-1], expanded
        for nb in _neigh(p, n):
            e = _edge(p, nb)
            over = max(0, occ.get(e, 0) + 1 - tracks)
            pen = 1.0 + pres_fac * over + hist.get(e, 0.0)
            w = crit_w * delay_w + (1.0 - crit_w) * pen
            ng = g[p] + w
            if ng < g.get(nb, float("inf")) - 1e-12:
                g[nb] = ng
                came[nb] = p
                heapq.heappush(heap, (ng + h(nb), cnt, nb))
                cnt += 1
    return None, expanded

def route(demands, n, tracks, max_iter=12, crit=None, arch=None):
    """PathFinder with A* directed search.

    crit: net -> criticality in [0,1] from timing.sta(); defaults to 0.5
    (neutral delay/congestion mix) for nets without timing data.
    arch: ArchSpec for the per-hop delay weight (unit grid -> 1.0).
    Returns routes/max_channel/tracks/overused/wirelength plus
    expanded_nodes (search effort — the A* vs BFS runtime metric).
    """
    delay_w = _delay_norm(arch)
    hist = {}
    pres_fac = 1.0
    final = None
    expanded_total = 0
    for _ in range(max_iter):
        occ = {}
        routes = {}
        for net, (src, sinks) in demands.items():
            crit_w = min(1.0, max(0.0, (crit or {}).get(net, 0.5)))
            tree = {src}
            edges_used = []
            for sink in sinks:
                path, ex = _astar(tree, sink, n, occ, hist, tracks,
                                  pres_fac, delay_w, crit_w)
                expanded_total += ex
                if path is None:                  # penalty-free fallback
                    path, ex = _astar(tree, sink, n, {}, {}, tracks,
                                      0.0, delay_w, 1.0)
                    expanded_total += ex
                for a, b in zip(path, path[1:]):
                    e = _edge(a, b)
                    edges_used.append(e)
                    occ[e] = occ.get(e, 0) + 1
                tree.update(path)
            routes[net] = edges_used
        over = {e: o - tracks for e, o in occ.items() if o > tracks}
        final = (routes, occ, len(over))
        if not over:
            break
        for e in over:
            hist[e] = hist.get(e, 0.0) + over[e]
        pres_fac *= 1.6
    total_wl = sum(len(v) for v in final[0].values())
    return {"routes": final[0], "max_channel": max(final[1].values(), default=0),
            "tracks": tracks, "overused": final[2], "wirelength": total_wl,
            "expanded_nodes": expanded_total}
