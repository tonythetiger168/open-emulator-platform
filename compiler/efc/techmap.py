"""Technology mapping: generic gates -> LUT6 (VP1902 CLB slice native).

Default (v0.7): cut-enumeration mapping in cutmap.py (ABC/FlowMap style).
method="greedy" keeps the original cone-merge for A/B measurement: a gate
merges into its single fanout LUT when the combined input count fits K.
Both produce the same LutNet shape with cone bookkeeping so every surviving
LUT can produce its INIT truth table for EDIF/unisim output.
"""
from .netlist import Netlist, Cell, CONST0, CONST1

MERGEABLE = {"AND2", "OR2", "XOR2", "NOT", "MUX2"}


def techmap(nl: Netlist, k: int = 6, method: str = "cut"):
    """Map generic gates to K-LUTs. method: "cut" (default) or "greedy"."""
    if method == "greedy":
        return _techmap_greedy(nl, k)
    from .cutmap import cutmap
    return cutmap(nl, k)

class LutNet:
    def __init__(self):
        self.luts = []        # Cell: type 'LUTK', ins (boundary nets), out
        self.dffs = []
        self.inputs = []
        self.outputs = []
        self.net_names = {}
        self.cones = {}       # id(lut cell) -> {net: driver gate Cell} inside cone

def _techmap_greedy(nl: Netlist, k: int = 6):
    """Original greedy cone-merge (kept for A/B via method="greedy")."""
    fanout = {}
    for c in nl.cells:
        for n in c.ins:
            fanout.setdefault(n, []).append(c)

    lut_in = {id(c): set(c.ins) for c in nl.cells if c.type in MERGEABLE}
    # cone membership: survivor cell id -> {internal net: driver cell}
    cone = {id(c): {} for c in nl.cells if c.type in MERGEABLE}
    surv_of = {}            # absorbed cell id -> survivor cell id

    merged_into = {}
    po_nets = set(nl.outputs)
    changed = True
    while changed:
        changed = False
        for c in reversed(nl.cells):
            if c.type not in MERGEABLE or id(c) in merged_into:
                continue
            if c.out in po_nets:
                continue               # never absorb a net that reaches a PO
            outs = fanout.get(c.out, [])
            real_outs = [f for f in outs if f.type in MERGEABLE and id(f) not in merged_into]
            if len(real_outs) == 1 and len(outs) == 1:
                f = real_outs[0]
                union = (lut_in[id(f)] | lut_in[id(c)]) - {c.out}
                if len(union) <= k:
                    lut_in[id(f)] = union
                    # fold c's cone into f, keyed by output nets
                    fc = cone[id(f)]
                    fc[c.out] = c
                    for n, drv in cone[id(c)].items():
                        fc[n] = drv
                    merged_into[id(c)] = id(f)
                    fanout[c.out] = []
                    changed = True

    out = LutNet()
    out.inputs, out.outputs = nl.inputs, nl.outputs
    out.net_names = dict(nl.net_names)
    for c in nl.cells:
        if c.type == "DFF":
            out.dffs.append(c)
        elif c.type in MERGEABLE:
            if id(c) in merged_into:
                continue
            ins = sorted(n for n in lut_in[id(c)] if n not in (CONST0, CONST1))
            n_in = max(1, len(ins))
            lut = Cell(f"LUT{n_in}", ins, c.out, c.name)
            out.luts.append(lut)
            cc = dict(cone[id(c)])
            cc[c.out] = c            # survivor's own gate drives the LUT output
            out.cones[id(lut)] = cc
    return out, merged_into

# ---------- INIT truth-table computation ----------
def _eval_gate(t, v):
    if t == "AND2": return v[0] & v[1]
    if t == "OR2":  return v[0] | v[1]
    if t == "XOR2": return v[0] ^ v[1]
    if t == "NOT":  return (~v[0]) & 1
    if t == "MUX2": return v[1] if v[0] else v[2]   # sel ? a : b
    raise ValueError(t)

def lut_init(lut: Cell, cone: dict) -> str:
    """INIT as an uppercase hex string covering 2^len(ins) entries."""
    ins = lut.ins
    idx = {n: i for i, n in enumerate(ins)}

    def val(net, bits):
        if net in idx:
            return (bits >> idx[net]) & 1
        if net == CONST0: return 0
        if net == CONST1: return 1
        drv = cone[net]
        return _eval_gate(drv.type, [val(n, bits) for n in drv.ins])

    init = 0
    for bits in range(1 << len(ins)):
        if val(lut.out, bits):
            init |= 1 << bits
    width_hex = max(1, (1 << len(ins)) // 4)
    return f"{init:0{width_hex}X}"

def stats(nl: Netlist, mapped, k):
    return {
        "gates_in": len(nl.cells),
        "LUTs": len(mapped.luts),
        "DFF": len(mapped.dffs),
        "PI": len(nl.inputs),
        "PO": len(nl.outputs),
    }
