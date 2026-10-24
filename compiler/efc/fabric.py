"""Fabric model: logical grid for P&R, built from a data-driven ArchSpec.

The logical N x N grid is where our SA placer / PathFinder router work;
capacity is checked against the arch envelope (real device numbers). One
grid CLB slot hosts one packed Block. The arch spec (arch/*.json) carries
CLB structure, routing segments, switch-block topology and IO policy —
see arch.py. Timing/segment data are consumed by later timing-driven
passes; the grid graph itself is still unit-length.
"""
from dataclasses import dataclass, field
from .arch import ArchSpec, load_arch


@dataclass
class Fabric:
    n: int                      # logical grid dimension (CLBs per side)
    tracks: int                 # routing tracks per channel
    arch: ArchSpec
    io_pos: dict = field(default_factory=dict)  # net id -> (x, y) on perimeter

    def clbs(self):
        return [(x, y) for x in range(self.n) for y in range(self.n)]


def _side_slots(side: str, n: int):
    if side == "west":  return [(0, y) for y in range(n)]
    if side == "east":  return [(n - 1, y) for y in range(n)]
    if side == "north": return [(x, 0) for x in range(1, n - 1)]
    if side == "south": return [(x, n - 1) for x in range(1, n - 1)]
    raise ValueError(f"bad io side {side!r}")


def build_fabric(n: int, tracks: int, pi_nets, po_nets, arch: ArchSpec = None):
    arch = arch or load_arch()
    fab = Fabric(n, tracks, arch, {})
    pi_slots = [p for side in arch.io.inputs for p in _side_slots(side, n)]
    po_slots = [p for side in arch.io.outputs for p in _side_slots(side, n)]
    # dedupe while keeping order (corner overlap between sides)
    pi_slots = list(dict.fromkeys(pi_slots))
    po_slots = list(dict.fromkeys(po_slots))
    if len(pi_nets) > len(pi_slots) or len(po_nets) > len(po_slots):
        raise ValueError(
            f"fabric {n}x{n} too small for {len(pi_nets)} PI + {len(po_nets)} PO")
    for net, pos in zip(pi_nets, pi_slots):
        fab.io_pos[net] = pos
    for net, pos in zip(po_nets, po_slots):
        fab.io_pos[net] = pos
    return fab


def utilization(n_luts: int, n_ffs: int, arch: ArchSpec = None):
    """Utilization against the arch envelope (real device), in percent."""
    arch = arch or load_arch()
    env, clb = arch.envelope, arch.clb
    clbs_needed = max(-(-n_luts // clb.luts), -(-n_ffs // clb.ffs))
    return {
        "LUT6": 100.0 * n_luts / env["LUT6"],
        "FF": 100.0 * n_ffs / env["FF"],
        "CLB": 100.0 * clbs_needed / arch.clb_count,
    }
