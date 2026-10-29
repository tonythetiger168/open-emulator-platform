"""xc7out tests (v0.9): 7-series primitive Verilog for OpenXC7/nextpnr-xilinx."""
import json, os, re, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from efc.verilog import parse_verilog
from efc.netlist import elaborate
from efc.techmap import techmap
from efc.arch import load_arch
from efc.xc7out import emit_xc7_verilog
from efc.lec import _find_yosys

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "examples", "alu4.v")

HAVE_YOSYS = _find_yosys() is not None


def compile_mapped(mapper="cut"):
    mod = parse_verilog(open(EX, encoding="utf-8").read())
    nl = elaborate(mod)
    spec = load_arch("xc7k325t")
    mapped, _ = techmap(nl, k=spec.clb.lut_k, method=mapper)
    return mod, nl, mapped


class TestXc7Arch(unittest.TestCase):
    def test_xc7k325t_loads(self):
        a = load_arch("xc7k325t")
        self.assertEqual(a.name, "xc7k325t")
        self.assertEqual(a.part, "xc7k325tffg900-2")
        self.assertEqual(a.envelope["LUT6"], 203_800)   # DS180: 50,950 slices x4
        self.assertEqual(a.envelope["FF"], 407_600)
        self.assertEqual(a.envelope["DSP48E1"], 840)
        self.assertEqual(a.clb.luts, 8)                 # CLB = 2 slices
        self.assertEqual(a.clb.ffs, 16)
        self.assertEqual(a.clb.lut_k, 6)
        self.assertEqual(a.clb_count, 203_800 // 8)


class TestEmit(unittest.TestCase):
    def test_primitives_and_init_widths(self):
        _mod, _nl, mapped = compile_mapped()
        v = emit_xc7_verilog(mapped, mod="alu4")
        self.assertIn("IBUF ", v)
        self.assertIn("OBUF ", v)
        self.assertIn("FDRE ", v)
        n_lut = 0
        for m in re.finditer(r"LUT(\d) #\(\.INIT\((\d+)'h([0-9A-Fa-f]+)\)\)", v):
            k, bits, hexs = int(m.group(1)), int(m.group(2)), m.group(3)
            self.assertEqual(bits, 1 << k)              # INIT is 2**k bits
            self.assertEqual(len(hexs), max(1, (1 << k) // 4))
            n_lut += 1
        self.assertEqual(n_lut, len(mapped.luts))
        self.assertEqual(v.count("FDRE #(.INIT(1'b0))"), len(mapped.dffs))

    def test_names_sanitized(self):
        _mod, _nl, mapped = compile_mapped()
        v = emit_xc7_verilog(mapped, mod="alu4")
        self.assertNotIn("[", v)                        # bus bits flattened
        self.assertNotIn("\\", v)                       # no escaped identifiers
        for tok in re.findall(r"\binput\s+([^;,()]+)", v):
            self.assertRegex(tok.strip(), r"^[A-Za-z_][A-Za-z0-9_]*$")

    def test_ibuf_obuf_alias_wiring(self):
        _mod, nl, mapped = compile_mapped()
        v = emit_xc7_verilog(mapped, mod="alu4")
        self.assertEqual(len(re.findall(r"\bIBUF\b", v)), len(nl.inputs))
        self.assertEqual(len(re.findall(r"\bOBUF\b", v)), len(nl.outputs))
        self.assertIn("__ibuf", v)
        self.assertIn("__obuf", v)


@unittest.skipUnless(HAVE_YOSYS, "yosys binary not available")
class TestYosysHandoff(unittest.TestCase):
    def _run_yosys(self, script, workdir):
        yosys = _find_yosys()
        return subprocess.run([yosys, "-p", script], cwd=workdir,
                              capture_output=True, text=True, timeout=120)

    def test_yosys_parses_and_stats(self):
        mod, _nl, mapped = compile_mapped()
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "out.v"), "w").write(
                emit_xc7_verilog(mapped, mod=mod.name))
            r = self._run_yosys(
                f"read_verilog -lib +/xilinx/cells_sim.v; read_verilog out.v; "
                f"hierarchy -top {mod.name}; stat", td)
            self.assertEqual(r.returncode, 0, r.stdout[-1000:] + r.stderr[-1000:])
            counts = {t: int(c) for t, c in re.findall(
                r"^\s+(LUT[1-6]|FDRE|IBUF|OBUF)\s+(\d+)$", r.stdout, re.M)}
            self.assertEqual(sum(counts.get(f"LUT{k}", 0) for k in range(1, 7)),
                             len(mapped.luts))
            self.assertEqual(counts.get("FDRE", 0), len(mapped.dffs))
            self.assertGreater(counts.get("IBUF", 0), 0)
            self.assertGreater(counts.get("OBUF", 0), 0)

    def test_write_json_for_nextpnr(self):
        mod, _nl, mapped = compile_mapped()
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "out.v"), "w").write(
                emit_xc7_verilog(mapped, mod=mod.name))
            r = self._run_yosys(
                f"read_verilog -lib +/xilinx/cells_sim.v; read_verilog out.v; "
                f"hierarchy -top {mod.name} -purge_lib; proc; "
                f"write_json out.json", td)
            self.assertEqual(r.returncode, 0, r.stdout[-1000:] + r.stderr[-1000:])
            j = json.load(open(os.path.join(td, "out.json")))
            cells = j["modules"][mod.name]["cells"]
            types = {c["type"] for c in cells.values()}
            legal = {f"LUT{k}" for k in range(1, 7)} | {"FDRE", "IBUF", "OBUF"}
            self.assertTrue(types <= legal, f"unexpected cell types: {types - legal}")
            self.assertEqual(len(cells),
                             len(mapped.luts) + len(mapped.dffs)
                             + len(j["modules"][mod.name]["ports"]))


class TestCli(unittest.TestCase):
    def test_cli_xc7_flag(self):
        from efc.cli import compile_file
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "alu4_xc7.v")
            rep = compile_file(EX, arch="xc7k325t", xc7=out)
            self.assertEqual(rep["xc7"], out)
            self.assertTrue(os.path.isfile(out))
            self.assertIn("XC7K325T_LUT6_util_%", rep)
            self.assertEqual(rep["arch"], "xc7k325t")


if __name__ == "__main__":
    unittest.main()
