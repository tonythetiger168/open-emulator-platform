"""QoR regression tracking (improvement-plan Phase C item 11).

Runs a benchmark corpus (compiler/benchmarks/*.v) through the full efc
flow and tracks the VTR-style golden QoR metrics — CPD, wirelength,
area, runtime — so a change that fixes A but breaks B is caught by
`python -m efc.qor --check` (exit 1 on any deterministic drift).

Deterministic metrics (exact match against golden): LUTs, DFF, PI, PO,
molecules (prepack summary), CLB_used, logic_depth_LUT,
critical_path_ns, placement_hpwl, route_wirelength, route_max_channel,
route_overused_channels, route_expanded_nodes, lec status. runtime_s is
recorded and reported with drift %, but NEVER asserted
(machine-dependent). LEC is part of the golden record; a "skipped"
current run (no yosys) is neutral, never a fake pass nor a fake
regression.

Grid sizing: fabric IO capacity is 2*grid slots per direction class, so
each benchmark gets grid = max(8, ceil(max(PI,PO)/2) + 2) — deterministic,
recorded in the metrics, and identical between --update and --check.

Usage:
  python -m efc.qor --update            # record golden.json (run on a
                                        #  known-good tree, with yosys)
  python -m efc.qor --check             # compare vs golden.json (default)
  python -m efc.qor --json out.json     # dump current metrics
"""
import json, math, os, sys, time

from .verilog import parse_verilog
from .netlist import elaborate
from .cli import compile_file

BENCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "benchmarks")
GOLDEN = os.path.join(BENCH_DIR, "golden.json")

DETERMINISTIC = ["LUTs", "DFF", "PI", "PO", "molecules", "CLB_used",
                 "logic_depth_LUT", "critical_path_ns", "placement_hpwl",
                 "route_wirelength", "route_max_channel",
                 "route_overused_channels", "route_expanded_nodes", "lec"]
CP_TOL = 1e-12  # ns; float ops are deterministic, allow only repr noise


def auto_grid(path):
    """Deterministic grid size from the design's PI/PO counts."""
    nl = elaborate(parse_verilog(open(path, encoding="utf-8").read()))
    need = max(len(nl.inputs), len(nl.outputs))
    return max(8, math.ceil(need / 2) + 2)


def run_one(path, arch="vp1902", clock_ns=10.0, lec=True):
    """Compile one benchmark and collect QoR metrics."""
    grid = auto_grid(path)
    t0 = time.perf_counter()
    rep = compile_file(path, grid=grid, tracks=8, arch=arch,
                       clock_ns=clock_ns, lec=lec)
    dt = time.perf_counter() - t0
    m = {k: rep[k] for k in DETERMINISTIC if k in rep}
    m["lec"] = str(rep.get("lec", "off"))
    m["grid"] = grid
    m["runtime_s"] = round(dt, 4)
    return m


def run_corpus(bench_dir=BENCH_DIR, **kw):
    out = {}
    for f in sorted(os.listdir(bench_dir)):
        if f.endswith(".v"):
            out[f[:-2]] = run_one(os.path.join(bench_dir, f), **kw)
    return out


def compare(golden, current):
    """Return a list of violation strings ([] = clean, no regression)."""
    bad = []
    for name in sorted(set(golden) | set(current)):
        if name not in golden:
            bad.append(f"{name}: new benchmark not in golden "
                       f"(record it with --update)")
            continue
        if name not in current:
            bad.append(f"{name}: missing from current run")
            continue
        g, c = golden[name], current[name]
        for k in DETERMINISTIC:
            if k not in g or k not in c:
                continue
            if k == "lec":
                if str(c[k]).startswith("skipped"):
                    continue  # no yosys here: honest skip, neutral
                if not str(c[k]).startswith(str(g[k]).split(" ")[0]):
                    bad.append(f"{name}.lec: {g[k]} -> {c[k]}")
                continue
            if k == "critical_path_ns":
                if abs(float(c[k]) - float(g[k])) > CP_TOL:
                    bad.append(f"{name}.{k}: {g[k]} -> {c[k]}")
                continue
            if c[k] != g[k]:
                bad.append(f"{name}.{k}: {g[k]} -> {c[k]}")
    return bad


def drift_report(golden, current):
    """Human-readable runtime drift lines (never asserted)."""
    out = []
    for name in sorted(set(golden) & set(current)):
        g = golden[name].get("runtime_s")
        c = current[name].get("runtime_s")
        if g and c:
            out.append(f"{name}: runtime {g:.4f}s -> {c:.4f}s "
                       f"({100.0 * (c - g) / g:+.1f}%)")
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="efc.qor")
    ap.add_argument("--bench-dir", default=BENCH_DIR)
    ap.add_argument("--golden", default=GOLDEN)
    ap.add_argument("--arch", default="vp1902")
    ap.add_argument("--clock", type=float, default=10.0)
    ap.add_argument("--no-lec", action="store_true")
    ap.add_argument("--update", action="store_true",
                    help="record current metrics as the golden reference")
    ap.add_argument("--check", action="store_true",
                    help="compare against golden (default action)")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    current = run_corpus(args.bench_dir, arch=args.arch,
                         clock_ns=args.clock, lec=not args.no_lec)
    if args.json:
        json.dump(current, open(args.json, "w"), indent=2, ensure_ascii=False)

    for name, m in sorted(current.items()):
        print(f"{name:12s}: LUTs={m['LUTs']} depth={m['logic_depth_LUT']} "
              f"CP={m['critical_path_ns']}ns wl={m['route_wirelength']} "
              f"hpwl={m['placement_hpwl']} lec={m['lec']} "
              f"({m['runtime_s']}s, grid {m['grid']})")

    if args.update:
        json.dump(current, open(args.golden, "w"), indent=2, ensure_ascii=False)
        print(f"golden recorded: {args.golden} ({len(current)} benchmarks)")
        return 0

    if not os.path.isfile(args.golden):
        print(f"no golden reference at {args.golden} — run --update first",
              file=sys.stderr)
        return 2
    golden = json.load(open(args.golden))
    bad = compare(golden, current)
    for line in drift_report(golden, current):
        print(line)
    if bad:
        print("QoR REGRESSIONS:", file=sys.stderr)
        for v in bad:
            print(f"  {v}", file=sys.stderr)
        return 1
    print(f"QoR check OK: {len(current)} benchmarks match golden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
