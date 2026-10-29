"""Cut-enumeration LUT mapping (ABC / FlowMap style) — improvement plan
Phase A item 5 (v0.7). Replaces greedy cone-merge as the default mapper.

Why: greedy cone-merge only folds a gate into its *single* fanout, so any
reconvergent fanout (a shared subcircuit used twice) forces a LUT boundary
and duplicates nothing — but also merges nothing. Cut enumeration explores
all K-feasible cuts per node, so shared logic can be *duplicated into* each
fanout cone's LUT when that wins (fewer LUTs, less depth), or kept as its own
LUT when sharing wins.

Algorithm:
  1. Enumerate K-feasible cuts per net (leaf = PI / DFF output / const /
     LUT-boundary net), dominated cuts dropped.
  2. FlowMap-style depth labels: label(n) = 1 + min over cuts of max label of
     leaves (boundary nets have label 0).
  3. Selection from required nets (POs, DFF data inputs): pass 1 picks
     min-depth cuts to get ref counts; pass 2 re-picks among depth-preserving
     cuts by area flow  1 + Σ af(leaf)/refs(leaf)  (ABC-style local area
     recovery that never worsens the depth label).
  4. Build LutNet identical in shape to techmap's: one LUT per selected net,
     cone = interior gates between leaves and root (drives lut_init for EDIF).

Dead logic (gates feeding no required net) is naturally dropped — greedy kept
it. Priority cuts (hard cut-count caps) are unnecessary at efc's scale.
"""
from .netlist import CONST0, CONST1
from .techmap import LutNet, MERGEABLE, Cell


def _topo_and_drivers(nl):
    """(cells in topological order, net -> driver cell) for MERGEABLE cells."""
    driver = {}
    for c in nl.cells:
        if c.type in MERGEABLE:
            driver[c.out] = c
    boundary = set(nl.inputs) | {CONST0, CONST1}
    for c in nl.cells:
        if c.type == "DFF":
            boundary.add(c.out)
    labelled = set(boundary)
    topo = []
    pending = [c for c in nl.cells if c.type in MERGEABLE]
    while pending:
        ready = [c for c in pending if all(n in labelled or n not in driver
                                           for n in c.ins)]
        if not ready:            # combinational loop — leave order as-is
            topo.extend(pending)
            break
        for c in ready:
            topo.append(c)
            labelled.add(c.out)
        pending = [c for c in pending if c not in ready]
    return topo, driver, boundary


def enumerate_cuts(nl, k):
    """net -> set of frozenset(leaf nets); only nets driven by MERGEABLE cells.

    PI / DFF-out / const nets are implicit boundaries with the unit cut
    {self}; they never appear as keys.
    """
    topo, driver, boundary = _topo_and_drivers(nl)
    cuts = {}

    def leaf_cuts(net):
        if net in boundary:
            return {frozenset({net})}
        return cuts.get(net, {frozenset({net})})

    for c in topo:
        pools = [leaf_cuts(n) for n in c.ins]
        combos = {frozenset(c.ins)}            # trivial cut: LUT = this gate
        for p0 in pools[0]:
            combos.add(frozenset(p0))
        acc = set(combos)
        for pool in pools[1:]:
            nxt = set()
            for a in acc:
                for b in pool:
                    u = a | b
                    if len(u) <= k:
                        nxt.add(u)
            acc = nxt
        if c.type == "NOT":                    # inverter is free: same leaves
            acc |= {frozenset(p) for p in pools[0]}
        acc = {a for a in acc if 0 < len(a) <= k}
        # drop dominated cuts (a subset cut is never worse)
        keep = set()
        for a in acc:
            if not any(b < a for b in acc):
                keep.add(a)
        cuts[c.out] = keep
    return cuts, driver, boundary


def _depth_labels(nl, cuts, driver, boundary, k):
    label = {n: 0 for n in boundary}
    topo = [c for c in nl.cells if c.type in MERGEABLE]
    for c in topo:
        if c.out not in cuts:
            continue
        best = None
        for cut in cuts[c.out]:
            d = 1 + max((label.get(l, 0) for l in cut), default=0)
            if best is None or d < best:
                best = d
        label[c.out] = best if best is not None else 0
    return label


def _cut_depth(cut, label):
    return 1 + max((label.get(l, 0) for l in cut), default=0)


def cutmap(nl, k: int = 6):
    """K-LUT mapping by cut enumeration. Returns (LutNet, selected) where
    selected = {net: chosen cut} (the mapping decisions, for inspection)."""
    cuts, driver, boundary = enumerate_cuts(nl, k)
    label = _depth_labels(nl, cuts, driver, boundary, k)

    dff_ins = [c.ins[0] for c in nl.cells if c.type == "DFF"]
    required = list(dict.fromkeys(list(nl.outputs) + dff_ins))

    def select(score):
        chosen = {}
        stack = [n for n in required if n not in boundary]
        while stack:
            n = stack.pop()
            if n in chosen or n in boundary or n not in cuts:
                continue
            best, best_key = None, None
            for cut in cuts[n]:
                if _cut_depth(cut, label) > label.get(n, 0):
                    continue                 # never worsen the depth label
                key = score(n, cut)
                if best_key is None or key < best_key:
                    best, best_key = cut, key
            if best is None:
                best = min(cuts[n], key=lambda c: (len(c), sorted(c)))
            chosen[n] = best
            for l in best:
                if l not in boundary and l in cuts:
                    stack.append(l)
        return chosen

    # pass 1: pure depth (tie-break smaller cut) -> ref counts
    sel1 = select(lambda n, cut: (len(cut), sorted(cut)))
    refs = {}
    for n, cut in sel1.items():
        for l in cut:
            refs[l] = refs.get(l, 0) + 1

    # area flow for EVERY mappable net (topo order), via its own depth-optimal
    # cut — not only nets selected in pass 1, or candidate leaves would score
    # 0 and win spuriously.
    aflow = {}
    topo_cells, _, _ = _topo_and_drivers(nl)
    for c in topo_cells:
        n = c.out
        if n not in cuts:
            continue
        best = min((cut for cut in cuts[n]
                    if _cut_depth(cut, label) <= label.get(n, 0)),
                   key=lambda cut: (len(cut), sorted(cut)), default=None)
        if best is None:
            best = min(cuts[n], key=lambda cut: (len(cut), sorted(cut)))
        aflow[n] = 1.0 + sum(aflow.get(l, 0.0) / max(1, refs.get(l, 1))
                             for l in best)

    # pass 2: area flow among depth-preserving cuts
    chosen = select(lambda n, cut: (sum(aflow.get(l, 0.0) / max(1, refs.get(l, 1))
                                        for l in cut), len(cut), sorted(cut)))

    # ---- materialize LutNet (same shape as techmap) ----
    out = LutNet()
    out.inputs, out.outputs = nl.inputs, nl.outputs
    out.net_names = dict(nl.net_names)
    for c in nl.cells:
        if c.type == "DFF":
            out.dffs.append(c)
    for n, cut in chosen.items():
        root = driver[n]
        cone = {n: root}
        stack = [root]
        while stack:
            g = stack.pop()
            for m in g.ins:
                if m in cut or m in boundary:
                    continue               # leaf / boundary: stop descent
                d = driver.get(m)
                if d is not None and m not in cone:
                    cone[m] = d
                    stack.append(d)
        ins = sorted(l for l in cut if l not in (CONST0, CONST1))
        lut = Cell(f"LUT{max(1, len(ins))}", ins, n, root.name)
        out.luts.append(lut)
        out.cones[id(lut)] = cone
    return out, chosen
