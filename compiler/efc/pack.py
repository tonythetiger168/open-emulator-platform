"""CLB packing for VP1902: each CLB (Versal slice) = 8 x LUT6 + 16 x FF.

Strategy: pair a LUT with the DFF it exclusively drives (LUT->DFF same CLB,
the classic BLE pattern), then first-fit bin-pack remaining cells into CLBs,
preferring blocks that share nets.
"""
from dataclasses import dataclass, field

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
    luts, dffs = list(mapped.luts), list(mapped.dffs)

    # net -> consuming cells, and net -> driving cell
    fanout = {}
    for c in luts + dffs:
        for n in c.ins:
            fanout.setdefault(n, []).append(c)
    lut_by_out = {c.out: c for c in luts}

    blocks = []
    used_lut, used_ff = set(), set()

    # 1) LUT->DFF exclusive pairs
    for f in dffs:
        d = f.ins[0]
        drv = lut_by_out.get(d)
        if drv is not None and len(fanout.get(d, [])) == 1:
            b = Block([drv], [f])
            blocks.append(b)
            used_lut.add(id(drv)); used_ff.add(id(f))
    # 2) remaining cells
    rest_luts = [c for c in luts if id(c) not in used_lut]
    rest_ffs = [c for c in dffs if id(c) not in used_ff]

    def nets_of(b):
        s = set()
        for c in b.luts + b.ffs:
            s.update(c.ins); s.add(c.out)
        return s

    for c in rest_luts:
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
    for c in rest_ffs:
        best = None
        for b in blocks:
            if b.fits(ff_add=1):
                best = b
                break
        if best is None:
            best = Block()
            blocks.append(best)
        best.ffs.append(c)

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
