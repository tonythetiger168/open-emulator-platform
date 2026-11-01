import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.cli import compile_file
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.pack import pack
from efc.fabric import build_fabric
from efc.place import place
from efc.shellpatch import partition_shell_patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "alu4.v")


def placed(grid=8):
    src = open(EX, encoding="utf-8").read()
    nl = elaborate(parse_verilog(src))
    mapped, _ = techmap(nl)
    blocks, ext_nets = pack(mapped)
    fab = build_fabric(grid, 8, nl.inputs, nl.outputs)
    blk_at, _ = place(blocks, ext_nets, fab)
    return blocks, ext_nets, fab, blk_at


class ShellPatchTest(unittest.TestCase):
    def test_every_block_covered_exactly_once(self):
        blocks, ext_nets, fab, blk_at = placed()
        sp = partition_shell_patch(blocks, blk_at, ext_nets, fab, (0, 0, 3, 3))
        p = {e["block"] for e in sp["patch_blocks"]}
        s = {e["block"] for e in sp["shell_blocks"]}
        self.assertEqual(p | s, set(range(len(blocks))))
        self.assertEqual(p & s, set())
        self.assertEqual(sp["stats"]["patch"], len(p))
        self.assertEqual(sp["stats"]["shell"], len(s))

    def test_partition_by_position(self):
        blocks, ext_nets, fab, blk_at = placed()
        sp = partition_shell_patch(blocks, blk_at, ext_nets, fab, (0, 0, 3, 7))
        for e in sp["patch_blocks"]:
            self.assertLessEqual(blk_at[e["block"]][0], 3)
        for e in sp["shell_blocks"]:
            self.assertGreater(blk_at[e["block"]][0], 3)

    def test_boundary_nets_detected(self):
        # hand-built: 2 blocks, one net between them across the patch edge
        class B:  # minimal block stand-in (names via cells)
            luts, ffs = [], []
        blocks = [B(), B()]
        blk_at = [(1, 1), (6, 6)]
        ext_nets = {7: [("blk", 0), ("blk", 1)],
                    8: [("blk", 0), ("io", 8)]}
        fab = build_fabric(8, 8, [], [])
        fab.io_pos[8] = (0, 0)                     # west pad -> shell side
        sp = partition_shell_patch(blocks, blk_at, ext_nets, fab, (0, 0, 3, 3))
        nets = {b["net"]: b for b in sp["boundary_nets"]}
        self.assertIn(7, nets)
        self.assertEqual(nets[7]["sides"], ["patch", "shell"])
        self.assertIn(8, nets)                     # patch -> IO pad boundary
        self.assertEqual(nets[8]["sides"], ["io", "patch"])

    def test_internal_patch_net_not_boundary(self):
        class B:
            luts, ffs = [], []
        blocks = [B(), B()]
        blk_at = [(1, 1), (2, 2)]
        ext_nets = {7: [("blk", 0), ("blk", 1)]}
        fab = build_fabric(8, 8, [], [])
        sp = partition_shell_patch(blocks, blk_at, ext_nets, fab, (0, 0, 3, 3))
        self.assertEqual(sp["boundary_nets"], [])

    def test_rect_outside_grid_rejected(self):
        blocks, ext_nets, fab, blk_at = placed()
        with self.assertRaises(ValueError):
            partition_shell_patch(blocks, blk_at, ext_nets, fab, (0, 0, 99, 3))

    def test_json_serialisable(self):
        blocks, ext_nets, fab, blk_at = placed()
        sp = partition_shell_patch(blocks, blk_at, ext_nets, fab, (2, 2, 5, 5))
        json.dumps(sp)   # must not raise

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "sp.json")
            rep = compile_file(EX, grid=8, arch="vp1902",
                               shell_patch=(2, 2, 5, 5), shell_patch_out=out)
            self.assertIn("boundary_nets=", rep["shell_patch"])
            sp = json.load(open(out))
            self.assertEqual(sp["stats"]["blocks"], 4)


if __name__ == "__main__":
    unittest.main()
