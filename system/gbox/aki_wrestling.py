"""AKI Corporation's N64 wrestling engine (WWF No Mercy; WCW/nWo Revenge and WCW vs. nWo World Tour share it):
identify the wrestlers, extract them into the character collection, and write any collection character in a wrestler's
place as a modded ROM (characters op=use / op=match / op=extract route here).

Formats (from AKI-Club's open-source VPW Studio, MIT, and akifiletable/akiarc, Unlicense; read as references only, no
code copied or run; checked against the operator's ROMs and in Ghidra, see docs/model_swaps.md "AKI wrestling"):
  * FileTable: u32 per file, (offset from FirstFile) | 1 when Asmik-LZSS compressed. File id k (1-based) spans
    entries k-1 .. k; raw size = next - this, compressed size = the 4-byte header (00 + 24-bit length).
  * AkiModel: {u8 scale, u8 nverts | 0x80 (vertex bytes are normals), u8 nfaces, u8 influence, s8 off x/y/z, u8 tex
    size (w/8 << 4 | h/8)}, then nverts x {s8 x, y, z, u8 u, v (texels), s8 nx, ny, nz}, then nfaces x 3 u8 indices.
    A vertex's position in the wrestler's rest space is (x, y, z) + 16 * off: every part of a wrestler shares one rest
    frame (arms down, facing +Z, his left = +X); the engine poses each part with its own matrix (G_MOVEMEM 0x0E,
    forced MVP) about its joint.
  * Ci8 texture: {w-1, h-1, u16 colours, mirror s, mirror t, log2 w, log2 h} + w*h indices; palette 256 x RGBA5551.
    The loaders 0x8000d688/0x8000e784 test header byte 2: == 1 is CI8 (256-colour TLUT), anything else CI4 with
    (w*h+1)/2 bytes, high nibble first, on the palette's first 16 colours (the shared neck 0x1F6A says 32 colours).
WWF No Mercy (NTSC-U Rev A, NW4E 1.1), RAM addresses from Ghidra on an RDRAM image (gBox DecompileAll, MIPS:BE:32):
  * 0x80003ab0 loads the file table (ROM 0x16C31D8, 0x1300C bytes = 0x4C03 entries, FirstFile 0x1BD150) into the heap
    and precomputes file sizes; 0x80003bd0 resolves a file id (ids 1..0x4C02).
  * 0x80018a3c builds a wrestler's part list from his costume: 0x270 bytes per slot at 0x800A8980, 24 part entries
    {u16 model, u16 texture, u16 palette, u8 skin, u8 x} at +0x08..+0xC0 (offsets PARTS below), then attire overlay
    layers (+0xE0..+0x24F) that are composited into each part's CI8 texture at load.
  * 0x800148f0 (slot, costume) calls it at 0x8001495c; wrestler id per slot = s16 at 0x80076264 + 2*slot.
  * Face texture of face number n = u16 at 0x8004D254[n] + 1: unique per roster wrestler, used as his key.
The writer: new model/texture/palette files appended after the last id (a spacer id keeps file 0x4C02's size), the
table moved to the end of the ROM with a little MIPS hook behind it (the table now loads to 0x80700000, Expansion Pak
RAM, which the game never uses); the hook runs after 0x80018a3c and, when the part list's face texture is a replaced
wrestler's, copies that character's part list over it (all 24 parts, no attire layers). The skeleton, animations,
moves and grapples are the game's: only the meshes and textures change.

  python -m gbox.aki_wrestling roster <rom>
  python -m gbox.aki_wrestling build <rom> <out.z64> <wrestler>=<character dir> [...]
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np
from . import n64_rom

# ---------------------------------------------------------------- catalog

NO_MERCY = {"23a346e48b6368a6": "WWF No Mercy (USA)", "2e8850a2a6c53375": "WWF No Mercy (Europe) (Rev A)"}
REVENGE = {"bca7ec4ecf71d164": "WCW-nWo Revenge (USA)", "061264c636cc284d": "WCW-nWo Revenge (Europe)"}
WORLD_TOUR = {"59bf059d2eadd372": "WCW vs. nWo: World Tour (USA)"}
GAME_IDS = {**NO_MERCY, **REVENGE, **WORLD_TOUR}

# ROM profiles (z64 offsets), by product code + revision. Only NW4E rev 1 has the writer; the others read.
PROFILES = {
    ("NW4E", 1): {"game": "nomercy", "first": 0x1BD150, "ft": 0x16C31D8, "nfiles": 0x4C02, "face_tbl": 0x4DE54,
                  "costumes_fid": 1, "writer": True},
    ("NW2E", 0): {"game": "revenge", "first": 0xDAC50, "ft": 0xCE2752, "nfiles": 7657, "writer": False},
    ("NWNE", 1): {"game": "worldtour", "first": 0x39500, "ft": 0x7C1C70, "nfiles": 5498, "writer": False},
}
MAX_V, MAX_F = 63, 84          # the largest models in the game: 63 vertices, 85 faces (more hangs the engine)
RAM_EXP = 0x80700000            # where the moved file table + hook + part lists live (Expansion Pak RAM, unused)

# No Mercy part list: offset -> (name, joint)
PARTS = {0x08: ("pelvis_r", "hip"), 0xB0: ("pelvis_l", "hip"), 0x10: ("waist_front", "waist"), 0xB8: ("waist_back", "waist"),
         0x18: ("chest_front", "chest"), 0xC0: ("chest_back", "chest"), 0x20: ("neck", "neck"), 0xA0: ("face", "head"),
         0x28: ("head_back", "head"), 0xA8: ("hair", "head"),
         0x60: ("l_upper_arm", "l_upper"), 0x58: ("l_lower_arm", "l_fore"), 0x48: ("l_hand", "l_hand"), 0x50: ("l_fingers", "l_fingers"),
         0x98: ("r_upper_arm", "r_upper"), 0x80: ("r_lower_arm", "r_fore"), 0x88: ("r_hand", "r_hand"), 0x90: ("r_fingers", "r_fingers"),
         0x38: ("l_upper_leg", "l_thigh"), 0x30: ("l_lower_leg", "l_shin"), 0x40: ("l_foot", "l_foot"),
         0x70: ("r_upper_leg", "r_thigh"), 0x68: ("r_lower_leg", "r_shin"), 0x78: ("r_foot", "r_foot")}
JOINTS = ["hip", "waist", "chest", "neck", "head", "l_upper", "l_fore", "l_hand", "l_fingers", "r_upper", "r_fore",
          "r_hand", "r_fingers", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]
JPARENT = {"hip": None, "waist": "hip", "chest": "waist", "neck": "chest", "head": "neck", "l_upper": "chest",
           "l_fore": "l_upper", "l_hand": "l_fore", "l_fingers": "l_hand", "r_upper": "chest", "r_fore": "r_upper",
           "r_hand": "r_fore", "r_fingers": "r_hand", "l_thigh": "hip", "l_shin": "l_thigh", "l_foot": "l_shin",
           "r_thigh": "hip", "r_shin": "r_thigh", "r_foot": "r_shin"}
# collection body roles for these joints (meta rig.roles)
ROLE_OF = {"hip": "hip", "chest": "chest", "neck": "neck", "head": "head", "l_upper": "l_upper", "l_fore": "l_fore",
           "l_hand": "l_hand", "r_upper": "r_upper", "r_fore": "r_fore", "r_hand": "r_hand", "l_thigh": "l_thigh",
           "l_shin": "l_shin", "l_foot": "l_foot", "r_thigh": "r_thigh", "r_shin": "r_shin", "r_foot": "r_foot"}

# No Mercy roster (wrestler number = costume block / 4 + 1), VPW Studio's WrestlerNames/NoMercy.txt order
NM_ROSTER = ["The Rock", "Steve Austin", "Undertaker", "Kane", "Steven Richards", "Mankind", "Cactus Jack", "Mick Foley",
             "Shawn Michaels", "Triple H", "X-Pac", "Mr. Ass", "Road Dogg", "Chris Benoit", "Dean Malenko", "Perry Saturn",
             "Eddie Guerrero", "Chris Jericho", "Kurt Angle", "Tazz", "Test", "Godfather", "D'Lo Brown", "Val Venis",
             "Ken Shamrock", "Rikishi", "Grandmaster Sexay", "Scotty 2 Hotty", "Edge", "Christian", "Matt Hardy",
             "Jeff Hardy", "Faarooq", "Bradshaw", "D-Von Dudley", "Buh Buh Ray Dudley", "Hardcore Holly", "Crash Holly",
             "Big Boss Man", "Albert", "Al Snow", "Steve Blackman", "British Bulldog", "Mark Henry", "Viscera",
             "Andre the Giant", "Bull Buchanan", "Essa Rios", "TAKA Michinoku", "Chyna", "Stephanie McMahon", "Tori",
             "Terri", "Trish Stratus", "Lita", "Ivory", "Linda McMahon", "The Kat", "Mae Young", "Ho", "Vince McMahon",
             "Shane McMahon", "Earl Hebner", "Jim Ross", "Original A"]
NM_ALIASES = {"Steve Austin": ["Stone Cold", "Stone Cold Steve Austin", "Austin"], "The Rock": ["Rock", "Dwayne Johnson"],
              "Undertaker": ["The Undertaker", "Taker"], "Triple H": ["HHH", "Hunter Hearst Helmsley"],
              "Shawn Michaels": ["HBK"], "Mankind": ["Mick Foley (Mankind)"]}


# ---------------------------------------------------------------- ROM + file table

def rom_bytes(path) -> bytes:
    return n64_rom.read(path)


def profile(rom: bytes) -> dict:
    key = (rom[0x3B:0x3F].decode(errors="replace"), rom[0x3F])
    p = PROFILES.get(key)
    if not p:
        raise ValueError(f"no AKI profile for {key[0]} rev {key[1]} (have: " +
                         ", ".join(f"{c} rev {r}" for c, r in PROFILES) + ")")
    return p


def lzss(d: bytes) -> bytes:
    """Asmik LZSS (4 KB ring, start 0xFEE): header 00 + 24-bit length, flag byte LSB first, 1 = literal."""
    n = int.from_bytes(d[1:4], "big")
    out = bytearray()
    i, cmd = 4, 0
    while len(out) < n:
        cmd >>= 1
        if cmd < 2:
            cmd = d[i] | 0x100
            i += 1
        if cmd & 1:
            out.append(d[i])
            i += 1
        else:
            p, ln = d[i], d[i + 1]
            i += 2
            p = ((p | ((ln << 4) & 0xF00)) + 0x12) & 0xFFF
            p -= len(out) & 0xFFF
            if p >= 0:
                p -= 0x1000
            p += len(out)
            for _ in range((ln & 0xF) + 3):
                out.append(out[p] if p >= 0 else 0)
                p += 1
    return bytes(out[:n])


def lzss_store(d: bytes, depth: int = 96) -> bytes:
    """Asmik LZSS encoder (4 KB window, matches of 3..18, optimal parse: the cheapest literal/match sequence by
    dynamic programming, plus matches into the ring's initial zeros). The game loads a wrestler's parts through a
    fixed staging buffer and files rewritten in place must fit their old span, so this packs a bit tighter than AKI's."""
    n = len(d)
    best = [(0, 0)] * n                                    # per position: (longest match, its source position)
    heads: dict[bytes, list[int]] = {}
    for i in range(n):
        bl, bp = 0, 0
        if i + 3 <= n:
            for q in reversed(heads.get(d[i:i + 3], [])[-depth:]):
                if i - q > 4096:
                    break
                ln = 3
                while ln < 18 and i + ln < n and d[q + ln] == d[i + ln]:
                    ln += 1
                if ln > bl:
                    bl, bp = ln, q
                    if ln == 18:
                        break
            if i < 4096 - 18 and bl < 18:                  # the ring starts as zeros: a run of zeros can come from it
                z = 0
                while z < 18 and i + z < n and d[i + z] == 0:
                    z += 1
                if z >= 3 and z > bl and i - 4096 + z <= 0:
                    bl, bp = z, i - 4096
            heads.setdefault(d[i:i + 3], []).append(i)
        best[i] = (bl, bp)
    cost = [0] * (n + 1)
    step = [1] * (n + 1)
    for i in range(n - 1, -1, -1):
        c, st = 9 + cost[i + 1], 1
        bl = best[i][0]
        for ln in range(3, bl + 1):
            if 17 + cost[i + ln] < c:
                c, st = 17 + cost[i + ln], ln
        cost[i], step[i] = c, st
    out = bytearray(b"\0" + n.to_bytes(3, "big"))
    i = 0
    while i < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            st = step[i]
            if st >= 3:
                sv = (best[i][1] - 0x12) & 0xFFF
                out += bytes([sv & 0xFF, ((sv >> 4) & 0xF0) | (st - 3)])
            else:
                flags |= 1 << bit
                out.append(d[i])
            i += st
        out[flag_at] = flags
    return bytes(out)


def modded(rom: bytes) -> dict | None:
    """A ROM written by NMWriter: {ft (ROM), entries, templates {key face texture: part list}}; else None."""
    try:
        if struct.unpack_from(">I", rom, _ram2rom(0x80003AD4))[0] != 0x3C020000 | (RAM_EXP >> 16):
            return None
    except Exception:                                      # noqa: BLE001
        return None
    hi = struct.unpack_from(">H", rom, _ram2rom(0x80003ADC) + 2)[0]
    lo = struct.unpack_from(">h", rom, _ram2rom(0x80003AE0) + 2)[0]
    ft = (hi << 16) + lo
    n = struct.unpack_from(">H", rom, _ram2rom(0x80003BD8) + 2)[0]
    hook = (struct.unpack_from(">I", rom, _ram2rom(0x8001495C))[0] & 0x3FFFFFF) << 2 | 0x80000000
    code_at = ft + (hook - RAM_EXP)
    hi2, lo2 = struct.unpack_from(">H", rom, code_at + 28 + 2)[0], struct.unpack_from(">h", rom, code_at + 32 + 2)[0]
    t = ft + ((hi2 << 16) + lo2 - RAM_EXP)
    templates = {}
    while True:
        k = struct.unpack_from(">H", rom, t)[0]
        if not k:
            break
        templates[k] = rom[t + 4:t + 4 + 0x250]
        t += 0x254
    return {"ft": ft, "entries": n, "templates": templates}


class FileTable:
    def __init__(self, rom: bytes, prof: dict | None = None):
        self.rom, self.p = rom, dict(prof or profile(rom))
        m = modded(rom) if self.p.get("game") == "nomercy" else None
        if m:                                              # a gBox mod: the moved, longer table
            self.p.update(ft=m["ft"], nfiles=m["entries"] - 1)
        n = self.p["nfiles"] + 1
        self.raw = list(struct.unpack_from(f">{n}I", rom, self.p["ft"]))

    def span(self, fid: int) -> tuple[int, int, bool]:
        a, b = self.raw[fid - 1], self.raw[fid]
        return self.p["first"] + (a & ~1), abs((b & ~1) - (a & ~1)), bool(a & 1)

    def get(self, fid: int) -> bytes:
        o, n, enc = self.span(fid)
        d = self.rom[o:o + n]
        return lzss(d) if enc else d


# ---------------------------------------------------------------- models + textures

def model_parse(d: bytes) -> dict:
    nv, nf = d[1] & 0x7F, d[2] & 0x7F
    off = np.array(struct.unpack_from("3b", d, 4), int) * 16
    V = np.frombuffer(d, np.int8, nv * 8, 8).reshape(nv, 8)
    uv = V[:, 3:5].view(np.uint8).astype(float)
    F = np.frombuffer(d, np.uint8, nf * 3, 8 + nv * 8).reshape(nf, 3).astype(int)
    F = F[(F < nv).all(1)]
    return {"pos": V[:, :3].astype(float) + off, "uv": uv, "nrm": V[:, 5:8].astype(float) / 127.0,
            "normals": bool(d[1] & 0x80), "faces": F, "scale": d[0], "influence": d[3], "tex": (d[7] >> 4) * 8, "texh": (d[7] & 15) * 8,
            "texbyte": d[7]}


def model_encode(pos: np.ndarray, nrm: np.ndarray, uv: np.ndarray, faces: np.ndarray, texbyte: int) -> bytes:
    """Rest-space positions -> one AkiModel (<= 127 vertices and faces; raises if the part doesn't fit)."""
    if len(pos) > MAX_V or len(faces) > MAX_F:
        raise ValueError(f"part has {len(pos)} vertices / {len(faces)} faces (max {MAX_V} / {MAX_F})")
    if not len(pos):
        return b""
    c = np.round((pos.min(0) + pos.max(0)) / 2 / 16).astype(int)
    q = np.round(pos - c * 16).astype(int)
    if np.abs(q).max() > 127:
        raise ValueError(f"part spans {np.ptp(pos, 0).max():.0f} units (max 254)")
    n = np.clip(np.round(nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9) * 127), -127, 127).astype(int)
    out = bytearray(struct.pack(">BBBBbbbB", 0, len(pos) | 0x80, len(faces), 0, *c.tolist(), texbyte))
    for p, u, nn in zip(q, np.clip(np.round(uv), 0, 255).astype(int), n):
        out += struct.pack(">bbbBBbbb", *p.tolist(), *u.tolist(), *nn.tolist())
    for f in faces:
        out += bytes(int(x) for x in f)
    return bytes(out)


def rgba5551(c) -> np.ndarray:
    c = np.asarray(c, np.uint16)
    r, g, b, a = (c >> 11) & 31, (c >> 6) & 31, (c >> 1) & 31, c & 1
    return np.stack([r * 255 // 31, g * 255 // 31, b * 255 // 31, a * 255], -1).astype(np.uint8)


def tex_format(tex: bytes) -> str:
    """'ci8' or 'ci4' by the game's rule (header byte 2 == 1 -> CI8, see gbox.nomercy_analysis); raises ValueError
    on a truncated file."""
    if len(tex) < 8:
        raise ValueError("truncated AKI texture header")
    fmt = "ci8" if tex[2] == 1 else "ci4"
    px = (tex[0] + 1) * (tex[1] + 1)
    need = 8 + (px if fmt == "ci8" else (px + 1) // 2)
    if len(tex) < need:
        raise ValueError(f"truncated AKI {fmt} texture: {len(tex)} < {need} bytes")
    return fmt


def tex_decode(tex: bytes, pal: bytes) -> np.ndarray:
    """CI8 or CI4 texture + RGBA5551 palette -> RGBA (h, w, 4). CI4 uses palette entries 0-15 (16-colour TLUT)."""
    w, h = tex[0] + 1, tex[1] + 1
    if tex_format(tex) == "ci8":
        idx, n = np.frombuffer(tex, np.uint8, w * h, 8).reshape(h, w), 256
    else:
        b = np.frombuffer(tex, np.uint8, (w * h + 1) // 2, 8)
        idx, n = np.stack([b >> 4, b & 15], 1).reshape(-1)[:w * h].reshape(h, w), 16
    p = rgba5551(np.frombuffer(pal[:2 * n].ljust(2 * n, b"\0"), ">u2"))
    return p[idx]


def ci8_decode(tex: bytes, pal: bytes) -> np.ndarray:
    """Any AKI model texture (CI8 or CI4) -> RGBA; kept for existing callers (see tex_decode)."""
    return tex_decode(tex, pal)


def quantize(img: np.ndarray, n: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """RGBA (h, w, 4) -> (indices (h, w), palette (k, 4) RGBA8) by median cut on 5551 colours."""
    px = img.reshape(-1, 4).astype(int)
    q = np.concatenate([px[:, :3] >> 3, (px[:, 3:] >= 128)], 1)
    key = (q[:, 0] << 11) | (q[:, 1] << 6) | (q[:, 2] << 1) | q[:, 3]
    uniq, inv = np.unique(key, return_inverse=True)
    if len(uniq) <= n:
        pal = rgba5551(uniq.astype(np.uint16))
        return inv.reshape(img.shape[:2]).astype(np.uint8), pal
    boxes = [np.arange(len(px))]
    while len(boxes) < n:
        i = max(range(len(boxes)), key=lambda k: np.ptp(px[boxes[k], :3], 0).max() * (len(boxes[k]) > 1))
        b = boxes[i]
        if len(b) < 2:
            break
        ch = int(np.ptp(px[b, :3], 0).argmax())
        o = b[np.argsort(px[b, ch], kind="stable")]
        boxes[i:i + 1] = [o[:len(o) // 2], o[len(o) // 2:]]
    pal = np.array([px[b].mean(0) for b in boxes]).round().astype(np.uint8)
    pal[:, 3] = np.where(pal[:, 3] >= 128, 255, 0)
    d = ((px[:, None, :3] - pal[None, :, :3].astype(int)) ** 2).sum(2)
    return d.argmin(1).reshape(img.shape[:2]).astype(np.uint8), pal


# ---------------------------------------------------------------- No Mercy roster / body tables

def _ram2rom(a: int) -> int:
    return a - 0x80000400 + 0x1000


def costumes(rom: bytes, ft: FileTable | None = None) -> list[bytes]:
    ft = ft or FileTable(rom)
    d = ft.get(ft.p["costumes_fid"])
    return [d[i * 38:(i + 1) * 38] for i in range(len(d) // 38)]


def face_tex(rom: bytes, face: int) -> int:
    return struct.unpack_from(">H", rom, PROFILES[("NW4E", 1)]["face_tbl"] + 2 * face)[0] + 1


def roster(rom: bytes) -> list[dict]:
    """Default wrestlers: number, name, the 4 costumes' body type and face texture (the hook's key)."""
    ft = FileTable(rom)
    cs = costumes(rom, ft)
    out = []
    for w in range(len(cs) // 4):
        c4 = cs[4 * w:4 * w + 4]
        name = NM_ROSTER[w] if w < len(NM_ROSTER) else f"Wrestler {w + 1}"
        out.append({"number": w + 1, "name": name, "aliases": NM_ALIASES.get(name, []),
                    "body": [c[0] for c in c4], "faces": [c[29] for c in c4],
                    "face_tex": sorted({face_tex(rom, c[29]) for c in c4 if c[29] < 0x7F})})
    return out


BODY_CLASS = 0x48A48            # RAM 0x80048A48: body type -> body class (22 types -> 11 classes)
CLASS_ROWS = 0x48A78            # pointers: class -> 20 model ids (order SLOT_ORDER)
SKIN_IDX = 0x48AA4              # body type -> skin row
SKIN_ROWS = 0x48AD4             # pointers: skin row -> 20 palette ids (texture = palette + 1)
SLOT_ORDER = 0x4FD28            # 20 bytes: part entry index (offset / 8) per row position


def body_parts(rom: bytes, body_type: int) -> dict:
    """{part offset: (model id, texture id, palette id)} of a body type's 20 body parts (no head, no attire)."""
    rd = lambda a, f, n=1: struct.unpack_from(f">{n}{f}", rom, _ram2rom(a))
    cls = rd(0x80000000 | BODY_CLASS + 2 * body_type, "h")[0]
    row = rd(0x80000000 | CLASS_ROWS + 4 * cls, "I")[0]
    skin = rd(0x80000000 | SKIN_ROWS + 4 * rd(0x80000000 | SKIN_IDX + 2 * body_type, "h")[0], "I")[0]
    order = rd(0x80000000 | SLOT_ORDER, "B", 20)
    models, pals = rd(row, "H", 20), rd(skin, "H", 20)
    return {o * 8: (m, p + 1 if p else 0, p) for o, m, p in zip(order, models, pals)}, cls


def head_parts(rom: bytes, costume: bytes) -> dict:
    """Face model, head back and face texture of a costume (No Mercy default path of 0x80018a3c)."""
    out = {}
    face = costume[29]
    if face < 0x7F:
        pal = face_tex(rom, face) - 1
        out[0xA0] = [0, pal + 1, pal]
    return out


# ---------------------------------------------------------------- skeleton (rest space)

def rest_body(rom: bytes, body_type: int, ft: FileTable | None = None) -> dict:
    """The body type's 20 parts in rest space + joint positions estimated from the seams (+ head/neck from the
    common neck model). -> {parts {off: model}, joints {name: xyz}}."""
    ft = ft or FileTable(rom)
    bp, cls = body_parts(rom, body_type)
    parts = {o: model_parse(ft.get(m)) for o, (m, _t, _p) in bp.items() if m}
    parts[0x20] = model_parse(ft.get(0x14FF))
    return {"parts": parts, "joints": joints_from(parts), "class": cls, "ids": bp}


def joints_from(parts: dict) -> dict:
    by = {}
    for o, m in parts.items():
        by.setdefault(PARTS[o][1], []).append(m["pos"])
    P = {j: np.concatenate(v) for j, v in by.items()}

    def seam(child, parent):
        a, b = P.get(child), P.get(parent)
        if a is None or b is None:
            return None
        d = np.linalg.norm(a[:, None] - b[None], axis=2).min(1)
        near = a[d <= max(1.5, np.sort(d)[min(len(d) - 1, 5)])]
        return near.mean(0)
    J = {}
    hipc = P["hip"].mean(0)
    J["hip"] = np.array([0.0, P["hip"][:, 1].max() - 4, hipc[2]])
    for j in JOINTS[1:]:
        if j in P:
            s = seam(j, JPARENT[j])
            J[j] = s if s is not None else P[j].mean(0)
    if "head" not in J:
        J["head"] = J.get("neck", J["chest"]) + [0, 12.0, 0]
    if "neck" not in J:
        J["neck"] = (J["chest"] + J["head"]) / 2
    for side in "lr":                                  # fingers: off the hand toward its far end
        if f"{side}_hand" in J and f"{side}_fingers" not in J:
            J[f"{side}_fingers"] = J[f"{side}_hand"] + [0, -6.0, 0]
    return {k: np.asarray(v, float) for k, v in J.items()}


# ---------------------------------------------------------------- extraction (rest-space glb with roles)

def part_list_static(rom: bytes, wrestler: int, costume: int = 0) -> dict:
    """A wrestler's parts from the ROM tables (body + face). Attire layers are not composited (see extract)."""
    cs = costumes(rom)
    c = cs[4 * (wrestler - 1) + costume]
    bp, cls = body_parts(rom, c[0])
    out = {o: list(v) for o, v in bp.items()}
    out[0x20] = [0x14FF, 0x1F6A, 0x1F6D if cls >= 6 else 0x1F6B]       # 0x80018C7C-0x80018C9C: palette by body class
    out.update(head_parts(rom, c))
    return out


def to_glb(rom: bytes, plist: dict, out: Path, name: str, textures: dict | None = None, face_model: int | None = None) -> dict:
    """Part list {off: [model, tex, pal]} -> skinned glTF in rest space (joint per part role), textures from the ROM
    (or `textures` {off: RGBA} composited elsewhere). Returns {path, roles, triangles}."""
    from .melee_models import write_gltf
    ft = FileTable(rom)
    parts = {}
    for o, (m, t, p) in plist.items():
        if not m:
            continue
        try:
            parts[o] = model_parse(ft.get(m))
        except Exception:                                  # noqa: BLE001
            continue
    J = joints_from(parts)
    names = [j for j in JOINTS if j in J]
    ji = {j: i for i, j in enumerate(names)}
    joints = []
    for j in names:
        w = np.eye(4)
        w[:3, 3] = J[j] / 64.0
        pj = JPARENT[j]
        while pj is not None and pj not in ji:
            pj = JPARENT[pj]
        joints.append({"parent": ji[pj] if pj else -1, "world": w})
    prims, tris = [], 0
    for o, m in parts.items():
        j = PARTS[o][1]
        j = j if j in ji else JPARENT[j]
        img = (textures or {}).get(o)
        _m, t, p = plist[o]
        if img is None and t and p:
            try:
                img = ci8_decode(ft.get(t), ft.get(p))
            except Exception:                              # noqa: BLE001
                img = None
        h, w = (img.shape[:2] if img is not None else (max(m["texh"], 8), max(m["tex"], 8)))
        uv = (m["uv"] + 0.5) / [w, h]
        n = len(m["pos"])
        Jv = np.zeros((n, 4), np.int64)
        Jv[:, 0] = ji[j]
        Wv = np.zeros((n, 4))
        Wv[:, 0] = 1
        tri = m["faces"]                                  # AKI faces are CCW like glTF
        prims.append({"pos": m["pos"] / 64.0, "nrm": m["nrm"], "uv": uv, "tris": tri, "J": Jv, "W": Wv,
                      "tex": img, "color": (255, 255, 255, 255), "name": PARTS[o][0], "wrap": ("mirror", "mirror")})
        tris += len(tri)
    write_gltf(Path(out), joints, prims, 1.0, name, names)
    roles = {ROLE_OF[j]: j for j in names if j in ROLE_OF}
    return {"path": str(out), "roles": roles, "triangles": tris, "joints": names}


# ---------------------------------------------------------------- writer

def _mips_hook(table_end: int, templ: int) -> list[int]:
    """The hook (at RAM table_end): call 0x80018a3c(a0, a1), then if the part list's face texture (+0xA2) is a key in
    the template table at `templ` ({u16 key, u16 0, 0x250 bytes} ... {0}), copy that template over the part list."""
    hi = lambda a: ((a + 0x8000) >> 16) & 0xFFFF
    lo = lambda a: a & 0xFFFF
    loop = table_end + 4 * 11
    found = table_end + 4 * 19
    copy = table_end + 4 * 21
    done = table_end + 4 * 27
    br = lambda here, tgt: ((tgt - here - 4) >> 2) & 0xFFFF
    w = [0x27BDFFE0, 0xAFBF001C, 0xAFA50018,               # addiu sp,-32; sw ra,28(sp); sw a1,24(sp)
         0x0C000000 | ((0x80018A3C >> 2) & 0x3FFFFFF), 0,    # jal 0x80018a3c; nop
         0x8FA50018, 0x94A800A2,                           # lw a1,24(sp); lhu t0,0xa2(a1)
         0x3C090000 | hi(templ), 0x25290000 | lo(templ),   # lui t1; addiu t1  (template table)
         0, 0]                                             # (pad to keep the layout simple)
    assert len(w) == 11
    here = table_end + 4 * len(w)
    w += [0x952A0000,                                       # loop: lhu t2,0(t1)
          0x11400000 | br(here + 4, done),                 # beq t2,zero,done
          0,
          0x110A0000 | br(here + 12, found),               # beq t0,t2,found
          0,
          0x10000000 | br(here + 20, loop),                # b loop
          0x25290254,                                      # addiu t1,t1,0x254 (delay)
          0]
    assert table_end + 4 * len(w) == found
    w += [0x25290004, 0x240B0250]                          # found: addiu t1,t1,4; li t3,0x250
    assert table_end + 4 * len(w) == copy
    here = copy
    w += [0x8D2C0000, 0xACAC0000, 0x25290004, 0x256BFFFC,  # copy: lw t4,0(t1); sw t4,0(a1); t1+=4; t3-=4
          0x15600000 | br(here + 16, copy),                # bne t3,zero,copy
          0x24A50004]                                      # addiu a1,a1,4 (delay)
    assert table_end + 4 * len(w) == done
    w += [0x8FBF001C, 0x03E00008, 0x27BD0020]              # done: lw ra; jr ra; addiu sp,32
    return w


def _patch_nm_code(rom: bytearray, ft_rom: int, n_entries: int, total: int, hook: int, with_hook: bool = True) -> None:
    """No Mercy NW4E 1.1 boot-segment patches (each checked against the original instruction first)."""
    def put(ram, old, new):
        o = _ram2rom(ram)
        cur = struct.unpack_from(">I", rom, o)[0]
        if cur != old:
            raise ValueError(f"unexpected code at {ram:#x}: {cur:08x} (want {old:08x}); not NW4E rev A?")
        struct.pack_into(">I", rom, o, new)
    hi = lambda a: (a >> 16) & 0xFFFF
    put(0x80003AD4, 0x0C0001F5, 0x3C020000 | (RAM_EXP >> 16))          # malloc(0x1300c) -> v0 = 0x80700000
    put(0x80003ADC, 0x3C04016C, 0x3C040000 | (((ft_rom + 0x8000) >> 16) & 0xFFFF))
    put(0x80003AE0, 0x248431D8, 0x24840000 | (ft_rom & 0xFFFF))
    put(0x80003AE8, 0x3C060001, 0x3C060000 | hi(total))
    put(0x80003AF8, 0x34C6300C, 0x34C60000 | (total & 0xFFFF))
    sz = 4 * n_entries
    put(0x80003AFC, 0x3C040001, 0x3C040000 | hi(sz))
    put(0x80003B04, 0x34843008, 0x34840000 | (sz & 0xFFFF))
    put(0x80003B98, 0x2E424C02, 0x2E420000 | (n_entries - 1))
    put(0x80003BD8, 0x2C424C03, 0x2C420000 | n_entries)
    if with_hook:
        put(0x8001495C, 0x0C00628F, 0x0C000000 | ((hook >> 2) & 0x3FFFFFF))


class NMWriter:
    """Collects new files + part-list templates, then writes the ROM."""
    def __init__(self, rom: bytes):
        self.rom = rom
        self.p = profile(rom)
        if not self.p.get("writer"):
            raise ValueError(f"no writer for {self.p['game']} yet")
        self.ft = FileTable(rom, self.p)
        self.files: list[bytes] = []
        self.templates: list[tuple[int, bytes]] = []
        self.inplace: dict[int, bytes] = {}               # file id -> new bytes written over the old file's span

    def replace_file(self, fid: int, data: bytes) -> None:
        """Rewrite an existing file where it is (the new bytes, compressed like the old ones, must fit its span)."""
        o, n, enc = self.ft.span(fid)
        z = lzss_store(data) if enc else data
        if len(z) > n:
            raise ValueError(f"file {fid:#x}: {len(z)} bytes don't fit its {n}-byte span")
        self.inplace[fid] = z + bytes(n - len(z))

    def add_file(self, data: bytes) -> int:
        self.files.append(data)
        return self.p["nfiles"] + 1 + len(self.files)      # id nfiles+1 is the spacer

    def add_template(self, keys: list[int], entries: dict) -> None:
        t = bytearray(0x250)
        for o, (m, tx, pl, fl) in entries.items():
            struct.pack_into(">HHHH", t, o, m, tx, pl, fl)
        for k in keys:
            self.templates.append((k, bytes(t)))

    def build(self, hook: bool = True, data_at: int | None = None) -> bytes:
        from .sm64_writer import fix_crc
        rom = bytearray(self.rom)
        first = self.p["first"]
        end = len(rom.rstrip(rom[-1:]))
        if data_at is None:
            data_at = (max(end, self.p["ft"] + 4 * (self.p["nfiles"] + 4)) + 0xFFF) & ~0xFFF
        blob = bytearray()
        offs = []
        flags = []
        for f in self.files:
            blob += bytes((-len(blob)) % 8)
            offs.append(data_at + len(blob))
            z = lzss_store(f)
            flags.append(len(z) < len(f))                  # like the game: raw when compression doesn't help
            blob += z if flags[-1] else f
        blob += bytes((-len(blob)) % 8)
        data_end = data_at + len(blob)
        raw = list(self.ft.raw)                            # entries 0..nfiles (the last = end of file nfiles)
        raw[-1] &= ~1                                      # it also starts the spacer: raw, not compressed
        raw.append((data_at - first) | (1 if flags and flags[0] else 0))  # spacer: old end .. our data
        for o, fl in zip(offs[1:], flags[1:]):
            raw.append((o - first) | int(fl))
        raw.append(data_end - first)                       # end of our last file
        n_entries = len(raw)
        table = struct.pack(f">{n_entries}I", *raw)
        ft_rom = data_end
        ft_ram_end = RAM_EXP + len(table)
        hook_at = (ft_ram_end + 15) & ~15
        code = _mips_hook(hook_at, 0)
        templ_at = hook_at + 4 * len(code) + 16 & ~15
        code = _mips_hook(hook_at, templ_at)
        tb = bytearray()
        for k, t in self.templates:
            tb += struct.pack(">HH", k, 0) + t
        tb += bytes(8)
        payload = table + bytes(hook_at - ft_ram_end) + struct.pack(f">{len(code)}I", *code)
        payload += bytes(templ_at - (RAM_EXP + len(payload))) + tb
        payload += bytes((-len(payload)) % 16)
        total = len(payload)
        need = ft_rom + total
        size = len(rom)
        while size < need:
            size *= 2
        if size > 0x4000000:
            raise ValueError("the modded ROM would exceed 64 MB")
        if size > len(rom):
            rom += b"\xff" * (size - len(rom))
        rom[data_at:data_end] = blob
        rom[ft_rom:ft_rom + total] = payload
        for fid, z in self.inplace.items():
            o, n, _enc = self.ft.span(fid)
            rom[o:o + n] = z
        _patch_nm_code(rom, ft_rom, n_entries, total, hook_at, hook)
        return bytes(fix_crc(rom))


# ---------------------------------------------------------------- character -> wrestler


def _write_parts_gltf(path: Path, parts: dict, mats: list) -> Path:
    """Static glTF, one node + mesh per part (name "pXX__<target tris>"), embedded PNG textures."""
    import base64
    from .melee_models import _png
    blob, views, accs, images, textures, materials, meshes, nodes = bytearray(), [], [], [], [], [], [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        arr = np.ascontiguousarray(arr)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": int(len(arr)), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    for mi, m in enumerate(mats):
        md = {"name": f"m{mi}", "doubleSided": True, "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1,
              "baseColorFactor": [c / 255 for c in m["color"][:3]] + [1.0]}}
        if m["tex"] is not None:
            png = _png(np.asarray(m["tex"], np.uint8))
            blob += bytes((-len(blob)) % 4)
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(png)})
            blob += png
            images.append({"bufferView": len(views) - 1, "mimeType": "image/png"})
            textures.append({"source": len(images) - 1})
            md["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(textures) - 1}
        materials.append(md)
    for name, (P, N, UV, F, FM) in parts.items():
        prims = []
        for mi in sorted(set(FM.tolist())):
            tri = F[FM == mi]
            used = np.unique(tri)
            remap = np.full(len(P), -1)
            remap[used] = np.arange(len(used))
            prims.append({"attributes": {"POSITION": add(P[used].astype(np.float32), 5126, "VEC3", 34962, True),
                                         "NORMAL": add(N[used].astype(np.float32), 5126, "VEC3", 34962),
                                         "TEXCOORD_0": add(UV[used].astype(np.float32), 5126, "VEC2", 34962)},
                          "indices": add(remap[tri].reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963), "material": int(mi)})
        meshes.append({"name": name, "primitives": prims})
        nodes.append({"name": name, "mesh": len(meshes) - 1})
    gl = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes,
          "meshes": meshes, "materials": materials, "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," +
                       base64.b64encode(bytes(blob)).decode()}]}
    if images:
        gl["images"], gl["textures"] = images, textures
    Path(path).write_text(json.dumps(gl))
    return Path(path)


def _decimate_parts(P, N, UV, F, FM, part, mats, caps, work: Path, blender, progress) -> dict:
    """Each part's faces, welded by position -> Blender edge-collapse to its budget. -> {off: {P, N, F, src}} where
    src = the part's source triangles (positions, uvs, materials) for the texture bake."""
    import subprocess
    from .re4gc_models import _gltf_load
    cur = {}
    for o in set(part.tolist()):
        sel = np.where(part == o)[0]
        src = {"P": P[F[sel]], "UV": UV[F[sel]], "FM": FM[sel]}            # (n,3,3) (n,3,2) (n,)
        used = np.unique(F[sel])
        key = np.round(P[used], 2)
        _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
        rm = np.full(len(P), -1)
        rm[used] = inv.reshape(-1)
        Fw = rm[F[sel]]
        ok = (Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])
        cur[o] = {"P": P[used][first], "N": N[used][first], "F": Fw[ok], "src": src}
    target = {o: caps[o][1] - 2 for o in cur}
    for rnd in range(5):
        over = {}
        for o, g in cur.items():
            nv_est = int(len(np.unique(g["F"])) * 1.12) + 2   # + the cylinder seam duplicates
            if len(g["F"]) > target[o] or nv_est > caps[o][0]:
                over[o] = nv_est
        if not over or not blender:
            break
        progress(45 + rnd * 5, f"Fitting {len(over)} parts into the game's vertex/face budget (Blender, pass {rnd + 1})")
        for o, nv_est in over.items():
            if nv_est > caps[o][0]:
                target[o] = max(4, min(target[o], int(len(cur[o]["F"]) * caps[o][0] / nv_est * 0.95)))
        parts = {f"p{o:02x}__{target[o]}": (cur[o]["P"], cur[o]["N"], np.zeros((len(cur[o]["P"]), 2)), cur[o]["F"],
                                            np.zeros(len(cur[o]["F"]), int)) for o in over}
        srcf = _write_parts_gltf(work / f"parts_{rnd}.gltf", parts, [{"tex": None, "color": (200, 200, 200, 255)}])
        dst = work / f"parts_{rnd}_dec.glb"
        script = Path(__file__).resolve().parents[1] / "scripts" / "decimate_parts_gltf.py"
        r = subprocess.run([blender, "--background", "--factory-startup", "--python", str(script), "--", str(srcf), str(dst)],
                           capture_output=True, text=True, timeout=900)
        if not dst.exists():
            raise RuntimeError("part decimation failed: " + (r.stdout + r.stderr)[-1500:])
        gl, acc, _image = _gltf_load(dst)
        for nd in gl["nodes"]:
            if "mesh" not in nd or not re.match(r"p[0-9a-f]{2}__", nd.get("name", "")):
                continue
            o = int(nd["name"][1:3], 16)
            Ps, Ns, Fs = [], [], []
            base = 0
            for pr in gl["meshes"][nd["mesh"]]["primitives"]:
                a_ = pr["attributes"]
                pp = acc(a_["POSITION"]).astype(float)
                Ps.append(pp)
                Ns.append(acc(a_["NORMAL"]).astype(float) if "NORMAL" in a_ else np.tile([0, 1.0, 0], (len(pp), 1)))
                Fs.append(acc(pr["indices"]).reshape(-1, 3).astype(int) + base)
                base += len(pp)
            if Fs:
                Pn, Fn = np.concatenate(Ps), np.concatenate(Fs)
                key = np.round(Pn, 3)
                _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
                Fn = inv.reshape(-1)[Fn]
                ok = (Fn[:, 0] != Fn[:, 1]) & (Fn[:, 1] != Fn[:, 2]) & (Fn[:, 0] != Fn[:, 2])
                cur[o] = {"P": Pn[first], "N": np.concatenate(Ns)[first], "F": Fn[ok], "src": cur[o]["src"]}
    return cur


def _sample_source(src: dict, pts: np.ndarray, mats: list) -> np.ndarray:
    """3D points -> RGB from the nearest source triangle (its texture at the projected barycentric uv)."""
    T = src["P"]                                           # (n,3,3)
    cen = T.mean(1)
    out = np.zeros((len(pts), 3), np.uint8)
    if not len(T):
        return out
    k = min(6, len(T))
    d2 = ((pts[:, None, :] - cen[None]) ** 2).sum(2)
    cand = np.argsort(d2, 1)[:, :k]
    best_t = np.zeros(len(pts), int)
    best_bc = np.zeros((len(pts), 3))
    best_d = np.full(len(pts), np.inf)
    for j in range(k):
        t = cand[:, j]
        a, b, c = T[t, 0], T[t, 1], T[t, 2]
        v0, v1, v2 = b - a, c - a, pts - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-12, 1e-12, d00 * d11 - d01 * d01)
        l1 = (d11 * d20 - d01 * d21) / den
        l2 = (d00 * d21 - d01 * d20) / den
        bc = np.clip(np.stack([1 - l1 - l2, l1, l2], 1), 0, 1)
        bc /= np.maximum(bc.sum(1, keepdims=True), 1e-9)
        q = bc[:, :1] * a + bc[:, 1:2] * b + bc[:, 2:] * c
        dist = ((q - pts) ** 2).sum(1)
        better = dist < best_d
        best_d[better], best_t[better], best_bc[better] = dist[better], t[better], bc[better]
    uv = (best_bc[:, :, None] * src["UV"][best_t]).sum(1)
    uv0 = np.floor(src["UV"][best_t].min(1))
    uv = uv - uv0
    for mi in set(src["FM"][best_t].tolist()):
        sel = src["FM"][best_t] == mi
        m = mats[int(mi)]
        if m["tex"] is None:
            out[sel] = np.array(m["color"][:3], np.uint8)
            continue
        tex = np.asarray(m["tex"], np.uint8)
        H, W = tex.shape[:2]
        sx = np.floor(uv[sel, 0] * W).astype(int) % W
        sy = np.floor(uv[sel, 1] * H).astype(int) % H
        out[sel] = (tex[sy, sx, :3].astype(float) * (np.array(m["color"][:3], float) / 255)).astype(np.uint8)
    return out


def _bake_parts(parts: list, mats: list, tw: int, th: int, joints: list) -> tuple:
    """Parts sharing one texture -> (RGBA image, [(vp, vn, vu, faces)] per part). Each part gets its own tile and a
    cylindrical UV map around its long axis (continuous UVs = few duplicated vertices, which the engine counts);
    every texel takes the colour of the nearest point of the part's source surface."""
    k = len(parts)
    cols = max(1, int(round(np.sqrt(k * tw / th))))
    rows = int(np.ceil(k / cols))
    cw, ch = tw / cols, th / rows
    img = np.zeros((th, tw, 4), np.uint8)
    img[..., 3] = 255
    filled = np.zeros((th, tw), bool)
    out = []
    for pi, g in enumerate(parts):
        x0, y0 = (pi % cols) * cw, (pi // cols) * ch
        V, Nn, Fw = g["P"], g["N"], g["F"]
        if not len(Fw):
            out.append(([], [], [], []))
            continue
        c = V.mean(0)
        d = V - c
        _e, evecs = np.linalg.eigh(np.cov(d.T) + np.eye(3) * 1e-6)
        ax = evecs[:, 2]
        if ax[np.argmax(np.abs(ax))] < 0:
            ax = -ax
        b1 = np.cross(ax, [0, 0, 1.0]) if abs(ax[2]) < 0.9 else np.cross(ax, [1.0, 0, 0])
        b1 /= np.linalg.norm(b1)
        b2 = np.cross(ax, b1)
        t = d @ ax
        u0 = (np.arctan2(d @ b2, d @ b1) + np.pi) / (2 * np.pi)
        v0 = (t - t.min()) / max(np.ptp(t), 1e-6)
        corners, vp, vn, vu, faces = {}, [], [], [], []
        su, sv = (cw - 1.2) / 1.25, ch - 1.2
        pts_all, pix_all = [], []
        for f in Fw:
            us = u0[f].copy()
            if us.max() - us.min() > 0.5:                  # crosses the seam: shift the low side by one turn
                us = np.where(us < 0.5, us + 1, us)
            idx, px = [], []
            for cI in range(3):
                kk = (int(f[cI]), bool(us[cI] >= 1))
                uv = (x0 + 0.6 + us[cI] * su, y0 + 0.6 + v0[f[cI]] * sv)
                if kk not in corners:
                    corners[kk] = len(vp)
                    vp.append(V[f[cI]]); vn.append(Nn[f[cI]]); vu.append(np.array(uv))
                idx.append(corners[kk])
                px.append(uv)
            faces.append(idx)
            px = np.array(px)                              # texels inside this face -> 3D points on it
            lo = np.maximum(np.floor(px.min(0) - 0.5).astype(int), 0)
            hi = np.minimum(np.ceil(px.max(0) + 0.5).astype(int), [tw - 1, th - 1])
            if (hi < lo).any():
                continue
            xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1) + 0.5, np.arange(lo[1], hi[1] + 1) + 0.5)
            m = np.array([[px[1, 0] - px[0, 0], px[2, 0] - px[0, 0]], [px[1, 1] - px[0, 1], px[2, 1] - px[0, 1]]])
            if abs(np.linalg.det(m)) < 1e-9:
                continue
            inv = np.linalg.inv(m)
            dx, dy = xs - px[0, 0], ys - px[0, 1]
            l1, l2 = inv[0, 0] * dx + inv[0, 1] * dy, inv[1, 0] * dx + inv[1, 1] * dy
            bc = np.stack([1 - l1 - l2, l1, l2], -1)
            inside = (bc >= -0.2).all(-1) & ~filled[ys.astype(int), xs.astype(int)]
            if not inside.any():
                continue
            bcc = np.clip(bc[inside], 0, 1)
            bcc /= bcc.sum(1, keepdims=True)
            pts_all.append(bcc @ V[f])
            pix_all.append(np.stack([ys[inside].astype(int), xs[inside].astype(int)], 1))
            filled[ys[inside].astype(int), xs[inside].astype(int)] = True
        if pts_all:
            pts, pix = np.concatenate(pts_all), np.concatenate(pix_all)
            img[pix[:, 0], pix[:, 1], :3] = _sample_source(g["src"], pts, mats)
        out.append((vp, vn, vu, faces))
    for _ in range(8):                                     # bleed into the gaps (texel filtering at tile edges)
        if filled.all():
            break
        nb = np.zeros(img.shape, float)
        cnt = np.zeros(filled.shape, float)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sh_f = np.roll(np.roll(filled, dy, 0), dx, 1)
            nb += np.roll(np.roll(img, dy, 0), dx, 1) * sh_f[..., None]
            cnt += sh_f
        grow = (~filled) & (cnt > 0)
        img[grow] = (nb[grow] / cnt[grow][:, None]).astype(np.uint8)
        filled |= grow
    img[..., 3] = 255
    return img, out

def target_skeleton(rest: dict) -> dict:
    """tgt for sm64_swap.retarget: joint positions in rest space, identity rotations."""
    J = rest["joints"]
    names = JOINTS
    T = np.array([J[j] for j in names])
    allp = np.concatenate([m["pos"] for m in rest["parts"].values()])
    heads = np.concatenate([rest["parts"][o]["pos"] for o in rest["parts"] if PARTS[o][1] == "head"]) \
        if any(PARTS[o][1] == "head" for o in rest["parts"]) else None
    W = []
    for t in T:
        m = np.eye(4)
        m[3, :3] = t
        W.append(m)
    head_h = float(np.ptp(heads[:, 1])) if heads is not None else 26.0
    return {"T": T, "W": W, "parent": [names.index(JPARENT[j]) if JPARENT[j] else -1 for j in names],
            "ground": float(allp[:, 1].min()), "head_h": head_h, "joints": len(names)}


def fit_character(rom: bytes, model: Path, roles: dict, body_type: int, work: Path, name: str, props=(), scale=None,
                  blender: str | None = None, max_tris: int = 900, progress=lambda p, m: None) -> dict:
    """Library model -> {off: (model bytes, tex bytes, pal bytes)} for the 24 parts + the rigged preview glTF."""
    from .sm64_swap import load_rig, retarget, write_rigged, read_rigged
    from .re4gc_enemies import decimate
    ft = FileTable(rom)
    rest = rest_body(rom, body_type, ft)
    # head parts (rest space) from a typical male face so the head size/shape target is known
    for o, mid in ((0xA0, 0x140B), (0x28, 0x151C)):
        try:
            rest["parts"][o] = model_parse(ft.get(mid))
        except Exception:                                  # noqa: BLE001
            pass
    rest["joints"] = joints_from(rest["parts"])
    tgt = target_skeleton(rest)
    jmap = {j: i for i, j in enumerate(JOINTS)}
    progress(20, f"Retargeting {name} onto the wrestler skeleton")
    rig = load_rig(Path(model), roles, props)
    tris_src = sum(len(p["tris"]) for p in rig["prims"])
    prims, rep = retarget(rig, tgt, scale, {k: v for k, v in jmap.items() if k in
                                           ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
                                            "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")})
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rigged = write_rigged(prims, tgt, work / "aki_rigged.gltf", name)
    src = rigged
    if tris_src > 8000 and blender:                        # very dense sources: a first global pass
        progress(30, f"Decimating {tris_src} -> 8000 triangles (Blender)")
        src = decimate(rigged, work / "aki_dec.glb", 8000.0, blender)
    rp = read_rigged(src)
    progress(40, "Cutting the model into the wrestler's 24 parts")
    mats, mkey = [], {}
    allP, allN, allUV, allJ, F, FM = [], [], [], [], [], []
    base = 0
    for p in rp:
        key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        if key not in mkey:
            mkey[key] = len(mats)
            mats.append({"tex": p["tex"], "color": p["color"]})
        allP.append(p["pos"]); allN.append(p["nrm"]); allUV.append(p["uv"]); allJ.append(p["jid"])
        F.append(p["tris"] + base)
        FM.append(np.full(len(p["tris"]), mkey[key]))
        base += len(p["pos"])
    P, N, UV, JV = np.concatenate(allP), np.concatenate(allN), np.concatenate(allUV), np.concatenate(allJ)
    F, FM = np.concatenate(F), np.concatenate(FM)
    jn = np.array(JOINTS)
    fj = np.array([np.bincount(JV[f]).argmax() for f in F])
    cen = P[F].mean(1)
    J = rest["joints"]
    part = np.empty(len(F), object)                        # torso: hip / waist / chest by height, halves like the game's
    hip_y, chest_y, neck_y = J["waist"][1], J["chest"][1], J["neck"][1]
    limb = {v[1]: o for o, v in PARTS.items() if v[1] not in ("hip", "waist", "chest", "neck", "head")}
    for i, (j, c) in enumerate(zip(jn[fj], cen)):
        if j in ("hip", "chest"):
            j = "neck" if c[1] >= neck_y else "chest" if c[1] >= chest_y else "waist" if c[1] >= hip_y else "hip"
        if j == "hip":
            part[i] = 0xB0 if c[0] >= 0 else 0x08
        elif j == "waist":
            part[i] = 0x10 if c[2] >= J["waist"][2] else 0xB8
        elif j == "chest":
            part[i] = 0x18 if c[2] >= J["chest"][2] else 0xC0
        elif j == "neck":
            part[i] = 0x20
        elif j == "head":
            part[i] = 0xA0 if c[2] >= J["head"][2] else 0x28
        else:
            part[i] = limb[j]
    # per-part budget = the original part's size: a wrestler's vertex / face pools hold about what the game's own
    # parts need (~700 vertices / ~800 faces; more hangs the game at load)
    caps = {o: (max(len(m["pos"]), 12), max(len(m["faces"]), 12)) for o, m in rest["parts"].items()}
    part[np.array([o not in caps for o in part], bool)] = 0x28    # no such part in the game (hair): head back
    ids = rest["ids"]
    geo = _decimate_parts(P, N, UV, F, FM, part, mats, caps, work, blender, progress)
    out, report = {}, {}

    def gkey(o):                                           # texture groups like the game's (shared skin textures):
        if o == 0xA0:                                      # a wrestler's composited textures live in a fixed buffer,
            return "face"                                  # so the number of distinct textures must not grow
        if o in (0x28, 0xA8):
            return "head"
        if o == 0x20:
            return gkey(0x18)
        return ids[o][1] if o in ids and ids[o][1] else f"p{o}"
    groups = {}
    for o in geo:
        groups.setdefault(gkey(o), []).append(o)
    gtex = {}
    for g, members in groups.items():
        tw, th, mirror = 32, 64, (0, 0)
        if isinstance(g, int):
            try:
                tb = ft.get(g)
                tw, th = tb[0] + 1, tb[1] + 1
            except Exception:                              # noqa: BLE001
                pass
        img, parts_v = _bake_parts([geo[o] for o in members], mats, tw, th, [J.get(PARTS[o][1]) for o in members])
        gtex[g] = (img, (0, 0), tw, th)
        for o, (vp, vn, vu, faces) in zip(members, parts_v):
            cv, cf = caps[o]
            dropped = 0
            while len(vp) > min(MAX_V, cv) or len(faces) > min(MAX_F, cf):   # still over: drop the smallest faces
                area = [np.linalg.norm(np.cross(vp[f[1]] - vp[f[0]], vp[f[2]] - vp[f[0]])) for f in faces]
                faces.pop(int(np.argmin(area)))
                dropped += 1
                usedv = sorted({v for f in faces for v in f})
                remap = {v: i for i, v in enumerate(usedv)}
                vp = [vp[v] for v in usedv]; vn = [vn[v] for v in usedv]; vu = [vu[v] for v in usedv]
                faces = [[remap[v] for v in f] for f in faces]
            if not faces:
                continue
            texbyte = ((tw // 8) << 4) | (th // 8)
            mb = model_encode(np.array(vp), np.array(vn), np.array(vu), np.array(faces), texbyte)
            out[o] = (mb, g, None)
            report[PARTS[o][0]] = {"verts": len(vp), "faces": len(faces), "budget": [cv, cf], "dropped": dropped,
                                   "tex": f"{tw}x{th}", "texture_group": str(g)}
    # the engine hangs when a body part entry is empty: every part but the hair gets at least a hidden speck
    for o in PARTS:
        if o in out or o == 0xA8:
            continue
        g = gkey(o) if gkey(o) in gtex else next(iter(gtex))
        _img, _mir, tw, th = gtex[g]
        j = J.get(PARTS[o][1], J["chest"])
        vp = np.array([j, j + [0.6, 0, 0], j + [0, 0.6, 0]])
        out[o] = (model_encode(vp, np.tile([0, 0, 1.0], (3, 1)), np.zeros((3, 2)), np.array([[0, 1, 2]]),
                               ((tw // 8) << 4) | (th // 8)), g, None)
        report[PARTS[o][0]] = {"verts": 3, "faces": 1, "placeholder": True, "texture_group": str(g)}
    # one 256-colour palette for the whole character
    allpx = np.concatenate([v[0].reshape(-1, 4) for v in gtex.values()])[None]
    _idx, pal = quantize(allpx)
    c = pal.astype(np.uint16)
    v5 = ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 3) << 6) | ((c[:, 2] >> 3) << 1) | (c[:, 3] >= 128)
    pal_file = v5.astype(">u2").tobytes().ljust(512, b"\0")
    pc = pal[:, :3].astype(int)
    textures = {}
    for g, (im, mirror, w, h) in gtex.items():
        px = im.reshape(-1, 4)[:, :3].astype(int)
        idx = ((px[:, None] - pc[None]) ** 2).sum(2).argmin(1).astype(np.uint8)
        textures[g] = struct.pack(">BBHBBBB", w - 1, h - 1, 256, mirror[0], mirror[1], int(np.log2(w)), int(np.log2(h))) + idx.tobytes()
    return {"parts": out, "textures": textures, "palette": pal_file, "rigged": rigged, "report": {"retarget": rep, "parts": report, "source_triangles": tris_src,
                                                       "triangles": sum(v["faces"] for v in report.values())}}


NAMES_FID = 2                    # No Mercy: u16 offsets (big-endian) then the strings, 3 per name slot k at entries
                                 # 3k..3k+2: full name (Superstar Select), short name (HUD), nickname ("STONE COLD").
                                 # Slots follow the roster but also hold alternate names (THE GOODFATHER, FUNAKI, HO...),
                                 # so a wrestler's slot is found by his name.


def ring_names(rom: bytes) -> list[str | None]:
    """File 2's strings in table order (None = an unused, zero table entry)."""
    d = FileTable(rom).get(NAMES_FID)
    first = struct.unpack_from(">H", d, 0)[0]
    offs = struct.unpack_from(f">{first // 2}H", d, 0)
    return [d[o:d.index(b"\0", o)].decode("latin-1") if o else None for o in offs]


def short_name(name: str) -> str:
    w = [x for x in re.split(r"\s+", name.strip()) if x.lower().rstrip(".") not in ("dr", "the", "mr", "miss")]
    return (w[0] if w else name)[:12]


def name_slot(strs: list, wrestler: str) -> int:
    """The name slot of a default wrestler (by his name: "Scotty 2 Hotty" = SCOTTY TOO HOTTY)."""
    import difflib
    norm = lambda x: re.sub(r"[^A-Z0-9]", "", (x or "").upper().replace(" 2 ", " TOO "))
    want = norm(wrestler)
    cands = [(0.99 if len(norm(strs[3 * k])) >= 4 and len(want) >= 4 and (want.startswith(norm(strs[3 * k])) or norm(strs[3 * k]).startswith(want))
              else difflib.SequenceMatcher(None, want, norm(strs[3 * k])).ratio(), k) for k in range(1, len(strs) // 3)
             if strs[3 * k]]
    r, k = max(cands)
    if r < 0.75:
        raise LookupError(f"no name slot for {wrestler!r}")
    return k


def set_ring_names(wr: "NMWriter", names: dict[str, tuple[str, str]]) -> dict:
    """{default wrestler name: (full, short)} -> file 2 rebuilt (offset table + strings) and written in place."""
    strs = ring_names(wr.rom)
    def clean(x):
        return re.sub(r"[^A-Z0-9 .'&-]", "", x.upper().encode("ascii", "ignore").decode())[:16]
    out = {}
    for who, (full, short) in names.items():
        try:
            n = name_slot(strs, who)
        except LookupError:
            out[who] = None
            continue
        strs[3 * n], strs[3 * n + 1], strs[3 * n + 2] = clean(full), clean(short), ""
        out[who] = strs[3 * n]
    head = len(strs) * 2
    body, offs = bytearray(), []
    for x in strs:
        if x is None:
            offs.append(0)
            continue
        offs.append(head + len(body))
        body += x.encode("latin-1") + b"\0"
    orig = wr.ft.get(NAMES_FID)
    data = struct.pack(f">{len(offs)}H", *offs) + bytes(body)
    data += bytes(max(0, len(orig) - len(data)))
    wr.replace_file(NAMES_FID, data)
    return out


def build_rom(rom: bytes, jobs: list[dict], work: Path, blender=None, progress=lambda p, m: None, **kw) -> dict:
    """jobs: [{wrestler (number), model, roles, name, props, scale, ring_name?}] -> {rom, reports}. ring_name (default
    the character's name; False = keep) replaces the wrestler's name on Superstar Select (skipped if it won't fit)."""
    wr = NMWriter(rom)
    ros = roster(rom)
    reports = []
    try:
        renamed = set_ring_names(wr, {ros[jb["wrestler"] - 1]["name"]: (jb.get("ring_name") or jb["name"],
                                                                       short_name(jb.get("ring_name") or jb["name"]))
                                      for jb in jobs if jb.get("ring_name", True)})
    except Exception as e:                                 # noqa: BLE001 - names are cosmetic
        renamed = {"error": str(e)}
    for k, jb in enumerate(jobs):
        w = ros[jb["wrestler"] - 1]
        body = w["body"][0]
        fit = fit_character(rom, jb["model"], jb["roles"], body, Path(work) / f"w{w['number']}", jb["name"],
                            jb.get("props", ()), jb.get("scale"), blender,
                            progress=lambda p, m, k=k: progress(5 + (k * 80 + p * 0.8) / max(1, len(jobs)), m))
        entries = {}
        pal = wr.add_file(fit["palette"])
        tex_id = {g: wr.add_file(tb) for g, tb in fit["textures"].items()}
        for o, (mb, g, _pb) in fit["parts"].items():
            tex = tex_id[g]
            mid = wr.add_file(mb)
            entries[o] = (mid, tex, pal, 0x00FF if o not in (0xA0, 0x28, 0xA8, 0x20) else 0)
        keys = w["face_tex"]
        others = {k2 for x in ros if x["number"] != w["number"] for k2 in x["face_tex"]}
        wr.add_template(keys, entries)
        reports.append({"wrestler": w["name"], "number": w["number"], "character": jb["name"], "keys": [hex(x) for x in keys],
                        "shared_faces": [x["name"] for x in ros if x["number"] != w["number"] and set(x["face_tex"]) & set(keys)],
                        "rigged": str(fit["rigged"]), **fit["report"]})
    progress(90, "Writing the ROM (file table moved to the end, hook installed)")
    return {"rom": wr.build(**kw), "reports": reports, "writer": wr, "names": renamed}


# ---------------------------------------------------------------- extraction from a running game (exact textures)

def _gfx_tasks(ram: bytes) -> list[int]:
    """OSTask structs (type 1 = graphics) -> their display list addresses."""
    out = []
    for o in range(0, min(len(ram), 0x400000) - 64, 8):
        t, _f, ub, ubs, uc, ucs = struct.unpack_from(">6I", ram, o)
        if t == 1 and ub >> 24 == 0x80 and 0 < ubs < 0x1000 and uc >> 24 == 0x80 and ucs == 0x1000:
            dp = struct.unpack_from(">I", ram, o + 48)[0]
            if dp >> 24 == 0x80:
                out.append(dp)
    return out


def _walk(ram: bytes, start: int, out: list, depth=0):
    pc = start & 0x7FFFFF
    for _ in range(200000):
        if pc + 8 > len(ram) or (start >> 24) not in (0x00, 0x80):
            return
        w0, w1 = struct.unpack_from(">II", ram, pc)
        op = w0 >> 24
        out.append((op, w0, w1))
        if op == 0xDE:
            if (w0 >> 16) & 0xFF == 1:
                pc = w1 & 0x7FFFFF
                continue
            if depth < 12:
                _walk(ram, w1, out, depth + 1)
        elif op == 0xDF:
            return
        pc += 8


def capture_textures(ram: bytes, rom: bytes, slot: int = 0) -> dict:
    """The composited CI8 texture of each part of the wrestler in `slot`, read from the frame's display list:
    a draw block = forced matrix + vertex loads (the part's own vertices first) + texture loads + triangles.
    -> {part offset: RGBA (h, w, 4)}."""
    ft = FileTable(rom)
    pl = ram[(PARTLIST & 0x7FFFFF) + 0x270 * slot:][:0x270]
    keys = {}
    for o in PARTS:
        m = struct.unpack_from(">H", pl, o)[0]
        if not m:
            continue
        try:
            d = ft.get(m)
        except Exception:                                  # noqa: BLE001
            continue
        nv = d[1] & 0x7F
        off = np.array(struct.unpack_from("3b", d, 4)) * 16
        keys[o] = {(int(d[8 + 8 * i]) - 256 * (d[8 + 8 * i] > 127) + off[0], int(d[9 + 8 * i]) - 256 * (d[9 + 8 * i] > 127) + off[1],
                    int(d[10 + 8 * i]) - 256 * (d[10 + 8 * i] > 127) + off[2], d[13 + 8 * i], d[14 + 8 * i], d[15 + 8 * i]) for i in range(nv)}
    out = {}
    for task in _gfx_tasks(ram):
        cmds = []
        _walk(ram, task, cmds)
        groups, pal, tex, tile = [], None, None, None
        for op, w0, w1 in cmds:
            if op == 0x01:
                n, a = (w0 >> 12) & 0xFF, w1 & 0x7FFFFF
                if w1 >> 24 not in (0x00, 0x80) or a + 16 * n > len(ram):
                    continue                               # segmented / out of range: not a wrestler part
                vs = {struct.unpack_from(">hhh", ram, a + 16 * k) + tuple(ram[a + 16 * k + 12:a + 16 * k + 15]) for k in range(n)}
                groups.append(vs)
            elif op == 0xFD:
                fmt = (w0 >> 21) & 7
                if fmt == 0:
                    pal = w1 & 0x7FFFFF
                else:
                    tex = w1 & 0x7FFFFF
            elif op == 0xF2:
                tile = (((w1 >> 12) & 0xFFF) >> 2) + 1, ((w1 & 0xFFF) >> 2) + 1
            elif op in (0x05, 0x06) and groups and pal is not None and tex is not None and tile:
                best, bo = 0, None
                for o, kset in keys.items():
                    hit = len(groups[0] & kset)
                    if hit > best:
                        best, bo = hit, o
                if bo is not None and bo not in out and best >= min(3, len(groups[0])):
                    w, h = tile
                    if w * h <= 4096 and tex + w * h <= len(ram) and pal + 512 <= len(ram):
                        idx = np.frombuffer(ram, np.uint8, w * h, tex).reshape(h, w)
                        p = rgba5551(np.frombuffer(ram, ">u2", 256, pal))
                        out[bo] = p[idx]
                groups = []
        if out:
            break
    return out


def extract_from_ram(ram: bytes, rom: bytes, out: Path, name: str, slot: int = 0) -> dict:
    """The wrestler in `slot` of a running No Mercy (big-endian RDRAM) -> rest-pose skinned glTF with body roles."""
    pl = ram[(PARTLIST & 0x7FFFFF) + 0x270 * slot:][:0x270]
    plist = {o: list(struct.unpack_from(">3H", pl, o)) for o in PARTS if struct.unpack_from(">H", pl, o)[0]}
    if not plist:
        raise LookupError(f"no wrestler loaded in slot {slot}")
    tex = capture_textures(ram, rom, slot)
    r = to_glb(rom, plist, out, name, textures=tex)
    r["captured_textures"] = len(tex)
    return r


def extract_static(rom: bytes, wrestler: int, out: Path, name: str, costume: int = 0) -> dict:
    """No running game: body + head from the ROM tables with the base (skin) textures; attire layers, which the game
    composites at load, are not applied."""
    plist = part_list_static(rom, wrestler, costume)
    cs = costumes(rom)[4 * (wrestler - 1) + costume]
    # head model: the face model of the costume's head shape (first entry of its table), else a typical male face
    plist.setdefault(0xA0, [0x140B, 0, 0])
    if not plist[0xA0][0]:
        plist[0xA0][0] = 0x140B
    plist[0x28] = [0x151C, 0x1F6C, 0x1F6B]
    return to_glb(rom, plist, out, name)


# ---------------------------------------------------------------- runtime (identify)

SLOT_WRESTLER = 0x80076264       # s16 per slot (in-match player index) = wrestler number
PARTLIST = 0x800A8980            # 0x270 per slot


def identify(read, rom: bytes) -> list[dict]:
    """read(addr, n) -> bytes (big-endian RDRAM). -> wrestlers in slots 0..3 by their part list's face texture."""
    ros = roster(rom)
    by_face = {}
    for w in ros:
        for k in w["face_tex"]:
            by_face.setdefault(k, w)
    m = modded(rom)
    for key, t in (m or {}).get("templates", {}).items():  # a gBox mod: the character's face texture -> the wrestler
        if key in by_face:
            by_face.setdefault(struct.unpack_from(">H", t, 0xA2)[0], by_face[key] | {"replaced": True})
    out = []
    for s in range(4):
        pl = read(PARTLIST + 0x270 * s, 0xC8)
        face = struct.unpack_from(">H", pl, 0xA2)[0]
        body = struct.unpack_from(">H", pl, 0x08)[0]
        if not body:
            continue
        w = by_face.get(face)
        out.append({"slot": s, "player": s + 1, "wrestler": w["name"] if w else None,
                    "number": w["number"] if w else None, "face_tex": hex(face),
                    **({"replaced_by_gbox": True} if w and w.get("replaced") else {})})
    return out


def slots_on_screen(ram: bytes, rom: bytes) -> list[dict]:
    """Each loaded slot's screen box (fractions of the picture) from its parts' forced MVP matrices in the frame's
    display list: [{slot, wrestler, number, box (x0, y0, x1, y1), centre}]."""
    ft = FileTable(rom)
    keys = []
    for sl in range(4):
        pl = ram[(PARTLIST & 0x7FFFFF) + 0x270 * sl:][:0x270]
        for o in PARTS:
            m = struct.unpack_from(">H", pl, o)[0]
            if not m:
                continue
            try:
                d = ft.get(m)
            except Exception:                              # noqa: BLE001
                continue
            nv = d[1] & 0x7F
            off = np.array(struct.unpack_from("3b", d, 4)) * 16
            V = np.frombuffer(d, np.int8, nv * 8, 8).reshape(nv, 8)
            keys.append((sl, {(int(v[0]) + off[0], int(v[1]) + off[1], int(v[2]) + off[2]) for v in V}))
    pts = {sl: [] for sl in range(4)}
    for task in _gfx_tasks(ram):
        cmds = []
        _walk(ram, task, cmds)
        mtx = None
        for op, w0, w1 in cmds:
            if op == 0xDC and (w0 & 0xFF) == 0x0E and (w1 & 0x7FFFFF) + 64 <= len(ram):
                a = w1 & 0x7FFFFF
                i = np.array(struct.unpack_from(">16h", ram, a), float)
                f = np.array(struct.unpack_from(">16H", ram, a + 32), float)
                mtx = (i + f / 65536).reshape(4, 4)
            elif op == 0x01 and mtx is not None and w1 >> 24 in (0x00, 0x80) and (w1 & 0x7FFFFF) + 16 * ((w0 >> 12) & 0xFF) <= len(ram):
                n, a = (w0 >> 12) & 0xFF, w1 & 0x7FFFFF
                vs = [struct.unpack_from(">hhh", ram, a + 16 * k) for k in range(n)]
                best, bs = 0, None
                for sl, kset in keys:
                    hit = sum(v in kset for v in vs)
                    if hit > best:
                        best, bs = hit, sl
                if bs is not None and best >= max(3, n // 2):
                    c = np.c_[np.array(vs, float), np.ones(n)] @ mtx
                    c = c[c[:, 3] > 1e-3]
                    if len(c):
                        pts[bs].append(c[:, :2] / c[:, 3:4])
        if any(pts.values()):
            break
    who = {x["slot"]: x for x in identify(lambda a, n: ram[(a & 0x7FFFFF):(a & 0x7FFFFF) + n], rom)}
    out = []
    for sl, ps in pts.items():
        if not ps:
            continue
        q = np.concatenate(ps)
        x = (q[:, 0] + 1) / 2
        y = (1 - q[:, 1]) / 2
        box = (float(x.min()), float(y.min()), float(x.max()), float(y.max()))
        w = who.get(sl, {})
        out.append({"slot": sl, "player": sl + 1, "wrestler": w.get("wrestler"), "number": w.get("number"),
                    "box": [round(v, 3) for v in box], "centre": [round(float(np.median(x)), 3), round(float(np.median(y)), 3)]})
    return out


def slot_at(ram: bytes, rom: bytes, x: float, y: float) -> dict | None:
    hits = [s for s in slots_on_screen(ram, rom) if s["box"][0] <= x <= s["box"][2] and s["box"][1] <= y <= s["box"][3]]
    if not hits:
        return None
    return min(hits, key=lambda s: (s["box"][2] - s["box"][0]) * (s["box"][3] - s["box"][1]))


def extract_cmd(ctx, game: dict, inp, root: Path) -> dict:
    """characters op=extract for No Mercy with a session and a picture point (or "player"): the wrestler there,
    with the exact composited textures."""
    from . import characters as C
    rom = session_rom(ctx, game, C._session(ctx, inp.session_id))
    ram = _session_ram(ctx, inp.session_id)
    if inp.x is not None and inp.y is not None:
        s = slot_at(ram, rom, inp.x, inp.y)
        if not s:
            raise LookupError(f"no wrestler at ({inp.x:.2f}, {inp.y:.2f}); on screen: {slots_on_screen(ram, rom)}")
        slot = s["slot"]
    else:
        ws = identify(lambda a, n: ram[(a & 0x7FFFFF):(a & 0x7FFFFF) + n], rom)
        q = (inp.character or "").lower()
        hit = next((w for w in ws if w["wrestler"] and q and q in w["wrestler"].lower()), None) or \
            next((w for w in ws if w["slot"] == 0), None)
        if not hit:
            raise LookupError("no wrestler loaded in this session")
        slot = hit["slot"]
    m = add_from_ram(root, rom, ram, game, slot, Path(ctx.config.cache) / "characters_build" / "extract" / "nomercy")
    return {"status": "extracted", "route": "dedicated:nomercy (session RAM)", "entry": C._brief(m)}


class PrivateN64:
    """A headless RetroArch (parallel_n64) on its own Xvfb display and UDP port, outside gBox's sessions (Linux control
    plane only): used to load a wrestler on Superstar Select and read the frame's composited textures."""
    KEYS = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "x", "b": "z", "l": "q", "r": "w",
            "start": "Return"}

    def __init__(self, cfg, disp: int = 131, port: int = 55131):
        import os
        self.cfg, self.disp, self.port = cfg, f":{disp}", port
        self.env = {**os.environ, "DISPLAY": self.disp}
        self.work = Path(cfg.cache) / "aki_private"
        self.work.mkdir(parents=True, exist_ok=True)

    def start(self, rom: Path):
        import subprocess
        rt = Path(self.cfg.runtime)
        conf = self.work / f"ra_{self.port}.cfg"
        lines = {"system_directory": rt / "system", "savefile_directory": self.work / "saves", "savestate_directory": self.work / "states",
                 "network_cmd_enable": "true", "network_cmd_port": self.port, "config_save_on_exit": "false",
                 "pause_nonactive": "false", "video_driver": "gl", "audio_driver": "null", "menu_driver": "rgui",
                 "video_fullscreen": "true", "video_windowed_fullscreen": "true", "input_driver": "x",
                 "core_options_path": rt / "retroarch" / "core-options.cfg", "global_core_options": "true",
                 "input_player1_up": "up", "input_player1_down": "down", "input_player1_left": "left", "input_player1_right": "right",
                 "input_player1_a": "x", "input_player1_b": "z", "input_player1_l": "q", "input_player1_r": "w",
                 "input_player1_start": "enter", "video_font_enable": "false", "rewind_enable": "false"}
        (self.work / "saves").mkdir(exist_ok=True)
        conf.write_text("".join(f'{k} = "{v}"\n' for k, v in lines.items()))
        self.stop()
        subprocess.Popen(["Xvfb", self.disp, "-screen", "0", "960x720x24", "+extension", "GLX", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.5)
        self.proc = subprocess.Popen([str(rt / "retroarch-bin" / "retroarch"), "--config", str(conf), "-L",
                                      str(rt / "cores" / "parallel_n64_libretro.so"), str(rom)], env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def stop(self):
        import subprocess
        subprocess.run(["pkill", "-f", f"ra_{self.port}.cfg"], check=False)
        subprocess.run(["pkill", "-f", f"Xvfb {self.disp}"], check=False)

    def _cmd(self, c: str) -> str:
        import socket
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.settimeout(3)
        sk.sendto(c.encode(), ("127.0.0.1", self.port))
        try:
            return sk.recv(65536).decode()
        finally:
            sk.close()

    def read(self, a: int, n: int) -> bytes:
        out = bytearray()
        for o in range(0, n, 16384):
            k = min(16384, n - o)
            r = self._cmd(f"READ_CORE_MEMORY {a + o:x} {k}").split()
            if len(r) < 3 or r[2] == "-1":
                raise RuntimeError("private RetroArch memory read failed")
            out += bytes(int(b, 16) for b in r[2:])
        return np.frombuffer(bytes(out), "<u4").astype(">u4").tobytes()      # word-swapped -> big-endian

    def write(self, a: int, data: bytes):
        data = data + bytes((-len(data)) % 4)
        raw = np.frombuffer(data, ">u4").astype("<u4").tobytes()
        for o in range(0, len(raw), 512):
            self._cmd(f"WRITE_CORE_MEMORY {a + o:x} " + " ".join(f"{b:02x}" for b in raw[o:o + 512]))

    def keys(self, seq):
        import subprocess
        for k in seq:
            if k.startswith("w"):
                time.sleep(float(k[1:]))
                continue
            x = self.KEYS[k]
            subprocess.run(["xdotool", "keydown", x], env=self.env, check=False)
            time.sleep(0.06)
            subprocess.run(["xdotool", "keyup", x], env=self.env, check=False)
            time.sleep(0.5)

    def shot(self, path: Path):
        import subprocess
        subprocess.run(["import", "-window", "root", str(path)], env=self.env, check=False)


ROSTER_PTR = 0x80047E90          # -> per-wrestler costume records (4 x 0x4E bytes, packed costume at +0x31)


def capture_wrestlers(cfg, rom_file: Path, numbers: list[int], progress=lambda p, m: None) -> dict:
    """Boot the original ROM headless, go to Exhibition > 1P vs CPU > Superstar Select (cursor on The Rock), and for
    each wrestler copy his four costume records over The Rock's, re-hover, read RDRAM. -> {number: (ram (4 MB), slot)}."""
    import tempfile
    rom = rom_bytes(rom_file)
    tmp = Path(tempfile.mkdtemp(prefix="aki_")) / "nm.z64"
    tmp.write_bytes(rom)
    ra = PrivateN64(cfg)
    out = {}
    try:
        ra.start(tmp)
        progress(10, "Booting No Mercy headless (private emulator, not a session)")
        time.sleep(24)
        ra.keys(["start", "w2", "start", "w3", "b", "w3", "b", "w3", "r", "w2", "down", "w1", "b", "w2", "start", "w5"])
        base = struct.unpack(">I", ra.read(ROSTER_PTR, 4))[0]
        if base >> 24 != 0x80:
            raise RuntimeError("Superstar Select not reached (roster pointer unset)")
        rock = ra.read(base + 0x138, 0x138)
        for k, n in enumerate(numbers):
            progress(20 + 70 * k / max(1, len(numbers)), f"Loading wrestler {n} on Superstar Select")
            ra.write(base + 0x138, ra.read(base + 0x138 * n, 0x138))
            ra.keys(["right", "w1.5", "left", "w3"])
            ram = ra.read(0x80000000, 0x800000)
            want = roster(rom)[n - 1]["face_tex"]
            faces = [struct.unpack_from(">H", ram, (PARTLIST & 0x7FFFFF) + 0x270 * sl + 0xA2)[0] for sl in range(2)]
            slot = next((sl for sl, f in enumerate(faces) if f in want), None)
            if slot is None:
                raise RuntimeError(f"wrestler {n} did not load (face textures {[hex(f) for f in faces]}, expected {[hex(x) for x in want]})")
            out[n] = (ram, slot)
        ra.write(base + 0x138, rock)
    finally:
        ra.stop()
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return out


# ---------------------------------------------------------------- gBox: collection, characters op=use / match / extract

def slug_of(name: str) -> str:
    return "nm_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def roster_entries(rom: bytes | None = None) -> list[dict]:
    """characters.DEDICATED roster (No Mercy default wrestlers)."""
    out = []
    for i, n in enumerate(NM_ROSTER[:64]):
        out.append({"key": i + 1, "slug": slug_of(n), "name": n, "aliases": NM_ALIASES.get(n, []) + [f"No Mercy {n}"],
                    "kind": "character"})
    return out


def find_wrestler(rom: bytes, query: str) -> dict:
    from .characters import best_match
    ros = roster(rom)
    q = str(query).strip()
    if q.isdigit() and 1 <= int(q) <= len(ros):
        return ros[int(q) - 1]
    hit = best_match([{"name": w["name"], "aliases": w["aliases"], "slug": slug_of(w["name"]), "number": w["number"]}
                      for w in ros], q)
    if not hit:
        raise LookupError(f"no No Mercy wrestler matches {query!r}")
    return ros[hit["number"] - 1]


def session_rom(ctx, game: dict, sess: dict | None) -> bytes:
    """The ROM a session runs: its gBox mod image when it has one (new file ids live there), else the catalog ROM."""
    from . import characters as C, filemods
    if sess and sess.get("mod"):
        d = filemods.mod_dir(ctx.config, game["game_id"], sess["mod"])
        mj = d / ".gbox-mod.json"
        if mj.exists():
            img = d / json.loads(mj.read_text()).get("image", "")
            if img.is_file():
                return rom_bytes(img)
    return rom_bytes(C._rom(ctx, game))


def _session_ram(ctx, sid: str) -> bytes:
    """4 MB of a running No Mercy session's RDRAM, big-endian (RetroArch reads N64 RAM word-swapped)."""
    from .characters import _api, _job
    j = _job(ctx, "read_memory", {"session_id": sid, "address": 0x80000000, "length": 0x400000}, None, 600)
    if j.get("state") != "succeeded":
        raise RuntimeError(f"read_memory {j.get('state')}: {j.get('error')}")
    import httpx
    r = httpx.get(f"{ctx.server}/api/artifacts/{j['output']['sha256']}", headers=ctx.headers, timeout=120)
    r.raise_for_status()
    d = r.content
    if d[0x400:0x404] != b"\x3c\x08\x80\x05":                  # boot code at 0x80000400 reads backwards: swap words
        d = np.frombuffer(d, "<u4").astype(">u4").tobytes()
    return d


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run: a running No Mercy session of this game -> exact composited textures of that
    wrestler (when he's loaded in a slot), else the ROM's body + head with the skin textures."""
    from .characters import _rom, _session
    rom = rom_bytes(_rom(ctx, game))
    w = roster(rom)[e["key"] - 1]
    out = Path(work) / f"{e['slug']}.gltf"
    sess = None
    try:
        sess = next((s for s in ctx_sessions(ctx) if s.get("game_id") == game["game_id"] and s.get("state") == "running"), None)
    except Exception:                                      # noqa: BLE001
        sess = None
    how = "static"
    if sess:
        try:
            ram = _session_ram(ctx, sess["session_id"])
            slots = [x for x in identify(lambda a, n: ram[(a & 0x7FFFFF):(a & 0x7FFFFF) + n], rom) if x["number"] == w["number"]]
            if slots:
                r = extract_from_ram(ram, rom, out, w["name"], slots[0]["slot"])
                how = f"session {sess['session_id']} slot {slots[0]['slot']} (composited textures)"
        except Exception:                                  # noqa: BLE001
            how = "static"
    if how == "static":
        try:
            ram, slot = capture_wrestlers(ctx.config, _rom(ctx, game), [w["number"]], ctx.progress)[w["number"]]
            r = extract_from_ram(ram, rom, out, w["name"], slot)
            how = "Superstar Select in a private headless emulator (composited textures)"
        except Exception as ex:                            # noqa: BLE001 - no Xvfb/RetroArch here: ROM parts only
            ctx.log.append(f"private capture failed: {ex}")
            r = extract_static(rom, w["number"], out, w["name"])
    return {"files": [out], "tool": "gbox.aki_wrestling", "roles": r["roles"],
            "source_files": [f"FileTable models/textures of wrestler {w['number']} ({how})"],
            "notes": "AKI rest pose (arms down); one rigid joint per body part" +
                     ("" if how != "static" else "; attire layers not composited (extract from a running session for the exact look)")}


def ctx_sessions(ctx) -> list:
    from .characters import _api
    return _api(ctx, "GET", "/api/sessions")


def add_from_ram(root: Path, rom: bytes, ram: bytes, game: dict, slot: int, work: Path) -> dict:
    """A wrestler loaded in a running game's slot -> collection entry (used for the starter set and op=extract
    with a session)."""
    from . import characters as C
    who = [x for x in identify(lambda a, n: ram[(a & 0x7FFFFF):(a & 0x7FFFFF) + n], rom) if x["slot"] == slot]
    if not who or not who[0]["number"]:
        raise LookupError(f"slot {slot}: no default wrestler recognised")
    w = roster(rom)[who[0]["number"] - 1]
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{slug_of(w['name'])}.gltf"
    r = extract_from_ram(ram, rom, out, w["name"], slot)
    return C.add(root, slug_of(w["name"]), w["name"], [out],
                 {"game_title": game["title"], "game_id": game["game_id"], "platform": "n64",
                  "files": [f"FileTable parts of wrestler {w['number']} + the composited textures of a running game"]},
                 "gbox.aki_wrestling (extract_from_ram)", rig={"roles": r["roles"]}, aliases=w["aliases"] + [f"No Mercy {w['name']}"],
                 notes="WWF No Mercy wrestler in AKI's rest pose (arms down); 19 rigid joints, one per body part")


def mod_name(pairs: list[tuple[dict, dict]], title: str | None = None) -> str:
    if title and len(pairs) > 2:                           # a whole roster: name it after the card title
        t = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        return "nomercy_" + re.sub(r"^(wwf_)?no_mercy_", "", t)[:48].strip("_")
    if len(pairs) == 1:
        return f"nomercy_{pairs[0][0]['slug']}_as_{slug_of(pairs[0][1]['name'])[3:]}"
    return "nomercy_" + "_vs_".join(m["slug"].replace("melee_", "") for m, _w in pairs)


def build_mod(cfg, game: dict, pairs: list[tuple[dict, dict]], progress=lambda p, m: None, root: Path | None = None,
              title: str | None = None) -> dict:
    """[(character meta, wrestler)] -> file mod (one ROM) under cache/mods/<game_id>/<name>; rigged previews into each
    character's targets/."""
    from . import characters as C, filemods
    from .models import CatalogEntry
    from .tools import rom_path
    root = root or C.library_root(cfg)
    gid = game["game_id"]
    rom_file = rom_path(CatalogEntry.model_validate(game), cfg)
    progress(3, f"Reading {rom_file.name}")
    rom = rom_bytes(rom_file)
    jobs = []
    for meta, w in pairs:
        roles = (meta.get("rig") or {}).get("roles") or {}
        if "hip" not in roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't map it onto a wrestler")
        jobs.append({"wrestler": w["number"], "model": root / meta["slug"] / meta["model"], "roles": roles, "name": meta["name"],
                     "props": [p["node"] for p in meta.get("props") or []], "scale": (meta.get("rig") or {}).get("scale")})
    name = mod_name(pairs, title)
    work = Path(cfg.cache) / "characters_build" / name
    shutil.rmtree(work, ignore_errors=True)
    from .sm64_swap import _blender
    b = build_rom(rom, jobs, work, _blender(cfg), progress)
    previews = []
    for (meta, w), rep in zip(pairs, b["reports"]):
        tdir = root / meta["slug"] / "targets"
        tdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rep["rigged"], tdir / "nomercy_wrestler.gltf")
        try:
            previews.append(str(C.render_preview(tdir / "nomercy_wrestler.gltf", tdir / "nomercy_preview.png")))
        except Exception:                                  # noqa: BLE001
            pass
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    img = "WWF No Mercy - " + re.sub(r"[^\w .()'-]+", "", title or " vs ".join(m["name"] for m, _w in pairs)).strip() + " (USA).z64"
    (d / img).write_bytes(b["rom"])
    mj = {"name": name, "game_id": gid, "image": img, "title": title or " vs ".join(m["name"] for m, _w in pairs),
          "files": ["@image: wrestler models (gbox.aki_wrestling)"], "built": time.time(),
          "characters": [m["slug"] for m, _w in pairs], "replaces": [w["name"] for _m, w in pairs],
          "triangles": [r["triangles"] for r in b["reports"]]}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    stale = Path(cfg.cache) / gid / img
    if stale.exists():
        stale.unlink()
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img, "previews": previews,
            "reports": [{k: v for k, v in r.items() if k != "rigged"} for r in b["reports"]]}


def _player1(ctx, sess, rom) -> dict | None:
    try:
        ram = _session_ram(ctx, sess["session_id"])
        ws = identify(lambda a, n: ram[(a & 0x7FFFFF):(a & 0x7FFFFF) + n], rom)
        hit = next((x for x in ws if x["slot"] == 0 and x["number"]), None)
        return roster(rom)[hit["number"] - 1] if hit else None
    except Exception:                                      # noqa: BLE001
        return None


def use(ctx, meta: dict, game: dict, inp, pairs: list | None = None, title: str | None = None) -> dict:
    """characters op=use / op=match for No Mercy: the wrestler slot = inp.slot (a wrestler's name or number; "player"
    = player 1's wrestler in the session, else The Rock), build the ROM on the control plane, launch it."""
    from . import characters as C
    from .models import CatalogEntry
    from .tools import rom_path
    gid = game["game_id"]
    from . import aki_wcw
    if gid in aki_wcw.GAME_IDS:                            # WCW vs. nWo: World Tour: its own writer (gbox.aki_wcw)
        return aki_wcw.use(ctx, meta, game, inp, pairs, title)
    if gid not in NO_MERCY or gid != "23a346e48b6368a6":
        return {"status": "missing", "missing": needs(game), "message": needs(game)["have"]}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    if not C.library_root(ctx.config).is_dir():           # not the control plane: build there, launch here
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        args = {"op": inp.op, "character": inp.character, "game_id": gid, "slot": inp.slot, "rebuild": inp.rebuild,
                "launch": False, "a": inp.a, "b": inp.b, "pairs": inp.pairs, "title": inp.title}
        j = C._job(ctx, "characters", args, cp, 2400)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        name = r["mod"]
        built = r.get("build")
    else:
        rom = rom_bytes(rom_path(CatalogEntry.model_validate(game), ctx.config))
        if pairs is None:
            if inp.slot and inp.slot != "player":
                w = find_wrestler(rom, inp.slot)
            else:
                w = (_player1(ctx, sess, rom) if sess and sess.get("game_id") == gid else None) or roster(rom)[0]
            pairs = [(meta, w)]
        name = mod_name(pairs, title)
        from . import filemods
        have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
        built = None
        if inp.rebuild or not have:
            built = build_mod(ctx.config, game, pairs, ctx.progress, title=title)
            for m, w in pairs:
                C._api(ctx, "POST", f"/api/characters/{m['slug']}/targets",
                       json={"game_id": gid, "slot": w["name"], "mod": name, "nodes": [C.HOST_OS],
                             "notes": f"replaces {w['name']} (all costumes; the game's skeleton, moves and grapples); "
                                      "preview targets/nomercy_preview.png"})
    res = {"mod": name, "build": built, "replaces": ", ".join(f"{w['name']} -> {m['name']}" for m, w in (pairs or []))}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(92, f"Launching WWF No Mercy (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    from .sm64_swap import _wait
    lj = _wait(ctx, lj, 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"WWF No Mercy is running with {res['replaces']} (mod {name}). Pick the replaced wrestler(s) on Superstar "
           "Select (every costume of theirs is the new character). A brand-new save is needed if the cart's save already "
           "holds edited wrestlers." if ok else f"Mod {name} built but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else "built, launch failed", "launch": launch,
                  "message": msg}


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]], title: str | None = None) -> dict:
    """op=match: several (character, wrestler slot) pairs in one ROM."""
    from . import aki_wcw
    if game["game_id"] in aki_wcw.GAME_IDS:
        return aki_wcw.match(ctx, chars, game, inp, pairs_in, title)
    from .models import CatalogEntry
    from .tools import rom_path
    rom = rom_bytes(rom_path(CatalogEntry.model_validate(game), ctx.config))
    from .characters import best_match
    pairs, used = [], set()
    defaults = [w for w in roster(rom)]
    for k, (cq, wq) in enumerate(pairs_in):
        meta = best_match(chars, cq)
        if not meta:
            raise LookupError(f"{cq!r} isn't in the collection")
        if wq:
            w = find_wrestler(rom, wq)
        else:
            w = next(x for x in defaults if x["number"] not in used)
        if w["number"] in used:
            raise ValueError(f"{w['name']} is already replaced in this match")
        used.add(w["number"])
        pairs.append((meta, w))
    return use(ctx, pairs[0][0], game, inp, pairs, title)


def needs(game: dict) -> dict:
    t = (game.get("title") or "").lower()
    if "world tour" in t:
        return {"target": "a wrestler", "format": "AKI FileTable + costume records", "steps": [],
                "have": "World Tour writer (gbox/aki_wcw.py): characters op=use slot=<wrestler | group-member | player>"}
    if "revenge" in t:
        return {"target": "a wrestler (17 body-part models per body type + head + per-costume part textures)",
                "format": "AKI FileTable (Asmik LZSS) + AkiModel parts, same as No Mercy (gbox/aki_wrestling.py reads them)",
                "steps": ["port the No Mercy writer: Revenge/World Tour costume defs list each part's texture/palette and a "
                          "body-type model table (VPW Studio CostumeDef/BodyModelDef), so a ROM-data repoint replaces a "
                          "wrestler without a code hook", "the same per-part vertex/face budgets as No Mercy"],
                "have": "the shared AKI reader (file table, LZSS, models) in gbox/aki_wrestling.py; the writer is No Mercy only"}
    return {"target": "a wrestler", "format": "AKI FileTable", "steps": [], "have": "WWF No Mercy (USA) Rev A only"}


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roster")
    r.add_argument("rom")
    b = sub.add_parser("build")
    b.add_argument("rom")
    b.add_argument("out")
    b.add_argument("pairs", nargs="+", help="<wrestler number>=<character dir>")
    a = ap.parse_args()
    rom = rom_bytes(a.rom)
    if a.cmd == "roster":
        for w in roster(rom):
            print(w["number"], w["name"], w["body"], [hex(x) for x in w["face_tex"]])
    else:
        from .sm64_swap import _blender
        jobs = []
        for pr in a.pairs:
            n, d = pr.split("=", 1)
            meta = json.loads((Path(d) / "meta.json").read_text())
            jobs.append({"wrestler": int(n), "model": Path(d) / meta["model"], "roles": meta["rig"]["roles"], "name": meta["name"],
                         "props": [p["node"] for p in meta.get("props") or []], "scale": (meta.get("rig") or {}).get("scale")})
        res = build_rom(rom, jobs, Path(a.out).parent / "aki_work", _blender(), lambda p, m: print(f"{p:3.0f}% {m}"))
        Path(a.out).write_bytes(res["rom"])
        print(json.dumps(res["reports"], indent=1, default=str))
