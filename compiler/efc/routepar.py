"""Spatial-partition parallel routing (improvement-plan Phase B item 8, v0.13).

VTR 9's AIR router parallelized routing with flat (non-hierarchical) route
trees + spatial partitioning, cutting routing time ~2.4x. This module is the
efc analogue on the unit grid:

  1. Partition the grid into `bins` vertical strips (x ranges).
  2. Classify nets: LOCAL = src + all sinks inside one strip; GLOBAL =
     crosses a strip boundary.
  3. Route GLOBAL nets sequentially first (they own the cut edges — the
     AIR lesson: only flat nets are embarrassingly parallel).
  4. Route each strip's LOCAL nets in worker processes (multiprocessing),
     each seeded with the global nets' edge occupancy (occ0) so a local net
     routes around already-occupied channels instead of colliding.
  5. Merge occupancy. Any overuse (local nets fighting each other or the
     globals) -> documented fallback to the full sequential PathFinder —
     the answer is then identical to route() by construction.

Honest scoping: the shipped benchmarks are tiny (grid 8-15), so this is a
correctness-first framework, not a measured speedup claim — runtime is
machine-dependent and the QoR golden never asserts it. The win shows up when
design scale grows (the plan defers this item 「設計規模上來後再做」; the
framework lands now so scale-up needs no new code).

Determinism: bin assignment, net classification, and per-bin net order are
all deterministic; Pool.map preserves task order, so repeated runs with the
same inputs produce bit-identical results (asserted in tests).

Public API: route_par().
"""
import os
from multiprocessing import Pool

from .route import route, _edge


def _bin_of(x, edges):
    """Strip index for column x. `edges`: right boundary column of each strip."""
    for b, hi in enumerate(edges):
        if x <= hi:
            return b
    return len(edges) - 1


def _classify(demands, n, bins):
    """net -> bin index (local) or None (global). bins = number of strips."""
    # strip b covers x in [b*W, (b+1)*W - 1]; W = ceil(n / bins)
    w = -(-n // bins)
    edges = [min((b + 1) * w - 1, n - 1) for b in range(bins)]
    cls = {}
    for net, (src, sinks) in demands.items():
        b = _bin_of(src[0], edges)
        cls[net] = b if all(_bin_of(s[0], edges) == b for s in sinks) else None
    return cls, edges


def _route_bin(task):
    """Worker: route one strip's local nets on top of the global occ.

    task = (net_list, demands, n, tracks, crit, arch, occ0)
    Returns (net -> edges, expanded, occ_local).
    """
    net_list, demands, n, tracks, crit, arch, occ0 = task
    sub = {net: demands[net] for net in net_list}
    crit_sub = {net: crit.get(net, 0.5) for net in net_list} if crit else None
    r = route(sub, n, tracks, crit=crit_sub, arch=arch, occ0=occ0)
    return r["routes"], r["expanded_nodes"], r["max_channel"]


def route_par(demands, n, tracks, bins=4, workers=None, crit=None, arch=None,
              max_iter=12):
    """Parallel PathFinder: globals sequential, locals per-strip parallel.

    Returns the same dict as route() plus route_mode/route_par_* fields.
    Any post-merge overuse falls back to sequential route() (reported as
    route_par_fallback=True).
    """
    if bins < 2:
        raise ValueError("bins must be >= 2 (bins=1 is sequential routing)")
    if not demands:
        return {"routes": {}, "max_channel": 0, "tracks": tracks,
                "overused": 0, "wirelength": 0, "expanded_nodes": 0,
                "route_mode": "par", "route_par_bins": bins,
                "route_par_global": 0, "route_par_local": 0,
                "route_par_fallback": False}

    cls, _edges = _classify(demands, n, bins)
    globals_ = [net for net in demands if cls[net] is None]
    local_by_bin = {}
    for net in demands:
        if cls[net] is not None:
            local_by_bin.setdefault(cls[net], []).append(net)

    # 1) global nets sequentially (they own the cut edges)
    g = route({net: demands[net] for net in globals_}, n, tracks,
              crit=crit, arch=arch, max_iter=max_iter) if globals_ else \
        {"routes": {}, "expanded_nodes": 0, "max_channel": 0}
    occ_global = {}
    for edges in g["routes"].values():
        for e in edges:
            occ_global[e] = occ_global.get(e, 0) + 1

    # 2) local nets per strip, in parallel
    tasks = [(nets, demands, n, tracks, crit, arch, occ_global)
             for b, nets in sorted(local_by_bin.items()) if nets]
    if workers is None:
        workers = min(len(tasks), os.cpu_count() or 1)
    results = Pool(workers).map(_route_bin, tasks) if len(tasks) > 1 else \
        [_route_bin(t) for t in tasks]

    routes = dict(g["routes"])
    expanded = g["expanded_nodes"]
    occ = dict(occ_global)
    for (bin_routes, bin_expanded, _mc), (nets, *_rest) in zip(results, tasks):
        routes.update(bin_routes)
        expanded += bin_expanded
        for edges in bin_routes.values():
            for e in edges:
                occ[e] = occ.get(e, 0) + 1

    overused = sum(1 for o in occ.values() if o > tracks)
    fallback = overused > 0
    if fallback:
        # documented fallback: full sequential PathFinder, identical to
        # the non-parallel flow by construction
        seq = route(demands, n, tracks, max_iter=max_iter, crit=crit, arch=arch)
        seq.update({"route_mode": "par", "route_par_bins": bins,
                    "route_par_global": len(globals_),
                    "route_par_local": len(demands) - len(globals_),
                    "route_par_fallback": True})
        return seq

    return {"routes": routes, "max_channel": max(occ.values(), default=0),
            "tracks": tracks, "overused": 0,
            "wirelength": sum(len(v) for v in routes.values()),
            "expanded_nodes": expanded,
            "route_mode": "par", "route_par_bins": bins,
            "route_par_global": len(globals_),
            "route_par_local": len(demands) - len(globals_),
            "route_par_fallback": False}
