import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.pack import pack
from efc.fabric import build_fabric
from efc.place import place
from efc.timing import sta, logic_depth, wire_delay_ns
from efc.arch import load_arch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")


def _placed(src, grid=8, tracks=8, seed=1):
    nl = elaborate(parse_verilog(src))
    mapped, _ = techmap(nl, k=6)
    blocks, ext = pack(mapped)
    fab = build_fabric(grid, tracks, nl.inputs, nl.outputs)
    blk_at, _hpwl = place(blocks, ext, fab, seed=seed)
    return nl, mapped, ext, blk_at, fab


class TestSTA(unittest.TestCase):
    def test_wire_delay_model(self):
        a = load_arch()
        self.assertEqual(wire_delay_ns(0, a), 0.0)          # intra-CLB
        l1 = a.segment_for(1)
        self.assertAlmostEqual(wire_delay_ns(1, a), l1.elmore_ns())
        # a 5-tile hop uses L1 x5 or a longer segment, but never cheaper than 1 hop
        self.assertGreater(wire_delay_ns(5, a), 0.0)

    def test_single_lut_path(self):
        # PI -> LUT2 -> DFF: cp = wire + t_lut + t_setup (register input side)
        src = ("module t(clk, a, b, y); input clk; input a; input b;\n"
               " output reg y;\n"
               " always @(posedge clk) begin y <= a & b; end endmodule\n")
        nl, mapped, ext, blk_at, fab = _placed(src)
        st = sta(mapped, ext, blk_at, fab, clock_ns=10.0)
        a = load_arch()
        expect_min = a.clb.t_lut_ns + a.clb.t_setup_ns      # wire >= 0
        self.assertGreaterEqual(st["critical_path_ns"], expect_min)
        self.assertFalse(st["violated"])
        self.assertGreater(st["fmax_mhz"], 0)
        # slack of a PI->register path at 10 ns is large and positive
        self.assertGreater(st["worst_slack_ns"], 5.0)

    def test_criticality_range_and_critical_net(self):
        nl, mapped, ext, blk_at, fab = _placed(open(EX).read())
        st = sta(mapped, ext, blk_at, fab, clock_ns=10.0)
        for n, c in st["criticality"].items():
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)
        # the most critical net has the least slack
        worst = min(st["slack"], key=lambda n: st["slack"][n])
        self.assertAlmostEqual(st["criticality"][worst],
                               max(st["criticality"].values()))

    def test_tight_clock_violates(self):
        nl, mapped, ext, blk_at, fab = _placed(open(EX).read())
        st = sta(mapped, ext, blk_at, fab, clock_ns=0.01)
        self.assertTrue(st["violated"])
        self.assertLess(st["worst_slack_ns"], 0.0)

    def test_sta_exceeds_logic_depth_bound(self):
        # placement-aware CP must be >= logic_depth * t_lut (wire only adds)
        nl, mapped, ext, blk_at, fab = _placed(open(EX).read())
        st = sta(mapped, ext, blk_at, fab, clock_ns=10.0)
        a = load_arch()
        self.assertGreaterEqual(st["critical_path_ns"],
                                logic_depth(mapped) * a.clb.t_lut_ns)

    def test_cli_reports_timing(self):
        rep = compile_file(EX, grid=8, tracks=8, seed=1)
        self.assertIn("critical_path_ns", rep)
        self.assertIn("est_fmax_mhz", rep)
        self.assertFalse(rep["timing_violated"])
        self.assertGreater(rep["est_fmax_mhz"], 0)

if __name__ == "__main__":
    unittest.main()
