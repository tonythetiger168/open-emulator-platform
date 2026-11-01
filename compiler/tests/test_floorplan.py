import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.pack import pack
from efc.fabric import build_fabric
from efc.place import place
from efc.floorplan import (Floorplan, FloorplanError, make_floorplan,
                           verify_floorplan, block_names)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")


def build(nb_blocks=6, grid=8):
    src = open(EX, encoding="utf-8").read()
    nl = elaborate(parse_verilog(src))
    mapped, _ = techmap(nl)
    blocks, ext_nets = pack(mapped)
    fab = build_fabric(grid, 8, nl.inputs, nl.outputs)
    return blocks, ext_nets, fab


class FloorplanTest(unittest.TestCase):
    def test_region_containment(self):
        blocks, ext_nets, fab = build()
        half = len(blocks) // 2
        names = [block_names(b) for b in blocks]
        sel = [names[i][0] for i in range(half)]           # first half of blocks
        spec = {"regions": [{"name": "west", "rect": [0, 0, 3, 7],
                             "blocks": sel}]}
        fp = make_floorplan(spec, blocks, fab)
        blk_at, _ = place(blocks, ext_nets, fab, floorplan=fp)
        self.assertEqual(verify_floorplan(blocks, blk_at, fab, fp), [])
        for i in range(half):
            x, y = blk_at[i]
            self.assertTrue(0 <= x <= 3, f"block {i} at {blk_at[i]} outside rect")

    def test_fixed_lock_holds_through_sa(self):
        blocks, ext_nets, fab = build()
        names = block_names(blocks[0])
        spec = {"fixed": {names[0]: [5, 5]}}
        fp = make_floorplan(spec, blocks, fab)
        blk_at, _ = place(blocks, ext_nets, fab, seed=7, floorplan=fp)
        self.assertEqual(blk_at[0], (5, 5))
        self.assertEqual(verify_floorplan(blocks, blk_at, fab, fp), [])

    def test_infeasible_region_rejected(self):
        blocks, ext_nets, fab = build()
        spec = {"regions": [{"name": "tiny", "rect": [0, 0, 0, 0],
                             "blocks": ["y["]}]}       # all DFF blocks, >1 slot
        with self.assertRaises(FloorplanError):
            make_floorplan(spec, blocks, fab)

    def test_double_lock_same_slot_rejected(self):
        blocks, ext_nets, fab = build()
        n0 = block_names(blocks[0])[0]
        n1 = block_names(blocks[1])[0]
        spec = {"fixed": {n0: [2, 2], n1: [2, 2]}}
        with self.assertRaises(FloorplanError):
            make_floorplan(spec, blocks, fab)

    def test_lock_outside_grid_rejected(self):
        blocks, ext_nets, fab = build()
        spec = {"fixed": {block_names(blocks[0])[0]: [99, 0]}}
        with self.assertRaises(FloorplanError):
            make_floorplan(spec, blocks, fab)

    def test_selector_matches_no_block_rejected(self):
        blocks, ext_nets, fab = build()
        spec = {"fixed": {"nonexistent_signal_xyz": [1, 1]}}
        with self.assertRaises(FloorplanError):
            make_floorplan(spec, blocks, fab)

    def test_verify_catches_violation(self):
        blocks, ext_nets, fab = build()
        spec = {"regions": [{"name": "w", "rect": [0, 0, 1, 7],
                             "blocks": [block_names(blocks[0])[0]]}]}
        fp = make_floorplan(spec, blocks, fab)
        bad = verify_floorplan(blocks, [(7, 7)] * len(blocks), fab, fp)
        self.assertTrue(any("outside its region" in b for b in bad))

    def test_exclusive_region_keeps_outsiders_out(self):
        blocks, ext_nets, fab = build()
        names = [block_names(b)[0] for b in blocks]
        member = names[0]
        spec = {"regions": [{"name": "priv", "rect": [0, 0, 3, 3],
                             "blocks": [member], "exclusive": True}]}
        fp = make_floorplan(spec, blocks, fab)
        blk_at, _ = place(blocks, ext_nets, fab, floorplan=fp)
        self.assertEqual(verify_floorplan(blocks, blk_at, fab, fp), [])
        for i in range(1, len(blocks)):
            self.assertFalse(0 <= blk_at[i][0] <= 3 and 0 <= blk_at[i][1] <= 3,
                             f"outsider block {i} inside exclusive rect")

    def test_default_flow_bit_identical(self):
        """floorplan=None must not perturb the QoR-guarded default flow."""
        blocks, ext_nets, fab = build()
        a, _ = place(blocks, ext_nets, fab, seed=3)
        b, _ = place(blocks, ext_nets, fab, seed=3, floorplan=None)
        self.assertEqual(a, b)

    def test_cli_floorplan_end_to_end(self):
        spec = {"regions": [{"name": "west", "rect": [0, 0, 3, 7],
                             "blocks": ["y["]}],
                "fixed": {"y[0]": [2, 2]}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            import json
            json.dump(spec, f)
            path = f.name
        try:
            rep = compile_file(EX, grid=8, arch="vp1902", floorplan=path)
            self.assertIn("violations=0", rep["floorplan"])
        finally:
            os.unlink(path)

    def test_deterministic_with_floorplan(self):
        blocks, ext_nets, fab = build()
        spec = {"regions": [{"name": "w", "rect": [0, 0, 3, 7],
                             "blocks": ["y["]}]}
        fp = make_floorplan(spec, blocks, fab)
        a, _ = place(blocks, ext_nets, fab, seed=5, floorplan=fp)
        b, _ = place(blocks, ext_nets, fab, seed=5, floorplan=fp)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
