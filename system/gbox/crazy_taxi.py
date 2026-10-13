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

This module's reader never writes the disc; the writer below replaces only the bank's driver blobs.

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

# ----------------------------------------------------------------------------------------------- writer (stage 2)
# The donor swap keeps every bank name/record in place and replaces only the plyrA blobs. Each part is re-encoded
# with the same header, material block (except the per-material display-list pointers), texture names and tail;
# only the arrays and display lists are rewritten. All driver parts share white.tex, so UVs are all (0, 0) and the
# driver's material colours carry the look (baked vertex colours are written for the parts that have CLR0).

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


def _material_list_slots(b: bytes, mat_off: int, dl_base: int, end: int) -> list[tuple[int, int, int]]:
    """(slot offset, pointed-to offset, size) for every per-material display-list pointer pair found in
    [mat_off, dl_base)."""
    out = []
    for o in range(mat_off, dl_base - 7, 4):
        off, size = _u32(b, o), _u32(b, o + 4)
        if dl_base <= off < end and 0 < size <= end - off and size % 0x20 == 0 and b[off] & 0xF8 in (0x90, 0x98, 0xA0):
            if not out or out[-1][1] + out[-1][2] <= off:
                out.append((o, off, size))
    return out


def _material_lists(b: bytes, mat_off: int, dl_base: int, end: int) -> list[tuple[int, int]]:
    """Find the (offset, size) display-list pointers in the material block: u32 pairs pointing at a GX
    primitive inside [dl_base, end)."""
    return [(off, size) for _slot, off, size in _material_list_slots(b, mat_off, dl_base, end)]


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


# --------------------------------------------------------------------------------------------------- writer stage 2
import hashlib
import time
from collections import Counter

import numpy as np

ATTR_WORDS = (("pos", 0xCC), ("nrm", 0xD0), ("clr", 0xD4), ("tex", 0xDC))
# Crazy Taxi part -> donor rig role name (the PSO/HUcast convention; earlier slots accept other common names).
CT_ROLE = {"koshi": ["hip", "hips", "pelvis"], "mune": ["chest", "torso"], "atama": ["head"],
           "kata_l": ["l_upper", "upperarm_l", "shoulder_l"], "ude_l": ["l_fore", "forearm_l"],
           "te_l": ["l_hand", "hand_l"], "kata_r": ["r_upper", "upperarm_r", "shoulder_r"],
           "ude_r": ["r_fore", "forearm_r"], "te_r": ["r_hand", "hand_r"],
           "momo_l": ["l_thigh", "thigh_l"], "sune_l": ["l_shin", "shin_l"],
           "kakato_l": ["l_foot", "foot_l"], "momo_r": ["r_thigh", "thigh_r"],
           "sune_r": ["r_shin", "shin_r"], "kakato_r": ["r_foot", "foot_r"]}


def resolve_roles(roles: dict) -> dict:
    """Donor rig roles (whatever names) -> the Crazy Taxi part each one feeds. Raises when a body part is missing."""
    out = {}
    for part, names in CT_ROLE.items():
        r = next((n for n in names if n in roles), None)
        if r is None:
            raise ValueError(f"the donor rig has no role for the {part} part (have: {sorted(roles)})")
        out[part] = r
    return out


def _pack_strips(tris: list[tuple], cap: int, rev: bool = False) -> tuple[list[list[int]], list[tuple]]:
    """Greedy GX strips (winding preserved) with growth capped at `cap` vertices per strip; rev=True iterates the
    seed candidates in reverse order (different packings strand different triangles)."""
    left = set(range(len(tris)))
    edge = {}
    for i, (a, b, c) in enumerate(tris):
        for e, w in (((a, b), c), ((b, c), a), ((c, a), b)):
            edge.setdefault(e, []).append((i, w))
    strips, singles = [], []
    while left:
        seeds = sorted(left, reverse=rev)
        best_v, best_used, best_seed = None, None, None
        for i in seeds:
            t0 = tris[i]
            for rot in range(3):
                v = [t0[rot], t0[(rot + 1) % 3], t0[(rot + 2) % 3]]
                used, k = [], 1
                while len(v) < cap:
                    e = (v[-2], v[-1]) if k % 2 == 0 else (v[-1], v[-2])
                    nxt = next(((j, w) for j, w in edge.get(e, ())
                                if j in left and j != i and j not in used), None)
                    if nxt is None:
                        break
                    used.append(nxt[0])
                    v.append(nxt[1])
                    k += 1
                if best_used is None or len(used) > len(best_used):
                    best_v, best_used, best_seed = v, used, i
        v, used, i = best_v, best_used, best_seed
        left.discard(i)
        for j in used:
            left.discard(j)
        if used:
            strips.append(v)
        else:
            singles.append(tuple(v))
    return strips, singles


def strips_cw(tris: list[tuple]) -> tuple[list[list[int]], list[tuple]]:
    """Triangle strips that keep every triangle's winding (GX strip parity: triangle k of a strip is
    (v[k], v[k+1], v[k+2]) for even k, (v[k+1], v[k], v[k+2]) for odd k). Several strip-length caps and both
    seed orders are tried and the byte-smallest packing wins (the game's own parts use short strips).
    Returns (strips, leftover triangles)."""
    tris = [tuple(map(int, t)) for t in tris]
    best = None
    for cap in (4, 5, 6, 8, 10, 12, 16, 20, 24, 999):
        for rev in (False, True):
            st, si = _pack_strips(tris, cap, rev)
            cost = sum(3 + 6 * len(v) for v in st) + (3 + 18 * len(si) if si else 0)
            if best is None or cost < best[0]:
                best = (cost, st, si)
    return best[1], best[2]


def _encode_dl(tris, attrs: list[str], nverts: int) -> bytes:
    """One display list: 0x98 strips then one 0x90 batch of leftover triangles; corner = one u16 index per
    attribute (nrm/clr use the vertex index, tex always 0: every part shares the solid white.tex)."""
    out = bytearray()
    strips, singles = strips_cw([tuple(map(int, t)) for t in tris])
    for v in strips:
        out += b"\x98" + struct.pack(">H", len(v))
        for i in v:
            out += struct.pack(f">{len(attrs)}H", *[0 if a in ("tex", "clr") else i for a in attrs])
    if singles:
        out += b"\x90" + struct.pack(">H", 3 * len(singles))
        for t in singles:
            for i in t:
                out += struct.pack(f">{len(attrs)}H", *[0 if a in ("tex", "clr") else i for a in attrs])
    return bytes(out)


def _dl_bytes(tris, attrs: list[str]) -> int:
    """Exact display-list bytes for a triangle set (a strip of n vertices costs 3 + 2*|attrs|*n; singles
    3 + 6*|attrs| each). Padding (<= 0x1f per chunk) is added by the caller's budget check."""
    strips, singles = strips_cw([tuple(map(int, t)) for t in tris])
    s = 2 * len(attrs)
    return sum(3 + s * len(v) for v in strips) + (3 + 3 * s * len(singles) if singles else 0)


def _umeyama(src, dst):
    """Rigid + uniform-scale fit of src onto dst (equal point counts): returns R, t, s with dst ~= s * src @ R.T + t."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    cov = (src - mu_s).T @ (dst - mu_d)
    U, S, Vt = np.linalg.svd(cov)
    d = np.eye(3)
    d[-1, -1] = np.sign(np.linalg.det(U @ Vt))
    R = Vt.T @ d @ U.T
    var = ((src - mu_s) ** 2).sum()
    s = float(np.trace(d @ np.diag(S)) / var) if var > 1e-12 else 1.0
    return R, mu_d - s * (mu_s @ R.T), s


def _farthest(pts, k: int) -> np.ndarray:
    """Farthest-point sampling: k indices spread over the point set."""
    if k >= len(pts):
        return np.arange(len(pts))
    chosen = [0]
    d2 = ((pts - pts[0]) ** 2).sum(1)
    while len(chosen) < k:
        i = int(d2.argmax())
        chosen.append(i)
        d2 = np.minimum(d2, ((pts - pts[i]) ** 2).sum(1))
    return np.asarray(chosen)


def _fit_rigid(src, dst) -> tuple:
    """Fit a (dense) donor point set onto a (coarse) target cloud: farthest-point-subsample the larger set to the
    smaller one's cardinality, then one Umeyama (ICP degrades when |src| >> |dst|). Returns R, t, s
    (dst ~= s * src @ R.T + t)."""
    if len(src) > len(dst):
        return _umeyama(src[_farthest(src, len(dst))], dst)
    if len(dst) > len(src):
        return _umeyama(src, dst[_farthest(dst, len(src))])
    return _umeyama(src, dst)


def _cluster(pos, nrm, tris, k: int):
    """Vertex-cluster decimation: k cluster centres chosen by farthest-point sampling, every vertex joins its
    nearest centre (position/normal averaged), degenerate triangles drop. Empty centres (duplicate positions)
    are dropped. Returns (pos, nrm, tris) arrays."""
    if k >= len(pos):
        return pos, nrm, list(tris)
    c = pos[_farthest(pos, k)]
    idx = ((pos[:, None, :] - c[None, :, :]) ** 2).sum(-1).argmin(1)
    keep = np.flatnonzero(np.bincount(idx, minlength=k) > 0)
    remap = np.zeros(k, np.int64)
    remap[keep] = np.arange(len(keep))
    npos = np.stack([pos[idx == j].mean(0) for j in keep])
    nnrm = np.stack([nrm[idx == j].mean(0) for j in keep])
    ln = np.linalg.norm(nnrm, axis=1, keepdims=True)
    nnrm = nnrm / np.maximum(ln, 1e-9)
    T = [(int(remap[idx[a]]), int(remap[idx[b]]), int(remap[idx[c]])) for a, b, c in tris
         if idx[a] != idx[b] and idx[b] != idx[c] and idx[a] != idx[c]]
    return npos, nnrm, T


def encode_shape(template: bytes, pos, nrm, tris, name: str = "", chunks=None) -> bytes:
    """Rewrite one .shp's arrays + display lists, keeping the header, material records (the DL pointer pairs get
    the new packed offsets/sizes), texture names and tail. pos/nrm are in the template's local frame and are
    quantised with the template's own scale/frac, so the game animates the part exactly as before. Returns a blob
    of the same size. chunks: the triangles per material record (display-list order; gbox.crazy_taxi_swap deals
    them by region); default: `tris` split evenly over the records."""
    if len(template) < 0x120 or struct.unpack_from(">f", template, 0)[0] != 1.0:
        raise ValueError(f"{name}: not a Crazy Taxi .shp")
    scale = struct.unpack_from(">3f", template, 0x2C)
    offs = {a: struct.unpack_from(">I", template, o)[0] for a, o in ATTR_WORDS}
    attrs = [a for a in ("pos", "nrm", "clr", "tex") if offs.get(a)]
    if "pos" not in attrs or "tex" not in attrs:
        raise ValueError(f"{name}: needs POS and TEX0 arrays")
    mat_off = _u32(template, 0x110)
    first = _u32(template, 0x114)
    dl_base = _u32(template, 0x118)
    tex_off = _u32(template, 0x11C)
    frac = read_shape(template, name).frac()
    pos, nrm, tris = np.asarray(pos, float), (np.asarray(nrm, float) if len(nrm) else np.zeros((len(pos), 3))), \
        [tuple(map(int, t)) for t in tris]
    V = len(pos)
    if V < 3 or not tris:
        raise ValueError(f"{name}: a part needs >= 3 vertices and >= 1 triangle")
    sizes = {"pos": 6 * V, "nrm": 6 * V if "nrm" in attrs else 0, "clr": 4 if "clr" in attrs else 0, "tex": 4}
    if first + sum(sizes.values()) > mat_off:
        raise ValueError(f"{name}: {V} vertices need {sum(sizes.values())} array bytes, region has {mat_off - first}")
    out = bytearray(template)
    out[first:mat_off] = b"\x00" * (mat_off - first)
    cur = first
    new_offs = {}
    for a in ("pos", "nrm", "clr", "tex"):
        if a in attrs:
            new_offs[a] = cur
            cur += sizes[a]
    for a, word in ATTR_WORDS:
        if a in attrs:
            struct.pack_into(">I", out, word, new_offs[a])
    k = 1 << frac
    q = np.clip(np.rint(pos * (k / np.asarray(scale))), -32767, 32767).astype(int)
    qn = np.clip(np.rint(nrm * 16384.0), -32767, 32767).astype(int)
    for i in range(V):
        struct.pack_into(">3h", out, new_offs["pos"] + 6 * i, *q[i])
    if "nrm" in attrs:
        for i in range(V):
            struct.pack_into(">3h", out, new_offs["nrm"] + 6 * i, *qn[i])
    if "clr" in attrs:
        # the driver's palette for this part (one flat colour: CLR0 corners all index entry 0)
        bounds = sorted({o for _, o in ATTR_WORDS if struct.unpack_from(">I", template, o)[0]} |
                        {mat_off, dl_base, tex_off, len(template)})
        nclr = (min(x for x in bounds if x > offs["clr"]) - offs["clr"]) // 4
        tclr = np.frombuffer(template, np.uint8, offs["clr"], 4 * max(nclr, 1)).reshape(-1, 4).mean(0).round() \
            .astype(np.uint8)
        out[new_offs["clr"]:new_offs["clr"] + 4] = tclr.tobytes()
    struct.pack_into(">2h", out, new_offs["tex"], 0, 0)
    pairs = _material_list_slots(template, mat_off, dl_base, tex_off or len(template))
    if not pairs:
        raise ValueError(f"{name}: no per-material display-list pointers found")
    out[dl_base:tex_off] = b"\x00" * (tex_off - dl_base)
    if chunks is None:
        chunks = [list(c) for c in np.array_split(np.asarray([list(t) for t in tris], int), len(pairs))] if tris else []
    else:
        chunks = [[tuple(map(int, t)) for t in c] for c in chunks]
        if len(chunks) != len(pairs):
            raise ValueError(f"{name}: {len(chunks)} triangle chunks for {len(pairs)} material records")
        if any(i < 0 or i >= V for c in chunks for t in c for i in t):
            raise ValueError(f"{name}: a chunk triangle indexes past {V} vertices")
    cur = dl_base
    for k in range(len(pairs)):
        block = _encode_dl(chunks[k] if k < len(chunks) else [], attrs, V)
        block += b"\x00" * ((0x20 - len(block) % 0x20) % 0x20)
        if cur + len(block) > tex_off:
            raise ValueError(f"{name}: display lists need {cur + len(block) - dl_base} bytes, region is "
                             f"{tex_off - dl_base} ({len(tris)} triangles)")
        out[cur:cur + len(block)] = block
        struct.pack_into(">II", out, pairs[k][0], cur, len(block))
        cur += len(block)
    return bytes(out)


def donor_segments(glb, part_roles: dict, joint_roles: dict) -> dict:
    """A library GLB + {Crazy Taxi part: donor role name} + {donor role: joint name} -> {part: (pos, nrm, tris)}
    in donor rest-pose space. Empty roles ride the nearest non-empty parent role (hand -> forearm -> upperarm,
    foot -> shin -> thigh, head -> chest)."""
    from .characters import rig_from_gltf
    rig = rig_from_gltf(Path(glb), dict(joint_roles))
    rmap = rig["roles"]                                       # role -> joint index
    parent = rig["parent"]
    jrole = {}
    for j in range(len(rig["joints"])):
        p, r = j, None
        while p != -1:
            for role, rj in rmap.items():
                if p == rj:
                    r = role
                    break
            if r is not None:
                break
            p = parent[p]
        jrole[j] = r
    P, N, O, T = [], [], [], []
    for pr in rig["prims"]:
        own = np.asarray(pr["owner"], int)
        P.append(np.asarray(pr["pos"], float))
        N.append(np.asarray(pr["nrm"], float))
        O.append(own)
        T.append(np.asarray(pr["tris"], int) + len(P[-1]) - len(pr["pos"]))
    P = np.concatenate(P) if P else np.zeros((0, 3))
    N = np.concatenate(N) if N else np.zeros((0, 3))
    O = np.concatenate(O) if O else np.zeros(0, int)
    T = np.concatenate(T) if T else np.zeros((0, 3), int)
    role_of_vert = np.array([jrole.get(int(j), "hip") for j in O])   # joints outside the role tree ride the hips
    # each triangle goes to the role of the majority of its corners, so no cross-role triangle is dropped
    tris_by_role = {r: [] for r in set(part_roles.values())}
    for t in T:
        r = Counter(role_of_vert[[int(c) for c in t]].tolist()).most_common(1)[0][0]
        tris_by_role[r].append(tuple(map(int, t)))
    segs = {}
    for part, role in part_roles.items():
        ts = tris_by_role.get(role, [])
        refs = sorted({c for t in ts for c in t})
        remap = {c: i for i, c in enumerate(refs)}
        segs[part] = (P[refs], N[refs], [(remap[a], remap[b], remap[c]) for a, b, c in ts])
    # Empty roles ride the nearest available segment: within-side parent first, then the mirrored left side
    # (the PSO export leaves the right arm/hand and both feet/shin verts unreferenced by triangles).
    for leaf, alt in (("mune", "koshi"), ("atama", "mune"),
                      ("kata_l", "mune"), ("kata_r", "kata_l"), ("kata_r", "mune"),
                      ("ude_l", "kata_l"), ("ude_r", "ude_l"), ("ude_r", "kata_r"),
                      ("te_l", "ude_l"), ("te_r", "te_l"), ("te_r", "ude_r"),
                      ("momo_l", "koshi"), ("momo_r", "momo_l"),
                      ("sune_l", "momo_l"), ("sune_r", "sune_l"), ("sune_r", "momo_r"),
                      ("kakato_l", "sune_l"), ("kakato_r", "kakato_l"), ("kakato_r", "sune_r")):
        if len(segs[leaf][0]) == 0:
            segs[leaf] = segs[alt]
    return segs


def part_budgets(template: bytes, attrs: list[str]) -> tuple[int, int]:
    """(max vertices, display-list region bytes) for a part blob: pos+nrm cost 6 bytes per vertex each, clr and
    tex are single entries (8 bytes together)."""
    mat_off, first, dl_base, tex_off = (_u32(template, o) for o in (0x110, 0x114, 0x118, 0x11C))
    per = 6 * (1 + int("nrm" in attrs))
    fixed = 4 + (4 if "clr" in attrs else 0)
    return (mat_off - first - fixed) // per, tex_off - dl_base


def _fit_segment(template: bytes, seg, name: str) -> tuple:
    """Fit one donor segment into one part blob: Umeyama onto the part's decoded cloud, then farthest-point
    clustering down to the vertex and display-list budgets. Returns (pos, nrm, tris)."""
    cloud = np.asarray(read_shape(template, name).positions(), float)
    if len(cloud) < 3:
        raise ValueError(f"{name}: target cloud too small")
    if len(seg[0]) < 3 or len(seg[2]) < 1:
        raise ValueError(f"{name}: the donor segment is empty")
    R, t, s = _fit_rigid(np.asarray(seg[0], float), cloud)
    pos = seg[0] @ R.T * s + t
    nrm = seg[1] @ R.T
    attrs = [a for a in ("pos", "nrm", "clr", "tex") if struct.unpack_from(">I", template, dict(ATTR_WORDS)[a])[0]]
    vmax, dlbudget = part_budgets(template, attrs)
    kpairs = len(_material_lists(template, _u32(template, 0x110), _u32(template, 0x118),
                                 _u32(template, 0x11C) or len(template)))
    best = None
    for k in range(min(vmax, len(pos)), 2, -1):
        mp, mn, mt = _cluster(pos, nrm, seg[2], k)
        if not mt:
            continue
        # lower bound: even one perfect strip needs 6*(T+2)+3 bytes
        if 6 * len(mt) + 15 + 0x1F * kpairs > dlbudget:
            continue
        if _dl_bytes(mt, attrs) + 0x1F * kpairs <= dlbudget:
            return mp, mn, mt
        best = (mp, mn, mt)
    raise ValueError(f"{name}: the donor segment won't fit: {len(best[0])} verts > {vmax} or "
                     f"{_dl_bytes(best[2], attrs)} DL bytes > {dlbudget}")


def _part_of(name: str) -> str:
    """'MP_YH_plyrA_sl_te_l_ok' -> 'te_l'."""
    k = name.split(".", 1)[0]
    for pre in ("MP_YH_plyrA_",):
        if k.startswith(pre):
            k = k[len(pre):]
    if k.startswith("sl_"):
        k = k[3:]
    for suf in ("_ok", "_ch", "_gu", "B", "C", "D"):
        if k.endswith(suf):
            k = k[:-len(suf)]
    return k


def swap_driver(bank: bytes, glb, part_roles: dict, joint_roles: dict, letter: str = "A", progress=None) -> \
        tuple[bytes, dict]:
    """Every MP_YH_plyr<letter>_*.shp blob -> the donor (Axel's parts, hand poses, head variants and sl_ LODs
    included, so no stock mesh ever appears). Returns (new bank, per-part stats)."""
    entries = read_bank(bank)
    pre = f"MP_YH_plyr{letter}_"
    parts = [(n, o, s) for n, o, s in entries if n.startswith(pre)]
    if not parts:
        raise ValueError(f"no {pre}* parts in the bank")
    segs = donor_segments(glb, part_roles, joint_roles)
    out = bytearray(bank)
    stats, done = {}, 0
    for n, o, s in parts:
        part = _part_of(n)
        seg = segs.get(part)
        if seg is None:
            raise ValueError(f"{n}: role for {part} missing from the donor rig")
        template = bytes(bank[o:o + s])
        mp, mn, mt = _fit_segment(template, seg, n)
        out[o:o + s] = encode_shape(template, mp, mn, mt, n)
        stats[n] = {"verts": len(mp), "tris": len(mt), "size": s}
        done += 1
        if progress:
            progress(10 + 80 * done / len(parts), f"Fitting {n}")
    return bytes(out), stats


def build_mod(cfg, game: dict, iso: Path, bank: bytes, name: str, image_name: str, progress=None) -> dict:
    """A Crazy Taxi file mod: a copy of the disc image with ct/polDC0.all replaced in place (same size)."""
    import shutil
    import types
    from . import filemods
    work = Path(cfg.cache) / "characters_build" / "crazy_taxi" / name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    bankfile = work / "polDC0.all"
    bankfile.write_bytes(bank)
    progress = progress or (lambda p, m: None)
    progress(90, f"Writing the disc image {image_name}")
    b = filemods.build_image(types.SimpleNamespace(cache=Path(cfg.cache)), game["game_id"], iso, name,
                             {BANK: {"from": str(bankfile)}})
    return b | {"files": [BANK]}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Crazy Taxi (GC): gbox.crazy_taxi_swap.use (slots player | driver:<name> | drivers |
    pedestrian(s) | passenger(s)). Kept so older callers of gbox.crazy_taxi.use reach the same writer."""
    from . import crazy_taxi_swap
    return crazy_taxi_swap.use(ctx, meta, game, inp)
