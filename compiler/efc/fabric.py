"""Abstract FPGA fabric model (VP1902-like CLB grid, bitstream-agnostic).

- grid N x N of CLB slots; each CLB hosts one mapped cell (LUT or DFF)
- IO pads fixed on the perimeter: inputs on west/north, outputs on east/south
- routing channels between adjacent CLBs with `tracks` capacity per direction
"""
from dataclasses import dataclass

@dataclass
class Fabric:
    n: int               # grid dimension (CLBs per side)
    tracks: int          # routing tracks per channel
    io_pos: dict = None  # net id -> (x, y) on perimeter

    def clbs(self):
        return [(x, y) for x in range(self.n) for y in range(self.n)]

def build_fabric(n: int, tracks: int, n_pi: int, n_po: int, pi_nets, po_nets):
    fab = Fabric(n, tracks, {})
    # perimeter slots (excluding corners), west/east first then north/south
    west = [(0, y) for y in range(n)]
    east = [(n - 1, y) for y in range(n)]
    north = [(x, 0) for x in range(1, n - 1)]
    south = [(x, n - 1) for x in range(1, n - 1)]
    pi_slots = west + north
    po_slots = east + south
    if n_pi > len(pi_slots) or n_po > len(po_slots):
        raise ValueError(f"fabric {n}x{n} too small for {n_pi} PI + {n_po} PO")
    for net, pos in zip(pi_nets, pi_slots):
        fab.io_pos[net] = pos
    for net, pos in zip(po_nets, po_slots):
        fab.io_pos[net] = pos
    return fab
