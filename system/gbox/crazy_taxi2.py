"""Crazy Taxi 2 (Dreamcast; gBox game id 45e9455ca5487e7d) model inventory: the `pol*.bin` model files (request #1482).

Owned image: QuickSwap2 `Crazy Taxi 2.cdi` (DiscJuggler, 787688567 bytes; gbox.gdrom.CDIRom reads it), IP.BIN
MK-51136 V1.000 2001-05-24 "CRAZY TAXI 2", 1ST_READ.BIN sha256 69f7bd24... (FILES_SHA256 below).

Not Ninja and not the GameCube Crazy Taxi `.shp`: there is no NJCM/NJTL chunk anywhere in these files. Every
`POL*.BIN` is a run of little-endian objects in the Sega NAOMI-library layout (the PowerVR TA parameter words are
stored verbatim):

* object: u32 flags (1; 0xFFFFFFFF with second word 3 = an empty slot), u32 flags, f32 centre xyz, f32 bounding
  radius, then meshes, then u32 0 + u32 vertex-entry count (full vertices + references) as the terminator;
* mesh (0x50-byte header): u32 PCW (top bit set), ISP/TSP, TSP, TCW words, f32 centre xyz + radius @0x10, u32 texture
  index @0x20, u32 @0x24, f32 @0x28, base and offset ARGB (8 f32) @0x2c, u32 strip-data size @0x4c;
* strip data: u32 flags + u32 count; flags & 0x08 = a triangle list of `count` triangles, otherwise a strip of
  `count` vertices; an entry is a full vertex (8 f32: position, normal, u, v) or a reference (8 bytes: a word with
  top nibble 5, then a signed byte offset from the end of the reference to an earlier full vertex).

All 35 POL*.BIN of the owned disc walk to their exact end with this layout and every terminator count matches
(`walk`): 103625 triangles, of which 95 have zero area (80 in polDC3) (references that resolved wrongly would scatter far more). 1ST_READ.BIN names the player files in driver-select order (polPP1A..D, polPP2A..D, then the `H` set) and
lists the drivers SLASH, ICEMAN, CINNAMON, HOT-D, AXEL, B.D.JOE, GENA, GUS, so DRIVERS maps them in that order (the
per-file identity is inferred from the order, not checked against a rendered frame).

The drivers are rigid, bone-local parts like the GameCube game's (gbox.crazy_taxi, #1369): polPP2A has 47 object
slots, 21 of them drawn (15 body parts + 3 hand poses per side, as in the GC rig), each centred near its own joint
(e.g. x 0.6..2.2, y -0.25..1.0). No skeleton (slot -> parent + offset) is decoded yet, so there is no assembled or
rigged character to collect and no DEDICATED reader is registered; the next step is the slot table and the motion
data in 1ST_READ.BIN.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

GAME_IDS = {"45e9455ca5487e7d"}
PRODUCT = "MK-51136"
FILES_SHA256 = {
    "1ST_READ.BIN": "69f7bd24cc82752d0b4995290e91b2e0de8eeda7efefadd4bd227ec6ba2b9042",
    "POLPP1A.BIN": "53c493c915903e0d3a625ef6e3eb9244866679ce03019755b98b3d7a7117cfb0",
    "POLPP2A.BIN": "5bef8e591478f5faf0d623b126ba1ab06ca52ea3f9e29d4148e161e57f3cd213",
    "POLPSG0.BIN": "bb79019b3785d387b4e8e3ef30251e3f2bb2c7b3f6ee3f110878fd4d427d8fdb",
    "POLPPL0.BIN": "2ffc1582bc4e8c6f1393555efa3e69950486a64ef25a50b0820668dbda971368",
    "POLDC0.BIN": "0a6f126a4c9197e9eb4a92b9cf73f41d16f125b0f114d3f662734eebd0d3df15",
}
# player model file -> driver (1ST_READ.BIN order); the `H` files are the same drivers with more triangles
DRIVERS = {"PP1A": "Slash", "PP1B": "Iceman", "PP1C": "Cinnamon", "PP1D": "Hot-D",
           "PP2A": "Axel", "PP2B": "B.D. Joe", "PP2C": "Gena", "PP2D": "Gus"}
KINDS = (("POLPP", "driver"), ("POLPC", "cab"), ("POLPSG", "passengers"), ("POLPPL", "pedestrians"),
         ("POLDC", "city"), ("POLPPTST", "test driver"))
EMPTY = 0xFFFFFFFF
MESH_HEADER = 0x50
VERTEX = 32


@dataclass
class Mesh:
    offset: int
    pcw: int
    texture: int
    pos: list = field(default_factory=list)       # full vertices: (x, y, z)
    nrm: list = field(default_factory=list)
    uv: list = field(default_factory=list)
    tris: list = field(default_factory=list)      # vertex indices into pos
    refs: int = 0


@dataclass
class Obj:
    offset: int
    flags: tuple
    centre: tuple
    radius: float
    meshes: list = field(default_factory=list)
    entries: int = 0                              # the terminator's count

    @property
    def empty(self) -> bool:
        return not self.meshes

    def tris(self) -> int:
        return sum(len(m.tris) for m in self.meshes)


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def read_mesh(b: bytes, o: int) -> tuple[Mesh, int]:
    """One mesh at `o` -> (Mesh, end offset). References resolve to the full vertex they point at."""
    if o + MESH_HEADER > len(b):
        raise ValueError(f"mesh header at {o:#x} runs past the end")
    pcw = _u32(b, o)
    size = _u32(b, o + 0x4C)
    end = o + MESH_HEADER + size
    if end > len(b):
        raise ValueError(f"mesh at {o:#x}: {size:#x} bytes of strips run past the end")
    m = Mesh(o, pcw, _u32(b, o + 0x20))
    at: dict[int, int] = {}                       # file offset of a full vertex -> index
    p = o + MESH_HEADER
    while p < end:
        flags, count = struct.unpack_from("<Ii", b, p)
        if count < 0 or count > 0x10000:
            raise ValueError(f"mesh at {o:#x}: bad strip count {count} at {p:#x}")
        p += 8
        n = 3 * count if flags & 0x08 else count
        idx = []
        for _ in range(n):
            if p + 8 > end:
                raise ValueError(f"mesh at {o:#x}: strip at {p:#x} runs past the mesh")
            w = _u32(b, p)
            if w >> 28 == 5:                      # reference: signed byte offset from the entry's end
                tgt = p + 8 + struct.unpack_from("<i", b, p + 4)[0]
                if tgt not in at:
                    raise ValueError(f"mesh at {o:#x}: reference at {p:#x} points at {tgt:#x}, not a vertex")
                idx.append(at[tgt])
                m.refs += 1
                p += 8
            else:
                if p + VERTEX > end:
                    raise ValueError(f"mesh at {o:#x}: vertex at {p:#x} runs past the mesh")
                v = struct.unpack_from("<8f", b, p)
                at[p] = len(m.pos)
                idx.append(len(m.pos))
                m.pos.append(v[0:3])
                m.nrm.append(v[3:6])
                m.uv.append(v[6:8])
                p += VERTEX
        if flags & 0x08:
            m.tris += [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]
        else:
            for i in range(len(idx) - 2):
                a, c, d = idx[i], idx[i + 1], idx[i + 2]
                m.tris.append((a, c, d) if i % 2 == 0 else (c, a, d))
    if p != end:
        raise ValueError(f"mesh at {o:#x}: strips end at {p:#x}, header says {end:#x}")
    return m, end


def walk(b: bytes) -> list[Obj]:
    """Every object of a POL*.BIN, in slot order (empty slots included). Raises ValueError when the layout breaks or
    the file does not end exactly after the last object."""
    out, o = [], 0
    while o < len(b):
        if o + 0x18 > len(b):
            raise ValueError(f"{len(b) - o} trailing bytes at {o:#x}")
        f0, f1 = struct.unpack_from("<II", b, o)
        cx, cy, cz, r = struct.unpack_from("<4f", b, o + 8)
        ob = Obj(o, (f0, f1), (cx, cy, cz), r)
        p = o + 0x18
        while True:
            if p + 8 > len(b):
                raise ValueError(f"object at {o:#x} has no terminator")
            w = _u32(b, p)
            if w == 0:
                ob.entries = _u32(b, p + 4)
                p += 8
                break
            if not w >> 31:
                raise ValueError(f"object at {o:#x}: {w:#x} at {p:#x} is neither a mesh nor the terminator")
            m, p = read_mesh(b, p)
            ob.meshes.append(m)
        if ob.entries != sum(len(m.pos) + m.refs for m in ob.meshes):
            raise ValueError(f"object at {o:#x}: terminator counts {ob.entries} entries, meshes hold "
                             f"{sum(len(m.pos) + m.refs for m in ob.meshes)}")
        if f0 == EMPTY and ob.meshes:
            raise ValueError(f"object at {o:#x} is flagged empty but has meshes")
        out.append(ob)
        o = p
    return out


def to_obj(objs: list[Obj], name: str = "model") -> str:
    """The drawn objects as one OBJ, one `o` group per slot, in each part's own (bone-local) frame."""
    lines, base = [], 1
    for i, ob in enumerate(objs):
        if ob.empty:
            continue
        lines.append(f"o {name}_{i:02d}")
        for m in ob.meshes:
            lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in m.pos]
            lines += [f"f {a + base} {c + base} {d + base}" for a, c, d in m.tris]
            base += len(m.pos)
    return "\n".join(lines) + "\n"


def kind_of(name: str) -> str:
    n = Path(name).name.upper()
    return next((k for pre, k in sorted(KINDS, key=lambda t: -len(t[0])) if n.startswith(pre)), "other")


def summary(name: str, b: bytes) -> dict:
    objs = walk(b)
    stem = Path(name).stem.upper()
    key = stem[3:7] if stem.startswith("POLPP") else ""
    row = {"file": name, "bytes": len(b), "kind": kind_of(name), "slots": len(objs),
           "drawn": sum(not o.empty for o in objs), "meshes": sum(len(o.meshes) for o in objs),
           "triangles": sum(o.tris() for o in objs), "textures": sorted({m.texture for o in objs for m in o.meshes})}
    if key in DRIVERS:
        row |= {"driver": DRIVERS[key], "detail": "high" if stem.endswith("H") else "normal"}
    return row


def inventory(disc) -> dict:
    """A disc (gbox.gdrom.CDIRom / GDRom: `.files`, `.read`) -> every POL*.BIN summarised."""
    rows = [summary(n, disc.read(n)) for n in sorted(disc.files) if Path(n).name.upper().startswith("POL")]
    return {"files": rows, "drivers": {r["driver"]: r for r in rows if r.get("detail") == "normal"},
            "triangles": sum(r["triangles"] for r in rows)}


def main(argv=None):
    import argparse
    import json
    from .gdrom import CDIRom
    ap = argparse.ArgumentParser(description="Crazy Taxi 2 (DC) POL*.BIN inventory")
    ap.add_argument("cdi")
    ap.add_argument("--obj", type=Path, help="write each driver file's parts as an OBJ here")
    a = ap.parse_args(argv)
    disc = CDIRom(a.cdi)
    inv = inventory(disc)
    if a.obj:
        a.obj.mkdir(parents=True, exist_ok=True)
        for r in inv["files"]:
            if r["kind"] == "driver":
                stem = Path(r["file"]).stem
                (a.obj / f"{stem}.obj").write_text(to_obj(walk(disc.read(r["file"])), stem))
    print(json.dumps(inv, indent=1))


if __name__ == "__main__":
    main()
