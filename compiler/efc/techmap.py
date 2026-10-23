"""Technology mapping: generic gates -> K-LUTs (Synplify 'mapper' analogue).

Simple greedy cone-merge: a gate merges into its single fanout LUT when the
combined input count fits K. DFFs are never merged. Constants are dropped
(const propagation into LUT truth handled later; here they just occupy inputs
and get pruned by mapper when possible).
"""
from .netlist import Netlist, Cell, CONST0, CONST1

MERGEABLE = {"AND2", "OR2", "XOR2", "NOT", "MUX2"}

class LutNet:
    def __init__(self):
        self.luts = []     # Cell-like: type 'LUTK', ins, out
        self.dffs = []
        self.inputs = []
        self.outputs = []
        self.net_names = {}

def techmap(nl: Netlist, k: int = 4):
    # fanout of each net
    fanout = {}
    for c in nl.cells:
        for n in c.ins:
            fanout.setdefault(n, []).append(c)

    # initial LUT input sets for mergeable cells
    lut_in = {id(c): set(c.ins) for c in nl.cells if c.type in MERGEABLE}

    merged_into = {}       # cell id -> survivor cell id
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
                    merged_into[id(c)] = id(f)
                    # redirect fanout bookkeeping: c's net now driven inside f
                    fanout[c.out] = []     # consumed internally
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
            ins = [n for n in lut_in[id(c)] if n not in (CONST0, CONST1)]
            out.luts.append(Cell(f"LUT{k}", sorted(ins), c.out, c.name))
    return out, merged_into

def stats(nl: Netlist, mapped, k):
    luts, dffs = mapped.luts, mapped.dffs
    return {
        "gates_in": len(nl.cells),
        f"LUT{k}": len(luts),
        "DFF": len(dffs),
        "PI": len(nl.inputs),
        "PO": len(nl.outputs),
    }
