"""Crazy Taxi 2 (Dreamcast) driver writer: a collection character as any of the eight drivers, written natively into
the driver's own files (polPP??.BIN + polPP??H.BIN, texPP??.BIN + texPP??H.BIN) and the slot tables in
1ST_READ.BIN, in a copied GD-ROM image (gdrom.patch_gdi; the source image is never written). Reader: gbox.crazy_taxi2;
formats and evidence: docs/crazy_taxi2.md.

Retarget (shared with the GameCube Crazy Taxi v2 writer, gbox.crazy_taxi_look): the donor is cut into the 15 body
parts by its rig roles, every part mapped into the stock part's own joint frame (same frame conventions in both games),
bones stretched to the stock driver's lengths, the donor's textures packed into one atlas. Fit events (gbox.fit_events)
report scale / retarget / weights / decimate / encode / write.

Native encoding, kept inside what the stock files already do:

* geometry: one textured opaque mesh per part (the stock part's first mesh header as template, texture index, TSP
  size and TCW format bits set to the atlas slot), PowerVR strips (flags 0xF2) plus one triangle list (0x6A) for the
  leftovers, full 32-byte vertices only (no vertex references: their first word indexes the game's transformed-vertex
  buffer by a rule only partly decoded, see docs), the gesture hands carry the donor's hand, accessory sub-parts
  (Gus's wristband) one zero-area triangle. Objects keep their order; the slot table offsets in 1ST_READ.BIN are
  rewritten. The pol file stays within the game's buffer for it (1ST_READ.BIN's per-model size word, unchanged):
  the donor is decimated (quadric edge collapse, gbox.auf_swap.decimate) until it fits, and no object exceeds the
  largest stock object's vertex entries.
* textures: the texture table in 1ST_READ.BIN is not touched (same count, sizes, formats, addresses): the atlas goes
  into the driver's largest texture slot in that slot's own format (twiddled / rectangle / mipmapped RGB565 or
  ARGB4444, or VQ with a k-means 256-entry codebook); the other textures keep their bytes. The tex file keeps its
  length, so VRAM use is unchanged.

`validate` is the PowerVR safety check every written file passes before the image is built: polygon parameter words
(PCW type 4, list type opaque / translucent / punch-through), TSP texture size and TCW pixel format / VQ / mipmap bits
equal to the texture table entry, texture index inside the table, strip lengths (>= 3 vertices, < 65536), finite
vertices and UVs, object vertex entries <= the stock maximum, the pol size within its buffer, textures power-of-two
8..1024 laying the tex file out exactly (total under the 8 MB VRAM), every slot offset on an object start and the part
names read back. Unverified in game (no emulator run on this PC yet).
"""
from __future__ import annotations

import hashlib
import json
import struct
import time
from pathlib import Path

import numpy as np

from . import crazy_taxi2 as c2

GAME_IDS = set(c2.GAME_IDS)
WRITER_VERSION = 1
STRIP_FLAGS, LIST_FLAGS = 0xF2, 0x6A          # the most common stock strip / triangle-list words
MAX_OBJECT_ENTRIES = 678                      # largest stock object (vertex entries) in any polPP file
VRAM = 8 << 20
OPAQUE_TSP_BLEND = (1, 0)                     # src ONE, dst ZERO
SLOT_ALIASES = {"axel": "PP1A", "bd_joe": "PP1B", "b.d. joe": "PP1B", "bd joe": "PP1B", "joe": "PP1B",
                "gena": "PP1C", "gus": "PP1D", "slash": "PP2A", "iceman": "PP2B", "cinnamon": "PP2C",
                "hot_d": "PP2D", "hot-d": "PP2D", "hot d": "PP2D", "hotd": "PP2D"}


# ----------------------------------------------------------------------------------------------- slots

def parse_slot(slot: str | None) -> list[str]:
    """player (Slash, first on the select screen) | driver:<name> | <name> | drivers (all eight) -> model keys."""
    s = (slot or "player").strip().casefold()
    if s in ("drivers", "all", "all drivers", "cast"):
        return list(c2.PLAYER_KEYS)
    if s == "player":
        return ["PP2A"]
    s = s.removeprefix("driver:").strip()
    if s.upper() in c2.PLAYER_KEYS:
        return [s.upper()]
    if s in SLOT_ALIASES:
        return [SLOT_ALIASES[s]]
    raise ValueError(f"unknown Crazy Taxi 2 slot {slot!r}: player, drivers or driver:<"
                     + "|".join(c2.SLUGS.values()) + ">")


def cast_slots() -> list[dict]:
    """The writer's slots for the cast menu (char_coverage.cast_slots)."""
    return [{"slot": "player", "name": "Slash (player)", "kind": "player"},
            {"slot": "drivers", "name": "All eight drivers", "kind": "group"}] + \
        [{"slot": f"driver:{c2.SLUGS[k]}", "name": n, "kind": "driver"} for k, n in c2.DRIVERS.items()]


def is_slot(slot: str | None) -> bool:
    try:
        parse_slot(slot)
        return True
    except ValueError:
        return False


# ----------------------------------------------------------------------------------------------- textures (encode)

def _to_words(rgba: np.ndarray, pix: int) -> np.ndarray:
    c = rgba.astype(np.uint32)
    r, g, b, a = c[..., 0], c[..., 1], c[..., 2], c[..., 3]
    if pix == 1:
        return ((r * 31 + 127) // 255 << 11 | (g * 63 + 127) // 255 << 5 | (b * 31 + 127) // 255).astype(np.uint16)
    if pix == 2:
        return ((a * 15 + 127) // 255 << 12 | (r * 15 + 127) // 255 << 8 | (g * 15 + 127) // 255 << 4
                | (b * 15 + 127) // 255).astype(np.uint16)
    if pix == 0:
        return ((a >= 128).astype(np.uint32) << 15 | (r * 31 + 127) // 255 << 10 | (g * 31 + 127) // 255 << 5
                | (b * 31 + 127) // 255).astype(np.uint16)
    raise ValueError(f"pixel format {pix} not encoded")


def _resize(rgba: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image
    if rgba.shape[0] == h and rgba.shape[1] == w:
        return rgba
    return np.asarray(Image.fromarray(np.asarray(rgba, np.uint8), "RGBA").resize((w, h), Image.LANCZOS))


def _twiddled(words: np.ndarray) -> np.ndarray:
    h, w = words.shape
    out = np.zeros(w * h, np.uint16)
    out[c2._morton(w, h).reshape(-1)] = words.reshape(-1)
    return out


def _levels(rgba: np.ndarray) -> list[np.ndarray]:
    """Mip levels smallest first (1x1 .. full)."""
    out, cur = [rgba], rgba
    while cur.shape[0] > 1:
        cur = _resize(cur, cur.shape[1] // 2, cur.shape[0] // 2)
        out.append(cur)
    return out[::-1]


def _kmeans(X: np.ndarray, k: int = 256, iters: int = 10, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    uniq = np.unique(X, axis=0)
    if len(uniq) <= k:
        C = np.zeros((k, X.shape[1]))
        C[:len(uniq)] = uniq
        C[len(uniq):] = uniq[0]
    else:
        C = uniq[rng.choice(len(uniq), k, replace=False)].astype(float)
    for _ in range(iters):
        d = (X ** 2).sum(1)[:, None] - 2 * X @ C.T + (C ** 2).sum(1)[None]
        lab = d.argmin(1)
        for j in range(k):
            sel = lab == j
            if sel.any():
                C[j] = X[sel].mean(0)
    d = (X ** 2).sum(1)[:, None] - 2 * X @ C.T + (C ** 2).sum(1)[None]
    return C, d.argmin(1)


def _blocks(rgba: np.ndarray) -> np.ndarray:
    """(h, w, 4) -> (h/2 * w/2, 16) VQ block vectors, texel order (0,0) (0,1) (1,0) (1,1) as x, y."""
    a = rgba.astype(float)
    return np.concatenate([a[0::2, 0::2], a[1::2, 0::2], a[0::2, 1::2], a[1::2, 1::2]], -1).reshape(-1, 16)


def encode_texture(rgba: np.ndarray, t: dict) -> bytes:
    """An RGBA image -> one texture table entry's exact bytes (its size, format and layout)."""
    w, h, pix, fmt = t["w"], t["h"], t["pix"], t["fmt"]
    img = _resize(np.asarray(rgba, np.uint8), w, h)
    if pix == 1:
        img = img.copy()
        img[..., 3] = 255
    if fmt in (1, 0x0D):
        out = _twiddled(_to_words(img, pix)).tobytes()
    elif fmt == 2:
        if w != h:
            raise ValueError("mipmapped textures are square")
        body = b"".join(_twiddled(_to_words(lv, pix)).tobytes() for lv in _levels(img))
        out = b"\0" * 6 + body
    elif fmt in (3, 4):
        if w != h:
            raise ValueError("VQ textures are square here")
        levels = _levels(img) if fmt == 4 else [img]
        X = _blocks(img)
        C, lab = _kmeans(X)
        book = np.clip(C.reshape(256, 4, 4).round(), 0, 255).astype(np.uint8)
        words = _to_words(book, pix).reshape(-1)
        idx_bytes = []
        for lv in levels:
            if lv.shape[0] == 1:
                lv = np.repeat(np.repeat(lv, 2, 0), 2, 1)
                one = True
            else:
                one = False
            Y = _blocks(lv)
            lab_lv = lab if lv.shape[0] == h and not one else \
                ((Y ** 2).sum(1)[:, None] - 2 * Y @ C.T + (C ** 2).sum(1)[None]).argmin(1)
            n = lv.shape[0] // 2
            grid = lab_lv.reshape(n, n)
            tw = np.zeros(n * n, np.uint8)
            tw[c2._morton(n, n).reshape(-1)] = grid.reshape(-1)
            idx_bytes.append(tw.tobytes()[:1] if one else tw.tobytes())
        out = words.astype("<u2").tobytes() + b"".join(idx_bytes)
    else:
        raise ValueError(f"texture data format {fmt:#x} not encoded")
    if len(out) != t["size"]:
        raise AssertionError(f"encoded {len(out)} bytes for a {t['size']}-byte texture")
    return out


def atlas_slot(table: list[dict]) -> int:
    """The texture slot the atlas goes into: the most texels, then the most bytes (VQ last on ties)."""
    return max(range(len(table)), key=lambda i: (table[i]["w"] * table[i]["h"], table[i]["fmt"] not in (3, 4),
                                                 table[i]["size"]))


def write_texture(tex: bytes, table: list[dict], slot: int, rgba: np.ndarray) -> bytes:
    t = table[slot]
    body = encode_texture(rgba, t)
    return tex[:t["offset"]] + body + tex[t["offset"] + len(body):]


# ----------------------------------------------------------------------------------------------- geometry (encode)

def look_measures(objs, names: dict) -> dict:
    """The stock driver's measures in the keys gbox.crazy_taxi_look.part_maps takes (same part frames)."""
    m = c2.measures(objs, names)
    lo = {p: c2._cloud(objs, i).min(0) for p, i in names.items() if "+" not in p}
    hi = {p: c2._cloud(objs, i).max(0) for p, i in names.items() if "+" not in p}
    m["chest"] = max(0.5, float(hi["mune"][0]))
    m["chest_width"] = float(hi["mune"][2] - lo["mune"][2])
    m["chest_depth"] = float(hi["mune"][1] - lo["mune"][1])
    m["head_height"] = float(hi["atama"][1] - lo["atama"][1])
    m["head_top"] = max(0.5, float(hi["atama"][1]))
    for s in "lr":
        m[f"hand_{s}"] = max(0.3, float(hi[f"te_{s}"][0] - lo[f"te_{s}"][0]))
    m["legs"] -= m["hips"]                                      # part_maps: hip sockets to soles
    return m


def signed_volume(P, T) -> float:
    P, T = np.asarray(P, float), np.asarray(T, int).reshape(-1, 3)
    if not len(T):
        return 0.0
    return float(np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])).sum() / 6.0)


def mesh_header(pol: bytes, mesh, tex_index: int, t: dict, P: np.ndarray, length: int) -> bytes:
    """The stock mesh header with the atlas texture: index, TSP size, TCW format bits; opaque list and blending;
    the mesh bounding sphere; the strip-data length."""
    h = bytearray(pol[mesh.offset:mesh.offset + c2.MESH_HEADER])
    pcw, isp, tsp, tcw = struct.unpack_from("<4I", h, 0)
    pcw = (pcw & ~(7 << 24)) | 0x08                             # opaque list, textured
    tsp = (tsp & ~0x3F) | ((t["w"].bit_length() - 4) << 3) | (t["h"].bit_length() - 4)
    tsp = (tsp & ~(0x3F << 26)) | (OPAQUE_TSP_BLEND[0] << 29) | (OPAQUE_TSP_BLEND[1] << 26)
    vq = t["fmt"] in (3, 4, 0x10, 0x11)
    mip = t["fmt"] in (2, 4, 0x11, 0x12)
    tcw = (int(mip) << 31) | (int(vq) << 30) | ((t["pix"] & 7) << 27)   # twiddled, address filled by the loader
    struct.pack_into("<4I", h, 0, pcw, isp, tsp, tcw)
    c = (P.min(0) + P.max(0)) / 2 if len(P) else np.zeros(3)
    r = float(np.linalg.norm(P - c, axis=1).max()) if len(P) else 0.0
    struct.pack_into("<4f", h, 0x10, *c, r)
    struct.pack_into("<I", h, 0x20, tex_index)
    struct.pack_into("<I", h, 0x4C, length)
    return bytes(h)


def strip_data(P, N, UV, T) -> tuple[bytes, int]:
    """Triangles -> PowerVR strips + one list, full vertices only. Returns (bytes, vertex entries)."""
    from .crazy_taxi_look import stripify
    strips, singles = stripify([tuple(map(int, t)) for t in T])
    out, entries = bytearray(), 0

    def vert(i):
        return struct.pack("<8f", *P[i], *N[i], *UV[i])
    for s in strips:
        out += struct.pack("<Ii", STRIP_FLAGS, len(s)) + b"".join(vert(i) for i in s)
        entries += len(s)
    if singles:
        out += struct.pack("<Ii", LIST_FLAGS, len(singles)) + b"".join(vert(i) for t in singles for i in t)
        entries += 3 * len(singles)
    return bytes(out), entries


def encode_object(pol: bytes, stock, P, N, UV, T, tex_index: int, t: dict) -> bytes:
    """One part object: header (flags 1, 1, bounding sphere), one atlas mesh, the terminator."""
    P, N, UV = (np.asarray(x, np.float32) for x in (P, N, UV))
    T = np.asarray(T, int).reshape(-1, 3)
    if not len(T):                                                # a part with nothing: one zero-area triangle
        P = np.zeros((3, 3), np.float32)
        N = np.tile(np.float32([0, 1, 0]), (3, 1))
        UV = np.zeros((3, 2), np.float32)
        T = np.array([[0, 1, 2]])
    data, entries = strip_data(P, N, UV, T)
    tmpl = next((m for m in stock.meshes if m.texture != 0xFFFFFFFF), stock.meshes[0])
    head = mesh_header(pol, tmpl, tex_index, t, P, len(data))
    c = (P.min(0) + P.max(0)) / 2
    r = float(np.linalg.norm(P - c, axis=1).max())
    return struct.pack("<II4f", 1, 1, *c, r) + head + data + struct.pack("<II", 0, entries)


def weld(P, N, UV, T):
    """Merge vertices with the same position and UV (normals averaged) so triangles share corners and strip."""
    P, N, UV = np.asarray(P, float), np.asarray(N, float), np.asarray(UV, float)
    T = np.asarray(T, int).reshape(-1, 3)
    if not len(P):
        return P, N, UV, T
    ext = float(np.ptp(P, 0).max()) or 1.0
    key = np.concatenate([np.round(P / (ext * 1e-5)), np.round(UV * 1e5)], 1).astype(np.int64)
    _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    Nn = np.zeros((len(first), 3))
    np.add.at(Nn, inv, N)
    ln = np.linalg.norm(Nn, axis=1, keepdims=True)
    Nn = np.where(ln > 1e-9, Nn / np.maximum(ln, 1e-9), N[first])
    T = inv[T]
    T = T[(T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])]
    return P[first], Nn, UV[first], T


def _decimate(P, N, UV, T, target: int):
    from .auf_swap import decimate
    T = np.asarray(T, int).reshape(-1, 3)
    if len(T) <= target:
        return P, N, UV, T
    Pm, F = decimate(np.asarray(P, float), T, max(1, target))
    used, inv = np.unique(F.reshape(-1), return_inverse=True)
    return Pm[used], np.asarray(N)[used], np.asarray(UV)[used], inv.reshape(-1, 3)


def _cap(P, N, UV, T, entries_cap: int):
    """Decimate until the strip encoding stays within entries_cap vertex entries."""
    T = np.asarray(T, int).reshape(-1, 3)
    while True:
        _d, n = strip_data(np.asarray(P, np.float32), np.asarray(N, np.float32), np.asarray(UV, np.float32), T) \
            if len(T) else (b"", 0)
        if n <= entries_cap or len(T) <= 1:
            return P, N, UV, T
        P, N, UV, T = _decimate(P, N, UV, T, int(len(T) * 0.85 * entries_cap / max(n, 1)))


def retarget(glb, joint_roles: dict, objs, names: dict, atlas_size: tuple,
             progress=None) -> tuple[dict, np.ndarray, dict]:
    """The donor cut and mapped into the stock driver's part frames: ({part: (P, N, UV, T)}, atlas rgba, info)."""
    from . import crazy_taxi_look as look
    from . import fit_events as FE
    progress = progress or (lambda p, m: None)
    m = look_measures(objs, names)
    d = look.load_donor(glb, joint_roles)
    parts_of = look.assign_parts(d)
    maps, info = look.part_maps(d, parts_of, m)
    parts_of = look.split_torso(d, parts_of, maps)
    if FE.active():
        FE.stage("scale", data={"donor_vertices": int(len(d.pos)), "donor_triangles": int(len(d.tris)),
                                "g": info.get("g"), "fit": "bones stretched to the stock driver's lengths"},
                 prims=[{"pos": d.pos, "tris": d.tris}])
    uv_ranges = {}
    for mi in sorted(set(int(x) for x in d.mat)):
        uv = d.uv[d.tris[d.mat == mi].reshape(-1)]
        if len(uv):
            uv_ranges[mi] = (float(uv[:, 0].min()), float(uv[:, 1].min()), float(uv[:, 0].max()), float(uv[:, 1].max()))
    progress(15, "Painting the texture atlas")
    atlas, regions = look.build_atlas(d.materials, uv_ranges, atlas_size)
    H, W = atlas.shape[:2]
    geo = look.part_geometry(d, parts_of, maps, regions, W, H, False)
    out = {}
    for part, (P, N, UV, T) in geo.items():                      # winding like the stock part's
        T = np.asarray(T, int).reshape(-1, 3)
        stock = c2._cloud(objs, names[part]) if part in names else None
        sv = signed_volume(np.asarray([p for mm in objs[names[part]].meshes for p in mm.pos]),
                           _stock_tris(objs[names[part]])) if stock is not None else 1.0
        if signed_volume(P, T) * sv < 0:
            T = T[:, [0, 2, 1]]
        out[part] = (np.asarray(P, float), np.asarray(N, float), np.asarray(UV, float), T)
    FE.stage("retarget", data={"parts": len(out), "triangles": int(sum(len(v[3]) for v in out.values())),
                               "fit": "per part into the stock joint frame (gbox.crazy_taxi_look.part_maps)", **info})
    return out, atlas, info


def _stock_tris(ob) -> np.ndarray:
    base, T = 0, []
    for mm in ob.meshes:
        T += [(a + base, b + base, c + base) for a, b, c in mm.tris]
        base += len(mm.pos)
    return np.asarray(T, int).reshape(-1, 3)


def write_pol(pol: bytes, tables: dict, geo: dict, tex_index: int, budget: int,
              progress=None) -> tuple[bytes, list, dict]:
    """The driver's pol file with the donor parts: (new pol, new slot offsets, report). Decimates uniformly until the
    file fits `budget` bytes."""
    from . import fit_events as FE
    progress = progress or (lambda p, m: None)
    objs = c2.walk(pol)
    names = c2.part_names(objs, tables["slots"])
    t = tables["textures"][tex_index]
    by_obj = {i: n for n, i in names.items()}
    base_geo = {}
    for i, n in by_obj.items():
        part = c2.joint_of(n)
        if "+" in n or part not in geo:
            base_geo[i] = None                                      # accessory / no donor part: zero-area triangle
        else:
            base_geo[i] = weld(*geo[part])
    # triangle budget per part in the stock driver's proportions: part target = stock triangles x k (never more than
    # the donor has); k shrinks until the file fits (the gesture hands then cost what the stock ones did)
    stock_tris = {i: max(4, objs[i].tris()) for i in base_geo}
    full = max((len(g[3]) / stock_tris[i] for i, g in base_geo.items() if g is not None), default=1.0)
    ratio, attempt = max(full, 1.0), 0
    while True:
        attempt += 1
        chunks, fitted, tris = [], {}, 0
        for i, ob in enumerate(objs):
            g = base_geo.get(i, "keep")
            if g == "keep":
                chunks.append(pol[ob.offset:(objs[i + 1].offset if i + 1 < len(objs) else len(pol))])
                continue
            if g is None:                                         # keeps its place (accessories stay off-joint)
                c = np.asarray(ob.centre, np.float32)
                chunks.append(encode_object(pol, ob, np.tile(c, (3, 1)), np.tile(np.float32([0, 1, 0]), (3, 1)),
                                            np.zeros((3, 2)), [(0, 1, 2)], tex_index, t))
                continue
            P, N, UV, T = g
            P, N, UV, T = _decimate(P, N, UV, T, max(4, int(stock_tris[i] * ratio)))
            P, N, UV, T = _cap(P, N, UV, T, MAX_OBJECT_ENTRIES)
            chunks.append(encode_object(pol, ob, P, N, UV, T, tex_index, t))
            fitted[by_obj[i]] = int(len(T))
            tris += len(T)
        new = b"".join(chunks)
        if len(new) <= budget or ratio < 0.05:
            break
        ratio *= min(0.9, (budget / len(new)) ** 1.1)
        progress(40 + min(30, 3 * attempt), f"Decimating to fit {budget} bytes ({len(new)} at {ratio:.2f})")
    if len(new) > budget:
        raise ValueError(f"the donor does not fit the driver's {budget}-byte buffer even at {ratio:.3f}")
    offs, o = [], 0
    for ch in chunks:
        offs.append(o)
        o += len(ch)
    remap = {ob.offset: offs[i] for i, ob in enumerate(objs)}
    slots = [remap[s] for s in tables["slots"]]
    FE.stage("decimate", data={"ratio": round(ratio, 4), "triangles": tris, "bytes": len(new), "budget": budget,
                               "attempts": attempt})
    return new, slots, {"ratio": round(ratio, 4), "triangles": tris, "bytes": len(new), "budget": budget,
                        "parts": fitted}


# ----------------------------------------------------------------------------------------------- validator

def validate(pol: bytes, tex: bytes, tables: dict, alloc: int | None, stock_names: dict | None = None) -> dict:
    """PowerVR / loader safety of one written driver (module doc). Raises ValueError listing every problem."""
    problems = []
    try:
        objs = c2.walk(pol)
    except ValueError as e:
        raise ValueError(f"pol does not walk: {e}") from None
    table = tables["textures"]
    if alloc is not None and len(pol) > alloc:
        problems.append(f"pol is {len(pol)} bytes, its buffer {alloc}")
    starts = {o.offset for o in objs}
    for s in tables["slots"]:
        if s not in starts:
            problems.append(f"slot offset {s:#x} is not an object")
    total = 0
    for t in table:
        if not (8 <= t["w"] <= 1024 and 8 <= t["h"] <= 1024) or t["w"] & (t["w"] - 1) or t["h"] & (t["h"] - 1):
            problems.append(f"texture {t['w']}x{t['h']} is not power-of-two 8..1024")
        total += t["size"]
    if total > VRAM:
        problems.append(f"textures {total} bytes exceed the 8 MB VRAM")
    try:
        c2.textures(tex, table)
    except ValueError as e:
        problems.append(f"textures: {e}")
    tris = 0
    for oi, ob in enumerate(objs):
        if ob.entries > MAX_OBJECT_ENTRIES:
            problems.append(f"object {oi}: {ob.entries} vertex entries > {MAX_OBJECT_ENTRIES}")
        for m in ob.meshes:
            pcw, isp, tsp, tcw = struct.unpack_from("<4I", pol, m.offset)
            if pcw >> 29 != 4:
                problems.append(f"mesh {m.offset:#x}: PCW {pcw:#x} is not a polygon parameter")
            if (pcw >> 24) & 7 not in (0, 2, 4):
                problems.append(f"mesh {m.offset:#x}: list type {(pcw >> 24) & 7}")
            if pcw & 0x08 and m.texture != 0xFFFFFFFF:
                if m.texture >= len(table):
                    problems.append(f"mesh {m.offset:#x}: texture {m.texture} outside the {len(table)}-entry table")
                else:
                    t = table[m.texture]
                    if (8 << ((tsp >> 3) & 7), 8 << (tsp & 7)) != (t["w"], t["h"]):
                        problems.append(f"mesh {m.offset:#x}: TSP size != texture {m.texture} {t['w']}x{t['h']}")
                    want = ((t["fmt"] in (2, 4, 0x11, 0x12)), (t["fmt"] in (3, 4, 0x10, 0x11)), t["pix"])
                    if (bool(tcw >> 31), bool((tcw >> 30) & 1), (tcw >> 27) & 7) != want:
                        problems.append(f"mesh {m.offset:#x}: TCW {tcw:#x} != texture {m.texture} format")
            P, UV = np.asarray(m.pos, float), np.asarray(m.uv, float)
            if len(P) and (not np.isfinite(P).all() or np.abs(P).max() > 1e4 or not np.isfinite(UV).all()):
                problems.append(f"mesh {m.offset:#x}: non-finite or huge vertices")
            tris += len(m.tris)
            p = m.offset + c2.MESH_HEADER
            end = p + struct.unpack_from("<I", pol, m.offset + 0x4C)[0]
            while p < end:
                fl, n = struct.unpack_from("<Ii", pol, p)
                if not fl & 0x08 and not 3 <= n < 0x10000:
                    problems.append(f"strip at {p:#x}: {n} vertices")
                if fl & 0x08 and not 1 <= n < 0x10000:
                    problems.append(f"list at {p:#x}: {n} triangles")
                p += 8
                for _ in range(3 * n if fl & 0x08 else n):
                    p += 8 if struct.unpack_from("<I", pol, p)[0] >> 28 == 5 else 32
    try:
        names = c2.part_names(objs, tables["slots"])
        if stock_names is not None and set(names) != set(stock_names):
            problems.append(f"part names differ: {sorted(set(names) ^ set(stock_names))}")
    except ValueError as e:
        problems.append(f"part names: {e}")
    if problems:
        raise ValueError("; ".join(problems[:12]))
    return {"objects": len(objs), "triangles": tris, "pol_bytes": len(pol), "buffer": alloc, "texture_bytes": total}


# ----------------------------------------------------------------------------------------------- 1ST_READ.BIN

def patch_slots(exe: bytes, va: int, slots: list[int]) -> bytes:
    o = va - c2.EXE_BASE
    b = bytearray(exe)
    struct.pack_into(f"<{len(slots)}I", b, o, *slots)
    return bytes(b)


# ----------------------------------------------------------------------------------------------- one driver

def write_driver(files: dict, glb, joint_roles: dict, key: str, progress=None) -> tuple[dict, dict]:
    """files {name: bytes} (1ST_READ.BIN + the driver's pol/tex, both detail levels) -> (changed files, report)."""
    from . import fit_events as FE
    progress = progress or (lambda p, m: None)
    exe = files["1ST_READ.BIN"]
    out, report = {}, {"driver": c2.DRIVERS[key], "key": key, "levels": {}}
    for high in (True, False):
        stem = key + ("H" if high else "")
        pol, tex = files[f"POL{stem}.BIN"], files[f"TEX{stem}.BIN"]
        tables = c2.player_tables(exe, key, high)
        if tables.get("alloc") is None or "va" not in tables:
            raise ValueError("the writer needs a known 1ST_READ.BIN build (crazy_taxi2.KNOWN_TABLES)")
        objs = c2.walk(pol)
        names = c2.part_names(objs, tables["slots"])
        slot = atlas_slot(tables["textures"])
        t = tables["textures"][slot]
        progress(10 if high else 55, f"{c2.DRIVERS[key]} ({'high' if high else 'race'} detail): retargeting")
        geo, atlas, info = retarget(glb, joint_roles, objs, names, (max(64, t["w"]), max(64, t["h"])), progress)
        FE.stage("weights", data={"mode": "rigid per part (each part rides its own joint)", "parts": len(geo)})
        new_pol, slots, rep = write_pol(pol, tables, geo, slot, tables["alloc"], progress)
        new_tex = write_texture(tex, tables["textures"], slot, atlas)
        exe = patch_slots(exe, tables["va"]["slots"], slots)
        check = validate(new_pol, new_tex, {"slots": slots, "textures": tables["textures"]}, tables["alloc"], names)
        FE.stage("encode", data={"file": f"POL{stem}.BIN", **check, "atlas_slot": slot,
                                 "atlas": [t["w"], t["h"], t["pix"], t["fmt"]]})
        out[f"POL{stem}.BIN"], out[f"TEX{stem}.BIN"] = new_pol, new_tex
        report["levels"][stem] = rep | {"check": check, "atlas_slot": slot, "atlas": [t["w"], t["h"]], "fit": info}
    out["1ST_READ.BIN"] = exe
    return out, report


def write_drivers(files: dict, glb, joint_roles: dict, keys: list[str], progress=None) -> tuple[dict, dict]:
    progress = progress or (lambda p, m: None)
    cur, reports = dict(files), {}
    for i, k in enumerate(keys):
        new, rep = write_driver(cur, glb, joint_roles, k,
                                lambda p, m, i=i: progress((100 * i + p) / len(keys), m))
        cur.update(new)
        reports[k] = rep
    changed = {n: b for n, b in cur.items() if files.get(n) != b}
    return changed, reports


def driver_file_names(keys) -> list[str]:
    return ["1ST_READ.BIN"] + [f"{kind}{k}{h}.BIN" for k in keys for h in ("", "H") for kind in ("POL", "TEX")]


def readback(files: dict, keys) -> dict:
    """The written files through the reader: every driver assembles (rigged, textured) from the patched tables."""
    out = {}
    for k in keys:
        for high in (True, False):
            stem = k + ("H" if high else "")
            t = c2.player_tables(files["1ST_READ.BIN"], k, high)
            a = c2.assemble(files[f"POL{stem}.BIN"], files[f"TEX{stem}.BIN"], t)
            out[stem] = {"parts": len(a["parts"]), "triangles": int(sum(len(p["tris"]) for p in a["parts"]))}
    return out


# ----------------------------------------------------------------------------------------------- mod + tool

def writer_fingerprint() -> str:
    return hashlib.sha256(Path(__file__).read_bytes() + Path(c2.__file__).read_bytes()).hexdigest()[:16]


def build_mod(gdi, glb, joint_roles: dict, keys: list[str], out_dir, name: str, progress=None) -> dict:
    """A copied GD-ROM with the drivers written (gdrom.patch_gdi), read back before it is reported."""
    from .gdrom import GDRom, patch_gdi
    progress = progress or (lambda p, m: None)
    if Path(gdi).suffix.lower() != ".gdi":
        raise ValueError("the Crazy Taxi 2 writer builds GD-ROM copies; this image is a .cdi (read-only here). Use "
                         "the retail GD-ROM (catalog b5dfa0c44de0ba90, HyperSpin Crazy Taxi 2 (USA).chd)")
    disc = GDRom(str(gdi))
    files = {n: disc.read(n) for n in driver_file_names(keys)}
    changed, reports = write_drivers(files, glb, joint_roles, keys, lambda p, m: progress(0.8 * p, m))
    progress(82, "Writing the GD-ROM copy")
    image = patch_gdi(gdi, out_dir, name, changed, progress)
    back = GDRom(str(image))
    for n, b in changed.items():
        if back.read(n) != b:
            raise AssertionError(f"{n} did not read back from the written image")
    rb = readback({**files, **changed}, keys)
    return {"image": Path(image), "files": sorted(changed), "reports": reports, "readback": rb}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Crazy Taxi 2 (DC): the library character as one driver (driver:<name>, player = Slash)
    or all eight (drivers), in a copied GD-ROM mod ct2_<slug>_<slot>."""
    from . import characters as C, filemods
    keys = parse_slot(inp.slot)
    tag = "drivers" if len(keys) > 1 else c2.SLUGS[keys[0]]
    name = f"ct2_{meta['slug']}_{tag}"
    out = filemods.mod_dir(ctx.config, game["game_id"], name)
    try:
        cached = json.loads((out / ".gbox-mod.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    result = None
    if inp.rebuild or cached.get("writer_sha256") != writer_fingerprint():
        joint_roles = dict((meta.get("rig") or {}).get("roles") or {})
        from .crazy_taxi import resolve_roles
        resolve_roles(joint_roles)
        glb = C._local_or_fetch(ctx, meta, meta["model"])
        gdi = C._dc_gdi(ctx, game)
        res = build_mod(gdi, glb, joint_roles, keys, out, name, ctx.progress)
        marker = {"name": name, "game_id": game["game_id"], "image": Path(res["image"]).name, "files": res["files"],
                  "character": meta["slug"], "slot": inp.slot or "player", "writer": "gbox.crazy_taxi2_swap",
                  "writer_sha256": writer_fingerprint(), "built_at": time.time(),
                  "report": {k: {s: {kk: v for kk, v in lv.items() if kk != "fit"} for s, lv in r["levels"].items()}
                             for k, r in res["reports"].items()}, "readback": res["readback"]}
        (out / ".gbox-mod.json").write_text(json.dumps(marker, default=str), encoding="utf-8")
        result = {"files": res["files"], "readback": res["readback"]}
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": game["game_id"], "slot": inp.slot or "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"Crazy Taxi 2 native driver rebuild ({', '.join(c2.DRIVERS[k] for k in keys)}); "
                              "unverified in game."})
    launch = C._launch(ctx, game["game_id"], name, C.HOST_OS) if inp.launch else None
    return {"status": "built_unverified", "mod": name, "build": result, "drivers": [c2.DRIVERS[k] for k in keys],
            "launch": launch, "gameplay_verified": False, "replacement_kind": "native_rom"}


def main(argv=None) -> int:
    """python -m gbox.crazy_taxi2_swap <disc.gdi|disc dir> <character dir (meta.json + model)> <slot> <out dir>
    [--image NAME]: writes the changed files + report.json (and with --image a GD-ROM copy)."""
    import argparse
    ap = argparse.ArgumentParser(description="Crazy Taxi 2 (DC) driver writer")
    ap.add_argument("source", help="a .gdi, or a folder of extracted disc files")
    ap.add_argument("character")
    ap.add_argument("slot")
    ap.add_argument("out", type=Path)
    ap.add_argument("--image", help="also build a GD-ROM copy with this name (source must be a .gdi)")
    a = ap.parse_args(argv)
    keys = parse_slot(a.slot)
    meta = json.loads((Path(a.character) / "meta.json").read_text(encoding="utf-8"))
    glb, roles = Path(a.character) / meta["model"], meta["rig"]["roles"]
    log = lambda p, m: print(f"{p:5.1f}% {m}", flush=True)       # noqa: E731
    t0 = time.time()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.image:
        res = build_mod(a.source, glb, roles, keys, a.out, a.image, log)
        report = {"image": str(res["image"]), "reports": res["reports"], "readback": res["readback"]}
    else:
        src = Path(a.source)
        if src.suffix.lower() == ".gdi":
            from .gdrom import GDRom
            d = GDRom(str(src))
            files = {n: d.read(n) for n in driver_file_names(keys)}
        else:
            files = {n: (src / n).read_bytes() for n in driver_file_names(keys)}
        changed, reports = write_drivers(files, glb, roles, keys, log)
        for n, b in changed.items():
            (a.out / n).write_bytes(b)
        report = {"files": sorted(changed), "reports": reports, "readback": readback({**files, **changed}, keys)}
    (a.out / "report.json").write_text(json.dumps(report | {"seconds": round(time.time() - t0, 1)}, indent=1,
                                                  default=str))
    print(json.dumps(report.get("readback"), indent=1), f"\n{round(time.time() - t0, 1)} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
