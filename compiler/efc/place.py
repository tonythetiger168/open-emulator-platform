"""Placement: smart-centroid analytic seeding (VTR 9 style) + SA refinement.

Improvement-plan Phase A item 4 (v0.6): the placer used to start from a
uniformly random shuffle and let simulated annealing dig out from there.
VTR 9 showed that a high-quality initial solution plus directed moves wins
on both runtime and QoR. This pass adds the initial solution:

  1. Smart centroid (star model): each block's ideal position is the
     connectivity-weighted centroid of the terminals on its nets (IOs are
     fixed anchors). Iterate to convergence — like VTR 9's smart centroid
     seeding, overlapping positions are legal during iteration.
  2. Legalization: greedy nearest-free-slot assignment in deterministic
     scan order (O(nb x slots) — fine for a seeding pass; swap in a
     Hungarian/auction solver if this ever shows up in a profile).
  3. SA refinement with the original VPR-style HPWL annealer, now starting
     from the seed instead of randomness.

v0.12 (Phase B item 7): optional floorplan constraints (floorplan.py) are
enforced through all three stages — centroid ideals are clamped into the
block's region rect, fixed locks claim their slots before legalization,
and SA only proposes moves that keep every constraint. floorplan=None is
the v0.6-v0.11 behaviour, bit-identical (QoR golden guard).

Public API: initial_placement() (the seed, testable on its own) and
place() (seed + refine, drop-in compatible with the v0.5 signature).
"""
import math, random

from .floorplan import FloorplanError


def _star_connectivity(ext_nets):
    """block -> list of (other_terminal_position_fn, weight) is built instead
    as block -> {net: [terms]}; here we just index nets per block."""
    blk_nets = {}
    for net, terms in ext_nets.items():
        for kind, ref in terms:
            if kind == "blk":
                blk_nets.setdefault(ref, []).append((net, terms))
    return blk_nets


def initial_placement(blocks, ext_nets, fab, iterations=25, floorplan=None):
    """Smart-centroid seed -> legal placement. Returns list of (x, y) slots.

    Deterministic: no RNG. IO terminals are fixed anchors; blocks with no
    external connectivity sit at the grid centre.

    floorplan: a resolved Floorplan (floorplan.py). Fixed blocks seed at
    their locked slot; regioned blocks clamp their ideal position into the
    region rect and legalize into in-rect free slots only. None = the
    v0.6-v0.11 behaviour, bit-identical (QoR golden guard).
    """
    nb = len(blocks)
    slots = fab.clbs()
    if nb > len(slots):
        raise ValueError(f"fabric too small: {nb} blocks > {len(slots)} CLBs")
    blk_nets = _star_connectivity(ext_nets)
    n = fab.n

    def tpos(term, pos):
        kind, ref = term
        return fab.io_pos[ref] if kind == "io" else pos[ref]

    # floats during iteration; unconnected blocks -> centre
    pos = [(n / 2.0, n / 2.0)] * nb
    for _ in range(iterations):
        new = []
        for b in range(nb):
            conns = blk_nets.get(b)
            if not conns:
                new.append((n / 2.0, n / 2.0))
                continue
            sx = sy = cnt = 0.0
            for _net, terms in conns:
                for t in terms:
                    kind, ref = t
                    if kind == "blk" and ref == b:
                        continue
                    x, y = tpos(t, pos)
                    sx += x; sy += y; cnt += 1.0
            if cnt == 0.0:
                new.append((n / 2.0, n / 2.0))
            else:
                new.append((sx / cnt, sy / cnt))
        pos = new

    # constraints shape the ideal positions before legalization
    if floorplan is not None:
        for b in range(nb):
            fx = floorplan.fixed_of(b)
            if fx is not None:
                pos[b] = (float(fx[0]), float(fx[1]))
                continue
            r = floorplan.region_of(b)
            if r is not None:
                pos[b] = (min(max(pos[b][0], r[0]), r[2]),
                          min(max(pos[b][1], r[1]), r[3]))

    # legalization: nearest free slot, deterministic scan order
    free = list(slots)
    blk_at = [None] * nb
    if floorplan is not None:
        # fixed locks claim their slots first (resolve() already proved
        # locks are unique and inside the grid)
        for b in sorted(floorplan.block_fixed):
            blk_at[b] = floorplan.block_fixed[b]
            free.remove(floorplan.block_fixed[b])
    order = sorted(range(nb), key=lambda b: (round(pos[b][1], 6),
                                             round(pos[b][0], 6), b))
    for b in order:
        if floorplan is not None and blk_at[b] is not None:
            continue                                  # fixed lock, already placed
        bx, by = pos[b]
        best_i, best_d = None, None
        for i, (x, y) in enumerate(free):
            if floorplan is not None and \
                    floorplan.exclusive_violation(b, (x, y)) is not None:
                continue
            d = abs(x - bx) + abs(y - by)
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        if best_i is None:
            raise FloorplanError(
                f"no legal slot for block {b} "
                f"(region {floorplan.region_of(b)}, "
                f"fixed {floorplan.fixed_of(b)})")
        blk_at[b] = free.pop(best_i)
    return blk_at


def place(blocks, ext_nets, fab, seed=1, moves_per_temp=40,
          t0=5.0, tmin=0.05, alpha=0.92, init="centroid", floorplan=None):
    """Seed (smart centroid by default) + VPR-style SA HPWL refinement.

    init="random" reproduces the v0.5 behaviour (uniform shuffle) — kept
    for A/B measurement. floorplan: resolved Floorplan — fixed blocks are
    immune to moves, regioned blocks only see in-rect slots, exclusive
    regions reject outsiders. None = v0.6-v0.11 behaviour (QoR-guarded).
    Returns (blk_at, final_hpwl).
    """
    rng = random.Random(seed)
    slots = fab.clbs()
    nb = len(blocks)
    if nb > len(slots):
        raise ValueError(f"fabric too small: {nb} blocks > {len(slots)} CLBs")
    if init == "centroid":
        blk_at = initial_placement(blocks, ext_nets, fab, floorplan=floorplan)
    else:
        pos = slots[:]
        rng.shuffle(pos)
        blk_at = pos[:nb]

    def legal(i, slot):
        return floorplan is None or \
            floorplan.exclusive_violation(i, slot) is None

    def tpos(term):
        kind, ref = term
        return fab.io_pos[ref] if kind == "io" else blk_at[ref]

    def hpwl():
        total = 0
        for terms in ext_nets.values():
            xs, ys = [], []
            for t in terms:
                x, y = tpos(t)
                xs.append(x); ys.append(y)
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
        return total

    cost = hpwl()
    t = t0
    while t > tmin:
        for _ in range(moves_per_temp * max(nb, 1)):
            a = rng.randrange(nb)
            if floorplan is not None and floorplan.fixed_of(a) is not None:
                continue                              # locked block, no moves
            if rng.random() < 0.5 and nb < len(slots):
                b_pos = rng.choice(slots)
                if b_pos in blk_at: continue
                if not legal(a, b_pos): continue
                old = blk_at[a]
                blk_at[a] = b_pos
                new = hpwl()
                d = new - cost
                if d <= 0 or rng.random() < math.exp(-d / t):
                    cost = new
                else:
                    blk_at[a] = old
            else:
                b = rng.randrange(nb)
                if a == b: continue
                if floorplan is not None:
                    if floorplan.fixed_of(b) is not None:
                        continue                      # b is locked, cannot swap
                    if not legal(a, blk_at[b]) or not legal(b, blk_at[a]):
                        continue                      # region / exclusive breach
                blk_at[a], blk_at[b] = blk_at[b], blk_at[a]
                new = hpwl()
                d = new - cost
                if d <= 0 or rng.random() < math.exp(-d / t):
                    cost = new
                else:
                    blk_at[a], blk_at[b] = blk_at[b], blk_at[a]
        t *= alpha
    return blk_at, cost
