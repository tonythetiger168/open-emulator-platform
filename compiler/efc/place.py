"""Simulated-annealing placement (VPR-style), cost = total half-perimeter WL."""
import math, random

def _build_nets(mapped, io_pos):
    """nets: net id -> list of terminals; terminal = ('cell', idx) or ('io', net)."""
    nets = {}
    cells = list(mapped.luts) + list(mapped.dffs)
    for idx, c in enumerate(cells):
        nets.setdefault(c.out, []).append(("cell", idx))
        for n in c.ins:
            nets.setdefault(n, []).append(("cell", idx))
    for net, _pos in io_pos.items():
        nets.setdefault(net, []).append(("io", net))
    # drop nets with <2 terminals (dangling/const-free)
    return {k: v for k, v in nets.items() if len(v) >= 2}, cells

def place(mapped, fab, seed=1, moves_per_temp=40, t0=5.0, tmin=0.05, alpha=0.92):
    rng = random.Random(seed)
    nets, cells = _build_nets(mapped, fab.io_pos)
    slots = fab.clbs()
    if len(cells) > len(slots):
        raise ValueError(f"fabric too small: {len(cells)} cells > {len(slots)} CLBs")
    pos = slots[:]
    rng.shuffle(pos)
    cell_at = pos[:len(cells)]           # idx -> (x,y)

    def hpwl():
        total = 0
        for terms in nets.values():
            xs, ys = [], []
            for kind, ref in terms:
                x, y = fab.io_pos[ref] if kind == "io" else cell_at[ref]
                xs.append(x); ys.append(y)
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
        return total

    cost = hpwl()
    t = t0
    while t > tmin:
        for _ in range(moves_per_temp * len(cells)):
            a = rng.randrange(len(cells))
            if rng.random() < 0.5 and len(cells) < len(slots):
                # move to a random empty slot
                b_pos = rng.choice(slots)
                if b_pos in cell_at: continue
                old = cell_at[a]
                cell_at[a] = b_pos
                new = hpwl()
                d = new - cost
                if d <= 0 or rng.random() < math.exp(-d / t):
                    cost = new
                else:
                    cell_at[a] = old
            else:
                b = rng.randrange(len(cells))
                if a == b: continue
                cell_at[a], cell_at[b] = cell_at[b], cell_at[a]
                new = hpwl()
                d = new - cost
                if d <= 0 or rng.random() < math.exp(-d / t):
                    cost = new
                else:
                    cell_at[a], cell_at[b] = cell_at[b], cell_at[a]
        t *= alpha
    return cell_at, cost, nets, cells
