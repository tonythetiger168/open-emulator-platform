"""Logic-depth estimation: levelize the LUT netlist between registers/IOs."""
from collections import deque, defaultdict

def logic_depth(mapped):
    driver = {c.out: c for c in mapped.luts}
    consumers = defaultdict(list)
    indeg = defaultdict(int)
    for c in mapped.luts:
        for n in c.ins:
            if n in driver:
                consumers[n].append(c)
                indeg[id(c)] += 1
    level = defaultdict(int)          # net -> level; PIs/DFF-outs stay 0
    q = deque([c for c in mapped.luts if indeg[id(c)] == 0])
    maxd = 0
    while q:
        c = q.popleft()
        level[c.out] = max([level[n] for n in c.ins], default=0) + 1
        maxd = max(maxd, level[c.out])
        for c2 in consumers[c.out]:
            indeg[id(c2)] -= 1
            if indeg[id(c2)] == 0:
                q.append(c2)
    return maxd
