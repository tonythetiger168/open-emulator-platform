"""7-series backend emitter (improvement-plan Phase C item 9).

Emits the mapped LutNet as flat Verilog built from Xilinx 7-series
primitives — LUT1..LUT6 (with .INIT), FDRE, IBUF/OBUF — the exact cell
set `yosys synth_xilinx` produces and nextpnr-xilinx (OpenXC7 flow)
consumes. The handoff chain for the Vivado-free target line:

  efc --arch xc7k325t --xc7 out.v
  yosys -p "read_verilog -lib +/xilinx/cells_sim.v; read_verilog out.v;
            hierarchy -top <top> -purge_lib; proc; write_json out.json"
  nextpnr-xilinx --chipdb <xc7k325t chipdb> --json out.json ...   (off-sandbox)

IO modelling: each PI gets an IBUF and each PO an OBUF, with internal
alias wires (`<name>__ibuf` / `<name>__obuf`) so port names stay pin
names while cells see buffer-internal nets — the synth_xilinx
convention. Clocks go through plain IBUFs (BUFG insertion belongs to
the Yosys/nextpnr side). Correctness of the emitted function is guarded
upstream by lec.py (generic netlist vs mapped LutNet is proven before
this pure format transform); yosys parse + stat + write_json smoke
tests cover the format contract.
"""
from .netlist import CONST0, CONST1
from .techmap import lut_init
from .lec import _Names


def _init_literal(lut, cones):
    """LUTk INIT as a Verilog literal: 2**k bits, hex, zero-padded."""
    k = max(1, len(lut.ins))
    digits = max(1, (1 << k) // 4)
    init = lut_init(lut, cones)
    return f"{1 << k}'h{init.rjust(digits, '0')}"


def emit_xc7_verilog(mapped, mod="top"):
    """Flat 7-series-primitive Verilog for a mapped LutNet."""
    names = _Names(mapped.net_names, priority=mapped.inputs + mapped.outputs)
    pi_alias = {n: f"{names.wire(n)}__ibuf" for n in mapped.inputs}
    po_alias = {n: f"{names.wire(n)}__obuf" for n in mapped.outputs}

    def ref(net):
        """Reference used on LUT/FF pins (buffer-alias aware)."""
        if net == CONST0:
            return "1'b0"
        if net == CONST1:
            return "1'b1"
        if net in pi_alias:
            return pi_alias[net]
        if net in po_alias:
            return po_alias[net]
        return names.wire(net)

    lines = [f"module {mod}("]
    ports = [names.wire(n) for n in mapped.inputs] + \
            [names.wire(n) for n in mapped.outputs]
    lines.append(", ".join(ports) + ");")
    for n in mapped.inputs:
        lines.append(f"input {names.wire(n)};")
    for n in mapped.outputs:
        lines.append(f"output {names.wire(n)};")

    driven = {c.out for c in mapped.luts} | {c.out for c in mapped.dffs}
    wires = set(pi_alias.values()) | set(po_alias.values())
    for n in sorted(driven):
        if n not in mapped.inputs and n not in mapped.outputs and n > CONST1:
            wires.add(names.wire(n))
    for wname in sorted(wires):
        lines.append(f"wire {wname};")

    for n in mapped.inputs:  # PI pads
        lines.append(f"IBUF ibuf_{names.wire(n)} "
                     f"(.I({names.wire(n)}), .O({pi_alias[n]}));")

    for i, lut in enumerate(mapped.luts):
        k = max(1, len(lut.ins))
        pins = ", ".join(f".I{j}({ref(lut.ins[j])})" for j in range(len(lut.ins)))
        if not pins:
            pins = ".I0(1'b0)"
        lines.append(f"LUT{k} #(.INIT({_init_literal(lut, mapped.cones.get(id(lut), {}))})) "
                     f"lut_{i} ({pins}, .O({ref(lut.out)}));")
    for i, dff in enumerate(mapped.dffs):
        lines.append(f"FDRE #(.INIT(1'b0)) fd_{i} "
                     f"(.C({ref(dff.ins[1])}), .CE(1'b1), .R(1'b0), "
                     f".D({ref(dff.ins[0])}), .Q({ref(dff.out)}));")

    for n in mapped.outputs:  # PO pads
        if n in pi_alias:          # PI->PO passthrough
            src = pi_alias[n]
        elif n in driven:          # cell-driven: cell pin is on the alias wire
            src = po_alias[n]
        elif n == CONST0:
            src = "1'b0"
        elif n == CONST1:
            src = "1'b1"
        else:                      # undriven: declare and emit as-is
            src = names.wire(n)
            lines.append(f"wire {src};")
        lines.append(f"OBUF obuf_{names.wire(n)} "
                     f"(.I({src}), .O({names.wire(n)}));")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def write_xc7(path, mapped, design):
    open(path, "w", encoding="utf-8").write(emit_xc7_verilog(mapped, mod=design))
