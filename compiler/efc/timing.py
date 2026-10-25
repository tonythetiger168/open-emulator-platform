"""Static timing analysis: Elmore wire delay + arrival/required/slack/criticality.

Delay model (consumes the arch spec — improvement-plan Phase A item 2):
  - LUT:  t_lut_ns            (arch.clb)
  - DFF:  t_ff_clkq_ns clock-to-Q, t_setup_ns setup
  - wire: per-net HPWL in grid tiles (from placement) -> segment via
          arch.segment_for(hpwl); delay = seg.elmore_ns() * ceil(hpwl/len)

Nets internal to one CLB (LUT->DFF pairs, intra-block) are modeled as 0 ns.
All values are logical-model estimates, NOT silicon-accurate (see arch JSON).
Assumes no combinational loops (guaranteed by the DFF/always structure).

sta() returns per-net arrival / required / slack / criticality so that
timing-driven place & route (Phase A items 3-4) can consume criticality
directly. logic_depth() is kept for reference/regression.
"""
import math
from collections import deque, defaultdict
from .arch import ArchSpec, load_arch


def logic_depth(mapped):
    """Levelize the LUT netlist between registers/IOs (delay-free)."""
    driver = {c.out: c for c in mapped.luts}
    consumers = defaultdict(list)
    indeg = defaultdict(int)
    for c in mapped.luts:
        for n in c.ins:
            if n in driver:
                consumers[n].append(c)
                indeg[id(c)] += 1
    level = defaultdict(int)          # net -> level; PIs/DFF-outs stay 0
    q = deque([c for c in mapped.luts if indeg[id(c)] == 0])
    maxd = 0
    while q:
        c = q.popleft()
        level[c.out] = max([level[n] for n in c.ins], default=0) + 1
        maxd = max(maxd, level[c.out])
        for c2 in consumers[c.out]:
            indeg[id(c2)] -= 1
            if indeg[id(c2)] == 0:
                q.append(c2)
    return maxd


def _net_hpwl(ext_nets, blk_at, io_pos):
    """net -> HPWL in grid tiles (0 for nets not in ext_nets = intra-CLB)."""
    out = {}
    for net, terms in ext_nets.items():
        xs, ys = [], []
        for kind, ref in terms:
            x, y = io_pos[ref] if kind == "io" else blk_at[ref]
            xs.append(x); ys.append(y)
        out[net] = (max(xs) - min(xs)) + (max(ys) - min(ys))
    return out


def wire_delay_ns(hpwl_tiles: int, arch: ArchSpec) -> float:
    """Elmore wire delay for a net spanning `hpwl_tiles` tiles."""
    if hpwl_tiles <= 0:
        return 0.0
    seg = arch.segment_for(hpwl_tiles)
    hops = max(1, math.ceil(hpwl_tiles / seg.length))
    return seg.elmore_ns() * hops


def sta(mapped, ext_nets, blk_at, fab, clock_ns=10.0, arch: ArchSpec = None):
    """Placement-aware STA on the mapped LUT/DFF netlist.

    Returns dict with per-net arrival / required / slack / criticality plus
    critical_path_ns, fmax_mhz, worst_slack_ns, violated.
    """
    arch = arch or fab.arch or load_arch()
    t_lut, t_clkq, t_su = arch.clb.t_lut_ns, arch.clb.t_ff_clkq_ns, arch.clb.t_setup_ns
    hpwl = _net_hpwl(ext_nets, blk_at, fab.io_pos)
    wdel = {n: wire_delay_ns(h, arch) for n, h in hpwl.items()}
    wd = lambda n: wdel.get(n, 0.0)   # intra-CLB nets -> 0

    driver = {}
    for c in mapped.luts + mapped.dffs:
        driver[c.out] = c
    lut_by_out = {c.out: c for c in mapped.luts}
    consumers = defaultdict(list)
    for c in mapped.luts + mapped.dffs:
        for n in c.ins:
            consumers[n].append(c)
    po_nets = set(mapped.outputs)
    pi_nets = set(mapped.inputs)

    # ---- forward: arrival ----
    arr = {}
    for n in pi_nets:
        arr[n] = 0.0
    for c in mapped.dffs:
        arr[c.out] = t_clkq                     # clock-to-Q at register output
    topo = []
    indeg = {id(c): 0 for c in mapped.luts}
    for c in mapped.luts:
        indeg[id(c)] = sum(1 for n in c.ins if n in lut_by_out)
    q = deque([c for c in mapped.luts if indeg[id(c)] == 0])
    while q:
        c = q.popleft()
        topo.append(c)
        arr[c.out] = max((arr.get(n, 0.0) + wd(n)) for n in c.ins) + t_lut
        for c2 in consumers[c.out]:
            if id(c2) in indeg:
                indeg[id(c2)] -= 1
                if indeg[id(c2)] == 0:
                    q.append(c2)
    if len(topo) != len(mapped.luts):
        raise ValueError("combinational loop detected during STA")

    # ---- endpoints: critical path & required ----
    # DFF data inputs must arrive T - t_setup; POs must arrive by T.
    req = {}
    for c in mapped.dffs:
        req[c.ins[0]] = clock_ns - t_su
    for n in po_nets:
        req[n] = min(req.get(n, clock_ns), clock_ns)
    cp = 0.0
    for c in mapped.dffs:
        cp = max(cp, arr.get(c.ins[0], 0.0) + wd(c.ins[0]) + t_su)
    for n in po_nets:
        cp = max(cp, arr.get(n, 0.0) + wd(n))

    # ---- backward: required time ----
    for c in reversed(topo):
        r_out = req.get(c.out, clock_ns)
        for n in c.ins:
            r_in = r_out - t_lut - wd(n)
            req[n] = min(req.get(n, clock_ns), r_in)

    # ---- slack & criticality (VPR-style: crit = 1 - slack/T) ----
    nets = set(arr) | set(req)
    slack = {n: req.get(n, clock_ns) - arr.get(n, 0.0) - wd(n) for n in nets}
    crit = {n: min(1.0, max(0.0, 1.0 - slack[n] / clock_ns)) for n in nets}

    return {
        "arrival": arr,
        "required": req,
        "slack": slack,
        "criticality": crit,
        "wire_delay": wdel,
        "critical_path_ns": round(cp, 4),
        "fmax_mhz": round(1000.0 / cp, 2) if cp > 0 else float("inf"),
        "worst_slack_ns": round(min(slack.values(), default=clock_ns), 4),
        "violated": min(slack.values(), default=clock_ns) < 0,
        "clock_ns": clock_ns,
    }
