"""CLI: single-FPGA compile flow targeting VP1902.

  python -m efc.cli examples/alu4.v --grid 8 --tracks 8 \
      --edif out/alu4.edif --xdc out/alu4.xdc
"""
import argparse, json, sys
from .verilog import parse_verilog
from .netlist import elaborate
from .techmap import techmap, stats
from .pack import pack
from .fabric import build_fabric, utilization, VP1902
from .place import place
from .route import route
from .timing import logic_depth
from .edif import write_edif, write_xdc

def compile_file(path, grid=8, tracks=8, seed=1, edif=None, xdc=None):
    src = open(path, encoding="utf-8").read()
    mod = parse_verilog(src)
    nl = elaborate(mod)
    mapped, _merged = techmap(nl, k=6)          # VP1902 native LUT6
    blocks, ext_nets = pack(mapped)
    fab = build_fabric(grid, tracks, nl.inputs, nl.outputs)
    blk_at, hpwl = place(blocks, ext_nets, fab, seed=seed)

    # routing demands: driver terminal first
    drv_blk = {}
    for i, b in enumerate(blocks):
        for c in b.luts + b.ffs:
            drv_blk[c.out] = i
    def tpos(term):
        kind, ref = term
        return fab.io_pos[ref] if kind == "io" else blk_at[ref]
    demands = {}
    for net, terms in ext_nets.items():
        src_term = None
        for t in terms:
            if (t[0] == "io" and net in set(nl.inputs)) or \
               (t[0] == "blk" and drv_blk.get(net) == t[1]):
                src_term = t
                break
        if src_term is None:
            src_term = terms[0]
        sinks = [tpos(t) for t in terms if t != src_term]
        demands[net] = (tpos(src_term), sinks)
    rr = route(demands, grid, tracks)

    n_luts = len(mapped.luts)
    n_ffs = len(mapped.dffs)
    util = utilization(n_luts, n_ffs)
    rep = {
        "module": mod.name,
        "target": VP1902["part"],
        **stats(nl, mapped, 6),
        "CLB_used": len(blocks),
        "VP1902_LUT6_util_%": round(util["LUT6"], 6),
        "VP1902_FF_util_%": round(util["FF"], 6),
        "fabric": f"{grid}x{grid} CLB(logical), {tracks} tracks/ch",
        "placement_hpwl": hpwl,
        "route_wirelength": rr["wirelength"],
        "route_max_channel": f"{rr['max_channel']}/{tracks}",
        "route_overused_channels": rr["overused"],
        "logic_depth_LUT": logic_depth(mapped),
    }
    if edif:
        write_edif(edif, mod.name, nl, mapped)
        rep["edif"] = edif
    if xdc:
        write_xdc(xdc, nl)
        rep["xdc"] = xdc
    return rep

def main(argv=None):
    ap = argparse.ArgumentParser(prog="efc")
    ap.add_argument("verilog")
    ap.add_argument("--grid", type=int, default=8)
    ap.add_argument("--tracks", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--edif", help="write EDIF 2.0.0 netlist for Vivado")
    ap.add_argument("--xdc", help="write XDC constraints skeleton")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    rep = compile_file(args.verilog, args.grid, args.tracks, args.seed,
                       edif=args.edif, xdc=args.xdc)
    for k, v in rep.items():
        print(f"{k:24s}: {v}")
    if args.json:
        json.dump(rep, open(args.json, "w"), indent=2, ensure_ascii=False)
    return 0 if rep["route_overused_channels"] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
