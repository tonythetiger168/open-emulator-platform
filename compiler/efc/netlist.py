"""Generic gate-level netlist + elaboration (bit-blasting) from AST.

Cell types: AND2 OR2 XOR2 NOT MUX2(sel,a,b) DFF(d,clk)  — all 1-bit.
Nets are integer ids; net 0 = const0, net 1 = const1.
"""
from dataclasses import dataclass, field
from . import verilog as V

CONST0, CONST1 = 0, 1

@dataclass
class Cell:
    type: str          # AND2 OR2 XOR2 NOT MUX2 DFF
    ins: list          # net ids (MUX2: [sel, a, b]; DFF: [d, clk])
    out: int
    name: str = ""

@dataclass
class Netlist:
    cells: list = field(default_factory=list)
    net_names: dict = field(default_factory=dict)   # net id -> human name
    inputs: list = field(default_factory=list)      # net ids of PIs
    outputs: list = field(default_factory=list)     # net ids of POs
    clocks: list = field(default_factory=list)

    def new_net(self, name=""):
        nid = self._next   # ids 0,1 are reserved for const0/const1
        self._next += 1
        if name:
            self.net_names[nid] = name
        return nid

    _next: int = 2

    def add(self, type_, ins, out, name=""):
        c = Cell(type_, ins, out, name)
        self.cells.append(c)
        return c

def _bits(nl, name, width):
    return [nl.new_net(f"{name}[{i}]" if width > 1 else name) for i in range(width)]

class Elaborator:
    def __init__(self, mod: V.Module):
        self.m = mod
        self.nl = Netlist()
        self.sig = {}       # name -> list of nets (bit 0 first)
        self.width = {}     # name -> width
        self.is_reg = {}

    def run(self):
        self.declare()
        for it in self.m.items:
            if isinstance(it, V.Assign):
                self.do_assign(it)
            elif isinstance(it, V.Always):
                self.do_always(it)
        self.bind_outputs()
        return self.nl

    def declare(self):
        for it in self.m.items:
            if isinstance(it, V.Decl):
                w = abs(it.msb - it.lsb) + 1
                for n in it.names:
                    self.width[n] = w
                    self.is_reg[n] = it.is_reg
                    self.sig[n] = _bits(self.nl, n, w)
                    if it.kind == "input":
                        self.nl.inputs.extend(self.sig[n])
        for pn in self.m.port_names:
            if pn not in self.sig:
                raise NameError(f"port {pn!r} not declared")

    def do_assign(self, a: V.Assign):
        w = self.width[a.lhs]
        e = self.ev(a.expr)
        if len(e) != w:
            raise ValueError(f"width mismatch: {a.lhs}={w} vs expr={len(e)}")
        self.sig[a.lhs] = e          # alias: lhs nets become expr nets

    def do_always(self, al: V.Always):
        clk_nets = self.sig.get(al.clk)
        if not clk_nets or len(clk_nets) != 1:
            raise NameError(f"clock {al.clk!r} must be a scalar input")
        clk = clk_nets[0]
        self.nl.clocks.append(clk)
        for st in al.body:
            if isinstance(st, V.NBAssign):
                self.reg_assign(st.lhs, self.ev(st.expr), clk)
            elif isinstance(st, V.IfStmt):
                cond = self.ev(st.cond)
                if len(cond) != 1:
                    raise ValueError("if condition must be scalar")
                t, e = st.then, st.els
                if t.lhs != (e.lhs if e else t.lhs):
                    raise ValueError("if/else must assign the same reg")
                e1 = self.ev(t.expr)
                e0 = self.ev(e.expr) if e else self.sig[t.lhs]  # hold
                if len(e1) != len(e0):
                    raise ValueError("if/else branch width mismatch")
                sel = cond[0]
                muxed = []
                for b1, b0 in zip(e1, e0):
                    o = self.nl.new_net()
                    self.nl.add("MUX2", [sel, b1, b0], o)
                    muxed.append(o)
                self.reg_assign(t.lhs, muxed, clk)

    def reg_assign(self, name, dnets, clk):
        w = self.width[name]
        if len(dnets) != w:
            raise ValueError(f"width mismatch in always: {name}")
        if not self.is_reg[name]:
            raise ValueError(f"{name} assigned in always but not declared reg")
        qs = []
        for i, d in enumerate(dnets):
            q = self.nl.new_net(f"{name}[{i}]" if w > 1 else name)
            self.nl.add("DFF", [d, clk], q, name=f"{name}[{i}]")
            qs.append(q)
        self.sig[name] = qs

    def bind_outputs(self):
        for it in self.m.items:
            if isinstance(it, V.Decl) and it.kind == "output":
                for n in it.names:
                    self.nl.outputs.extend(self.sig[n])

    # expression evaluation -> list of nets, bit 0 first
    def ev(self, e):
        nl = self.nl
        if isinstance(e, V.Var):
            if e.name not in self.sig:
                raise NameError(f"undeclared signal {e.name!r}")
            return list(self.sig[e.name])
        if isinstance(e, V.Const):
            return [CONST1 if (e.value >> i) & 1 else CONST0 for i in range(e.width)]
        if isinstance(e, V.Un):
            xs = self.ev(e.x)
            out = []
            for x in xs:
                o = nl.new_net()
                nl.add("NOT", [x], o)
                out.append(o)
            return out
        if isinstance(e, V.Bin):
            l, r = self.ev(e.l), self.ev(e.r)
            if len(l) != len(r):
                raise ValueError(f"operand width mismatch for {e.op!r}: {len(l)} vs {len(r)}")
            op = {"&": "AND2", "|": "OR2", "^": "XOR2"}[e.op]
            out = []
            for a, b in zip(l, r):
                o = nl.new_net()
                nl.add(op, [a, b], o)
                out.append(o)
            return out
        raise TypeError(e)

def elaborate(mod: V.Module) -> Netlist:
    return Elaborator(mod).run()
