"""CLI: run the full single-FPGA compile flow on a Verilog file.

  python -m efc.cli examples/alu4.v --lut-k 4 --grid 10 --tracks 8 --json out.json
"""
import argparse, json, sys
from .verilog import parse_verilog
from .netlist import elaborate
from .techmap import techmap, stats
from .fabric import build_fabric
from .place import place
from .route import route
from .timing import logic_depth

def compile_file(path, lut_k=4, grid=10, tracks=8, seed=1):
    src = open(path, encoding="utf-8").read()
    mod = parse_verilog(src)
    nl = elaborate(mod)
    mapped, _merged = techmap(nl, k=lut_k)
    fab = build_fabric(grid, tracks, len(nl.inputs), len(nl.outputs),
                       nl.inputs, nl.outputs)
    cell_at, hpwl, nets, cells = place(mapped, fab, seed=seed)
    rr = route(nets, cells, cell_at, fab.io_pos, grid, tracks)
    rep = {
        "module": mod.name,
        **stats(nl, mapped, lut_k),
        "fabric": f"{grid}x{grid} CLB, {tracks} tracks/ch",
        "placement_hpwl": hpwl,
        "route_wirelength": rr["wirelength"],
        "route_max_channel": f"{rr['max_channel']}/{tracks}",
        "route_overused_channels": rr["overused"],
        "logic_depth_LUT": logic_depth(mapped),
    }
    return rep

def main(argv=None):
    ap = argparse.ArgumentParser(prog="efc")
    ap.add_argument("verilog")
    ap.add_argument("--lut-k", type=int, default=4)
    ap.add_argument("--grid", type=int, default=10)
    ap.add_argument("--tracks", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    rep = compile_file(args.verilog, args.lut_k, args.grid, args.tracks, args.seed)
    for k, v in rep.items():
        print(f"{k:24s}: {v}")
    if args.json:
        json.dump(rep, open(args.json, "w"), indent=2, ensure_ascii=False)
    return 0 if rep["route_overused_channels"] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
