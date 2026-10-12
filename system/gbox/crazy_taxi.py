"""Crazy Taxi (GameCube, GCTE51) native model reader: the `polDC*.all` shape archives and their `.shp` models.

Evidence (requests #608/#459/#1369; owned hyperspin ISO `Crazy Taxi (USA).iso`, header GCTE51 disc 0 revision 0
"Crazy Taxi"; full hashes in ISO_SHA256/DOL_SHA256/BANK_SHA256/MOTION_SHA256 below, main.dol measured on
`GCDisc.dol()` = 2190496 bytes; the earlier "c6447c2d..." DOL prefix did not reproduce):

* `ct/polDC0.all` is the common shape bank (1586 shapes: cars, pedestrians, passengers and the four drivers).
  Layout: u32le count, u32le 0x00410020, u32le 0, u32le 0, then `count` records of name[64] + u32le size, 8 bytes
  of padding, then the shape blobs back to back in record order (sizes are multiples of 0x20; the last blob ends
  exactly at EOF).
* The drivers are `MP_YH_plyrA..D_*` (Axel, B.D. Joe, Gena, Gus in select order), one rigid `.shp` per body part
  (atama head, mune chest, koshi hips, kata/ude/te upper arm/forearm/hand, momo/sune/kakato thigh/shin/foot, with
  hand-pose variants `_ok/_ch/_gu` and `sl_` low-detail twins). Pedestrians (`MP_YH_Man_*`) use the same part set.
* A `.shp` is big-endian. Header: f32 1.0, f32 bounding radius, ..., vec3 centre @0x20, vec3 quantisation scale
  @0x2c, per-attribute format words @0x60, GX attribute array offsets @0xc8 (POS @0xcc, NRM @0xd0, CLR0 @0xd4,
  TEX0 @0xdc), material table offset @0x110, first array offset @0x114, display-list base @0x118, texture name
  table @0x11c (64-byte names, e.g. `white.tex`).
  Positions are s16x3 and normals s16x3 (1.14); colours RGBA8; UVs s16x2. Each material record (0x24 bytes) holds
  a display-list offset and size. Display lists are GX: 0x90|vat = triangles, 0x98|vat = strip, 0xa0|vat = fan,
  u16 vertex count, then one u16 index per present attribute, in POS, NRM, CLR0, TEX0 order.
  `ct/cube0.shp` (a loose 8-vertex cube) is the oracle: 36 triangle corners, positions +-1.

main.dol (GCTE51) evidence for the writer stage: `polDC0.all` is opened at 0x800866e0 and `motDC.bin` at
0x80059cfc/0x8005a12c/0x8005a94c/0x8005b810/0x8005b988 (lis/addi xrefs). main.dol also carries game-side shape
enum tables of 0x44-byte records (u32 enum id, name[64] without `.shp`); `MP_YH_plyrA_koshi` is id 0x48a at
0x80190a9c while its bank position is 1136 (the drivers sit at a constant +26; cars and props use other shifts), so
ids are not bank positions. A writer must therefore keep every bank name and record order in place and only
replace blobs. The `.shp` name list at 0x80135158 is still unread (candidate part hierarchy / pose tables).
`motDC.bin` is a bank of self-contained motions (`motion_bank`): u32 frame count + 17 u32 group word offsets,
each group three X/Y/Z channel tracks of Hermite keys; it is the people animation bank.

This module is read-only; it never writes the disc. The writer (re-encoding a donor into the driver parts) is the
next stage of #608 and is intentionally not routed in `characters` yet.

Skeleton/animation stage (#1369): the driver parts are bone-local, not pre-placed. Every `MP_YH_plyr*` part's
decoded vertices (header centre included) surround its own joint origin (Axel: hips x -0.2..2.31, chest
x 0.15..4.99, head y -0.87..2.62, thigh x -0.88..4.23; the head and feet boxes overlap), so concatenating the 15
parts is a pile of parts, not a driver. The animation bank `ct/motDC.bin` (`motion_bank`/`parse_motion`) is a sequence of
self-contained motions (278 parse back to back from offset 0 to 0x174738; the remaining 1328488 bytes are a
different float table, unread): u32 frame count, then 17 u32 word offsets (relative to the motion; the first is always 18)
of 17 channel groups. A group is three channel tracks (X, Y, Z), each u32 count + count x (u32 frame, value word,
tangent-in word, tangent-out word). The header offsets delimit the tracks: frames are not always rising (the
61-frame motion at 0x8a18 keys frames 0, 1, 30, 40, 50, 60, 75, 60, and the motion at 0x20080 has group-9 frame
words above 0xFFFF, kept raw: their meaning is unverified). Groups 1, 6, 9, 13
and 16 hold f32 positions; the other twelve hold s32 angles (0x10000 = 360 degrees; motion 0 group 2 starts at
exactly -0xC000 = -270). In motion 0 (91 frames) group 1 starts at (-4.4, 9.8, 2.62), groups 6/9 sit about 3 units
either side of it at the same height and groups 13/16 about 8-9 units below it. That is consistent with a root
position plus hand and foot effector targets (an IK rig, unverified), so the bank carries no bone lengths.
main.dol lists the driver parts in rig order at 0x80135158 (`DRIVER_BONES`, `dol_shape_names`). Until the IK
segment lengths and parent offsets are bound in main.dol's motDC.bin loader, the drivers stay out of
`characters op=collect`; only fully posed cabs (`WHEEL_POSE`) opt into background collection (`collect`: True in
`roster()`).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

GAME_IDS = {"bc02bb68790ce2e7"}
DISC_ID = "GCTE51"
BANK = "ct/polDC0.all"
MOTION = "ct/motDC.bin"
ISO_SHA256 = "dd341c50bc60d81beef6a88da7fb1611a0e4ad230d2adb125063c2993915d42c"   # whole owned ISO (sha256sum)
DOL_SHA256 = "ca0e38f6b7d481fc512e4d67c8704261ce95a01ccc6a8680d963f6b8edd494d7"   # GCDisc.dol(), 2190496 bytes
BANK_SHA256 = "a5171e43e8458a2eca20ec482450730f44c77414132aa6fb0018f4fecc492648"  # ct/polDC0.all
MOTION_SHA256 = "e91f413f950bfe901e5076918602079fb4a63b08ec9e74cd6cea9c86c36e68a0"  # ct/motDC.bin
DRIVERS = {"A": "axel", "B": "bd_joe", "C": "gena", "D": "gus"}
# Body parts of one driver, parent first (rigid parts, one per bone).
PARTS = ("koshi", "mune", "atama", "kata_l", "ude_l", "te_l", "kata_r", "ude_r", "te_r",
         "momo_l", "sune_l", "kakato_l", "momo_r", "sune_r", "kakato_r")
ROLE = {"koshi": "hips", "mune": "chest", "atama": "head",
        "kata_l": "upperarm_l", "ude_l": "forearm_l", "te_l": "hand_l",
        "kata_r": "upperarm_r", "ude_r": "forearm_r", "te_r": "hand_r",
        "momo_l": "thigh_l", "sune_l": "shin_l", "kakato_l": "foot_l",
        "momo_r": "thigh_r", "sune_r": "shin_r", "kakato_r": "foot_r"}

ATTR_OFFS = (("pos", 0xCC), ("nrm", 0xD0), ("clr", 0xD4), ("tex", 0xDC))


def read_bank(data: bytes) -> list[tuple[str, int, int]]:
    """polDC*.all -> [(name, offset, size)]. Raises ValueError when the layout does not add up."""
    if len(data) < 16:
        raise ValueError("bank too small")
    count = struct.unpack_from("<I", data, 0)[0]
    table_end = 0x10 + count * 0x44
    if count <= 0 or table_end > len(data):
        raise ValueError(f"bad shape count {count}")
    out, off = [], table_end + 8
    for i in range(count):
        p = 0x10 + i * 0x44
        name = data[p:p + 64].split(b"\0")[0].decode("latin-1")
        size = struct.unpack_from("<I", data, p + 64)[0]
        out.append((name, off, size))
        off += size
    if off != len(data):
        raise ValueError(f"bank sizes end at {off:#x}, file is {len(data):#x}")
    return out


def write_bank(entries: list[tuple[str, bytes]], word1: int = 0x00410020) -> bytes:
    """Inverse of read_bank (used for the no-op round trip and later for the driver writer)."""
    hdr = bytearray(struct.pack("<4I", len(entries), word1, 0, 0))
    for name, blob in entries:
        nm = name.encode("latin-1")
        if len(nm) >= 64:
            raise ValueError(f"name too long: {name}")
        hdr += nm.ljust(64, b"\0") + struct.pack("<I", len(blob))
    hdr += b"\0" * 8
    return bytes(hdr) + b"".join(b for _, b in entries)


@dataclass
class Shape:
    name: str
    radius: float
    centre: tuple
    scale: tuple
    pos: list = field(default_factory=list)       # raw s16 triples
    nrm: list = field(default_factory=list)
    uv: list = field(default_factory=list)
    textures: list = field(default_factory=list)
    tris: list = field(default_factory=list)      # [(corner, corner, corner)], corner = {attr: index}
    lists: list = field(default_factory=list)     # [(dl_offset, dl_size)]

    def frac(self) -> int:
        """POS fixed-point shift. The VAT field that sets it is not located yet, so derive it from the bounding
        radius: cube0.shp is 6 (18918 * 0.0033829 / 64 = 1.0); 1411 of the 1584 decodable polDC0 shapes,
        all driver parts included, are 8."""
        used = {c["pos"] for t in self.tris for c in t} or set(range(len(self.pos)))
        if not used or self.radius <= 0:
            return 8
        far = max(math.sqrt(sum((self.pos[i][a] * self.scale[a]) ** 2 for a in range(3))) for i in used)
        return max(0, min(15, round(math.log2(far / self.radius)))) if far > 0 else 8

    def positions(self, frac: int | None = None, pivot: bool = True) -> list[tuple[float, float, float]]:
        """Decoded positions: centre + s16 * scale / 2**frac. The header centre is the part's
        placement: the taxi sign's vertices are local (+-0.72) and sit on the roof only after adding
        its centre (0, 13.625, -3.45); the body's delta plus its centre lands on the ground plane."""
        k = 1.0 / (1 << (self.frac() if frac is None else frac))
        cx, cy, cz = self.centre if pivot else (0.0, 0.0, 0.0)
        return [(x * self.scale[0] * k + cx, y * self.scale[1] * k + cy, z * self.scale[2] * k + cz)
                for x, y, z in self.pos]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def decode_dl(dl: bytes, attrs: list[str]) -> list[tuple]:
    """GX display list (u16 index per attribute) -> triangles of corner dicts."""
    tris, p, stride = [], 0, 2 * len(attrs)
    while p + 3 <= len(dl):
        cmd = dl[p]
        if cmd == 0:                   # NOP / padding
            p += 1
            continue
        prim = cmd & 0xF8
        if prim not in (0x90, 0x98, 0xA0):
            raise ValueError(f"unknown GX command {cmd:#x} at {p:#x}")
        n = struct.unpack_from(">H", dl, p + 1)[0]
        p += 3
        if p + n * stride > len(dl):
            raise ValueError("display list overruns its block")
        vs = []
        for i in range(n):
            idx = struct.unpack_from(f">{len(attrs)}H", dl, p + i * stride)
            vs.append(dict(zip(attrs, idx)))
        p += n * stride
        if prim == 0x90:
            tris += [tuple(vs[i:i + 3]) for i in range(0, n - 2, 3)]
        elif prim == 0x98:
            for i in range(n - 2):
                a, b, c = vs[i], vs[i + 1], vs[i + 2]
                tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
        else:
            tris += [(vs[0], vs[i], vs[i + 1]) for i in range(1, n - 1)]
    return tris


def _material_lists(b: bytes, mat_off: int, dl_base: int, end: int) -> list[tuple[int, int]]:
    """Find the (offset, size) display-list pointers in the material block: u32 pairs pointing at a GX
    primitive inside [dl_base, end)."""
    out = []
    for o in range(mat_off, dl_base - 7, 4):
        off, size = _u32(b, o), _u32(b, o + 4)
        if dl_base <= off < end and 0 < size <= end - off and size % 0x20 == 0 and b[off] & 0xF8 in (0x90, 0x98, 0xA0):
            if not out or out[-1][0] + out[-1][1] <= off:
                out.append((off, size))
    return out


def read_shape(b: bytes, name: str = "") -> Shape:
    if len(b) < 0x120 or struct.unpack_from(">f", b, 0)[0] != 1.0:
        raise ValueError(f"{name}: not a Crazy Taxi .shp")
    radius = struct.unpack_from(">f", b, 4)[0]
    centre = struct.unpack_from(">3f", b, 0x20)
    scale = struct.unpack_from(">3f", b, 0x2C)
    mat_off, dl_base, tex_off = _u32(b, 0x110), _u32(b, 0x118), _u32(b, 0x11C)
    present = [(a, _u32(b, o)) for a, o in ATTR_OFFS if _u32(b, o)]
    bounds = sorted({o for _, o in present} | {mat_off, dl_base, tex_off, len(b)})
    nxt = {o: min(x for x in bounds if x > o) for _, o in present}
    s = Shape(name, radius, centre, scale)
    for a, o in present:
        n = nxt[o] - o
        if a == "pos":
            s.pos = [struct.unpack_from(">3h", b, o + 6 * i) for i in range(n // 6)]
        elif a == "nrm":
            s.nrm = [tuple(v / 16384 for v in struct.unpack_from(">3h", b, o + 6 * i)) for i in range(n // 6)]
        elif a == "tex":
            s.uv = [tuple(v / 256 for v in struct.unpack_from(">2h", b, o + 4 * i)) for i in range(n // 4)]
    if tex_off and tex_off < len(b):
        for o in range(tex_off, len(b) - 63, 64):
            nm = b[o:o + 64].split(b"\0")[0]
            if nm.endswith(b".tex"):
                s.textures.append(nm.decode("latin-1"))
    attrs = [a for a, _ in present]
    s.lists = _material_lists(b, mat_off, dl_base, tex_off or len(b))
    for off, size in s.lists:
        s.tris += decode_dl(b[off:off + size], attrs)
    np_ = len(s.pos)
    for t in s.tris:
        for c in t:
            if c["pos"] >= np_:
                raise ValueError(f"{name}: position index {c['pos']} >= {np_}")
    return s


def to_obj(s: Shape, frac: int | None = None) -> str:
    lines = [f"o {s.name or 'shape'}"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in s.positions(frac)]
    lines += [f"vt {u:.6f} {1 - v:.6f}" for u, v in s.uv] or []
    for t in s.tris:
        if s.uv and all("tex" in c for c in t):
            lines.append("f " + " ".join(f"{c['pos'] + 1}/{c['tex'] + 1}" for c in t))
        else:
            lines.append("f " + " ".join(str(c["pos"] + 1) for c in t))
    return "\n".join(lines) + "\n"


def driver_parts(entries, letter: str, low: bool = False) -> dict[str, tuple[int, int]]:
    """Map the PARTS of driver A-D to (offset, size) inside the bank."""
    pre = f"MP_YH_plyr{letter}_" + ("sl_" if low else "")
    by = {n: (o, s) for n, o, s in entries}
    return {p: by[f"{pre}{p}.shp"] for p in PARTS if f"{pre}{p}.shp" in by}


# --- vehicles: the playable cabs (request #459 extracts the yellow taxi, Axel's CZ_CADI) ---

CARS = {
    "CZ_CADI": {"slug": "crazy_taxi_yellow", "name": "Yellow taxi (Crazy Taxi)",
                "aliases": ["yellow taxi", "crazy taxi", "Axel cab", "Cadillac cab"], "driver": "Axel"},
    "CZ_MUST": {"slug": "crazy_taxi_mustang", "name": "Mustang cab (Crazy Taxi)",
                "aliases": ["red cab", "mustang", "Gus cab"], "driver": "Gus"},
    "CZ_MERCURY": {"slug": "crazy_taxi_mercury", "name": "Mercury cab (Crazy Taxi)",
                   "aliases": ["mercury cougar", "B.D. Joe cab"], "driver": "B.D. Joe"},
    "CZ_IMPALA": {"slug": "crazy_taxi_impala", "name": "Impala cab (Crazy Taxi)",
                  "aliases": ["green cab", "impala", "Gena cab"], "driver": "Gena"},
    "CZ_CHARI": {"slug": "crazy_taxi_chariot", "name": "Pedal chariot (Crazy Taxi)",
                 "aliases": ["chariot", "rickshaw"], "driver": "Gus (Crazy Box)"},
}
# Parts of one cab, in car space except the wheels (hub-local) and DX/`sl` twins which the game animates.
CAR_PARTS = ("shp", "flw", "frw", "rlw", "rrw", "taxiON", "taxiOFF", "stop_ON", "stop_OFF", "mabi")
# A cab is drawn from: body, roof TAXI sign, rear stop lamps and the four wheels. Every part's header
# centre is its placement and its vertices are stored relative to it (positions() adds it back). The
# wheel parts additionally need the game's hub offset: y = the wheel radius (ground plane at y=0, so
# hub_y = radius) and z = the wheelbase half-lengths from main.dol's float tables (front z -16.5, rear
# +16.25, matching the body's wheel wells between its side-rail slabs at z 0/12/30 and the front
# bumper at -23.15); x comes from each wheel header's centre (track). Live 3D acceptance is pending:
# the agent launch path cannot start Examine 3D, so these are cross-checked against the disc geometry
# and the executable float table, not a RenderDoc capture (request #459).
WHEEL_POSE = {  # extra translation per wheel, added to its header centre (which already carries track x)
    "CZ_CADI": {"flw": (0.0, 2.960, -16.50), "frw": (0.0, 2.960, -16.50),
                "rlw": (0.0, 2.960, 16.25), "rrw": (0.0, 2.960, 16.25)},
}


def car_part_name(car: str, p: str) -> str:
    if p == "shp":
        return f"{car}.shp"
    if p in ("stop_ON", "stop_OFF"):
        return f"{car}{p}.shp"
    return f"{car}_{p}.shp"


def car_parts(entries, car: str) -> dict[str, tuple[int, int]]:
    """Map a cab's part names to (offset, size) inside the bank."""
    by = {n: (o, s) for n, o, s in entries}
    out = {}
    for p in CAR_PARTS:
        name = car_part_name(car, p)
        if name in by:
            out[p] = by[name]
    return out


def car_glb(bank: bytes, car: str) -> tuple[bytes, dict]:
    """Build the GLB binary container for car_gltf's scene (JSON + binary buffer)."""
    import json as _json
    entries = read_bank(bank)
    parts = car_parts(entries, car)
    if "shp" not in parts:
        raise ValueError(f"{car}: no body part in the bank")
    static = [p for p in ("shp", "taxiON", "stop_OFF") if p in parts]
    pose = WHEEL_POSE.get(car, {})
    wheels = [p for p in ("flw", "frw", "rlw", "rrw") if p in parts and p in pose]
    pieces = []
    for p in static:
        o, size = parts[p]
        pieces.append((p, read_shape(bank[o:o + size], f"{car}_{p}"), None))
    for p in wheels:
        o, size = parts[p]
        pieces.append((p, read_shape(bank[o:o + size], f"{car}_{p}"), pose[p]))
    buf = bytearray()
    nodes, meshes, materials, accs, views = [], [], [], [], []
    for name, s, trans in pieces:
        pts = s.positions()
        nrms = ((s.nrm or []) + [(0.0, 0.0, 1.0)] * len(pts))[:len(pts)]
        uvs = ((s.uv or []) + [(0.0, 0.0)] * len(pts))[:len(pts)]
        assert len(nrms) == len(pts) and len(uvs) == len(pts), name
        vbase = len(buf)
        for (x, y, z), (nx, ny, nz), (u, v) in zip(pts, nrms, uvs):
            buf += struct.pack("<8f", x, y, z, nx, ny, nz, u, v)
        ibase = len(buf)
        idx = [c["pos"] for t in s.tris for c in t]
        if max(idx, default=0) >= len(pts):
            raise ValueError(f"{name}: triangle index out of range")
        buf += struct.pack(f"<{len(idx)}H", *idx)
        while len(buf) % 4:
            buf.append(0)
        v_len = ibase - vbase
        i_len = len(buf) - ibase
        nv = len(accs)
        views.append({"buffer": 0, "byteOffset": vbase, "byteLength": v_len, "byteStride": 32})
        views.append({"buffer": 0, "byteOffset": ibase, "byteLength": i_len})
        accs.append({"bufferView": len(views) - 2, "componentType": 5126, "count": len(pts), "type": "VEC3", "min": [min(p[a] for p in pts) for a in range(3)], "max": [max(p[a] for p in pts) for a in range(3)]})
        accs.append({"bufferView": len(views) - 2, "componentType": 5126, "count": len(pts), "type": "VEC3"})
        accs.append({"bufferView": len(views) - 2, "componentType": 5126, "count": len(pts), "type": "VEC2"})
        accs.append({"bufferView": len(views) - 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"})
        meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": nv, "NORMAL": nv + 1, "TEXCOORD_0": nv + 2}, "indices": nv + 3, "material": len(materials)}]})
        materials.append({"name": s.textures[0] if s.textures else "white.tex", "pbrMetallicRoughness": {"metallicFactor": 0.0}})
        nodes.append({"mesh": len(meshes) - 1, "name": name, "translation": list(trans)} if trans else {"mesh": len(meshes) - 1, "name": name})
    gl = {"asset": {"version": "2.0", "generator": "gbox.crazy_taxi"},
          "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes,
          "meshes": meshes, "materials": materials,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(buf)}]}
    js = _json.dumps(gl, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    while len(buf) % 4:
        buf.append(0)
    total = 12 + 8 + len(js) + 8 + len(buf)
    glb = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    stats = {"car": car, "parts": {n: {"verts": len(s.pos), "tris": len(s.tris)} for n, s, _ in pieces},
             "tris": sum(len(s.tris) for _, s, _ in pieces), "verts": sum(len(s.pos) for _, s, _ in pieces),
             "posed_wheels": [n for n, _, t in pieces if t]}
    return glb, stats


def car_obj(bank: bytes, car: str, frac: int | None = None) -> tuple[str, dict]:
    """Assemble a cab into one OBJ (wheel parts translated to their hub poses)."""
    entries = read_bank(bank)
    parts = car_parts(entries, car)
    if "shp" not in parts:
        raise ValueError(f"{car}: no body part in the bank")
    static = [p for p in ("shp", "taxiON", "stop_OFF") if p in parts]
    pose = WHEEL_POSE.get(car, {})
    wheels = [p for p in ("flw", "frw", "rlw", "rrw") if p in parts and p in pose]
    lines = [f"o {car}"]
    vbase, vtbase, stats = 1, 1, {}
    for p in static + wheels:
        o, size = parts[p]
        s = read_shape(bank[o:o + size], f"{car}_{p}")
        trans = pose.get(p)
        k = s.frac() if frac is None else frac
        for x, y, z in s.positions(k):
            if trans:
                x, y, z = x + trans[0], y + trans[1], z + trans[2]
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        if s.uv:
            lines += [f"vt {u:.6f} {1 - v:.6f}" for u, v in s.uv]
        for t in s.tris:
            if s.uv and all("tex" in c for c in t):
                lines.append("f " + " ".join(f"{c['pos'] + vbase}/{c['tex'] + vtbase}" for c in t))
            else:
                lines.append("f " + " ".join(str(c["pos"] + vbase) for c in t))
        stats[p] = {"verts": len(s.pos), "tris": len(s.tris)}
        vbase += len(s.pos)
        vtbase += len(s.uv)
    return "\n".join(lines) + "\n", stats


def roster() -> list[dict]:
    """The collection roster for the Crazy Taxi native extractor. The cabs are vehicles; a cab joins background
    collection (`collect`: True) only when all its parts are posed (`WHEEL_POSE`). The drivers are bone-local parts
    awaiting the motDC.bin skeleton (module doc), so they are not listed as characters yet."""
    return [{"key": car, "slug": v["slug"], "name": v["name"], "aliases": v["aliases"],
             "kind": "vehicle", "driver": v["driver"], "collect": car in WHEEL_POSE} for car, v in CARS.items()]


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """characters op=extract: a Crazy Taxi cab straight from the disc -> one posed GLB + OBJ."""
    from . import characters as C
    from .gcdisc import GCDisc
    iso = C._gc_iso(ctx, game)
    disc = GCDisc(iso)
    if disc.game_id != DISC_ID:
        raise ValueError(f"expected {DISC_ID}, got {disc.game_id}")
    bank = disc.read(BANK)
    car = e["key"]
    glb, stats = car_glb(bank, car)
    obj, _ = car_obj(bank, car)
    dst = Path(work)
    dst.mkdir(parents=True, exist_ok=True)
    glb_path = dst / f"{car}.glb"
    obj_path = dst / f"{car}.obj"
    glb_path.write_bytes(glb)
    obj_path.write_text(obj)
    posed = ", ".join(stats["posed_wheels"]) or "no wheels"
    return {"files": [glb_path, obj_path], "tool": "gbox.crazy_taxi",
            "roles": None,
            "source_files": [f"{BANK}: {car} body + {len(stats['parts']) - 1} parts "
                             f"({', '.join(sorted(stats['parts']))})"],
            "notes": f"Crazy Taxi {car}: {stats['verts']} verts, {stats['tris']} triangles across "
                     f"{len(stats['parts'])} rigid parts; posed wheels: {posed}. Static parts carry their "
                     "car-space vertices on the disc; the wheel hubs come from the live scene capture."}


def inventory(bank: bytes) -> dict:
    """Drivers, their parts, triangle counts and texture names (the reader stage of #608)."""
    entries = read_bank(bank)
    out = {"shapes": len(entries), "drivers": {}}
    for letter, slug in DRIVERS.items():
        parts = {}
        for p, (o, size) in driver_parts(entries, letter).items():
            s = read_shape(bank[o:o + size], p)
            parts[p] = {"offset": o, "size": size, "verts": len(s.pos), "tris": len(s.tris),
                        "textures": s.textures, "role": ROLE[p]}
        out["drivers"][slug] = {"letter": letter, "parts": parts,
                                "tris": sum(v["tris"] for v in parts.values())}
    return out



def driver_part_extents(bank: bytes, letter: str) -> dict[str, tuple[tuple, tuple]]:
    """Decoded (centre-included) bounds of driver A-D's parts. Each surrounds its own joint origin: the parts are
    bone-local and need the motion bank's skeleton before they can be assembled (#1369)."""
    entries = read_bank(bank)
    out = {}
    for p, (o, size) in driver_parts(entries, letter).items():
        s = read_shape(bank[o:o + size], p)
        pts = s.positions()
        used = sorted({c["pos"] for t in s.tris for c in t}) or range(len(pts))
        sel = [pts[i] for i in used]
        out[p] = (tuple(min(v[a] for v in sel) for a in range(3)), tuple(max(v[a] for v in sel) for a in range(3)))
    return out


BONE_LIST_VA = 0x80135158  # main.dol (GCTE51): driver part names in rig order, then MP_YH_Man_*, passengers...
DRIVER_BONES = ("koshi", "momo_r", "sune_r", "kakato_r", "momo_l", "sune_l", "kakato_l", "muneB", "mune",
                "kata_rB", "kata_r", "ude_r", "te_r_gu", "te_r_ch", "te_r_ok", "te_r", "kata_lB", "kata_l", "ude_l",
                "te_l_gu", "te_l_ch", "te_l_ok", "te_l", "atamaD", "atamaC", "atamaB", "atama")
MOTION_GROUPS = 17
POSITION_GROUPS = (1, 6, 9, 13, 16)  # 1-based groups holding f32 positions; the rest hold s32 angles
BAMS = 0x10000  # angle units per full turn


def dol_va_to_offset(dol: bytes, va: int) -> int | None:
    """File offset of virtual address `va` in a GameCube DOL (7 text + 11 data sections), or None."""
    offs = struct.unpack_from(">18I", dol, 0)
    addrs = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    for o, a, n in zip(offs, addrs, sizes):
        if n and a <= va < a + n:
            return o + va - a
    return None


def dol_shape_names(dol: bytes, va: int = BONE_LIST_VA, limit: int = 512) -> list[str]:
    """The consecutive NUL-terminated `.shp` names main.dol stores from `va` (suffix dropped), stopping at the first
    string that is not a `.shp` name. On GCTE51 the list at 0x80135158 opens with driver A's 27 parts in rig order."""
    o = dol_va_to_offset(dol, va)
    out: list[str] = []
    while o is not None and o < len(dol) and len(out) < limit:
        e = dol.find(b"\0", o)
        if e < 0 or not dol[o:e].endswith(b".shp"):
            break
        out.append(dol[o:e - 4].decode("latin1"))
        o = e + 1
        while o < len(dol) and dol[o] == 0:
            o += 1
    return out


def driver_bones_from_dol(dol: bytes, letter: str = "A") -> tuple[str, ...]:
    """Driver `letter`'s part names (without the `MP_YH_plyrX_` prefix) in main.dol's rig order."""
    pre = f"MP_YH_plyr{letter}_"
    names = dol_shape_names(dol)
    out = []
    for n in names:
        if not n.startswith(pre):
            if out:
                break
            continue
        out.append(n[len(pre):])
    return tuple(out)


@dataclass
class Motion:
    offset: int                 # byte offset of the motion in motDC.bin
    frames: int                 # header frame count
    groups: list = field(default_factory=list)  # 17 x 3 channels x [(frame_word, value, tangent_in_word, tangent_out_word)]
    size: int = 0               # bytes, header included

    def at_frame0(self, group: int) -> tuple:
        """Group `group` (1-based) X/Y/Z values at its first key (positions in units, angles in degrees)."""
        return tuple(ch[0][1] if ch else 0.0 for ch in self.groups[group - 1])


def _s32(w: int) -> int:
    return w - (1 << 32) if w >> 31 else w


def parse_motion(m: bytes, base: int = 0) -> Motion | None:
    """One `motDC.bin` motion at byte `base`, or None when the bytes break the layout (see module docstring).
    Position values decode as f32, angle values as s32 BAMS converted to degrees; tangent words stay raw."""
    hw = MOTION_GROUPS + 1
    if base < 0 or base + 4 * hw > len(m):
        return None
    head = struct.unpack_from(f">{hw}I", m, base)
    nf = head[0]
    if head[1] != hw or not 0 < nf < 100000 or any(b <= a for a, b in zip(head[1:], head[2:])):
        return None
    o, groups = base + 4 * hw, []
    for g in range(1, hw):
        if o != base + 4 * head[g]:
            return None
        pos = g in POSITION_GROUPS
        chans = []
        for _ in range(3):
            if o + 4 > len(m):
                return None
            n = struct.unpack_from(">I", m, o)[0]
            if n > 4096 or o + 4 + 16 * n > len(m):
                return None
            keys = [struct.unpack_from(">4I", m, o + 4 + 16 * i) for i in range(n)]
            vals = []
            for fr, w, tin, tout in keys:
                if pos:
                    v = struct.unpack(">f", struct.pack(">I", w))[0]
                    if not math.isfinite(v) or abs(v) > 1e5:
                        return None
                else:
                    if not -(1 << 20) < _s32(w) < 1 << 20:
                        return None
                    v = _s32(w) * 360.0 / BAMS
                vals.append((fr, v, tin, tout))
            chans.append(vals)
            o += 4 + 16 * n
        groups.append(chans)
    return Motion(base, nf, groups, o - base)


def motion_bank(m: bytes, limit: int = 100000) -> dict:
    """Walk `motDC.bin` motion by motion from offset 0 (each motion ends where the next begins). Returns the motions
    and `end`, the byte offset of the first record that is not a motion in this layout (== len(m) when all parse)."""
    o, motions = 0, []
    while o < len(m) and len(motions) < limit:
        mo = parse_motion(m, o)
        if mo is None:
            break
        motions.append(mo)
        o += mo.size
    return {"motions": motions, "end": o}


def main(argv=None):
    import argparse
    import json
    from .gcdisc import GCDisc
    ap = argparse.ArgumentParser(description="Crazy Taxi GC shape reader")
    ap.add_argument("iso")
    ap.add_argument("--obj", type=Path, help="write the drivers' parts as OBJ files here")
    a = ap.parse_args(argv)
    disc = GCDisc(a.iso)
    if disc.game_id != DISC_ID:
        raise SystemExit(f"expected {DISC_ID}, got {disc.game_id}")
    bank = disc.read(BANK)
    inv = inventory(bank)
    if a.obj:
        entries = read_bank(bank)
        for letter, slug in DRIVERS.items():
            for p, (o, size) in driver_parts(entries, letter).items():
                dst = a.obj / slug / f"{p}.obj"
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(to_obj(read_shape(bank[o:o + size], p)))
    print(json.dumps(inv, indent=1))


if __name__ == "__main__":
    main()
