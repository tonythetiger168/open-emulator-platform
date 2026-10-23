"""EDIF 2 0 0 + XDC writers — the real-device path into Vivado (xcvp1902).

EDIF references unisim-style primitives from an external `hdi_primitives`
library (the same convention Synplify EDIF uses; Vivado links LUTn/FDRE
against its unisim library). Bus ports are flattened to scalars and renamed
back to `name[i]` via EDIF `rename`.
"""
import re
from .techmap import lut_init

def _legal(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not s or s[0].isdigit():
        s = "n_" + s
    return s

def _port_name(net, net_names):
    raw = net_names.get(net, f"n{net}")
    return _legal(raw), raw

def write_edif(path, design, nl, mapped):
    nn = dict(nl.net_names)
    lines = []
    w = lines.append
    w(f"(edif {_legal(design)}")
    w("  (edifVersion 2 0 0)")
    w("  (edifLevel 0)")
    w("  (keywordMap (keywordLevel 0))")
    w('  (status (written (timeStamp 2026 10 23 0 0 0) (program "efc" (version "0.2.0"))))')

    # external primitive library
    w("  (external hdi_primitives (edifLevel 0) (technology (numberDefinition))")
    for k in range(1, 7):
        ins = " ".join(f"(port I{i} (direction INPUT))" for i in range(k))
        w(f"    (cell LUT{k} (cellType GENERIC) (view v (viewType NETLIST) (interface {ins} (port O (direction OUTPUT)))))")
    w("    (cell FDRE (cellType GENERIC) (view v (viewType NETLIST) (interface (port D (direction INPUT)) (port C (direction INPUT)) (port Q (direction OUTPUT)))))")
    w("  )")

    # instance naming
    inst = {}
    for i, c in enumerate(mapped.luts):
        inst[id(c)] = (f"LUT_{i}", c.type)
    for i, c in enumerate(mapped.dffs):
        inst[id(c)] = (f"FD_{i}", "FDRE")

    # net terminal collector: net -> list of portRef strings
    term = {}
    for net in nl.inputs + nl.outputs:
        legal, raw = _port_name(net, nn)
        ref = f"(portRef {legal})" if legal == raw else f"(portRef (rename {legal} \"{raw}\"))"
        term.setdefault(net, []).append(ref)
    for c in mapped.luts:
        name, _ = inst[id(c)]
        for j, n in enumerate(c.ins):
            term.setdefault(n, []).append(f"(instanceRef {name} (portRef I{j}))")
        term.setdefault(c.out, []).append(f"(instanceRef {name} (portRef O))")
    for c in mapped.dffs:
        name, _ = inst[id(c)]
        term.setdefault(c.ins[0], []).append(f"(instanceRef {name} (portRef D))")
        term.setdefault(c.ins[1], []).append(f"(instanceRef {name} (portRef C))")
        term.setdefault(c.out, []).append(f"(instanceRef {name} (portRef Q))")

    w('  (library work (edifLevel 0) (technology (numberDefinition))')
    w(f"    (cell {_legal(design)} (cellType GENERIC)")
    w("      (view netlist (viewType NETLIST)")
    # interface
    w("        (interface")
    for net in nl.inputs:
        legal, raw = _port_name(net, nn)
        decl = f"(port {legal} (direction INPUT))" if legal == raw else f"(port (rename {legal} \"{raw}\") (direction INPUT))"
        w(f"          {decl}")
    for net in nl.outputs:
        legal, raw = _port_name(net, nn)
        decl = f"(port {legal} (direction OUTPUT))" if legal == raw else f"(port (rename {legal} \"{raw}\") (direction OUTPUT))"
        w(f"          {decl}")
    w("        )")
    # contents
    w("        (contents")
    for c in mapped.luts:
        name, ctype = inst[id(c)]
        init = lut_init(c, mapped.cones[id(c)])
        w(f"          (instance {name} (cellRef {ctype} (libraryRef hdi_primitives)) (property INIT (string \"{init}\")))")
    for c in mapped.dffs:
        name, ctype = inst[id(c)]
        w(f"          (instance {name} (cellRef {ctype} (libraryRef hdi_primitives)))")
    for net, refs in sorted(term.items()):
        legal, raw = _port_name(net, nn)
        nname = legal if legal == raw else f"(rename {legal} \"{raw}\")"
        w(f"          (net {nname} (joined {' '.join(refs)}))")
    w("        )")
    w("      )")
    w("    )")
    w("  )")
    w(")")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")

def write_xdc(path, nl, clock_period_ns=10.0):
    nn = dict(nl.net_names)
    out = ["# efc-generated XDC for xcvp1902 — pin locations are placeholders;",
           "# assign real pins per the ProtoBoard board file before Vivado runs.", ""]
    for clk in nl.clocks:
        raw = nn.get(clk, f"n{clk}")
        out.append(f"create_clock -period {clock_period_ns:.3f} [get_ports {{{raw}}}]")
    out.append("")
    for net in nl.inputs + nl.outputs:
        if net in nl.clocks:
            continue
        raw = nn.get(net, f"n{net}")
        out.append(f"# set_property PACKAGE_PIN <TBD> [get_ports {{{raw}}}]")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
