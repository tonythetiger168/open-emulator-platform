"""Simulated-annealing placement of packed CLB blocks (VPR-style, HPWL cost)."""
import math, random

def place(blocks, ext_nets, fab, seed=1, moves_per_temp=40,
          t0=5.0, tmin=0.05, alpha=0.92):
    rng = random.Random(seed)
    slots = fab.clbs()
    nb = len(blocks)
    if nb > len(slots):
        raise ValueError(f"fabric too small: {nb} blocks > {len(slots)} CLBs")
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
