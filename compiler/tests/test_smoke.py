import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "examples", "alu4.v")

class TestPipeline(unittest.TestCase):
    def test_alu4_end_to_end(self):
        rep = compile_file(EX, lut_k=4, grid=10, tracks=8, seed=1)
        self.assertEqual(rep["module"], "alu4")
        self.assertEqual(rep["gates_in"], 24)
        self.assertEqual(rep["DFF"], 4)
        self.assertGreater(rep["LUT4"], 0)
        self.assertLessEqual(rep["LUT4"], 16)   # mapping never worse than 1:1
        self.assertEqual(rep["route_overused_channels"], 0)
        self.assertGreaterEqual(rep["logic_depth_LUT"], 1)

    def test_lut6_not_worse_than_lut4(self):
        r4 = compile_file(EX, lut_k=4, grid=10, tracks=8, seed=1)
        r6 = compile_file(EX, lut_k=6, grid=10, tracks=8, seed=1)
        self.assertLessEqual(r6["LUT6"], r4["LUT4"])

if __name__ == "__main__":
    unittest.main()
