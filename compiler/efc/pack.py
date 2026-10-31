"""CLB packing for VP1902: each CLB (Versal slice) = 8 x LUT6 + 16 x FF.

v0.11: consumes prepack molecules (efc/prepack.py) atomically — lutff
forced pairs and carry8 chains seed their own CLB block, single cells
first-fit by shared nets (LUTs scored by net sharing, FFs first-fit).
On designs without carry chains the packing is bit-identical to v0.10
(guarded by the qor.py golden).
"""
from dataclasses import dataclass, field

from .prepack import prepack

CLB_LUTS, CLB_FFS = 8, 16

@dataclass
class Block:
    luts: list = field(default_factory=list)
    ffs: list = field(default_factory=list)

    def fits(self, lut_add=0, ff_add=0):
        return (len(self.luts) + lut_add <= CLB_LUTS
                and len(self.ffs) + ff_add <= CLB_FFS)

def pack(mapped):
    """-> (blocks, ext_nets)
    ext_nets: net id -> [('blk', i) | ('io', net), ...]  (driver first)."""
    return pack_molecules(prepack(mapped), mapped)

def pack_molecules(molecules, mapped):
    blocks = []

    def nets_of(b):
        s = set()
        for c in b.luts + b.ffs:
            s.update(c.ins); s.add(c.out)
        return s

    for m in molecules:
        if m.kind in ("lutff", "carry8"):
            blocks.append(Block(list(m.luts), list(m.ffs)))
            continue
        c = m.cells[0]  # single
        if c.type == "DFF":
            best = None
            for b in blocks:
                if b.fits(ff_add=1):
                    best = b
                    break
            if best is None:
                best = Block()
                blocks.append(best)
            best.ffs.append(c)
        else:
            best, best_share = None, 0
            cn = set(c.ins) | {c.out}
            for b in blocks:
                if b.fits(lut_add=1):
                    share = len(cn & nets_of(b))
                    if share > best_share:
                        best, best_share = b, share
            if best is None:
                best = Block()
                blocks.append(best)
            best.luts.append(c)

    # external nets (internal CLB nets = driven and consumed inside one block)
    cell_blk = {}
    for i, b in enumerate(blocks):
        for c in b.luts + b.ffs:
            cell_blk[id(c)] = i
    ext = {}
    for i, b in enumerate(blocks):
        for c in b.luts + b.ffs:
            for n in c.ins:
                ext.setdefault(n, []).append(("blk", i))
            ext.setdefault(c.out, []).append(("blk", i))
    for n in mapped.inputs + mapped.outputs:
        ext.setdefault(n, []).append(("io", n))
    # drop nets internal to a single block and dangling nets
    ext = {k: v for k, v in ext.items()
           if len({t for t in v}) >= 2}
    return blocks, ext
