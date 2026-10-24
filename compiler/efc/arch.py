"""Data-driven architecture description — the VPR architecture-XML analogue.

One JSON spec per target device decouples the P&R algorithms from the device:
  - envelope:  real device resource counts (utilization reporting)
  - clb:       logic block structure (LUTs/FFs per CLB, LUT K, block timing)
  - routing:   wire segment types (length / frequency / R / C for Elmore)
               + switch block topology (subset / wilton / universal, Fs)
  - io:        perimeter pad placement policy

fabric.py builds the logical grid from an ArchSpec; later timing-driven
passes (improvement plan Phase A items 2-4) read delays from the same spec.
Default spec: arch/vp1902.json shipped in the repo.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ARCH = "vp1902"
_ARCH_DIR = Path(__file__).resolve().parent.parent / "arch"


@dataclass
class Segment:
    """A wire segment type: spans `length` tiles, covers `freq` of channels."""
    name: str
    length: int
    freq: float          # fraction of channel tracks using this segment type
    r_ohm: float         # per-segment resistance (logical-model estimate)
    c_pf: float          # per-segment capacitance (logical-model estimate)

    def elmore_ns(self) -> float:
        """One-segment Elmore delay estimate (ns): R*(C/2 + C) = 1.5*R*C."""
        return 1.5 * self.r_ohm * self.c_pf * 1e-3  # ohm * pF -> ns


@dataclass
class SwitchBlock:
    type: str = "wilton"  # subset | wilton | universal
    fs: int = 3           # switch-block flexibility


@dataclass
class ClbSpec:
    luts: int = 8         # LUTs per CLB (VP1902: 8 x LUT6)
    ffs: int = 16         # FFs per CLB
    lut_k: int = 6        # LUT input count
    t_lut_ns: float = 0.05    # LUT delay estimate
    t_ff_clkq_ns: float = 0.10
    t_setup_ns: float = 0.02


@dataclass
class IoSpec:
    inputs: list = field(default_factory=lambda: ["west", "north"])
    outputs: list = field(default_factory=lambda: ["east", "south"])


@dataclass
class ArchSpec:
    name: str
    part: str
    envelope: dict        # real device resource counts
    clb: ClbSpec
    segments: list        # list[Segment], sorted by length
    switch_block: SwitchBlock
    io: IoSpec

    @property
    def clb_count(self) -> int:
        return self.envelope["LUT6"] // self.clb.luts

    def segment_for(self, hop_len: int) -> Segment:
        """Shortest segment type that covers a hop of `hop_len` tiles."""
        for s in self.segments:
            if s.length >= hop_len:
                return s
        return self.segments[-1]

    @staticmethod
    def from_dict(d: dict) -> "ArchSpec":
        sb = d["routing"]["switch_block"]
        segs = sorted(
            (Segment(s["name"], s["length"], s["freq"], s["r_ohm"], s["c_pf"])
             for s in d["routing"]["segments"]),
            key=lambda s: s.length)
        if not segs:
            raise ValueError("arch spec needs >= 1 routing segment")
        io = d.get("io", {})
        return ArchSpec(
            name=d["name"], part=d["part"], envelope=d["envelope"],
            clb=ClbSpec(**d["clb"]),
            segments=segs,
            switch_block=SwitchBlock(sb["type"], sb["fs"]),
            io=IoSpec(io.get("inputs", ["west", "north"]),
                      io.get("outputs", ["east", "south"])),
        )


def arch_path(name_or_path) -> Path:
    """Resolve an arch name ('vp1902') or an explicit JSON path."""
    p = Path(str(name_or_path))
    if p.suffix == ".json" or p.is_absolute() or "/" in str(name_or_path):
        if not p.is_file():
            raise FileNotFoundError(f"arch spec not found: {p}")
        return p
    p = _ARCH_DIR / f"{name_or_path}.json"
    if not p.is_file():
        raise FileNotFoundError(f"unknown arch {name_or_path!r} (looked in {_ARCH_DIR})")
    return p


def load_arch(name_or_path=DEFAULT_ARCH) -> ArchSpec:
    p = arch_path(name_or_path)
    return ArchSpec.from_dict(json.loads(p.read_text(encoding="utf-8")))
