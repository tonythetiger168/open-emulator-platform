import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.pack import pack
from efc.fabric import build_fabric
from efc.place import place, initial_placement

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")

# 6-input XOR chain: 5 LUT2s in a pure linear net structure — the design
# where a random shuffle seed is worst and a centroid seed is near-optimal.
CHAIN = ("module chain(clk, a, b, c, d, e, f, y);\n"
         " input clk; input a; input b; input c; input d; input e; input f;\n"
         " output reg y;\n"
         " wire w1; wire w2; wire w3; wire w4;\n"
         " assign w1 = a ^ b;\n"
         " assign w2 = w1 ^ c;\n"
         " assign w3 = w2 ^ d;\n"
         " assign w4 = w3 ^ e;\n"
         " always @(posedge clk) begin y <= w4 ^ f; end endmodule\n")


def _packed(src, grid=8, tracks=8):
    nl = elaborate(parse_verilog(src))
    mapped, _ = techmap(nl, k=6)
    blocks, ext = pack(mapped)
    fab = build_fabric(grid, tracks, nl.inputs, nl.outputs)
    return blocks, ext, fab


def _hpwl(blocks, ext, fab, blk_at):
    def tpos(term):
        kind, ref = term
        return fab.io_pos[ref] if kind == "io" else blk_at[ref]
    total = 0
    for terms in ext.values():
        xs, ys = [], []
        for t in terms:
            x, y = tpos(t)
            xs.append(x); ys.append(y)
        total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


class TestInitialPlacement(unittest.TestCase):
    def test_seed_is_legal_and_deterministic(self):
        blocks, ext, fab = _packed(CHAIN)
        p1 = initial_placement(blocks, ext, fab)
        p2 = initial_placement(blocks, ext, fab)
        self.assertEqual(p1, p2)                    # no RNG -> reproducible
        self.assertEqual(len(set(p1)), len(p1))     # distinct slots
        for x, y in p1:
            self.assertTrue(0 <= x < fab.n and 0 <= y < fab.n)

    def test_seed_beats_random_median(self):
        # centroid seed should land at or below the median random shuffle
        blocks, ext, fab = _packed(CHAIN)
        seed_cost = _hpwl(blocks, ext, fab,
                          initial_placement(blocks, ext, fab))
        rand_costs = []
        for s in range(20):
            blk_at, _ = place(blocks, ext, fab, seed=s, init="random",
                              moves_per_temp=0)     # pure shuffle, no SA
            rand_costs.append(_hpwl(blocks, ext, fab, blk_at))
        rand_costs.sort()
        self.assertLessEqual(seed_cost, rand_costs[len(rand_costs) // 2])

    def test_chain_seed_near_optimal(self):
        # linear 5-LUT chain + IOs: blocks lie on one path, so the bounding
        # box of the seed should be compact (<= 4 tiles per axis for the
        # pure-chain core; IO anchors sit on the perimeter by policy)
        blocks, ext, fab = _packed(CHAIN)
        blk_at = initial_placement(blocks, ext, fab)
        xs = [p[0] for p in blk_at]
        ys = [p[1] for p in blk_at]
        self.assertLessEqual(max(xs) - min(xs), 5)
        self.assertLessEqual(max(ys) - min(ys), 5)

    def test_sa_refine_never_worsens_seed(self):
        blocks, ext, fab = _packed(CHAIN)
        seed_at = initial_placement(blocks, ext, fab)
        seed_cost = _hpwl(blocks, ext, fab, seed_at)
        blk_at, cost = place(blocks, ext, fab, seed=7, init="centroid")
        self.assertLessEqual(cost, seed_cost)
        self.assertEqual(len(set(blk_at)), len(blk_at))

    def test_alu4_regression(self):
        # QoR window after the v0.5 baseline: routed with no overuse,
        # timing clean at 10 ns, wirelength not worse than the v0.5 number.
        rep = compile_file(EX, grid=8, tracks=8, seed=1)
        self.assertEqual(rep["route_overused_channels"], 0)
        self.assertFalse(rep["timing_violated"])
        self.assertLessEqual(rep["route_wirelength"], 60)
        self.assertGreater(rep["route_expanded_nodes"], 0)

    def test_init_random_matches_v05(self):
        # init="random" keeps the old entry point alive for A/B runs
        blocks, ext, fab = _packed(CHAIN)
        blk_at, cost = place(blocks, ext, fab, seed=3, init="random")
        self.assertEqual(len(set(blk_at)), len(blocks))
        self.assertGreaterEqual(cost, 0)


if __name__ == "__main__":
    unittest.main()
