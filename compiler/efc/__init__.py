"""efc — Emulator FPGA Compiler (single-FPGA, targeting AMD VP1902).

Pipeline (Synplify Pro analogue):
  verilog.py  frontend parse             ~ Synplify HDL compiler
  netlist.py  elaborate, bit-blast       ~ HDL Analyst (RTL view)
  techmap.py  gates -> LUT6 + INIT       ~ technology mapper (Technology view)
  arch.py     device arch spec (JSON)    ~ VPR architecture XML
  fabric.py   logical grid from arch     ~ VPR grid builder
  pack.py     CLB packing (8 LUT6+16 FF) ~ VP1902 slice structure
  place.py    SA placement (block level) ~ self-developed P&R, VPR-style
  route.py    A* timing-driven PathFinder ~ self-developed P&R
  timing.py   STA (Elmore + criticality) ~ Timing Analyst
  edif.py     EDIF 2.0.0 + XDC writers   ~ Vivado real-device path
"""
__version__ = "0.5.0"
