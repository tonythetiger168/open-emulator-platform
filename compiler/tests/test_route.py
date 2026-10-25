import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.route import route, _astar
from efc.arch import load_arch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")


def _penalized_row0(k):
    """history penalty k on every edge of row y=0 from x=0..4."""
    hist = {}
    for x in range(4):
        hist[((x, 0), (x + 1, 0))] = float(k)
    return hist


class TestAStar(unittest.TestCase):
    def test_minhop_path_empty_grid(self):
        # (0,0)->(3,2): Manhattan = 5 hops; A* must find exactly 5
        path, expanded = _astar({(0, 0)}, (3, 2), 8, {}, {}, 8, 1.0, 1.0, 1.0)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (3, 2))
        self.assertEqual(len(path) - 1, 5)
        # directed search: expands far less than BFS's full 8x8 wavefront
        self.assertLess(expanded, 64)

    def test_multisource_tree_attach(self):
        # sink equidistant to two tree nodes; must attach to either, 1 hop
        path, _ = _astar({(0, 0), (2, 0)}, (1, 0), 8, {}, {}, 8, 1.0, 1.0, 1.0)
        self.assertEqual(len(path) - 1, 1)
        self.assertIn(path[0], {(0, 0), (2, 0)})

    def test_critical_net_ignores_congestion(self):
        # crit=1: straight along penalized row 0 (4 hops, delay-only cost)
        hist = _penalized_row0(5)
        path, _ = _astar({(0, 0)}, (4, 0), 8, {}, hist, 8, 1.0, 1.0, 1.0)
        self.assertEqual(len(path) - 1, 4)
        for p in path:
            self.assertEqual(p[1], 0)

    def test_noncritical_net_detours(self):
        # crit=0: pays 6/hop on row 0 -> detour via row 1 (6 hops) is cheaper
        hist = _penalized_row0(5)
        path, _ = _astar({(0, 0)}, (4, 0), 8, {}, hist, 8, 1.0, 1.0, 0.0)
        self.assertGreater(len(path) - 1, 4)
        for a, b in zip(path, path[1:]):
            e = (a, b) if a <= b else (b, a)
            self.assertNotIn(e, hist)

    def test_route_converges_and_crit_optional(self):
        demands = {"n1": ((0, 0), [(7, 7)]),
                   "n2": ((0, 7), [(7, 0), (3, 3)]),
                   "n3": ((2, 2), [(5, 5)])}
        r_plain = route(demands, 8, 4)                       # crit=None OK
        r_crit = route(demands, 8, 4, crit={"n1": 1.0, "n2": 0.2},
                       arch=load_arch())
        for r in (r_plain, r_crit):
            self.assertEqual(r["overused"], 0)
            self.assertGreater(r["expanded_nodes"], 0)
            # bounds: per-net first sink costs >= Manhattan(src, sink0);
            # each sink costs at most Manhattan(src, sink) (tree attach only
            # shortens), so sum-of-src-distances is the upper bound.
            lb = sum(abs(d[0][0] - d[1][0][0]) + abs(d[0][1] - d[1][0][1])
                     for d in demands.values())
            ub = sum(abs(s[0] - d[0][0]) + abs(s[1] - d[0][1])
                     for d in demands.values() for s in d[1])
            self.assertGreaterEqual(r["wirelength"], lb)
            self.assertLessEqual(r["wirelength"], ub)

    def test_cli_report_has_expanded_nodes(self):
        rep = compile_file(EX, grid=8, tracks=8, seed=1)
        self.assertIn("route_expanded_nodes", rep)
        self.assertEqual(rep["route_overused_channels"], 0)
        self.assertGreater(rep["route_expanded_nodes"], 0)

if __name__ == "__main__":
    unittest.main()
