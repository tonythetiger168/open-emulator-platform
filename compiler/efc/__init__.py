"""efc — Emulator FPGA Compiler (single-FPGA MVP).

Pipeline (Synplify Pro analogue):
  verilog.py  frontend parse        ~ Synplify HDL compiler / HDL Analyst
  netlist.py  elaborate, bit-blast  ~ generic netlist (RTL view)
  techmap.py  gates -> LUTK         ~ technology mapper (Technology view)
  place.py    SA placement          ~ (self-developed P&R, VPR-style)
  route.py    PathFinder routing    ~ (self-developed P&R)
  timing.py   logic depth           ~ static timing estimate
"""
__version__ = "0.1.0"
