import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.arch import load_arch, arch_path, ArchSpec, DEFAULT_ARCH
from efc.fabric import build_fabric, utilization

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestArchSpec(unittest.TestCase):
    def test_default_arch_loads(self):
        a = load_arch()
        self.assertEqual(a.name, "vp1902")
        self.assertEqual(a.part, "xcvp1902")
        self.assertEqual(a.clb.luts, 8)
        self.assertEqual(a.clb.ffs, 16)
        self.assertEqual(a.clb.lut_k, 6)
        self.assertEqual(a.switch_block.fs, 3)
        self.assertGreaterEqual(len(a.segments), 1)
        self.assertEqual(a.envelope["LUT6"], 8_460_000)
        self.assertEqual(a.clb_count, 8_460_000 // 8)

    def test_load_by_explicit_path(self):
        p = os.path.join(ROOT, "arch", "vp1902.json")
        a = load_arch(p)
        self.assertEqual(a.name, "vp1902")

    def test_unknown_arch_raises(self):
        with self.assertRaises(FileNotFoundError):
            arch_path("no_such_device_xyz")

    def test_segments_sorted_and_covering(self):
        a = load_arch()
        lens = [s.length for s in a.segments]
        self.assertEqual(lens, sorted(lens))
        self.assertEqual(a.segment_for(1).length, 1)
        self.assertGreaterEqual(a.segment_for(99).length, 1)  # clamps to longest
        for s in a.segments:
            self.assertGreater(s.elmore_ns(), 0.0)

    def test_utilization_unchanged(self):
        # alu4 v0.2 baseline: 12 LUT6 / 4 DFF -> 0.000142% LUT6 util
        u = utilization(12, 4)
        self.assertAlmostEqual(u["LUT6"], 100.0 * 12 / 8_460_000, places=9)
        self.assertAlmostEqual(u["FF"], 100.0 * 4 / 16_920_000, places=9)
        self.assertGreater(u["CLB"], 0.0)

    def test_fabric_uses_arch_io_policy(self):
        a = load_arch()
        fab = build_fabric(8, 8, [1, 2, 3], [4, 5], arch=a)
        self.assertIs(fab.arch, a)
        self.assertEqual(len(fab.io_pos), 5)
        # default policy: inputs on west/north, outputs on east/south
        self.assertEqual(fab.io_pos[1], (0, 0))       # first west slot
        self.assertEqual(fab.io_pos[4], (7, 0))       # first east slot

if __name__ == "__main__":
    unittest.main()
