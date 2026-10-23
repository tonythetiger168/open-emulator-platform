"""VP1902 fabric: real device resource envelope + logical grid for P&R.

The logical N x N grid is where our SA placer / PathFinder router work;
capacity is checked against the real VP1902 envelope. One grid CLB slot
hosts one packed Block (one physical CLB = 8 x LUT6 + 16 FF).
"""
from dataclasses import dataclass

# Real VP1902 envelope (AMD Versal Premium VP1902 datasheet numbers)
VP1902 = {
    "part": "xcvp1902",
    "system_logic_cells": 18_500_000,
    "LUT6": 8_460_000,
    "FF": 16_920_000,
    "CLB": 8_460_000 // 8,          # 1,057,500 CLBs
    "DSP58": 6_864,
    "BRAM36Kb": 6_972,              # 239 Mb total
    "URAM288Kb": 2_250,             # 619 Mb total
    "SelectIO": 2_328,
}

@dataclass
class Fabric:
    n: int               # logical grid dimension (CLBs per side)
    tracks: int          # routing tracks per channel
    io_pos: dict = None  # net id -> (x, y) on perimeter

    def clbs(self):
        return [(x, y) for x in range(self.n) for y in range(self.n)]

def build_fabric(n: int, tracks: int, pi_nets, po_nets):
    fab = Fabric(n, tracks, {})
    west = [(0, y) for y in range(n)]
    east = [(n - 1, y) for y in range(n)]
    north = [(x, 0) for x in range(1, n - 1)]
    south = [(x, n - 1) for x in range(1, n - 1)]
    pi_slots = west + north
    po_slots = east + south
    if len(pi_nets) > len(pi_slots) or len(po_nets) > len(po_slots):
        raise ValueError(
            f"fabric {n}x{n} too small for {len(pi_nets)} PI + {len(po_nets)} PO")
    for net, pos in zip(pi_nets, pi_slots):
        fab.io_pos[net] = pos
    for net, pos in zip(po_nets, po_slots):
        fab.io_pos[net] = pos
    return fab

def utilization(n_luts: int, n_ffs: int):
    """Utilization against the real VP1902 envelope, in percent."""
    return {
        "LUT6": 100.0 * n_luts / VP1902["LUT6"],
        "FF": 100.0 * n_ffs / VP1902["FF"],
        "CLB": 100.0 * max(-(-n_luts // CLB_LUTS), -(-n_ffs // CLB_FFS)) / VP1902["CLB"],
    }

CLB_LUTS, CLB_FFS = 8, 16
