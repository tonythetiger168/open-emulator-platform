"""Prepacking molecules (improvement-plan Phase B item 6; VPR prepacker analogue).

Groups mapped cells into indivisible molecules before CLB packing:

- "lutff": LUT -> exclusive DFF forced pair (classic BLE pattern;
  formalizes what pack.py did implicitly since v0.1 as an explicit,
  inspectable molecule)
- "carry8": ordered carry chain, <= CARRY8_MAX_BITS LUTs per molecule
  (VP1902 CARRY8 spans exactly one CLB). Chains are read from the
  optional `LutNet.carry_chains` annotation; end-to-end activation
  awaits frontend arithmetic inference (the parser subset has no `+`
  yet), so today they are exercised by unit tests building LutNets
  directly. This is an honest framework landing, not fake inference.
- "single": everything else.

pack.py consumes molecules atomically; on designs without carry chains
the resulting packing is bit-identical to v0.10 (guarded by the qor.py
golden, Phase C item 11).
"""

CARRY8_MAX_BITS = 8  # VP1902 CARRY8 primitive: 8 bits, exactly one CLB


class Molecule:
    __slots__ = ("kind", "cells")

    def __init__(self, kind, cells):
        self.kind = kind          # "single" | "lutff" | "carry8"
        self.cells = list(cells)  # carry8: bit order (LSB first)

    @property
    def luts(self):
        return [c for c in self.cells if c.type != "DFF"]

    @property
    def ffs(self):
        return [c for c in self.cells if c.type == "DFF"]

    def __repr__(self):
        return f"Molecule({self.kind}, {len(self.cells)} cells)"


def prepack(mapped):
    """LutNet -> [Molecule]. Order is significant for QoR parity:
    carry8 chains first, then lutff pairs in DFF order, then singles
    (LUTs in netlist order, then DFFs in netlist order) — matching the
    v0.10 pack phase order exactly."""
    luts, dffs = list(mapped.luts), list(mapped.dffs)

    fanout = {}
    for c in luts + dffs:
        for n in c.ins:
            fanout.setdefault(n, []).append(c)
    lut_by_out = {c.out: c for c in luts}
    all_ids = {id(c) for c in luts + dffs}

    molecules = []
    used = set()

    # 1) carry8 chains — indivisible, ordered, capacity-checked
    for chain in getattr(mapped, "carry_chains", []):
        cells = list(chain)
        n_bits = sum(1 for c in cells if c.type != "DFF")
        if n_bits > CARRY8_MAX_BITS:
            raise ValueError(
                f"carry chain of {n_bits} bits exceeds CARRY8 capacity "
                f"{CARRY8_MAX_BITS}; split it upstream (frontend duty)")
        unknown = [c for c in cells if id(c) not in all_ids]
        if unknown:
            raise ValueError("carry chain references cells not in the LutNet")
        dup = [c for c in cells if id(c) in used]
        if dup:
            raise ValueError("cell appears in multiple molecules")
        for c in cells:
            used.add(id(c))
        molecules.append(Molecule("carry8", cells))

    # 2) lutff forced pairs (DFF order preserved for QoR parity)
    for f in dffs:
        if id(f) in used:
            continue
        d = f.ins[0]
        drv = lut_by_out.get(d)
        if (drv is not None and id(drv) not in used
                and len(fanout.get(d, [])) == 1):
            used.add(id(drv))
            used.add(id(f))
            molecules.append(Molecule("lutff", [drv, f]))

    # 3) singles in original order (LUTs, then DFFs)
    for c in luts:
        if id(c) not in used:
            molecules.append(Molecule("single", [c]))
    for c in dffs:
        if id(c) not in used:
            molecules.append(Molecule("single", [c]))
    return molecules


def molecule_stats(molecules):
    """Deterministic one-line summary for reports and QoR tracking."""
    n = {"single": 0, "lutff": 0, "carry8": 0}
    for m in molecules:
        n[m.kind] += 1
    return f"single={n['single']} lutff={n['lutff']} carry8={n['carry8']}"
