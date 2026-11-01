"""Shell+patch partition (improvement-plan Phase C item 12, v0.14).

RapidWright's answer to fast compile iterations is pre-implemented blocks /
stamped modules: keep a fixed *shell* (static logic, IO, host interface)
implemented once, and re-implement only the *patch* region that actually
changes between emulator bring-up runs. This module produces the partition
efc can hand to that flow:

  partition_shell_patch() classifies every packed block as shell or patch by
  its placement (inside/outside the patch rect), then audits the external
  nets: any net touching both sides is a BOUNDARY NET — the shell must
  provide the connection (partition pins / RP interface), exactly the
  information RapidWright's BlockStitcher-style stitching consumes.

efc-side scope (this file):
  - deterministic partition of a placed design (JSON-serialisable dict)
  - boundary-net audit with per-net terminal breakdown
  - consumed via CLI: --shell-patch x0,y0,x1,y1 [--shell-patch-out FILE]

RapidWright-side scope (docs/rapidwright-shell-patch.md):
  - the actual DCP/stitching work needs Java + Vivado and runs OUTSIDE this
  sandbox; the doc maps our partition JSON onto the RapidWright API calls.
  We do not fake that step here — the JSON is the hand-off artifact.
"""
from .floorplan import block_names


def _in_rect(pos, rect):
    x0, y0, x1, y1 = rect
    return x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1


def partition_shell_patch(blocks, blk_at, ext_nets, fab, patch_rect,
                          block_names_of=block_names):
    """Classify blocks and audit boundary nets for a shell+patch flow.

    patch_rect: (x0, y0, x1, y1) inclusive CLB rect = reconfigurable region.
    Returns a JSON-serialisable dict:
      patch_rect        rect echoed back
      patch_blocks      [{block, names, slot}]
      shell_blocks      [{block, names, slot}]
      boundary_nets     [{net, sides, patch_terms, shell_terms, io_terms}]
      stats             {blocks, patch, shell, boundary_nets}
    IO terminals count as shell-side connections (they live on the static
    perimeter) — a net touching patch + io is a boundary net too.
    """
    patch_rect = tuple(patch_rect)
    n = fab.n
    x0, y0, x1, y1 = patch_rect
    if not (0 <= x0 <= x1 < n and 0 <= y0 <= y1 < n):
        raise ValueError(f"patch rect {patch_rect} outside {n}x{n} grid")

    patch, shell = [], []
    for i, (b, slot) in enumerate(zip(blocks, blk_at)):
        entry = {"block": i, "names": block_names_of(b), "slot": list(slot)}
        (patch if _in_rect(slot, patch_rect) else shell).append(entry)

    def term_pos(t):
        kind, ref = t
        return fab.io_pos[ref] if kind == "io" else blk_at[ref]

    boundary = []
    for net, terms in ext_nets.items():
        sides = set()
        p_terms = s_terms = io_terms = 0
        for t in terms:
            if t[0] == "io":
                sides.add("io")
                io_terms += 1
            elif _in_rect(term_pos(t), patch_rect):
                sides.add("patch")
                p_terms += 1
            else:
                sides.add("shell")
                s_terms += 1
        # boundary = net reaches the patch AND something outside it
        # (shell blocks or static IO pads)
        if "patch" in sides and len(sides) > 1:
            boundary.append({"net": net, "sides": sorted(sides),
                             "patch_terms": p_terms,
                             "shell_terms": s_terms,
                             "io_terms": io_terms})

    return {
        "patch_rect": list(patch_rect),
        "patch_blocks": patch,
        "shell_blocks": shell,
        "boundary_nets": boundary,
        "stats": {"blocks": len(blocks), "patch": len(patch),
                  "shell": len(shell), "boundary_nets": len(boundary)},
    }
