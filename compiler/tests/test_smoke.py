import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap, lut_init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")

class TestPipeline(unittest.TestCase):
    def test_alu4_end_to_end(self):
        rep = compile_file(EX, grid=8, tracks=8, seed=1)
        self.assertEqual(rep["module"], "alu4")
        self.assertEqual(rep["target"], "xcvp1902")
        self.assertEqual(rep["gates_in"], 24)
        self.assertEqual(rep["DFF"], 4)
        self.assertGreater(rep["LUTs"], 0)
        self.assertLessEqual(rep["LUTs"], 16)   # mapping never worse than 1:1
        self.assertGreater(rep["CLB_used"], 0)
        self.assertEqual(rep["route_overused_channels"], 0)
        self.assertGreaterEqual(rep["logic_depth_LUT"], 1)

    def test_lut_init_and2(self):
        # a & b -> single LUT2 with INIT = 0b1000 = 0x8 (I0=a, I1=b)
        src = ("module t(a, b, y); input a; input b; output y;\n"
               " assign y = a & b; endmodule\n")
        nl = elaborate(parse_verilog(src))
        mapped, _ = techmap(nl, k=6)
        self.assertEqual(len(mapped.luts), 1)
        lut = mapped.luts[0]
        self.assertEqual(lut.type, "LUT2")
        self.assertEqual(lut_init(lut, mapped.cones[id(lut)]), "8")

    def test_lut_init_mux(self):
        # if(sel) y<=a; else y<=b;  -> MUX2 cone in one LUT3 (8 INIT entries)
        src = ("module t(clk, a, b, sel, y); input clk; input a; input b;\n"
               " input sel; output reg y;\n"
               " always @(posedge clk) begin\n"
               "  if (sel) y <= a; else y <= b; end endmodule\n")
        nl = elaborate(parse_verilog(src))
        mapped, _ = techmap(nl, k=6)
        self.assertEqual(len(mapped.luts), 1)
        lut = mapped.luts[0]
        self.assertEqual(lut.type, "LUT3")
        init = lut_init(lut, mapped.cones[id(lut)])
        self.assertEqual(len(init) * 4, 8)      # 3-input LUT -> 8 entries
        int(init, 16)                            # parses as hex

    def test_edif_xdc_written(self):
        with tempfile.TemporaryDirectory() as d:
            ep, xp = os.path.join(d, "a.edif"), os.path.join(d, "a.xdc")
            rep = compile_file(EX, grid=8, tracks=8, seed=1, edif=ep, xdc=xp)
            ed = open(ep, encoding="utf-8").read()
            xd = open(xp, encoding="utf-8").read()
            self.assertIn("(edif alu4", ed)
            self.assertIn("(external hdi_primitives", ed)
            self.assertIn("cellRef LUT", ed)
            self.assertIn("(property INIT", ed)
            self.assertIn("cellRef FDRE", ed)
            self.assertIn("create_clock", xd)

if __name__ == "__main__":
    unittest.main()
