"""Minimal Verilog subset frontend: lexer + recursive-descent parser + AST.

Supported subset (MVP):
  module m(ports);  input/output [reg] [msb:lsb] name, ...;  wire/reg decls;
  assign x = expr;                    expr: ~ & | ^ ( ) ident const
  always @(posedge clk) begin ... end  stmts: y <= expr;  if (c) y<=e1; else y<=e0;
Numbers: 4'b1010, 8'hFF, 12'd5, plain decimal (32-bit).
"""
from dataclasses import dataclass, field

# ---------------- lexer ----------------
PUNCT2 = {"<="}
PUNCT1 = set("()[];,:=@&|^~")
KEYWORDS = {"module", "endmodule", "input", "output", "wire", "reg",
            "assign", "always", "posedge", "begin", "end", "if", "else"}

@dataclass
class Tok:
    kind: str   # 'ident' 'num' 'punct' 'kw'
    val: str
    line: int

def lex(src: str):
    toks, i, line, n = [], 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c.isspace():
            i += 1; continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n": i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0: raise SyntaxError(f"unterminated comment at line {line}")
            line += src.count("\n", i, j); i = j + 2; continue
        two = src[i:i+2]
        if two in PUNCT2:
            toks.append(Tok("punct", two, line)); i += 2; continue
        if c in PUNCT1:
            toks.append(Tok("punct", c, line)); i += 1; continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_'"): j += 1
            toks.append(Tok("num", src[i:j], line)); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"): j += 1
            w = src[i:j]
            toks.append(Tok("kw" if w in KEYWORDS else "ident", w, line)); i = j; continue
        raise SyntaxError(f"bad char {c!r} at line {line}")
    toks.append(Tok("punct", "<eof>", line))
    return toks

# ---------------- AST ----------------
@dataclass
class Const:
    value: int
    width: int

@dataclass
class Var:
    name: str

@dataclass
class Un:
    op: str
    x: object

@dataclass
class Bin:
    op: str
    l: object
    r: object

@dataclass
class Decl:     # kind in {input,output,wire,reg}; is_reg for 'output reg'
    kind: str
    names: list
    msb: int = 0
    lsb: int = 0
    is_reg: bool = False

@dataclass
class Assign:
    lhs: str
    expr: object

@dataclass
class NBAssign:  # non-blocking y <= expr
    lhs: str
    expr: object

@dataclass
class IfStmt:
    cond: object
    then: object   # NBAssign
    els: object = None

@dataclass
class Always:
    clk: str
    body: list = field(default_factory=list)

@dataclass
class Module:
    name: str
    port_names: list
    items: list = field(default_factory=list)

# ---------------- parser ----------------
class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=None, v=None):
        t = self.t[self.i]
        if k and t.kind != k: return False
        if v and t.val != v: return False
        return True

    def eat(self, v=None, k=None):
        t = self.t[self.i]
        if v is not None and t.val != v:
            raise SyntaxError(f"expect {v!r} got {t.val!r} at line {t.line}")
        if k is not None and t.kind != k:
            raise SyntaxError(f"expect {k} got {t.kind} at line {t.line}")
        self.i += 1
        return t

    def parse(self):
        self.eat("module")
        name = self.eat(k="ident").val
        self.eat("(")
        ports = []
        while not self.peek(v=")"):
            ports.append(self.eat(k="ident").val)
            if self.peek(v=","): self.eat(",")
        self.eat(")"); self.eat(";")
        items = []
        while not self.peek(k="kw", v="endmodule"):
            items.append(self.item())
        self.eat("endmodule")
        return Module(name, ports, items)

    def rng(self):
        if self.peek(v="["):
            self.eat("[")
            msb = int(self.eat(k="num").val)
            self.eat(":")
            lsb = int(self.eat(k="num").val)
            self.eat("]")
            return msb, lsb
        return 0, 0

    def namelist(self):
        names = [self.eat(k="ident").val]
        while self.peek(v=","):
            self.eat(",")
            names.append(self.eat(k="ident").val)
        return names

    def item(self):
        t = self.t[self.i]
        if t.kind == "kw" and t.val in ("input", "output", "wire", "reg"):
            kind = t.val; self.i += 1
            is_reg = False
            if self.peek(k="kw", v="reg"):
                self.eat("reg"); is_reg = True
            msb, lsb = self.rng()
            names = self.namelist()
            self.eat(";")
            return Decl(kind, names, msb, lsb, is_reg or kind == "reg")
        if t.val == "assign":
            self.eat("assign")
            lhs = self.eat(k="ident").val
            self.eat("=")
            e = self.expr()
            self.eat(";")
            return Assign(lhs, e)
        if t.val == "always":
            self.eat("always"); self.eat("@"); self.eat("(")
            self.eat("posedge")
            clk = self.eat(k="ident").val
            self.eat(")"); self.eat("begin")
            body = []
            while not self.peek(k="kw", v="end"):
                body.append(self.stmt())
            self.eat("end")
            return Always(clk, body)
        raise SyntaxError(f"unexpected {t.val!r} at line {t.line}")

    def stmt(self):
        if self.peek(k="kw", v="if"):
            self.eat("if"); self.eat("(")
            cond = self.expr()
            self.eat(")")
            then = self.nbassign()
            els = None
            if self.peek(k="kw", v="else"):
                self.eat("else")
                els = self.nbassign()
            return IfStmt(cond, then, els)
        a = self.nbassign()
        return a

    def nbassign(self):
        lhs = self.eat(k="ident").val
        self.eat("<=")
        e = self.expr()
        self.eat(";")
        return NBAssign(lhs, e)

    def expr(self):
        e = self.xor_expr()
        while self.peek(v="|"):
            self.eat("|"); e = Bin("|", e, self.xor_expr())
        return e

    def xor_expr(self):
        e = self.and_expr()
        while self.peek(v="^"):
            self.eat("^"); e = Bin("^", e, self.and_expr())
        return e

    def and_expr(self):
        e = self.unary()
        while self.peek(v="&"):
            self.eat("&"); e = Bin("&", e, self.unary())
        return e

    def unary(self):
        if self.peek(v="~"):
            self.eat("~"); return Un("~", self.unary())
        return self.primary()

    def primary(self):
        t = self.t[self.i]
        if self.peek(v="("):
            self.eat("("); e = self.expr(); self.eat(")"); return e
        if t.kind == "ident":
            self.i += 1; return Var(t.val)
        if t.kind == "num":
            self.i += 1
            return parse_num(t.val, t.line)
        raise SyntaxError(f"unexpected {t.val!r} at line {t.line}")

def parse_num(s, line=0):
    if "'" in s:
        size_s, rest = s.split("'", 1)
        base, digits = rest[0], rest[1:]
        width = int(size_s) if size_s else None
        b = {"b": 2, "d": 10, "h": 16}.get(base)
        if b is None: raise SyntaxError(f"bad base in {s!r} at line {line}")
        val = int(digits.replace("x", "0").replace("z", "0"), b)
        return Const(val, width or max(val.bit_length(), 1))
    return Const(int(s), 32)

def parse_verilog(src: str) -> Module:
    return Parser(lex(src)).parse()
