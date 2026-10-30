"""QoR regression tests (v0.10): corpus compiles, golden matches, regressions caught."""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc import qor
from efc.lec import _find_yosys

HAVE_YOSYS = _find_yosys() is not None


def load_golden():
    with open(qor.GOLDEN, encoding="utf-8") as f:
        return json.load(f)


class TestCorpus(unittest.TestCase):
    def test_corpus_present(self):
        names = sorted(f[:-2] for f in os.listdir(qor.BENCH_DIR)
                       if f.endswith(".v"))
        self.assertEqual(names, ["alu4", "maj4", "mixer8", "regpipe8", "sel4"])

    def test_corpus_compiles(self):
        cur = qor.run_corpus(lec=False)
        self.assertEqual(sorted(cur),
                         ["alu4", "maj4", "mixer8", "regpipe8", "sel4"])
        for name, m in cur.items():
            self.assertGreater(m["LUTs"], 0, name)
            self.assertIn("runtime_s", m, name)
            self.assertEqual(m["grid"], qor.auto_grid(
                os.path.join(qor.BENCH_DIR, name + ".v")), name)

    def test_auto_grid_fabric_capacity(self):
        # fabric IO capacity = 2*grid per direction class; 25 PIs need grid >= 15
        self.assertEqual(qor.auto_grid(os.path.join(qor.BENCH_DIR, "alu4.v")), 8)
        self.assertEqual(qor.auto_grid(os.path.join(qor.BENCH_DIR, "mixer8.v")), 15)


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.golden = load_golden()
        self.cur = copy.deepcopy(self.golden)

    def test_golden_has_no_drift_keys(self):
        for name, m in self.golden.items():
            for k in qor.DETERMINISTIC:
                self.assertIn(k, m, (name, k))
            self.assertIn("runtime_s", m, name)

    def test_identical_passes(self):
        self.assertEqual(qor.compare(self.golden, self.cur), [])

    def test_catches_lut_regression(self):
        self.cur["alu4"]["LUTs"] += 1
        bad = qor.compare(self.golden, self.cur)
        self.assertEqual(len(bad), 1)
        self.assertIn("alu4", bad[0])
        self.assertIn("LUTs", bad[0])

    def test_catches_cp_regression(self):
        self.cur["sel4"]["critical_path_ns"] += 1.0
        bad = qor.compare(self.golden, self.cur)
        self.assertEqual(len(bad), 1)
        self.assertIn("critical_path_ns", bad[0])

    def test_runtime_never_asserted(self):
        for m in self.cur.values():
            m["runtime_s"] *= 10.0
        self.assertEqual(qor.compare(self.golden, self.cur), [])
        drift = qor.drift_report(self.golden, self.cur)
        self.assertEqual(len(drift), len(self.golden))
        self.assertIn("+900.0%", drift[0])

    def test_missing_and_new_benchmarks_flagged(self):
        del self.cur["maj4"]
        self.cur["newblk"] = copy.deepcopy(self.golden["alu4"])
        bad = qor.compare(self.golden, self.cur)
        self.assertTrue(any("missing" in b and "maj4" in b for b in bad))
        self.assertTrue(any("new" in b and "newblk" in b for b in bad))

    def test_lec_skipped_current_is_neutral(self):
        self.cur["alu4"]["lec"] = "skipped (yosys not found)"
        self.assertEqual(qor.compare(self.golden, self.cur), [])
        self.cur["alu4"]["lec"] = "failed (1 unproven)"
        bad = qor.compare(self.golden, self.cur)
        self.assertEqual(len(bad), 1)
        self.assertIn("lec", bad[0])


class TestGoldenEndToEnd(unittest.TestCase):
    def setUp(self):
        self.golden = load_golden()

    @unittest.skipUnless(HAVE_YOSYS, "yosys not found")
    def test_golden_matches_current_run(self):
        cur = qor.run_corpus()
        self.assertEqual(qor.compare(self.golden, cur), [])

    @unittest.skipUnless(HAVE_YOSYS, "yosys not found")
    def test_lec_proven_per_bench(self):
        cur = qor.run_corpus()
        for name, m in cur.items():
            self.assertTrue(m["lec"].startswith("proven"), (name, m["lec"]))

    @unittest.skipUnless(HAVE_YOSYS, "yosys not found")
    def test_main_check_exit_zero(self):
        self.assertEqual(qor.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
