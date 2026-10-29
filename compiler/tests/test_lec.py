"""LEC tests (v0.8): netlist vs mapped-LUT equivalence via Yosys."""
import os, re, shutil, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.lec import (emit_gates_verilog, emit_luts_verilog, run_lec,
                     run_lec_files, _find_yosys)

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "examples", "alu4.v")

RECONV = ("module t(a, b, c, d, clk, q); input a; input b; input c; input d;\n"
          " input clk; output reg q;\n"
          " wire s; assign s = a & b;\n"
          " wire t2; assign t2 = s | c;\n"
          " always @(posedge clk) begin\n"
          "   q <= t2 ^ d;\n"
          " end\n"
          "endmodule\n")

HAVE_YOSYS = _find_yosys() is not None


def compile_nl(src=RECONV, mapper="cut", k=6):
    nl = elaborate(parse_verilog(src))
    mapped, _ = techmap(nl, k=k, method=mapper)
    return nl, mapped


class TestEmit(unittest.TestCase):
    def test_gates_verilog_sanitizes_names(self):
        nl = elaborate(parse_verilog(open(EX, encoding="utf-8").read()))
        v = emit_gates_verilog(nl)
        self.assertIn("module gold(", v)
        self.assertNotRegex(v, r"\\")            # no escaped identifiers
        for tok in re.findall(r"\binput\s+([^;,()]+)", v):
            self.assertRegex(tok.strip(), r"^[A-Za-z_][A-Za-z0-9_]*$")

    def test_luts_verilog_init_tables(self):
        nl, mapped = compile_nl()
        v = emit_luts_verilog(mapped)
        self.assertIn("module gate(", v)
        for m in re.finditer(r"64'h([0-9A-Fa-f]+)", v):
            self.assertEqual(len(m.group(1)), 16)   # left-padded to 64 bits
        self.assertIn("posedge", v)                 # DFFs emitted


@unittest.skipUnless(HAVE_YOSYS, "yosys binary not available")
class TestLec(unittest.TestCase):
    def test_alu4_cut_proven(self):
        nl = elaborate(parse_verilog(open(EX, encoding="utf-8").read()))
        mapped, _ = techmap(nl, k=6, method="cut")
        r = run_lec(nl, mapped)
        self.assertEqual(r["status"], "proven", r["log"][-800:])
        self.assertEqual(r["proven"], r["total"])

    def test_greedy_mapper_also_proven(self):
        nl, mapped = compile_nl(mapper="greedy")
        r = run_lec(nl, mapped)
        self.assertEqual(r["status"], "proven", r["log"][-800:])

    def test_cut_mapper_proven(self):
        nl, mapped = compile_nl(mapper="cut")
        r = run_lec(nl, mapped)
        self.assertEqual(r["status"], "proven", r["log"][-800:])

    def test_catches_broken_init(self):
        nl, mapped = compile_nl()
        gold = emit_gates_verilog(nl)
        gate = emit_luts_verilog(mapped)
        # flip bit0 of the first INIT table -> a functionally wrong LUT
        m = re.search(r"64'h([0-9A-Fa-f]{16})", gate)
        self.assertIsNotNone(m)
        v = int(m.group(1), 16) ^ 1
        bad = gate[:m.start()] + f"64'h{v:016X}" + gate[m.end():]
        r = run_lec_files(gold, bad)
        self.assertEqual(r["status"], "failed",
                         "corrupted INIT must NOT pass LEC: " + r["log"][-400:])


class TestSkip(unittest.TestCase):
    def test_missing_yosys_skips_not_fakes(self):
        from unittest import mock
        import efc.lec as lec_mod
        nl, mapped = compile_nl()
        with mock.patch.object(lec_mod, "_find_yosys", return_value=None):
            r = run_lec(nl, mapped)
        self.assertEqual(r["status"], "skipped")   # honest skip, never a fake pass
        self.assertIsNone(r["proven"])

    def test_cli_lec_flag(self):
        from efc.cli import compile_file
        rep = compile_file(EX, lec=True)
        self.assertIn("lec", rep)
        if HAVE_YOSYS:
            self.assertTrue(rep["lec"].startswith("proven"), rep["lec"])
        else:
            self.assertEqual(rep["lec"], "skipped (yosys not found)")


if __name__ == "__main__":
    unittest.main()
