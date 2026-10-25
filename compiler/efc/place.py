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

Public API: initial_placement() (the seed, testable on its own) and
place() (seed + refine, drop-in compatible with the v0.5 signature).
"""
import math, random


def _star_connectivity(ext_nets):
    """block -> list of (other_terminal_position_fn, weight) is built instead
    as block -> {net: [terms]}; here we just index nets per block."""
    blk_nets = {}
    for net, terms in ext_nets.items():
        for kind, ref in terms:
            if kind == "blk":
                blk_nets.setdefault(ref, []).append((net, terms))
    return blk_nets


def initial_placement(blocks, ext_nets, fab, iterations=25):
    """Smart-centroid seed -> legal placement. Returns list of (x, y) slots.

    Deterministic: no RNG. IO terminals are fixed anchors; blocks with no
    external connectivity sit at the grid centre.
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

    # legalization: nearest free slot, deterministic scan order
    free = list(slots)
    order = sorted(range(nb), key=lambda b: (round(pos[b][1], 6),
                                             round(pos[b][0], 6), b))
    blk_at = [None] * nb
    for b in order:
        bx, by = pos[b]
        best_i, best_d = 0, None
        for i, (x, y) in enumerate(free):
            d = abs(x - bx) + abs(y - by)
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        blk_at[b] = free.pop(best_i)
    return blk_at


def place(blocks, ext_nets, fab, seed=1, moves_per_temp=40,
          t0=5.0, tmin=0.05, alpha=0.92, init="centroid"):
    """Seed (smart centroid by default) + VPR-style SA HPWL refinement.

    init="random" reproduces the v0.5 behaviour (uniform shuffle) — kept
    for A/B measurement. Returns (blk_at, final_hpwl).
    """
    rng = random.Random(seed)
    slots = fab.clbs()
    nb = len(blocks)
    if nb > len(slots):
        raise ValueError(f"fabric too small: {nb} blocks > {len(slots)} CLBs")
    if init == "centroid":
        blk_at = initial_placement(blocks, ext_nets, fab)
    else:
        pos = slots[:]
        rng.shuffle(pos)
        blk_at = pos[:nb]

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
            if rng.random() < 0.5 and nb < len(slots):
                b_pos = rng.choice(slots)
                if b_pos in blk_at: continue
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
                blk_at[a], blk_at[b] = blk_at[b], blk_at[a]
                new = hpwl()
                d = new - cost
                if d <= 0 or rng.random() < math.exp(-d / t):
                    cost = new
                else:
                    blk_at[a], blk_at[b] = blk_at[b], blk_at[a]
        t *= alpha
    return blk_at, cost
