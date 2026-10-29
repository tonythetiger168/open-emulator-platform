"""LEC: logical equivalence check between the generic netlist and the
mapped LUT netlist (improvement-plan Phase C item 10).

Both sides are emitted as flat Verilog and proven with Yosys:
  read_verilog gold.v gate.v; proc; flatten gold; flatten gate;
  equiv_make gold gate equiv; equiv_simple equiv; equiv_induct equiv;
  equiv_status -assert equiv

Why this closes the proof: techmap (both greedy and cut mappers) only
re-maps combinational cones; DFFs survive 1:1 with identical output net
names, so equiv_make matches state bits by name, equiv_simple discharges
the combinational $equiv cells, and equiv_induct (k-step SAT induction)
proves the state-bit pairs. No cell library is emitted: LUTs are written
as `assign o = INIT[idx];` tables and DFFs as plain always blocks, so the
flow needs nothing but stock Yosys (verified 0.23).

Yosys is an external dependency. If the binary is not found the result is
status "skipped" — never a silent pass. A genuine mismatch yields
"failed" (exit 1 from equiv_status -assert); a tool crash yields "error"
with the log tail attached.
"""
import os, re, shutil, subprocess, tempfile
from .netlist import CONST0, CONST1
from .techmap import lut_init

_LIBDIRS = ["/home/kimi/local/usr/bin", os.path.expanduser("~/local/usr/bin")]


def _find_yosys(explicit=None):
    """Locate a yosys binary: explicit arg > $EFC_YOSYS > PATH > user prefixes."""
    cands = [explicit, os.environ.get("EFC_YOSYS")]
    cands.append(shutil.which("yosys"))
    cands += [os.path.join(d, "yosys") for d in _LIBDIRS]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


class _Names:
    """Deterministic net-id -> Verilog identifier map, shared by both emitters
    so PIs/POs/DFF-qs match by name across gold and gate."""

    def __init__(self, net_names):
        self.map = {}
        used = set()
        nets = set(net_names)
        for n, nm in sorted(net_names.items()):
            base = re.sub(r"[^A-Za-z0-9_]", "_", nm) or f"n{n}"
            if base[0].isdigit():
                base = "w_" + base
            name = base
            while name in used:
                name = f"{base}__{n}"
            used.add(name)
            self.map[n] = name
        self.net_names = net_names

    def wire(self, net):
        if net in self.map:
            return self.map[net]
        name = f"n{net}"
        self.map[net] = name
        return name

    def ref(self, net):
        if net == CONST0:
            return "1'b0"
        if net == CONST1:
            return "1'b1"
        return self.wire(net)


def _emit_header(mod, names, inputs, outputs):
    lines = [f"module {mod}("]
    ports = [names.wire(n) for n in inputs] + [names.wire(n) for n in outputs]
    lines.append(", ".join(ports) + ");")
    for n in inputs:
        lines.append(f"input {names.wire(n)};")
    for n in outputs:
        lines.append(f"output {names.wire(n)};")
    return lines


def _emit_dff(lines, names, d, clk, q, tag):
    lines.append(f"reg dffq_{tag};")
    lines.append(f"always @(posedge {names.ref(clk)}) dffq_{tag} <= {names.ref(d)};")
    lines.append(f"assign {names.ref(q)} = dffq_{tag};")


def emit_gates_verilog(nl, mod="gold"):
    """Flat gate-level Verilog for the generic Netlist (LEC golden side)."""
    names = _Names(nl.net_names)
    lines = _emit_header(mod, names, nl.inputs, nl.outputs)
    driven = {c.out for c in nl.cells}
    for n in sorted(driven):
        if n not in nl.inputs and n not in nl.outputs and n > CONST1:
            lines.append(f"wire {names.wire(n)};")
    tag = 0
    for c in nl.cells:
        o = names.ref(c.out)
        if c.type == "AND2":
            lines.append(f"assign {o} = {names.ref(c.ins[0])} & {names.ref(c.ins[1])};")
        elif c.type == "OR2":
            lines.append(f"assign {o} = {names.ref(c.ins[0])} | {names.ref(c.ins[1])};")
        elif c.type == "XOR2":
            lines.append(f"assign {o} = {names.ref(c.ins[0])} ^ {names.ref(c.ins[1])};")
        elif c.type == "NOT":
            lines.append(f"assign {o} = ~{names.ref(c.ins[0])};")
        elif c.type == "MUX2":  # ins = [sel, a, b] -> sel ? a : b
            lines.append(f"assign {o} = {names.ref(c.ins[0])} ? "
                         f"{names.ref(c.ins[1])} : {names.ref(c.ins[2])};")
        elif c.type == "DFF":
            _emit_dff(lines, names, c.ins[0], c.ins[1], c.out, tag)
            tag += 1
        else:
            raise ValueError(f"cannot emit gate {c.type}")
    for n in nl.outputs:  # PO passthroughs (PI->PO or const->PO)
        if n not in driven:
            lines.append(f"assign {names.wire(n)} = {names.ref(n)};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def emit_luts_verilog(mapped, mod="gate"):
    """Flat Verilog for the mapped LutNet (LEC gate side).

    Each LUTK becomes `assign out = init[ {pad, in_{k-1}, ..., in_0} ];`
    with INIT left-padded to 64 bits; DFFs are emitted identically to the
    golden side so state bits match by construction.
    """
    names = _Names(mapped.net_names)
    lines = _emit_header(mod, names, mapped.inputs, mapped.outputs)
    driven = {c.out for c in mapped.luts} | {c.out for c in mapped.dffs}
    for n in sorted(driven):
        if n not in mapped.inputs and n not in mapped.outputs and n > CONST1:
            lines.append(f"wire {names.wire(n)};")
    for i, lut in enumerate(mapped.luts):
        k = len(lut.ins)
        init = lut_init(lut, mapped.cones.get(id(lut), {}))
        lines.append(f"wire [63:0] init_{i} = 64'h{init.rjust(16, '0')};")
        idx = ", ".join(names.ref(n) for n in reversed(lut.ins))
        if k < 6:
            idx = f"{6 - k}'b0" + (", " + idx if idx else "")
        lines.append(f"assign {names.ref(lut.out)} = init_{i}[{{{idx}}}];")
    for tag, dff in enumerate(mapped.dffs):
        _emit_dff(lines, names, dff.ins[0], dff.ins[1], dff.out, tag)
    for n in mapped.outputs:
        if n not in driven:
            lines.append(f"assign {names.wire(n)} = {names.ref(n)};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


_YS_SCRIPT = ("read_verilog gold.v gate.v; proc; flatten gold; flatten gate; "
              "equiv_make gold gate equiv; equiv_simple equiv; equiv_induct equiv; "
              "equiv_status -assert equiv")


def run_lec_files(gold_v, gate_v, yosys=None, timeout=120, keep_dir=None):
    """Run the Yosys equiv flow on two Verilog sources.

    Returns dict: status in {"proven","failed","error","skipped"},
    plus proven/total $equiv cell counts and a log tail.
    """
    yosys = _find_yosys(yosys)
    if not yosys:
        return {"status": "skipped", "reason": "yosys binary not found",
                "proven": None, "total": None, "log": ""}
    work = keep_dir or tempfile.mkdtemp(prefix="efc_lec_")
    with open(os.path.join(work, "gold.v"), "w") as f:
        f.write(gold_v)
    with open(os.path.join(work, "gate.v"), "w") as f:
        f.write(gate_v)
    try:
        r = subprocess.run([yosys, "-p", _YS_SCRIPT], cwd=work,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": f"yosys timeout ({timeout}s)",
                "proven": None, "total": None, "log": ""}
    out = r.stdout + r.stderr
    total = proven = unproven = None
    m = re.search(r"Found (\d+) \$equiv cells.*?:\s*Of those cells "
                  r"(\d+) are proven and (\d+) are unproven", out, re.S)
    if m:
        total, proven, unproven = int(m.group(1)), int(m.group(2)), int(m.group(3))
    mu = re.search(r"Found (\d+) unproven \$equiv cells", out)
    if mu:
        unproven = int(mu.group(1))
    if r.returncode == 0 and "Equivalence successfully proven" in out:
        status = "proven"
    elif "unproven $equiv cells" in out or (unproven or 0) > 0:
        status = "failed"
    else:
        status = "error"
    return {"status": status, "proven": proven, "total": total,
            "log": out[-4000:], "workdir": work}


def run_lec(nl, mapped, **kw):
    """LEC of a generic Netlist vs its mapped LutNet."""
    return run_lec_files(emit_gates_verilog(nl), emit_luts_verilog(mapped), **kw)
