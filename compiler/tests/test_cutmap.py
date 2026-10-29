import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap, lut_init
from efc.cutmap import enumerate_cuts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")

# reconvergent fanout: s feeds two cones. Greedy cannot merge either
# (s has 2 fanouts); cut enumeration duplicates s into both LUTs.
RECONV = ("module t(a, b, c, d, y1, y2); input a; input b; input c; input d;\n"
          " output y1; output y2;\n"
          " wire s; assign s = a & b;\n"
          " assign y1 = s | c;\n"
          " assign y2 = s ^ d; endmodule\n")

XOR3 = ("module t(a, b, c, y); input a; input b; input c; output y;\n"
        " wire w1; assign w1 = a ^ b;\n"
        " assign y = w1 ^ c; endmodule\n")

XOR5 = ("module t(a, b, c, d, e, y); input a; input b; input c; input d;\n"
        " input e; output y;\n"
        " wire w1; wire w2; wire w3;\n"
        " assign w1 = a ^ b; assign w2 = w1 ^ c; assign w3 = w2 ^ d;\n"
        " assign y = w3 ^ e; endmodule\n")

DEAD = ("module t(a, b, y); input a; input b; output y;\n"
        " wire u; assign u = a & b;\n"
        " assign y = a | b; endmodule\n")


def _map(src, k=6, method="cut"):
    return techmap(elaborate(parse_verilog(src)), k=k, method=method)


class TestCutMap(unittest.TestCase):
    def test_reconvergent_fanout_beats_greedy(self):
        m_greedy, _ = _map(RECONV, method="greedy")
        m_cut, _ = _map(RECONV, method="cut")
        self.assertEqual(len(m_greedy.luts), 3)      # s cannot merge
        self.assertEqual(len(m_cut.luts), 2)         # s duplicated into both
        # y1 = (a&b)|c -> LUT3 INIT bits {3,4,5,6,7} = 0xF8
        inits = sorted(lut_init(l, m_cut.cones[id(l)]) for l in m_cut.luts)
        self.assertIn("F8", inits)                   # (a&b)|c: bits {3,4,5,6,7}
        self.assertIn("78", inits)                   # (a&b)^d: bits {1,2,4,5,6}

    def test_xor3_single_lut(self):
        m_cut, _ = _map(XOR3)
        self.assertEqual(len(m_cut.luts), 1)
        lut = m_cut.luts[0]
        self.assertEqual(lut.type, "LUT3")
        self.assertEqual(lut_init(lut, m_cut.cones[id(lut)]), "96")  # parity

    def test_k_limit_splits_deep_cone(self):
        # 5-input XOR with K=4 cannot fit one LUT -> 2 LUTs, depth 2
        m_cut, _ = _map(XOR5, k=4)
        self.assertEqual(len(m_cut.luts), 2)
        sizes = sorted(len(l.ins) for l in m_cut.luts)
        self.assertEqual(sizes, [2, 4])              # LUT4(a..d) + LUT2(.., e)

    def test_dead_logic_dropped(self):
        m_greedy, _ = _map(DEAD, method="greedy")
        m_cut, _ = _map(DEAD, method="cut")
        self.assertEqual(len(m_greedy.luts), 2)      # keeps unused u = a&b
        self.assertEqual(len(m_cut.luts), 1)         # only y = a|b survives
        self.assertEqual(lut_init(m_cut.luts[0],
                                  m_cut.cones[id(m_cut.luts[0])]), "E")

    def test_alu4_cut_le_greedy(self):
        nl = elaborate(parse_verilog(open(EX).read()))
        m_greedy, _ = techmap(nl, k=6, method="greedy")
        m_cut, _ = techmap(nl, k=6, method="cut")
        self.assertEqual(len(m_greedy.luts), 12)     # v0.4 baseline
        self.assertLessEqual(len(m_cut.luts), len(m_greedy.luts))

    def test_cli_default_mapper_is_cut(self):
        rep = compile_file(EX, grid=8, tracks=8, seed=1)
        self.assertEqual(rep["mapper"], "cut")
        self.assertLessEqual(rep["LUTs"], 12)
        self.assertEqual(rep["route_overused_channels"], 0)
        self.assertFalse(rep["timing_violated"])

if __name__ == "__main__":
    unittest.main()
