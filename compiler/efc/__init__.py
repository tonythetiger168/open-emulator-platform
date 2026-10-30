"""efc — Emulator FPGA Compiler (single-FPGA, targeting AMD VP1902).

Pipeline (Synplify Pro analogue):
  verilog.py  frontend parse             ~ Synplify HDL compiler
  netlist.py  elaborate, bit-blast       ~ HDL Analyst (RTL view)
  techmap.py  gates -> LUT6 (dispatcher) ~ technology mapper (Technology view)
  cutmap.py   cut-enumeration LUT mapper ~ ABC/FlowMap-style mapping
  lec.py      SAT equivalence check      ~ Formality/LEC (via Yosys equiv)
  arch.py     device arch spec (JSON)    ~ VPR architecture XML
  fabric.py   logical grid from arch     ~ VPR grid builder
  pack.py     CLB packing (8 LUT6+16 FF) ~ VP1902 slice structure
  place.py    SA placement (block level) ~ self-developed P&R, VPR-style
  route.py    A* timing-driven PathFinder ~ self-developed P&R
  timing.py   STA (Elmore + criticality) ~ Timing Analyst
  edif.py     EDIF 2.0.0 + XDC writers   ~ Vivado real-device path
  xc7out.py   7-series primitive Verilog ~ OpenXC7/nextpnr-xilinx (no Vivado)
  qor.py      QoR golden regression       ~ VTR golden-QoR tracking
"""
__version__ = "0.10.0"
