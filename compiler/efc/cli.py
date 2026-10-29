"""CLI: single-FPGA compile flow, device described by a data-driven arch spec.

  python -m efc.cli examples/alu4.v --grid 8 --tracks 8 \
      --arch vp1902 --edif out/alu4.edif --xdc out/alu4.xdc
"""
import argparse, json, sys
from .verilog import parse_verilog
from .netlist import elaborate
from .techmap import techmap, stats
from .pack import pack
from .arch import load_arch, DEFAULT_ARCH
from .fabric import build_fabric, utilization
from .place import place
from .route import route
from .timing import logic_depth, sta
from .edif import write_edif, write_xdc

def compile_file(path, grid=8, tracks=8, seed=1, edif=None, xdc=None,
                 arch=DEFAULT_ARCH, clock_ns=10.0, mapper="cut", lec=False,
                 xc7=None):
    spec = load_arch(arch) if not hasattr(arch, "envelope") else arch
    src = open(path, encoding="utf-8").read()
    mod = parse_verilog(src)
    nl = elaborate(mod)
    mapped, _sel = techmap(nl, k=spec.clb.lut_k, method=mapper)  # LUT-K from arch
    lec_res = None
    if lec:
        from .lec import run_lec
        lec_res = run_lec(nl, mapped)
    blocks, ext_nets = pack(mapped)
    fab = build_fabric(grid, tracks, nl.inputs, nl.outputs, arch=spec)
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

    # placement-aware STA (Elmore wire delay from arch spec) — runs pre-route
    # so the A* router can consume per-net criticality (VPR-style flow).
    st = sta(mapped, ext_nets, blk_at, fab, clock_ns=clock_ns, arch=spec)
    rr = route(demands, grid, tracks, crit=st["criticality"], arch=spec)

    n_luts = len(mapped.luts)
    n_ffs = len(mapped.dffs)
    util = utilization(n_luts, n_ffs, arch=spec)
    rep = {
        "module": mod.name,
        "arch": spec.name,
        "mapper": mapper,
        "target": spec.part,
        **stats(nl, mapped, spec.clb.lut_k),
        "CLB_used": len(blocks),
        f"{spec.name.upper()}_LUT6_util_%": round(util["LUT6"], 6),
        f"{spec.name.upper()}_FF_util_%": round(util["FF"], 6),
        "fabric": f"{grid}x{grid} CLB(logical), {tracks} tracks/ch, "
                  f"sb={spec.switch_block.type}(Fs={spec.switch_block.fs})",
        "placement_hpwl": hpwl,
        "route_wirelength": rr["wirelength"],
        "route_max_channel": f"{rr['max_channel']}/{tracks}",
        "route_overused_channels": rr["overused"],
        "route_expanded_nodes": rr["expanded_nodes"],
        "logic_depth_LUT": logic_depth(mapped),
    }
    if lec_res is not None:
        rep["lec"] = (lec_res["status"] if lec_res["status"] != "proven"
                      else f"proven ({lec_res['proven']}/{lec_res['total']} equiv cells)")
        if lec_res["status"] == "skipped":
            rep["lec"] = "skipped (yosys not found)"
    rep.update({
        "clock_ns": clock_ns,
        "critical_path_ns": st["critical_path_ns"],
        "est_fmax_mhz": st["fmax_mhz"],
        "worst_slack_ns": st["worst_slack_ns"],
        "timing_violated": st["violated"],
    })
    if edif:
        write_edif(edif, mod.name, nl, mapped)
        rep["edif"] = edif
    if xdc:
        write_xdc(xdc, nl, clock_period_ns=clock_ns)
        rep["xdc"] = xdc
    if xc7:
        from .xc7out import write_xc7
        write_xc7(xc7, mapped, mod.name)
        rep["xc7"] = xc7
    return rep

def main(argv=None):
    ap = argparse.ArgumentParser(prog="efc")
    ap.add_argument("verilog")
    ap.add_argument("--grid", type=int, default=8)
    ap.add_argument("--tracks", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--clock", type=float, default=10.0,
                    help="clock period in ns for STA and XDC create_clock")
    ap.add_argument("--arch", default=DEFAULT_ARCH,
                    help="arch name in compiler/arch/ or path to a JSON spec")
    ap.add_argument("--mapper", default="cut", choices=["cut", "greedy"],
                    help="LUT mapper: cut-enumeration (default) or legacy greedy cone-merge")
    ap.add_argument("--lec", action="store_true",
                    help="prove netlist vs mapped LUTs with Yosys equiv (needs yosys)")
    ap.add_argument("--edif", help="write EDIF 2.0.0 netlist for Vivado")
    ap.add_argument("--xdc", help="write XDC constraints skeleton")
    ap.add_argument("--xc7", help="write 7-series primitive Verilog (LUTn/FDRE/IBUF/OBUF) "
                                  "for the OpenXC7/nextpnr-xilinx Vivado-free flow")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    rep = compile_file(args.verilog, args.grid, args.tracks, args.seed,
                       edif=args.edif, xdc=args.xdc, arch=args.arch,
                       clock_ns=args.clock, mapper=args.mapper, lec=args.lec,
                       xc7=args.xc7)
    for k, v in rep.items():
        print(f"{k:24s}: {v}")
    if args.json:
        json.dump(rep, open(args.json, "w"), indent=2, ensure_ascii=False)
    ok = rep["route_overused_channels"] == 0 and not rep["timing_violated"]
    if args.lec:
        # "failed"/"error" block the build; "skipped" (no yosys) is reported
        # in the lec line but must not fake-fail a clean compile.
        lec_status = str(rep.get("lec", ""))
        ok = ok and not (lec_status.startswith("failed") or lec_status.startswith("error"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
