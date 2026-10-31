"""Prepack molecule tests (v0.11): detection, packing atomicity, QoR parity."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.netlist import Cell
from efc.techmap import LutNet
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.prepack import prepack, molecule_stats, CARRY8_MAX_BITS
from efc.pack import pack, pack_molecules

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "examples", "alu4.v")

DUPFF = ("module t(a, b, clk, q, r); input a; input b; input clk;\n"
         " output reg q; output reg r;\n"
         " wire s; assign s = a & b;\n"
         " always @(posedge clk) begin\n"
         "   q <= s;\n"
         "   r <= s;\n"
         " end\n"
         "endmodule\n")

PIREG = ("module t(a, clk, q); input a; input clk; output reg q;\n"
         " always @(posedge clk) begin\n"
         "   q <= a;\n"
         " end\n"
         "endmodule\n")


def mk_lut(ins, out):
    return Cell("LUT6", list(ins), out)


def mk_dff(d, clk, out):
    return Cell("DFF", [d, clk], out)


def synth_lutnet(luts, dffs, inputs=(), outputs=(), carry_chains=None):
    ln = LutNet()
    ln.luts, ln.dffs = list(luts), list(dffs)
    ln.inputs, ln.outputs = list(inputs), list(outputs)
    if carry_chains is not None:
        ln.carry_chains = carry_chains
    return ln


class TestDetect(unittest.TestCase):
    def test_alu4_all_paired(self):
        nl = elaborate(parse_verilog(open(EX, encoding="utf-8").read()))
        mapped, _ = techmap(nl, k=6)
        mols = prepack(mapped)
        self.assertEqual(molecule_stats(mols), "single=0 lutff=4 carry8=0")
        total = sum(len(m.cells) for m in mols)
        self.assertEqual(total, len(mapped.luts) + len(mapped.dffs))

    def test_shared_lut_not_paired(self):
        # s feeds two DFFs: fanout 2 -> no lutff molecule, all singles
        nl = elaborate(parse_verilog(DUPFF))
        mapped, _ = techmap(nl, k=6)
        mols = prepack(mapped)
        self.assertEqual(molecule_stats(mols), "single=3 lutff=0 carry8=0")

    def test_pi_driven_dff_stays_single(self):
        nl = elaborate(parse_verilog(PIREG))
        mapped, _ = techmap(nl, k=6)
        mols = prepack(mapped)
        self.assertEqual(molecule_stats(mols), "single=1 lutff=0 carry8=0")
        self.assertEqual(mols[0].cells[0].type, "DFF")


class TestCarry8(unittest.TestCase):
    def setUp(self):
        # synthetic 4-bit carry chain: LUTs 1..4 (bit order) + 2 paired DFFs
        self.luts = [mk_lut([100 + i], 200 + i) for i in range(4)]
        self.dffs = [mk_dff(200, 900, 300), mk_dff(201, 900, 301)]
        self.chain = self.luts
        self.mapped = synth_lutnet(self.luts, self.dffs,
                                   inputs=[100, 101, 102, 103],
                                   outputs=[300, 301],
                                   carry_chains=[self.chain])

    def test_chain_forms_one_molecule(self):
        mols = prepack(self.mapped)
        carry = [m for m in mols if m.kind == "carry8"]
        self.assertEqual(len(carry), 1)
        self.assertEqual(carry[0].cells, self.luts)  # bit order preserved
        self.assertEqual(molecule_stats(mols), "single=2 lutff=0 carry8=1")
        # chain LUTs must not double as lutff partners
        self.assertFalse(any(m.kind == "lutff" for m in mols))

    def test_chain_packed_atomically(self):
        mols = prepack(self.mapped)
        blocks, _ = pack_molecules(mols, self.mapped)
        blk0 = blocks[0]
        self.assertEqual(len(blk0.luts), 4)  # whole chain in one CLB
        self.assertEqual([id(c) for c in blk0.luts],
                         [id(c) for c in self.luts])

    def test_chain_capacity_checked(self):
        big = synth_lutnet([mk_lut([i], 100 + i) for i in range(9)], [],
                           carry_chains=[None])
        big.carry_chains = [list(big.luts)]
        with self.assertRaises(ValueError):
            prepack(big)
        ok = synth_lutnet([mk_lut([i], 100 + i) for i in range(CARRY8_MAX_BITS)],
                          [])
        ok.carry_chains = [list(ok.luts)]
        self.assertEqual(len(prepack(ok)), 1)  # exactly 8 bits is legal

    def test_chain_cell_validation(self):
        alien = synth_lutnet([], [])
        alien.carry_chains = [[mk_lut([1], 2)]]  # not in luts/dffs
        with self.assertRaises(ValueError):
            prepack(alien)
        dup = synth_lutnet([mk_lut([1], 2)], [])
        dup.carry_chains = [[dup.luts[0]], [dup.luts[0]]]
        with self.assertRaises(ValueError):
            prepack(dup)


class TestPackParity(unittest.TestCase):
    def test_alu4_packing_unchanged(self):
        nl = elaborate(parse_verilog(open(EX, encoding="utf-8").read()))
        mapped, _ = techmap(nl, k=6)
        blocks, ext = pack(mapped)
        self.assertEqual(len(blocks), 4)  # v0.10 golden: CLB_used = 4
        for b in blocks:
            self.assertEqual((len(b.luts), len(b.ffs)), (1, 1))
        self.assertEqual(len(ext), 14)  # v0.10 golden ext nets


class TestCli(unittest.TestCase):
    def test_cli_reports_molecules(self):
        from efc.cli import compile_file
        rep = compile_file(EX, grid=8, tracks=8)
        self.assertEqual(rep["molecules"], "single=0 lutff=4 carry8=0")
        self.assertEqual(rep["CLB_used"], 4)


if __name__ == "__main__":
    unittest.main()
