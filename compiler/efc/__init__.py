"""efc — Emulator FPGA Compiler (single-FPGA, targeting AMD VP1902).

Pipeline (Synplify Pro analogue):
  verilog.py  frontend parse             ~ Synplify HDL compiler
  netlist.py  elaborate, bit-blast       ~ HDL Analyst (RTL view)
  techmap.py  gates -> LUT6 + INIT       ~ technology mapper (Technology view)
  pack.py     CLB packing (8 LUT6+16 FF) ~ VP1902 slice structure
  place.py    SA placement (block level) ~ self-developed P&R, VPR-style
  route.py    PathFinder routing         ~ self-developed P&R
  timing.py   logic depth                ~ static timing estimate
  edif.py     EDIF 2.0.0 + XDC writers   ~ Vivado real-device path
"""
__version__ = "0.2.0"
