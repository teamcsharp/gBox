"""Resident Evil 4 PS2 (SLUS-21134, #1321): native model reader.

Decodes the PS2-native BIN mesh and TPL texture list that ``re4ps2_model`` only headers,
and exports an editable GLB.  Everything is pinned to the owned boot ELF / pl00.dat, not
guessed: the BIN is a VIF/VU1 stream (0x30-byte header, bone table, then per-object DMA
chains), the TPL is a 0x1000-tagged texture list whose C4/C8 images and CLUT palettes use
the PS2 GS swizzle.

Layout facts (derived in the analysis stage, ``re4ps2_model``):
  * BIN header (little-endian) -> ``re4ps2_model.bin_header``: 0x30 header, u32 bone-table
    offset at +4, u8 bone count at +9, u16 object count at +0xA, u32 packet-data offset at
    +0xC, u32 after-bones table at +0x1C, u32 bbox offset at +0x28.  Bones are the GC
    layout: 16 B {u8 id, u8 parent (0xFF root), 2 pad, f32 x, y, z} relative to the parent.
  * Object table: ``object_count`` 16-byte records at the packet-data offset; +0xC of each
    record is the offset of that object's packet.  A packet is 16 bytes of bone-list, then
    one or more DMA chains.  Each chain part is, in order:
        1. tag {qwc+id, addr, STCYCL 4/4, UNPACK V4-32 num=W} -> W/2 skin entries,
           each {4x u8 bone base, 4x f32 blend weights}.
        2. tag {..., UNPACK V4-32 num=1}  -> one qword: low u8 = triangle count,
           f32 +3 = 0x3D800000 = 1/16 (the position scale).
        3. tag {..., UNPACK V4-16 num=V}  -> V vertices of 4x s16 = {x, y, z, skin}.
           V == 3 * triangle_count, so the mesh is a non-indexed triangle list.
    The tags are CNT (id 1) and the last vertex tag of a part is REF (id 6); the payload
    is always inline and contiguous, ``qwc`` quadwords per tag.

The skin index on each vertex selects a matrix in the VU1 palette derived from the weight
table; resolving that palette needs the VU1 microprogram (.DVP.overlay), which is the next
step.  Here the raw skin index is preserved as a ``_SKINID`` attribute and the mesh is
exported un-skinned (positions + flat normals) alongside the bone hierarchy.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from .re4ps2_model import bin_header, dat_slots, slot_bytes, tpl_header, GX_FORMATS

# ---------------------------------------------------------------- PS2 GS swizzle

def _unswizzle(data: bytes, w: int, h: int, bpp: int) -> bytearray:
    """Unswizzle a PS2 GS 'swizzled' texture (8x8 blocks, 4-block columns).

    bpp is 4 or 8.  The swizzled image is 8x8-pixel blocks; blocks are grouped into
    32-pixel columns (4 blocks wide), stacked vertically within a column, and the columns
    run left to right.  Pixels inside a block are row-major.  Returns one index byte per
    pixel (0-255 for 8bpp, 0-15 for 4bpp).
    """
    if w % 8 or h % 8:
        raise ValueError(f"swizzle needs 8-multiple dimensions, got {w}x{h}")
    npx = w * h
    out = bytearray(npx)
    for y in range(h):
        for x in range(w):
            bx, px = divmod(x, 8)
            by, py = divmod(y, 8)
            col, in_col = divmod(bx, 4)
            block = (col * (h >> 3) + by) * 4 + in_col
            if bpp == 8:
                out[y * w + x] = data[block * 64 + py * 8 + px]
            else:
                byte = data[block * 32 + (py * 8 + px) // 2]
                out[y * w + x] = (byte >> 4) & 0xF if (px & 1) == 0 else byte & 0xF
    return out


def _clut(data: bytes, n: int) -> list[tuple[int, int, int, int]]:
    """De-swizzle a PS2 GS CLUT (16-entry rows of 8 real colours + 8 pad).

    Colour words are PSMCT32, little-endian 0xAARRGGBB.
    """
    words = struct.unpack_from(f"<{n * 2}I", data)
    return [(words[(i % 8) + (i // 8) * 16] >> 16 & 0xFF,
             words[(i % 8) + (i // 8) * 16] >> 8 & 0xFF,
             words[(i % 8) + (i // 8) * 16] & 0xFF,
             words[(i % 8) + (i // 8) * 16] >> 24 & 0xFF) for i in range(n)]


def _png_bytes(rgba: bytes, w: int, h: int) -> bytes:
    """Minimal PNG encoder (RGBA8, no deps) for writing decoded textures."""
    import zlib

    def chunk(ty, data):
        return struct.pack(">I", len(data)) + ty + data + struct.pack(">I", zlib.crc32(ty + data) & 0xFFFFFFFF)

    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- TPL decode

def _decode_texture(t: bytes, rec: dict) -> dict:
    w, h, fmt = rec["w"], rec["h"], rec["format"]
    img, pal = rec["image_offset"], rec["palette_offset"]
    rgba = bytearray(w * h * 4)
    if fmt == 8:                                   # C4: 4-bit indices, 16-colour CLUT
        idx = _unswizzle(t[img:], w, h, 4)
        clut = _clut(t[pal:], 16)
        for p in range(w * h):
            r, g, b, a = clut[idx[p]]
            rgba[p * 4:p * 4 + 4] = bytes((r, g, b, a))
    elif fmt == 9:                                 # C8: 8-bit indices, 256-colour CLUT
        idx = _unswizzle(t[img:], w, h, 8)
        clut = _clut(t[pal:], 256)
        for p in range(w * h):
            r, g, b, a = clut[idx[p]]
            rgba[p * 4:p * 4 + 4] = bytes((r, g, b, a))
    elif fmt == 4:                                 # RGB565
        raw = t[img:img + w * h * 2]               # linear 16bpp (PSMCT16 swizzle unproven)
        for p in range(w * h):
            v = struct.unpack_from("<H", raw, p * 2)[0]
            rgba[p * 4:p * 4 + 4] = bytes(((v >> 11 & 0x1F) << 3, (v >> 5 & 0x3F) << 2, (v & 0x1F) << 3, 255))
    elif fmt == 6:                                 # RGBA8 (linear on PS2)
        for p in range(w * h):
            rgba[p * 4:p * 4 + 4] = t[img + p * 4:img + p * 4 + 4]
    else:
        raise ValueError(f"unhandled GX texture format {GX_FORMATS.get(fmt, hex(fmt))}")
    return {**rec, "rgba": bytes(rgba)}


def decode_tpl(t: bytes) -> list[dict]:
    h = tpl_header(t)
    return [_decode_texture(t, r) for r in h["textures"]]


# ---------------------------------------------------------------- BIN decode

_VIF_UNPACK = {0x60: ("S", 32), 0x64: ("V2", 32), 0x65: ("V2", 16), 0x68: ("V3", 32),
               0x69: ("V3", 16), 0x6C: ("V4", 32), 0x6D: ("V4", 16), 0x6E: ("V4", 8)}


def bin_mesh(b: bytes) -> dict:
    """Full parse of a BIN: bones, objects, and each object's mesh parts (skin table,
    triangle count + scale, and the raw V4-16 vertex stream)."""
    h = bin_header(b)
    out = {"bones": h["bones"], "bbox": h["bbox"], "objects": []}
    packets = []
    for i in range(h["object_count"]):
        rec = b[h["data_offset"] + 16 * i:h["data_offset"] + 16 * i + 16]
        packets.append(struct.unpack_from("<I", rec, 12)[0])
    for i, pkt in enumerate(packets):
        bound = packets[i + 1] if i + 1 < len(packets) else len(b)
        obj = {"index": i, "record": b[h["data_offset"] + 16 * i:h["data_offset"] + 16 * i + 16].hex(),
               "packet": pkt, "bone_list": list(b[pkt:pkt + 16]), "parts": []}
        o = pkt + 16
        part = None
        while o + 16 <= bound:
            qwc_id, _addr, v0, v1 = struct.unpack_from("<4I", b, o)
            qwc, tid = qwc_id & 0xFFFF, (qwc_id >> 28) & 7
            vif = []
            for wd in (v0, v1):
                cmd, num, imm = (wd >> 24) & 0x7F, (wd >> 16) & 0xFF, wd & 0xFFFF
                if cmd >= 0x60:
                    vn, vl = _VIF_UNPACK.get(cmd, ("?", 0))
                    vif.append({"cmd": "UNPACK", "fmt": f"{vn}-{vl}", "num": num or 256,
                                "addr": imm & 0x3FF, "usn": bool(imm & 0x4000), "flg": bool(imm & 0x8000)})
                else:
                    vif.append({"cmd": {1: "STCYCL"}.get(cmd, hex(cmd)), "imm": imm})
            payload = b[o + 16:o + 16 + qwc * 16]
            o += 16 + qwc * 16
            up = next((v for v in vif if v["cmd"] == "UNPACK"), None)
            if up is None:                                      # control tag (MSCNT/NOP): skip
                continue
            if up["fmt"] == "V4-32":
                if part is None:
                    part = {"skin": [], "param": None, "vertices": []}
                if up["num"] == 1 and len(payload) >= 16:            # param qword
                    part["param"] = {"triangle_count": payload[0],
                                     "scale": struct.unpack_from("<f", payload, 12)[0]}
                else:                                                # weight table (n/2 skin entries)
                    for k in range(up["num"] // 2):
                        part["skin"].append({"bones": list(payload[k * 32:k * 32 + 4]),
                                             "weights": list(struct.unpack_from("<4f", payload, k * 32 + 16))})
            elif up["fmt"] == "V4-16":
                if part is not None and part.get("param") is not None:
                    step = 8
                    part["vertices"] = [struct.unpack_from("<4h", payload, k * step)
                                        for k in range(up["num"])]
                    obj["parts"].append(part)
                    part = None
            if tid == 7:                                             # END
                break
        out["objects"].append(obj)
    return out


def _flat_normals(parts: list[dict], scale: float) -> tuple[list[float], list[float], list[int]]:
    """Triangle-list positions (scaled) and per-vertex flat normals, plus raw skin ids."""
    pos, nrm, skin = [], [], []
    for part in parts:
        v = part["vertices"]
        for t in range(0, len(v) - 2, 3):
            a, bb, c = v[t], v[t + 1], v[t + 2]
            ax, ay, az = a[0] * scale, a[1] * scale, a[2] * scale
            bx, by, bz = bb[0] * scale, bb[1] * scale, bb[2] * scale
            cx, cy, cz = c[0] * scale, c[1] * scale, c[2] * scale
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            ln = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
            nx, ny, nz = nx / ln, ny / ln, nz / ln
            for p in (a, bb, c):
                pos += [p[0] * scale, p[1] * scale, p[2] * scale]
                nrm += [nx, ny, nz]
                skin.append(p[3])
    return pos, nrm, skin


# ---------------------------------------------------------------- GLB export

def _glb(json_obj: dict, buffers: list[bytes]) -> bytes:
    js = json.dumps(json_obj, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    bin_blob = b"".join(buffers)
    bin_blob += b"\0" * ((4 - len(bin_blob) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_blob)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(bin_blob), 0x004E4942) + bin_blob
    return bytes(out)


def to_glb(bin_bytes: bytes, tpl_bytes: bytes | None = None) -> bytes:
    """Export a BIN (+ optional TPL) to a glTF 2.0 binary (GLB).

    Skeleton bones become a node hierarchy (TRS from the parent-relative translation);
    every object's triangles become one static mesh (positions, flat normals) with the raw
    skin id kept as a _SKINID attribute.
    """
    m = bin_mesh(bin_bytes)
    nodes, children = [], []
    bone_node = {b["id"]: i for i, b in enumerate(m["bones"])}
    for b in m["bones"]:
        nodes.append({"name": f"bone_{b['id']}", "translation": b["t"]})
        children.append([])
    roots = []
    for b in m["bones"]:
        if b["parent"] == 0xFF:
            roots.append(bone_node[b["id"]])
        else:
            children[bone_node[b["parent"]]].append(bone_node[b["id"]])
    for i, ch in enumerate(children):
        if ch:
            nodes[i]["children"] = ch
    scene_nodes = list(roots)

    pos = []; nrm = []; skin = []; scale = 1.0 / 16.0
    for obj in m["objects"]:
        p, n, s = _flat_normals(obj["parts"], scale)
        pos += p; nrm += n; skin += s

    buffers, accessors, views = [], [], []
    def add_accessor(comps, ctype, arr):
        raw = struct.pack(f"<{len(arr)}{ctype}", *arr)
        off = len(b"".join(buffers))
        buffers.append(raw)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw)})
        accessors.append({"bufferView": len(views) - 1, "componentType": {"f": 5126, "h": 5122, "H": 5123}[ctype],
                          "count": len(arr) // comps, "type": {1: "SCALAR", 3: "VEC3"}[comps],
                          "min": [min(arr[i::comps]) for i in range(comps)],
                          "max": [max(arr[i::comps]) for i in range(comps)]})

    prims = []
    if pos:
        add_accessor(3, "f", pos)
        add_accessor(3, "f", nrm)
        add_accessor(1, "h", skin)
        prims = [{"attributes": {"POSITION": 0, "NORMAL": 1, "_SKINID": 2}}]

    meshes = [{"primitives": prims}] if prims else []
    if meshes:                                   # a mesh must be instanced by a scene node
        nodes.append({"name": "leon_mesh", "mesh": 0})
        scene_nodes.append(len(nodes) - 1)
    gltf = {"asset": {"version": "2.0"}, "scenes": [{"nodes": scene_nodes}],
            "nodes": nodes, "meshes": meshes, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": sum(len(x) for x in buffers)}]}
    return _glb(gltf, buffers)


def export_leon(pack: bytes, bin_slot: int = 0, tpl_slot: int = 1) -> dict:
    """Decode the (bin_slot, tpl_slot) DAT pair of a pack into meshes + textures."""
    bin_bytes = slot_bytes(pack, bin_slot)
    tpl_bytes = slot_bytes(pack, tpl_slot) if tpl_slot is not None else None
    return {"mesh": bin_mesh(bin_bytes),
            "textures": decode_tpl(tpl_bytes) if tpl_bytes is not None else [],
            "glb": to_glb(bin_bytes, tpl_bytes)}


# ---------------------------------------------------------------- DEDICATED reader

def roster() -> list[dict]:
    """RE4 PS2 model slots: player pl00-pl1a and enemy em00-em4f (pl00 = Leon default)."""
    from .re4ps2_inventory import KNOWN
    out = []
    for cid in [f"pl{i:02x}" for i in range(0x1B)] + [f"em{i:02x}" for i in range(0x50)]:
        out.append({"key": cid, "slug": f"re4ps2_{cid}", "name": KNOWN.get(cid, cid.upper()),
                    "aliases": [cid, cid.upper()], "kind": "character"})
    return out


def _resolve_source(ctx, game: dict) -> str:
    for p in game.get("source_paths") or []:
        pp = Path(p)
        if pp.exists() and pp.suffix.lower() in (".cso", ".iso"):
            return str(pp)
    cached = Path(ctx.config.cache) / "modbase" / game["game_id"] / "Resident Evil 4 (USA).iso"
    if cached.exists():
        return str(cached)
    raise FileNotFoundError(f"no RE4 PS2 disc image for {game.get('game_id')}")


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """DEDICATED runner: export one RE4 PS2 character (BIN#0 body + TPL#1 textures) to GLB."""
    from .re4ps2_inventory import read_char_dat
    work = Path(work)
    pack = read_char_dat(_resolve_source(ctx, game), e["key"])
    res = export_leon(pack, 0, 1)
    glb = work / "model.glb"
    glb.write_bytes(res["glb"])
    files = [str(glb)]
    for i, t in enumerate(res["textures"]):
        p = work / f"tex{i}.png"
        p.write_bytes(_png_bytes(t["rgba"], t["w"], t["h"]))
        files.append(str(p))
    return {"files": files, "tool": "gbox.re4ps2_reader", "source_files": [f"{e['key']}.dat"],
            "notes": "PS2-native BIN mesh (VU1 V4-16 stream, 1/16 fixed-point positions) + TPL C4/C8 "
                     "textures -> GLB with skeleton + flat normals + raw _SKINID. UV / normal / skin-matrix "
                     "resolution needs the VU1 microprogram (next step)."}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("dat")
    ap.add_argument("--bin", type=int, default=0)
    ap.add_argument("--tpl", type=int, default=1)
    ap.add_argument("--glb")
    ap.add_argument("--png-prefix")
    a = ap.parse_args()
    res = export_leon(open(a.dat, "rb").read(), a.bin, a.tpl)
    if a.glb:
        open(a.glb, "wb").write(res["glb"])
        print(f"wrote {a.glb} ({len(res['glb'])} bytes, {len(res['mesh']['bones'])} bones, "
              f"{sum(len(o['parts']) for o in res['mesh']['objects'])} parts)")
    if a.png_prefix:
        from zlib import crc32
        for i, t in enumerate(res["textures"]):
            w, h = t["w"], t["h"]
            def chunk(ty, data):
                return struct.pack(">I", len(data)) + ty + data + struct.pack(">I", crc32(ty + data) & 0xFFFFFFFF)
            raw = b"".join(b"\0" + t["rgba"][y * w * 4:(y + 1) * w * 4] for y in range(h))
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) \
                + chunk(b"IDAT", __import__("zlib").compress(raw)) + chunk(b"IEND", b"")
            open(f"{a.png_prefix}{i}.png", "wb").write(png)
            print(f"wrote {a.png_prefix}{i}.png {w}x{h}")
