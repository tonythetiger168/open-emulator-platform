import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.route import route
from efc.routepar import route_par, _classify
from efc.qor import auto_grid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")
BENCH = os.path.join(ROOT, "benchmarks")


def _demands(n, specs):
    """specs: net -> (src, [sinks])"""
    return {i: (s, k) for i, (s, k) in enumerate(specs)}


class RouteParTest(unittest.TestCase):
    def test_classify_local_vs_global(self):
        d = _demands(8, [((0, 0), [(0, 3)]),          # local, strip 0
                         ((1, 0), [(6, 7)]),         # global (crosses strips)
                         ((5, 2), [(6, 3)])])        # local, strip 1 (bins=2)
        cls, edges = _classify(d, 8, 2)
        self.assertEqual(cls[0], 0)
        self.assertIsNone(cls[1])
        self.assertEqual(cls[2], 1)

    def test_matches_sequential_wirelength(self):
        d = _demands(8, [((0, 0), [(7, 7), (0, 7)]),
                         ((2, 2), [(5, 5)]),
                         ((1, 7), [(6, 0)])])
        seq = route(d, 8, 4)
        par = route_par(d, 8, 4, bins=2, workers=2)
        self.assertEqual(par["overused"], 0)
        self.assertFalse(par["route_par_fallback"])
        self.assertEqual(par["wirelength"], seq["wirelength"])

    def test_deterministic(self):
        d = _demands(12, [((0, 0), [(11, 11)]),
                          ((3, 1), [(8, 9)]),
                          ((2, 5), [(2, 10)]),
                          ((9, 0), [(1, 3)])])
        a = route_par(d, 12, 4, bins=3, workers=2)
        b = route_par(d, 12, 4, bins=3, workers=2)
        self.assertEqual(a["wirelength"], b["wirelength"])
        self.assertEqual(a["expanded_nodes"], b["expanded_nodes"])
        self.assertEqual(a["routes"], b["routes"])

    def test_fallback_on_merged_overuse(self):
        # rig a local-phase route that double-uses an edge; the merged
        # occupancy check must detect overuse and fall back to the
        # sequential PathFinder (result identical to route() by construction)
        from unittest import mock
        import efc.routepar as rp
        real = rp.route

        def rigged(demands, n, tracks, **kw):
            r = real(demands, n, tracks, **kw)
            if "occ0" in kw:              # local-phase call carries occ0
                net = next(iter(r["routes"]))
                r["routes"][net] = r["routes"][net] + [((0, 0), (1, 0))]
                r["overused"] = 1
            return r

        d = _demands(8, [((0, 0), [(3, 3)]), ((5, 0), [(7, 7)])])
        with mock.patch.object(rp, "route", side_effect=rigged):
            par = rp.route_par(d, 8, 1, bins=2, workers=1)   # tracks=1: the
            # rigged double-use of one edge exceeds capacity
        self.assertTrue(par["route_par_fallback"])
        self.assertEqual(par["overused"], 0)
        seq = route(d, 8, 1)
        self.assertEqual(par["wirelength"], seq["wirelength"])

    def test_bins_must_be_ge2(self):
        with self.assertRaises(ValueError):
            route_par(_demands(4, [((0, 0), [(3, 3)])]), 4, 2, bins=1)

    def test_all_benchmarks_route_clean(self):
        for f in sorted(os.listdir(BENCH)):
            if f.endswith(".v"):
                p = os.path.join(BENCH, f)
                rep = compile_file(p, grid=auto_grid(p),
                                   arch="vp1902", route_par=True, workers=2)
                self.assertEqual(rep["route_overused_channels"], 0, f)
                self.assertIn("fallback=False", rep["route_par"], f)

    def test_cli_default_unchanged(self):
        a = compile_file(EX, grid=8, arch="vp1902")
        b = compile_file(EX, grid=8, arch="vp1902")
        self.assertEqual(a["route_wirelength"], b["route_wirelength"])
        self.assertNotIn("route_par", a)   # report only carries par fields on request


if __name__ == "__main__":
    unittest.main()
