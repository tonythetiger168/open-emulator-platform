"""Floorplanning constraints (improvement-plan Phase B item 7, v0.12).

VTR 9 added floorplanning constraints to VPR; for the emulator platform this
is the module-level floorplan hook and the precursor of multi-FPGA
partitioning (plan item 7: 「鋪 multi-FPGA partition 的路」).

Constraint file (JSON):

  {
    "regions": [
      {"name": "core", "rect": [x0, y0, x1, y1],
       "blocks": ["q[", "alt_w*"],            # cell-name selectors
       "exclusive": true}                      # optional: reserve rect
    ],
    "fixed": {"q[0]": [3, 4]}                  # exact lock, cell-name -> slot
  }

Block addressing: packed Blocks carry their source cells; a selector matches
a block when ANY cell name in the block starts with the selector (trailing
'*' may be written explicitly, a bare string is treated as a prefix too).
Unmatched blocks stay unconstrained. Constraints are hard: a placement that
violates any of them is rejected by verify_floorplan() and the CLI exits 1 —
constraints are never silently degraded.

Semantics:
  - fixed:    the block is locked to the exact CLB slot (removed from the
              free pool; immune to SA moves). Two blocks locked to the same
              slot, or a lock outside the grid, is infeasible -> ValueError.
  - regions:  member blocks must be placed inside rect. The centroid seed
              clamps ideal positions into the rect; legalization searches
              only free slots inside it; SA proposes only in-rect moves.
  - exclusive regions reserve their slots for member blocks only (other
              blocks may not use them); non-exclusive rects only constrain
              member blocks, slots stay shared.

Feasibility is checked up front: each region needs at least as many in-rect
slots as member blocks, accounting for fixed locks and exclusive
reservations. Infeasible specs fail before placement starts.

Public API: load_floorplan(), apply_floorplan() (constraint bookkeeping on
blocks), place(floorplan=...), verify_floorplan().
"""
import json


class FloorplanError(ValueError):
    """Infeasible or malformed floorplan constraint."""


def _norm_selector(sel):
    return sel[:-1] if sel.endswith("*") else sel


def block_names(block):
    """Human-addressable names of a packed block (its named cells)."""
    return [c.name for c in block.luts + block.ffs if getattr(c, "name", "")]


def _matches(names, sel):
    p = _norm_selector(sel)
    return any(n.startswith(p) for n in names)


class Floorplan:
    """Resolved constraints: per-block region rect / fixed slot."""

    def __init__(self, regions=None, fixed=None):
        # block index -> (x0, y0, x1, y1) inclusive rect
        self.block_region = {}
        # block index -> (x, y) exact slot
        self.block_fixed = {}
        # region name -> rect, for reporting
        self.regions = regions or {}
        self.fixed = fixed or {}

    @staticmethod
    def load(path):
        d = json.loads(open(path, encoding="utf-8").read())
        if not isinstance(d, dict):
            raise FloorplanError("floorplan file must be a JSON object")
        return d

    def resolve(self, blocks, fab):
        """Match selectors to blocks and check feasibility. Returns self."""
        slots = set(fab.clbs())
        n = fab.n

        names = [block_names(b) for b in blocks]

        # --- regions ---
        claimed = {}   # block -> region name (detect double assignment)
        for reg in self.regions:
            rect = tuple(reg["rect"])
            if len(rect) != 4:
                raise FloorplanError(f"region {reg.get('name')!r}: rect needs 4 ints")
            x0, y0, x1, y1 = rect
            if not (0 <= x0 <= x1 < n and 0 <= y0 <= y1 < n):
                raise FloorplanError(
                    f"region {reg.get('name')!r}: rect {rect} outside {n}x{n} grid")
            in_rect = [(x, y) for x in range(x0, x1 + 1)
                              for y in range(y0, y1 + 1)]
            members = []
            for i, ns in enumerate(names):
                if any(_matches(ns, sel) for sel in reg.get("blocks", [])):
                    if i in claimed:
                        raise FloorplanError(
                            f"block {i} matches both regions "
                            f"{claimed[i]!r} and {reg.get('name')!r}")
                    claimed[i] = reg.get("name", "?")
                    members.append(i)
                    self.block_region[i] = rect
            # feasibility: member blocks must fit in the rect
            if len(members) > len(in_rect):
                raise FloorplanError(
                    f"region {reg.get('name')!r}: {len(members)} member blocks "
                    f"> {len(in_rect)} slots in rect {rect}")
            reg["_members"] = members

        # --- fixed locks ---
        locked = {}    # slot -> block (detect double lock)
        for sel, slot in self.fixed.items():
            slot = tuple(slot)
            if slot not in slots:
                raise FloorplanError(f"fixed slot {slot} is not a CLB slot")
            hit = [i for i, ns in enumerate(names) if _matches(ns, sel)]
            if not hit:
                raise FloorplanError(f"fixed selector {sel!r} matches no block")
            for i in hit:
                if i in self.block_fixed and self.block_fixed[i] != slot:
                    raise FloorplanError(
                        f"block {i} locked twice: {self.block_fixed[i]} vs {slot}")
                self.block_fixed[i] = slot
                if slot in locked and locked[slot] != i:
                    raise FloorplanError(
                        f"slot {slot} locked by both block {locked[slot]} "
                        f"and block {i}")
                locked[slot] = i
                r = self.block_region.get(i)
                if r and not (r[0] <= slot[0] <= r[2] and r[1] <= slot[1] <= r[3]):
                    raise FloorplanError(
                        f"fixed slot {slot} of block {i} outside its region {r}")
        # exclusive regions: member + exclusive -> no outsider may use rect
        self._exclusive = []
        for reg in self.regions:
            if reg.get("exclusive"):
                self._exclusive.append((tuple(reg["rect"]), set(reg["_members"])))
        return self

    def region_of(self, i):
        return self.block_region.get(i)

    def fixed_of(self, i):
        return self.block_fixed.get(i)

    def exclusive_violation(self, i, slot):
        """None if block i may occupy slot, else reason string."""
        r = self.block_region.get(i)
        if r and not (r[0] <= slot[0] <= r[2] and r[1] <= slot[1] <= r[3]):
            return f"block {i} outside its region rect {r}"
        for rect, members in getattr(self, "_exclusive", []):
            x0, y0, x1, y1 = rect
            if (x0 <= slot[0] <= x1 and y0 <= slot[1] <= y1) and i not in members:
                return f"block {i} in exclusive region rect {rect}"
        return None


def load_floorplan(path_or_dict):
    """Floorplan spec from a JSON path or an already-parsed dict."""
    if isinstance(path_or_dict, dict):
        return path_or_dict
    return Floorplan.load(path_or_dict)


def make_floorplan(spec, blocks, fab):
    """One-shot: spec -> resolved Floorplan (raises FloorplanError)."""
    spec = load_floorplan(spec)
    fp = Floorplan(regions=spec.get("regions", []),
                   fixed=spec.get("fixed", {}))
    return fp.resolve(blocks, fab)


def verify_floorplan(blocks, blk_at, fab, fp):
    """Post-placement audit: [] means every constraint holds."""
    bad = []
    seen = {}
    for i, slot in enumerate(blk_at):
        if slot in seen:
            bad.append(f"blocks {seen[slot]} and {i} both at {slot}")
        seen[slot] = i
        if i in fp.block_fixed and fp.block_fixed[i] != slot:
            bad.append(f"fixed block {i} at {slot}, "
                       f"expected {fp.block_fixed[i]}")
        reason = fp.exclusive_violation(i, slot)
        if reason:
            bad.append(reason)
    return bad
