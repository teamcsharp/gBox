"""Emulated-RAM analysis for the pick whip (gbox.pick_tool): a snapshot of a session's main RAM and the searches that
turn "the thing under the cursor" into addresses - the entity struct, the model / node tree, display lists, vertex
arrays, skeleton matrices and textures - plus the free-space checks the live injector (gbox.live_inject) uses.

Everything here works on a `Ram` (bytes + base address + byte order), never on a live emulator, so every search is
tested on synthetic images (tests/test_pick_ram.py). Only `Ram.snapshot` / `Ram.read_live` talk to an adapter.

Addresses are canonical CPU addresses (Dreamcast 0x8C..., GameCube 0x80..., N64 KSEG0 0x80..., PS1 0x80..., PS2
0x00...). Pointer words in RAM may use an alias of the same byte (DC P0/P2 0x0C.. / 0xAC.., GC uncached 0xC0..,
N64 KSEG1 0xA0..); `canon` maps them back and `alias_ranges` gives every raw form of a canonical range.

N64 RDRAM from ParaLLEl (RetroArch) reads as little-endian 32-bit words: the snapshot detects it (reset vector in the
header) and keeps the image big-endian; `device_bytes` swaps data back for writes.
"""
from __future__ import annotations

import math
import struct
from collections import Counter

import numpy as np

BIG_ENDIAN = {"ps3", "gamecube", "wii", "n64", "n64dd", "genesis", "segacd", "sega32x", "saturn", "x68000", "xbox360"}
N64_RESET_WORD = 0x3C1A8000                  # lui k0, 0x8000: first word of every N64 exception vector (RAM 0x80000180)
READ_CHUNK = 0x100000


# ---------------------------------------------------------------- the snapshot

class Ram:
    """One main-RAM image. data is in the CPU's byte order (N64 word-swap already undone)."""

    def __init__(self, data: bytes, base: int, big: bool, platform: str = "", swapped: bool = False):
        self.data = bytes(data)
        self.base, self.big, self.platform, self.swapped = int(base), bool(big), platform or "", bool(swapped)
        self.end = self.base + len(self.data)
        self.e = ">" if self.big else "<"
        self._words = None

    # -- construction
    @classmethod
    def snapshot(cls, ad, platform: str, region: tuple[int, int] | None = None, progress=None) -> "Ram":
        """Read the session's main RAM (tools.MAIN_RAM layout) in 1 MiB requests."""
        if region is None:
            from .tools import MAIN_RAM
            if platform not in MAIN_RAM:
                raise ValueError(f"no main-RAM layout for platform {platform!r}")
            region = tuple(MAIN_RAM[platform][0])
        base, size = region
        out = bytearray()
        for o in range(0, size, READ_CHUNK):
            n = min(READ_CHUNK, size - o)
            b = ad.read_memory(base + o, n)
            if len(b) != n:
                raise RuntimeError(f"short RAM read at {base + o:#x}: {len(b)} of {n} bytes")
            out += b
            if progress:
                progress(o + n, size)
        raw, swapped = bytes(out), False
        if platform in ("n64", "n64dd"):
            raw, swapped = fix_n64(raw)
        return cls(raw, base, platform in BIG_ENDIAN, platform, swapped)

    def read_live(self, ad, addr: int, n: int) -> bytes:
        """Fresh bytes from the emulator in this image's order (aligned to words when the device is word-swapped)."""
        if not self.swapped:
            return bytes(ad.read_memory(addr, n))
        lo, hi = addr & ~3, (addr + n + 3) & ~3
        raw = bytes(ad.read_memory(lo, hi - lo))
        return swap32(raw)[addr - lo:addr - lo + n]

    def device_bytes(self, addr: int, data: bytes) -> bytes:
        """Data as the emulator expects it at addr (word-swapped devices need 4-aligned whole words)."""
        if not self.swapped:
            return bytes(data)
        if addr & 3 or len(data) & 3:
            raise ValueError("word-swapped RAM takes whole aligned words")
        return swap32(data)

    def patched(self, writes) -> "Ram":
        """A copy with [(addr, data)] applied (to plan follow-up steps on the expected result)."""
        d = bytearray(self.data)
        for a, b in writes:
            o = a - self.base
            d[o:o + len(b)] = b
        return Ram(bytes(d), self.base, self.big, self.platform, self.swapped)

    # -- access
    def contains(self, a: int, n: int = 1) -> bool:
        return self.base <= a and a + n <= self.end

    def off(self, a: int) -> int:
        return a - self.base

    def read(self, a: int, n: int) -> bytes:
        if not self.contains(a, n):
            raise IndexError(f"{a:#x}+{n:#x} outside RAM {self.base:#x}..{self.end:#x}")
        o = a - self.base
        return self.data[o:o + n]

    def u32(self, a: int) -> int:
        return struct.unpack_from(self.e + "I", self.data, a - self.base)[0]

    def i32(self, a: int) -> int:
        return struct.unpack_from(self.e + "i", self.data, a - self.base)[0]

    def u16(self, a: int) -> int:
        return struct.unpack_from(self.e + "H", self.data, a - self.base)[0]

    def s16(self, a: int) -> int:
        return struct.unpack_from(self.e + "h", self.data, a - self.base)[0]

    def f32(self, a: int) -> float:
        return struct.unpack_from(self.e + "f", self.data, a - self.base)[0]

    def words(self) -> np.ndarray:
        """Every aligned 32-bit word (index i = address base + 4 i)."""
        if self._words is None:
            n = len(self.data) // 4
            self._words = np.frombuffer(self.data[:n * 4], self.e + "u4")
        return self._words

    # -- pointers
    def canon(self, v: int) -> int | None:
        """A pointer word -> the canonical RAM address it names, or None."""
        return canon(self.platform, v, self.base, len(self.data))

    def alias_ranges(self, lo: int, hi: int) -> list[tuple[int, int]]:
        return alias_ranges(self.platform, lo, hi, self.base)

    def pointers_to(self, lo: int, hi: int | None = None, limit: int = 4096, exclude=()) -> list[tuple[int, int]]:
        """[(address of the word, raw value)] of aligned words pointing into [lo, hi) in any alias form."""
        hi = lo + 1 if hi is None else hi
        w = self.words()
        mask = np.zeros(len(w), bool)
        for a, b in self.alias_ranges(lo, hi):
            mask |= (w >= a) & (w < b)
        idx = np.nonzero(mask)[0]
        out = []
        for i in idx[:limit * 4]:
            addr = self.base + 4 * int(i)
            if any(x0 <= addr < x1 for x0, x1 in exclude):
                continue
            out.append((addr, int(w[i])))
            if len(out) >= limit:
                break
        return out


def swap32(b: bytes) -> bytes:
    n = len(b) // 4 * 4
    return np.frombuffer(b[:n], "<u4").astype(">u4").tobytes() + b[n:]


def fix_n64(raw: bytes) -> tuple[bytes, bool]:
    """ParaLLEl exposes RDRAM as LE words: undo it when the exception vectors read swapped."""
    be = struct.pack(">I", N64_RESET_WORD)
    head = raw[:0x400]
    if be in head:
        return raw, False
    if be[::-1] in head:
        return swap32(raw), True
    return raw, False


# canonical base, size and the raw pointer forms of the same bytes, per platform
_ALIASES = {
    "dreamcast": (0x8C000000, [0x0C000000, 0x8C000000, 0xAC000000]),
    "naomi": (0x8C000000, [0x0C000000, 0x8C000000, 0xAC000000]),
    "gamecube": (0x80000000, [0x80000000, 0xC0000000]),
    "wii": (0x80000000, [0x80000000, 0xC0000000]),
    "n64": (0x80000000, [0x80000000, 0xA0000000]),
    "n64dd": (0x80000000, [0x80000000, 0xA0000000]),
    "psx": (0x80000000, [0x80000000, 0xA0000000]),
    "ps2": (0x00000000, [0x00000000, 0x20000000, 0x30000000]),
}
PS2_USER = 0x00100000                       # below it: the EE kernel (and small integers): never a model pointer


def canon(platform: str, v: int, base: int, size: int) -> int | None:
    spec = _ALIASES.get(platform)
    if spec is None:
        return v if base <= v < base + size else None
    cbase, forms = spec
    for f in forms:
        o = v - f
        if 0 <= o < size:
            if platform == "ps2" and o < PS2_USER:
                return None
            return cbase + o
    return None


def alias_ranges(platform: str, lo: int, hi: int, base: int) -> list[tuple[int, int]]:
    spec = _ALIASES.get(platform)
    if spec is None:
        return [(lo, hi)]
    cbase, forms = spec
    return [(f + (lo - cbase), f + (hi - cbase)) for f in forms]


# ---------------------------------------------------------------- structure detectors

def _finite(*v, lim=1e6) -> bool:
    return all(math.isfinite(x) and abs(x) < lim for x in v)


def _ptr_or_null(ram: Ram, v: int) -> bool:
    return v == 0 or ram.canon(v) is not None


def ninja_node(ram: Ram, a: int) -> dict | None:
    """One NJS_OBJECT (Ninja SDK): {u32 evalflags, model*, f32 pos[3], s32 ang[3], f32 scl[3], child*, sibling*}."""
    if a & 3 or not ram.contains(a, 0x34):
        return None
    e = ram.e
    flags, model = struct.unpack_from(e + "II", ram.data, a - ram.base)
    pos = struct.unpack_from(e + "3f", ram.data, a - ram.base + 8)
    ang = struct.unpack_from(e + "3i", ram.data, a - ram.base + 20)
    scl = struct.unpack_from(e + "3f", ram.data, a - ram.base + 32)
    child, sib = struct.unpack_from(e + "II", ram.data, a - ram.base + 44)
    if flags > 0xFFFF or not _finite(*pos, lim=1e5) or not _finite(*scl, lim=1e4):
        return None
    if any(abs(x) > 0x100000 for x in ang):
        return None
    if not (_ptr_or_null(ram, model) and _ptr_or_null(ram, child) and _ptr_or_null(ram, sib)):
        return None
    if model == 0 and child == 0 and sib == 0 and not any(pos) and not any(ang):
        return None                                         # an all-zero record is not a node
    return {"flags": flags, "model": ram.canon(model) if model else 0, "pos": pos, "ang": ang, "scl": scl,
            "child": ram.canon(child) if child else 0, "sibling": ram.canon(sib) if sib else 0}


def chunk_model(ram: Ram, a: int) -> dict | None:
    """NJS_CNK_MODEL {vlist*, plist*, f32 center[3], f32 radius}: vertex chunks 32..50, strip chunks 64..75."""
    if not a or a & 3 or not ram.contains(a, 0x18):
        return None
    vl, pl = struct.unpack_from(ram.e + "II", ram.data, a - ram.base)
    c = struct.unpack_from(ram.e + "4f", ram.data, a - ram.base + 8)
    if not (_ptr_or_null(ram, vl) and _ptr_or_null(ram, pl)) or not _finite(*c, lim=1e6) or c[3] < 0 or not (vl or pl):
        return None
    out = {"vlist": ram.canon(vl) if vl else 0, "plist": ram.canon(pl) if pl else 0, "center": c[:3], "radius": c[3]}
    if out["vlist"]:
        if not ram.contains(out["vlist"], 4):
            return None
        cid = ram.data[out["vlist"] - ram.base] if not ram.big else ram.data[out["vlist"] - ram.base + 3]
        if not (32 <= cid <= 50 or cid == 255):
            return None
        out["vertex_chunk"] = cid
    return out


def ninja_tree(ram: Ram, a: int, max_nodes: int = 512) -> dict | None:
    """A whole Ninja node tree from its root: node count, depth, the chunk models it draws, its byte span."""
    root = ninja_node(ram, a)
    if root is None:
        return None
    seen, stack, models, lo, hi = {}, [(a, 0)], {}, a, a + 0x34
    depth = 0
    while stack:
        n, d = stack.pop()
        if n in seen:
            return None                                     # a cycle: not a tree
        nd = ninja_node(ram, n)
        if nd is None:
            return None
        seen[n] = nd
        depth = max(depth, d)
        lo, hi = min(lo, n), max(hi, n + 0x34)
        if nd["model"]:
            cm = chunk_model(ram, nd["model"])
            models[n] = {"at": nd["model"], "chunk": cm is not None}
            lo, hi = min(lo, nd["model"]), max(hi, nd["model"] + 0x18)
        if len(seen) > max_nodes:
            return None
        if nd["sibling"]:
            stack.append((nd["sibling"], d))
        if nd["child"]:
            stack.append((nd["child"], d + 1))
    if len(seen) < 2 and not models:
        return None
    return {"kind": "ninja_object", "at": a, "nodes": len(seen), "depth": depth, "models": len(models),
            "chunk_models": sum(1 for m in models.values() if m["chunk"]), "span": [lo, hi],
            "model_addresses": sorted(m["at"] for m in models.values()), "score": min(1.0, 0.3 + 0.05 * len(seen))}


# N64 microcode dialects: opcode -> name (RDP commands 0xE4..0xFF are shared)
_RDP = {0xE4: "TEXRECT", 0xE5: "TEXRECTFLIP", 0xE6: "RDPLOADSYNC", 0xE7: "RDPPIPESYNC", 0xE8: "RDPTILESYNC",
        0xE9: "RDPFULLSYNC", 0xED: "SETSCISSOR", 0xEE: "SETPRIMDEPTH", 0xEF: "RDPSETOTHERMODE", 0xF0: "LOADTLUT",
        0xF2: "SETTILESIZE", 0xF3: "LOADBLOCK", 0xF4: "LOADTILE", 0xF5: "SETTILE", 0xF6: "FILLRECT",
        0xF7: "SETFILLCOLOR", 0xF8: "SETFOGCOLOR", 0xF9: "SETBLENDCOLOR", 0xFA: "SETPRIMCOLOR", 0xFB: "SETENVCOLOR",
        0xFC: "SETCOMBINE", 0xFD: "SETTIMG", 0xFE: "SETZIMG", 0xFF: "SETCIMG"}
F3DEX2 = {0x00: "NOOP", 0x01: "VTX", 0x02: "MODIFYVTX", 0x03: "CULLDL", 0x04: "BRANCH_Z", 0x05: "TRI1", 0x06: "TRI2",
          0x07: "QUAD", 0xD3: "SPECIAL_3", 0xD4: "SPECIAL_2", 0xD5: "SPECIAL_1", 0xD6: "DMA_IO", 0xD7: "TEXTURE",
          0xD8: "POPMTX", 0xD9: "GEOMETRYMODE", 0xDA: "MTX", 0xDB: "MOVEWORD", 0xDC: "MOVEMEM", 0xDD: "LOAD_UCODE",
          0xDE: "DL", 0xDF: "ENDDL", 0xE0: "SPNOOP", 0xE1: "RDPHALF_1", 0xE2: "SETOTHERMODE_L", 0xE3: "SETOTHERMODE_H",
          0xF1: "RDPHALF_2", **_RDP}
F3D = {0x00: "SPNOOP", 0x01: "MTX", 0x03: "MOVEMEM", 0x04: "VTX", 0x06: "DL", 0x09: "SPRITE2D", 0xB1: "TRI2",
       0xB2: "RDPHALF_CONT", 0xB3: "RDPHALF_2", 0xB4: "RDPHALF_1", 0xB5: "QUAD", 0xB6: "CLEARGEOMETRYMODE",
       0xB7: "SETGEOMETRYMODE", 0xB8: "ENDDL", 0xB9: "SETOTHERMODE_L", 0xBA: "SETOTHERMODE_H", 0xBB: "TEXTURE",
       0xBC: "MOVEWORD", 0xBD: "POPMTX", 0xBE: "CULLDL", 0xBF: "TRI1", 0xC0: "NOOP", **_RDP}


def n64_display_list(ram: Ram, a: int, max_cmds: int = 4096) -> dict | None:
    """An N64 display list (F3D or F3DEX2) up to its ENDDL: commands, triangles, the vertex loads it makes."""
    if a & 7 or not ram.contains(a, 16):
        return None
    best = None
    for name, table, vtx, tris, dl, end in (("F3DEX2", F3DEX2, 0x01, {0x05: 1, 0x06: 2, 0x07: 2}, 0xDE, 0xDF),
                                             ("F3D", F3D, 0x04, {0xBF: 1, 0xB1: 2, 0xB5: 2}, 0x06, 0xB8)):
        p, n, ntri, verts, calls, ok = a, 0, 0, [], [], False
        while n < max_cmds and ram.contains(p, 8):
            w0, w1 = struct.unpack_from(">II", ram.data, p - ram.base) if ram.big else \
                struct.unpack_from("<II", ram.data, p - ram.base)
            op = w0 >> 24
            if op not in table:
                break
            n += 1
            p += 8
            if op == vtx:
                verts.append(w1)
            elif op in tris:
                ntri += tris[op]
            elif op == dl:
                calls.append(w1)
                if (w0 >> 16) & 0xFF == 1:                   # G_DL with "no push": a branch, the list ends here
                    ok = True
                    break
            elif op == end:
                ok = True
                break
        if ok and n >= 2 and (ntri or calls) and (verts or calls):
            cand = {"kind": "n64_display_list", "at": a, "dialect": name, "commands": n, "triangles": ntri,
                    "vertex_loads": len(verts), "vertex_addresses": verts[:64], "calls": calls[:64], "span": [a, p],
                    "score": min(1.0, 0.4 + 0.02 * n)}
            if best is None or cand["commands"] > best["commands"]:
                best = cand
    return best


GX_DRAW = {0x80: "quads", 0x90: "triangles", 0x98: "strip", 0xA0: "fan", 0xA8: "lines", 0xB0: "linestrip",
           0xB8: "points"}


def gx_display_list(ram: Ram, a: int) -> dict | None:
    """A GameCube/Wii GX display list head: a draw opcode (+ VAT index) with a plausible vertex count, or the BP/CP/XF
    register loads materials start with. The vertex size needs the VAT, so this is a hint, not a parse."""
    if a & 31 or not ram.contains(a, 8):
        return None
    op = ram.data[a - ram.base]
    if op & 0xF8 in GX_DRAW:
        cnt = struct.unpack_from(">H", ram.data, a - ram.base + 1)[0]
        if 0 < cnt < 0x4000:
            return {"kind": "gx_display_list", "at": a, "primitive": GX_DRAW[op & 0xF8], "vat": op & 7,
                    "vertices": cnt, "score": 0.35}
    if op in (0x61, 0x08) and ram.data[a - ram.base + 5] in (0x61, 0x08, 0x10, 0x00):
        return {"kind": "gx_display_list", "at": a, "primitive": "state", "score": 0.2}
    return None


def vertex_array(ram: Ram, a: int, min_count: int = 6, max_count: int = 4096) -> dict | None:
    """A run of vertices at a: N64 Vtx (s16 xyz, flag 0, s16 st, rgba; 16 bytes), float xyz (12 / 24 / 32 byte
    strides) or s16 xyz (6 / 8). The longest plausible run of distinct points wins."""
    if a & 1 or not ram.contains(a, 12):
        return None
    best = None
    fmts = [("n64_vtx", 16, "3h"), ("f32x3", 12, "3f"), ("f32x3", 24, "3f"), ("f32x3", 32, "3f"), ("s16x3", 6, "3h"),
            ("s16x3", 8, "3h")]
    for fmt, stride, code in fmts:
        if code == "3f" and a & 3:
            continue
        n, pts, last_new = 0, set(), 0
        p = a
        while n < max_count and ram.contains(p, stride):
            v = struct.unpack_from(ram.e + code, ram.data, p - ram.base)
            if fmt == "n64_vtx" and struct.unpack_from(ram.e + "H", ram.data, p - ram.base + 6)[0] != 0:
                break
            if code == "3f":
                if not _finite(*v, lim=1e5) or any(x != 0 and abs(x) < 1e-20 for x in v):
                    break
            if v not in pts:
                pts.add(v)
                last_new = n + 1
            n += 1
            p += stride
            if n >= 32 and len(pts) * 4 < n:                # a fill pattern (zeros), not geometry
                break
        n = last_new                                        # trailing repeats (padding) aren't part of the run
        if fmt == "f32x3" and stride == 12 and n >= 4:      # position, normal, position, normal ...: stride 24
            odd = [struct.unpack_from(ram.e + "3f", ram.data, a - ram.base + 12 * k) for k in range(1, n, 2)]
            if sum(1 for v in odd if 0.9 <= math.sqrt(sum(x * x for x in v)) <= 1.1) >= 0.9 * len(odd):
                continue
        if n >= min_count and len(pts) >= max(3, n // 3) and len({q[0] for q in pts}) > 1:
            cand = {"kind": "vertex_array", "at": a, "format": fmt, "stride": stride, "count": n,
                    "distinct": len(pts), "span": [a, a + n * stride], "score": min(0.8, 0.2 + 0.01 * len(pts))}
            # floats that pass the sanity filter are rarely anything else; N64 Vtx first on N64; s16 last
            rank = {"f32x3": 0, "n64_vtx": 1, "s16x3": 2}[fmt] if ram.platform != "n64" else \
                {"n64_vtx": 0, "f32x3": 1, "s16x3": 2}[fmt]
            if best is None or (rank, -cand["distinct"]) < (best["_rank"], -best["distinct"]):
                best = cand | {"_rank": rank}
    if best:
        best.pop("_rank")
    return best


def matrix_array(ram: Ram, a: int, max_count: int = 256) -> dict | None:
    """Consecutive 3x4 / 4x4 float matrices whose rotation part is near-orthogonal (a skeleton's pose / bind
    matrices): -> count and layout."""
    if a & 3:
        return None
    best = None
    for rows, size in ((3, 48), (4, 64)):
        n = 0
        p = a
        while n < max_count and ram.contains(p, size):
            m = struct.unpack_from(ram.e + f"{rows * 4}f", ram.data, p - ram.base)
            if not _finite(*m, lim=1e6):
                break
            r = [m[0:3], m[4:7], m[8:11]]
            norms = [math.sqrt(sum(x * x for x in row)) for row in r]
            if min(norms) < 1e-3:
                break
            s = sum(norms) / 3
            if any(abs(nm - s) > 0.05 * s for nm in norms):
                break
            dots = [abs(sum(x * y for x, y in zip(r[i], r[j]))) / (s * s) for i, j in ((0, 1), (0, 2), (1, 2))]
            if max(dots) > 0.05:
                break
            if rows == 4 and not _finite(m[12], m[13], m[14]) or rows == 4 and abs(m[15] - 1) > 1e-3 and m[15] != 0:
                break
            n += 1
            p += size
        if n >= 2:
            cand = {"kind": "matrix_array", "at": a, "layout": f"{rows}x4", "count": n, "span": [a, a + n * size],
                    "score": min(0.7, 0.2 + 0.05 * n)}
            if best is None or cand["count"] > best["count"]:
                best = cand
    return best


DETECTORS = {"ninja_object": ninja_tree, "n64_display_list": n64_display_list, "gx_display_list": gx_display_list,
             "matrix_array": matrix_array, "vertex_array": vertex_array}
PLATFORM_DETECTORS = {
    "dreamcast": ("ninja_object", "matrix_array", "vertex_array"),
    "naomi": ("ninja_object", "matrix_array", "vertex_array"),
    "gamecube": ("ninja_object", "gx_display_list", "matrix_array", "vertex_array"),
    "wii": ("gx_display_list", "matrix_array", "vertex_array"),
    "n64": ("n64_display_list", "matrix_array", "vertex_array"),
}
ROLES = {"ninja_object": "model", "n64_display_list": "display_list", "gx_display_list": "display_list",
         "matrix_array": "skeleton", "vertex_array": "vertex_buffer"}


def classify(ram: Ram, a: int, kinds=None) -> list[dict]:
    """Every detector that recognises a structure at a, best first."""
    out = []
    for k in kinds or PLATFORM_DETECTORS.get(ram.platform, tuple(DETECTORS)):
        try:
            r = DETECTORS[k](ram, a)
        except (struct.error, IndexError):
            r = None
        if r:
            out.append(r)
    return sorted(out, key=lambda r: -r["score"])


# ---------------------------------------------------------------- following pointers

def walk(ram: Ram, start: int, size: int, depth: int = 2, fanout: int = 48, kinds=None, max_nodes: int = 400) -> list[dict]:
    """Forward pointer walk from a struct (an entity): every pointer word in [start, start+size), followed depth
    levels deep (each target read as a 0x100-byte struct), classified by the platform's detectors.
    -> [{at, path: [(struct, offset)], found: [detector results]}] for targets something recognised."""
    out, seen = [], {start}
    frontier = [(start, size, [])]
    for _level in range(depth):
        nxt = []
        for s, n, path in frontier:
            n = min(n, 0x1000)
            if not ram.contains(s, 4):
                continue
            n = min(n, ram.end - s) & ~3
            k = 0
            for o in range(0, n, 4):
                v = ram.u32(s + o)
                t = ram.canon(v)
                if t is None or t in seen or t == s:
                    continue
                seen.add(t)
                k += 1
                if k > fanout or len(seen) > max_nodes:
                    break
                p = path + [(s, o)]
                found = classify(ram, t, kinds)
                if found:
                    out.append({"at": t, "path": p, "found": found})
                nxt.append((t, 0x100, p))
        frontier = nxt
    return out


def back_chains(ram: Ram, target: int, depth: int = 3, limit: int = 8, roots=None, span: int = 0x400) -> list[list[dict]]:
    """Who points at target (or at most span bytes before it: a struct holding it at an offset), recursively:
    chains [{at, offset}] from target up to a root. roots(addr) -> label when addr is a known root (a static table,
    an entity) and the climb stops there."""
    chains = []

    def climb(addr: int, chain: list, d: int):
        if roots and (lab := roots(addr)):
            chains.append(chain + [{"at": addr, "root": lab}])
            return
        if d == 0 or len(chains) >= limit:
            if chain:
                chains.append(chain)
            return
        refs = ram.pointers_to(addr, addr + 1, limit=16)
        if not refs:
            refs = ram.pointers_to(max(ram.base, addr - span), addr + 1, limit=16)
        if not refs:
            if chain:
                chains.append(chain)
            return
        for where, raw in refs[:4]:
            tgt = ram.canon(raw)
            climb(where, chain + [{"at": where, "points_to": tgt, "offset": addr - tgt if tgt is not None else 0}], d - 1)
    climb(target, [], depth)
    return chains[:limit]


# ---------------------------------------------------------------- finding known bytes (relocation-tolerant)

def _anchor_offsets(n: int, ptr_offs: set[int], length: int = 16, count: int = 4) -> list[int]:
    """Offsets of word-aligned runs of `length` bytes inside a window of n bytes free of known pointer words."""
    good, run = [], 0
    for o in range(0, n - 3, 4):
        run = 0 if o in ptr_offs else run + 4
        if run >= length:
            good.append(o + 4 - length)
    if not good:
        return []
    step = max(1, len(good) // count)
    return sorted(set(good[::step][:count]))


def verify_at(ram: Ram, addr: int, window: bytes, ptr_offs: set[int] | None = None, delta: int | None = None) -> dict:
    """Word-compare window with RAM at addr. Words that differ by one constant (the loader's relocation) count as
    relocated matches. -> {score, delta, relocated (window offsets), mismatched (window offsets), exact}."""
    n = len(window) // 4 * 4
    if not ram.contains(addr, max(n, 1)) or n == 0:
        return {"score": 0.0, "delta": None, "relocated": [], "mismatched": list(range(0, n, 4)), "exact": False}
    a = np.frombuffer(window[:n], ram.e + "u4").astype(np.int64)
    b = np.frombuffer(ram.data[addr - ram.base:addr - ram.base + n], ram.e + "u4").astype(np.int64)
    diff = (b - a) % (1 << 32)
    neq = np.nonzero(diff)[0]
    if delta is None and len(neq):
        cands = diff[neq]
        if ptr_offs:
            sel = [i for i in neq if 4 * int(i) in ptr_offs]
            cands = diff[sel] if sel else cands
        delta = int(Counter(cands.tolist()).most_common(1)[0][0])
    rel, bad = [], []
    for i in neq:
        o = 4 * int(i)
        if delta and int(diff[i]) == delta and ram.canon(int(b[i])) is not None and (not ptr_offs or o in ptr_offs):
            rel.append(o)
        else:
            bad.append(o)
    tail_ok = window[n:] == ram.data[addr - ram.base + n:addr - ram.base + len(window)]
    score = (n // 4 - len(bad)) / max(1, n // 4) * (1.0 if tail_ok else 0.99)
    return {"score": score, "delta": (delta or 0) if rel else 0, "relocated": rel, "mismatched": bad,
            "exact": not len(neq) and tail_ok}


def find_window(ram: Ram, window: bytes, ptr_offs=None, min_score: float = 0.9, limit: int = 8,
                lo: int | None = None, hi: int | None = None) -> list[dict]:
    """Where are these bytes in RAM, allowing pointer words relocated by one constant? -> candidates best first
    [{addr, score, delta, relocated, mismatched, exact}]. ptr_offs: known pointer-word offsets in the window."""
    ptr = set(ptr_offs or ())
    out, tried = [], set()
    lo_o = 0 if lo is None else max(0, lo - ram.base)
    hi_o = len(ram.data) if hi is None else min(len(ram.data), hi - ram.base)
    if not ptr:
        i = ram.data.find(window, lo_o, hi_o)
        hits = steps = 0
        while i >= 0 and hits < limit and steps < 4096:
            steps += 1
            if (ram.base + i) % 4 == 0:
                out.append({"addr": ram.base + i, "score": 1.0, "delta": 0, "relocated": [], "mismatched": [],
                            "exact": True})
                tried.add(ram.base + i)
                hits += 1
            i = ram.data.find(window, i + 1, hi_o)
        if out:
            return out
    anchors = _anchor_offsets(len(window), ptr, 16 if len(window) >= 64 else 8)
    for ao in anchors:
        needle = window[ao:ao + (16 if len(window) >= 64 else 8)]
        if needle.count(needle[:1]) == len(needle):        # a run of one byte (zeros) anchors nowhere useful
            continue
        i = ram.data.find(needle, lo_o, hi_o)
        hits = 0
        while i >= 0 and hits < 64:
            cand = ram.base + i - ao
            if cand % 4 == 0 and cand not in tried and ram.contains(cand, len(window)):
                tried.add(cand)
                v = verify_at(ram, cand, window, ptr or None)
                if v["score"] >= min_score:
                    out.append({"addr": cand, **v})
            hits += 1
            i = ram.data.find(needle, i + 1, hi_o)
    out.sort(key=lambda c: (-c["score"], c["addr"]))
    return out[:limit]


def find_vertices(ram: Ram, verts: list[tuple[float, float, float]], tol: float = 1e-3, limit: int = 4) -> list[dict]:
    """Model-space vertex positions (in order) -> where they sit in RAM: f32 xyz (any stride 12..64) or integer-valued
    s16 xyz (stride 6..32). -> [{addr, format, stride, count}]."""
    if len(verts) < 3:
        return []
    out = []
    for fmt, code, size in (("f32x3", "3f", 12), ("s16x3", "3h", 6)):
        if code == "3h" and not all(float(x).is_integer() and -32768 <= x < 32768 for v in verts[:8] for x in v):
            continue
        enc = lambda v: struct.pack(ram.e + code, *[int(x) if code == "3h" else float(x) for x in v])   # noqa: E731
        k = next((j for j, v in enumerate(verts) if len(set(enc(v))) > 3), None)   # a distinctive anchor vertex
        if k is None:
            continue
        needle = enc(verts[k])
        i = ram.data.find(needle)
        seen = 0
        while i >= 0 and seen < 256 and len(out) < limit:
            seen += 1
            for stride in range(size, 65, 2 if code == "3h" else 4):
                start = i - k * stride
                if start < 0 or start + stride * (len(verts) - 1) + size > len(ram.data):
                    continue
                if all(all(abs(x - y) <= tol for x, y in zip(struct.unpack_from(ram.e + code, ram.data, start + stride * j),
                                                             verts[j])) for j in range(len(verts))):
                    a = ram.base + start
                    out.append({"addr": a, "format": fmt, "stride": stride, "count": len(verts),
                                "span": [a, a + stride * len(verts)]})
                    break
            i = ram.data.find(needle, i + 1)
    return out


# ---------------------------------------------------------------- textures: re-encode a captured texture, find it

def _c5(v):
    return v >> 3


def tex_encodings(rgba: bytes, w: int, h: int) -> list[tuple[str, bytes]]:
    """The first block of a decoded texture (RGBA8 bytes, as an emulator decoded it) in the console encodings it may
    have come from, losslessly re-encoded: GX RGB5A3 / RGB565 / IA8 / I8 / RGBA8 (4x4 / 8x4 tiles), N64 RGBA16 /
    RGBA32 rows. -> [(format, bytes to search)] (16..64 bytes each)."""
    if w < 4 or h < 4 or len(rgba) < w * h * 4:
        return []
    px = lambda x, y: rgba[4 * (y * w + x):4 * (y * w + x) + 4]      # noqa: E731
    out = []
    tile4 = [(x, y) for y in range(4) for x in range(4)]
    rgb5a3 = b""
    for x, y in tile4:
        r, g, b, a = px(x, y)
        v = 0x8000 | (_c5(r) << 10) | (_c5(g) << 5) | _c5(b) if a == 255 else ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        rgb5a3 += struct.pack(">H", v)
    out.append(("gx_rgb5a3", rgb5a3))
    out.append(("gx_rgb565", b"".join(struct.pack(">H", (_c5(px(x, y)[0]) << 11) | ((px(x, y)[1] >> 2) << 5) | _c5(px(x, y)[2]))
                                      for x, y in tile4)))
    out.append(("gx_ia8", b"".join(bytes((px(x, y)[3], px(x, y)[0])) for x, y in tile4)))
    if w >= 8:
        out.append(("gx_i8", bytes(px(x, y)[0] for y in range(4) for x in range(8))))
    ar = b"".join(bytes((px(x, y)[3], px(x, y)[0])) for x, y in tile4)
    gb = b"".join(bytes((px(x, y)[1], px(x, y)[2])) for x, y in tile4)
    out.append(("gx_rgba8", ar + gb))
    row = min(w, 16)
    out.append(("n64_rgba16", b"".join(struct.pack(">H", (_c5(px(x, 0)[0]) << 11) | (_c5(px(x, 0)[1]) << 6) | (_c5(px(x, 0)[2]) << 1)
                                                   | (1 if px(x, 0)[3] >= 128 else 0)) for x in range(row))))
    out.append(("rgba32", b"".join(px(x, 0) for x in range(row))))
    return [(f, b) for f, b in out if len(set(b)) > 2]     # flat colour blocks match everywhere: useless


def find_texture(ram: Ram, rgba: bytes, w: int, h: int, limit: int = 4) -> list[dict]:
    """A captured texture's first block in RAM in any lossless console encoding -> [{addr, format}]."""
    out = []
    for fmt, needle in tex_encodings(rgba, w, h):
        i = ram.data.find(needle)
        while i >= 0 and len(out) < limit:
            if (ram.base + i) % 32 == 0 or fmt in ("n64_rgba16", "rgba32") and (ram.base + i) % 8 == 0:
                out.append({"addr": ram.base + i, "format": fmt, "width": w, "height": h})
            i = ram.data.find(needle, i + 1)
    return out


# ---------------------------------------------------------------- free space (live injection beyond a footprint)

def zero_runs(ram: Ram, size: int, lo: int | None = None, hi: int | None = None, align: int = 32,
              guard: int = 256, limit: int = 8) -> list[tuple[int, int]]:
    """Runs of zero bytes big enough for size + a guard band on both sides, inside [lo, hi): [(start, end)] of the
    usable (aligned, guarded) part."""
    lo = ram.base if lo is None else max(lo, ram.base)
    hi = ram.end if hi is None else min(hi, ram.end)
    seg = np.frombuffer(ram.data, np.uint8)[lo - ram.base:hi - ram.base]
    nz = np.flatnonzero(seg)
    bounds = np.concatenate(([-1], nz, [len(seg)]))
    gaps = np.diff(bounds) - 1
    out = []
    for k in np.argsort(-gaps):
        g = int(gaps[k])
        if g < size + 2 * guard:
            break
        s = lo + int(bounds[k]) + 1 + guard
        s = (s + align - 1) // align * align
        e = lo + int(bounds[k + 1]) - guard
        if e - s >= size:
            out.append((s, e))
        if len(out) >= limit:
            break
    return out


def free_region(ram: Ram, size: int, arenas: list[tuple[int, int]], guard: int = 256) -> dict | None:
    """Space for size bytes inside a declared arena: all zero (with guard bands), and no pointer in RAM points into
    it (nothing owns it). -> {start, end, arena} or None. Without a declared arena there is no free region: zeroed
    bss is often a buffer the game fills later."""
    for lo, hi in arenas:
        for s, e in zero_runs(ram, size, lo, hi, guard=guard):
            if not ram.pointers_to(s - guard, e + guard, limit=1):
                return {"start": s, "end": e, "arena": [lo, hi]}
    return None
