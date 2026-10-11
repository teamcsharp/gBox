"""Dead or Alive 2 - Limited Edition (Japan) (Dreamcast) character assets: CHR mesh + BIN texture readers.

Ghidra-verified facts (analysis in docs/doa2_re_findings.md; 1ST_READ.BIN sha256
27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1, unscrambled, loads at 0x8C010000,
SuperH4:LE:32:default; NaomiLib NL1 model grammar cross-checked against the format references and
the owned KAS00/AYA00/GEN00 archives):

  CHR header (u32 LE): [0]=24, [1]=model-pointer-table offset, [2]=TEXTURE-descriptor-table offset,
    [3]=n_models, [4]=n_textures, [5]=0, [6]=1, [7]=1, [8]=0.  Model 0 starts at file offset 24
    (its first 24 bytes {2I flags, 4f sphere} overlap what the first reader slice mislabeled
    "character scale floats"); word[4] and the 12-byte tail table are TEXTURES, not bones.
  Model pointers are ABSOLUTE SH-4 work-RAM addresses: fighters (KAS/AYA/GEN/...) base 0x0C300000,
  system CHR (EFC0/FIX) base 0x0C400000; file offset = ptr - base + 24.
  Each model: {u32 global0, u32 global1, 4f bounding-sphere}, then submeshes until a {0, vertex_count}
  end marker (count must equal the walked inline+referenced vertex total) and zero padding.
  Each submesh: 80-byte native material header (word0>>29==4; +32 texture id, +36 shader, +76 payload
  length), then strip blocks {u32 flags, u32 count}: flags&8 = indexed triangle list (count triples),
  else triangle strip of count vertices; flags&3 = culling mode. Vertex records: inline (32 B:
    3f pos, 3f normal, 2f uv at +24; 56 B for shader -2; shader -3 packs the normal as 3 signed bytes)
  or 8-B back-references {0x5ff000xx tag, i32 rel} to an earlier inline record in the same submesh.
  Texture descriptors (12 B each): [u16 width, u16 height][u8 pixel, u8 format, u16 pad][u32 address];
  addresses are relative to the first texture's address and index the costume .BIN payload
  (sizes sum exactly to the BIN length: KAS00 55 textures -> 332,800 B).  pixel 0/1/2 =
  ARGB1555/RGB565/ARGB4444; format 1/0xD = twiddled 16-bit, 3 = 8-bit VQ (256-entry codebook).

This module is the READER: parse and decode read-only (owned disc, never written). The native writer
route lives in the doa2_swap stack (PR #8); the rig/skeleton is NOT in CHR (SUP/ACS carry it).
"""
from __future__ import annotations

import struct
from pathlib import Path

GAME_IDS = {"1de2e7634f3161ff": "Dead or Alive 2 - Limited Edition (Japan)"}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


# --------------------------------------------------------------------------- containers
def parse_chr(data: bytes) -> dict:
    """Parse a DOA2 LE JP .CHR archive header. Corrected layout: word[4]/tail table describe
    TEXTURES (12-byte descriptors), not bones (the first reader slice misread this)."""
    if len(data) < 0x40:
        raise ValueError("too small for a CHR header")
    hdr = [u32(data, o) for o in range(0, 0x18, 4)]
    if hdr[0] != 24:
        raise ValueError(f"unexpected header size {hdr[0]}")
    tbl, tex_tbl, n_obj, n_tex = hdr[1], hdr[2], hdr[3], hdr[4]
    if not (0 < n_obj < 0x1000 and 0 <= n_tex < 0x1000):
        raise ValueError(f"implausible counts n_models={n_obj} n_textures={n_tex}")
    if tbl + 4 * n_obj > tex_tbl or tex_tbl + 12 * n_tex > len(data):
        raise ValueError("pointer tables outside the archive")
    ptrs = [u32(data, tbl + 4 * i) for i in range(n_obj)]
    base = min(ptrs)
    if base >> 24 not in (0x0C,):                       # absolute SH-4 address in work RAM
        raise ValueError(f"model table not absolute pointers (min {base:#x})")
    objs = [p - base + 24 for p in ptrs]                # -> file offsets (model 0 == 24)
    if objs != sorted(set(objs)) or objs[0] != 24:
        raise ValueError("non-monotonic model pointers")
    return {"n_objects": n_obj, "n_textures": n_tex, "ptr_base": base, "objects": objs,
            "model_table": tbl, "texture_table": tex_tbl,
            "model0_sphere": [round(f32(data, 32 + 4 * k), 5) for k in range(4)]}


def texture_size(width: int, height: int, pixel: int, fmt: int) -> int:
    """Native BIN payload size for one texture (VQ carries a 256-entry codebook)."""
    if pixel not in (0, 1, 2):
        raise ValueError(f"unsupported pixel format {pixel:#x}")
    if fmt == 3:
        return 2048 + width * height // 4
    if fmt in (1, 0x0D):
        return 2 * width * height
    raise ValueError(f"unsupported texture format {fmt:#x}")


def parse_textures(chr_data: bytes, bin_size: int) -> list[dict]:
    """Texture descriptors from the CHR tail; each addresses the costume .BIN (relative to the
    first texture). Validates power-of-two dimensions and BIN-allocation fit."""
    info = parse_chr(chr_data)
    raw = [struct.unpack_from("<III", chr_data, info["texture_table"] + 12 * i)
           for i in range(info["n_textures"])]
    base = raw[0][2] if raw else 0
    out = []
    for i, (wh, flags, addr) in enumerate(raw):
        w, h = wh & 0xFFFF, wh >> 16
        pixel, fmt = flags & 0xFF, (flags >> 8) & 0xFF
        if not w or not h or w & (w - 1) or h & (h - 1) or w > 4096 or h > 4096:
            raise ValueError(f"invalid texture dimensions at slot {i}: {w}x{h}")
        size = texture_size(w, h, pixel, fmt)
        off = addr - base
        end = (raw[i + 1][2] - base) if i + 1 < len(raw) else bin_size
        if off < 0 or end < off or end > bin_size or off + size > end:
            raise ValueError(f"texture {i} exceeds its BIN allocation")
        out.append({"index": i, "width": w, "height": h, "pixel": pixel, "format": fmt,
                    "offset": off, "size": size, "capacity": end - off})
    return out


def parse_sup(data: bytes) -> dict:
    """SUP: offset table then records of float data (physics supplement)."""
    offs = []
    o = 0
    while o < len(data) - 4 and (len(offs) == 0 or offs[-1] != 0):
        offs.append(u32(data, o))
        o += 4
    offs = offs[:-1] if offs and offs[-1] == 0 else offs
    recs = []
    for i, r in enumerate(offs):
        n = (offs[i + 1] - r) if i + 1 < len(offs) else len(data) - r
        if 0 < n <= 0x1000:
            recs.append([round(f32(data, r + 4 * k), 4) for k in range(n // 4)])
    return {"n_records": len(recs), "records": recs}


def parse_mot_table(data: bytes) -> dict:
    """MOT: leading u32 offset table (0 ends?), offsets into per-clip blobs."""
    offs = []
    o = 0
    while o < min(len(data), 0x4000):
        v = u32(data, o)
        if v == 0 or v >= len(data):
            break
        offs.append(v)
        o += 4
    return {"n_clips": len(offs), "offsets": offs}


# --------------------------------------------------------------------------- mesh decode
def _triangles(flags: int, indices: list[int]) -> list[tuple[int, int, int]]:
    culling = flags & 3
    if flags & 8:                                        # indexed list: count triples
        triples: list[tuple[int, int, int]] = [(indices[k], indices[k + 1], indices[k + 2])
                                               for k in range(0, len(indices), 3)]
        if culling == 2:
            triples = [(y, x, z) for x, y, z in triples]
    else:                                                # strip
        triples = []
        for k in range(len(indices) - 2):
            x, y, z = indices[k:k + 3]
            if (k % 2 == 0) == (culling == 2):
                x, y = y, x
            triples.append((x, y, z))
    return [t for t in triples if len(set(t)) == 3]


def parse_meshes(chr_data: bytes) -> dict:
    """Decode every NL1 model in a CHR: submeshes (80-B native material headers), strips,
    inline/referenced vertices (pos/normal/uv) and triangles. Validates each model's
    {0, vertex_count} end marker and rejects non-finite floats."""
    import math

    info = parse_chr(chr_data)
    objs, count = info["objects"], info["n_objects"]
    limit0 = info["model_table"]
    models = []
    for mid, start in enumerate(objs):
        model_limit = objs[mid + 1] if mid + 1 < count else limit0
        limit = model_limit - 8 if mid + 1 < count else limit0
        if start + 24 > limit:
            raise ValueError(f"model {mid} too short at {start:#x}")
        gp0, gp1 = struct.unpack_from("<2I", chr_data, start)
        sphere = struct.unpack_from("<4f", chr_data, start + 8)
        cursor = start + 24
        meshes, vertex_total, tri_total = [], 0, 0
        while cursor + 4 <= limit and u32(chr_data, cursor):
            if cursor + 80 > limit:
                raise ValueError(f"truncated submesh header at {cursor:#x}")
            header = chr_data[cursor:cursor + 80]
            if u32(header, 0) >> 29 != 4:
                raise ValueError(f"unsupported native parameter word at {cursor:#x}")
            texture_id = struct.unpack_from("<i", header, 32)[0]
            shader = struct.unpack_from("<i", header, 36)[0]
            length = u32(header, 76)
            position = cursor + 80
            stop = position + length
            if stop > model_limit:
                raise ValueError("submesh crosses model boundary")
            vertices, strips, triangles = [], [], []
            registered = {}
            while position < stop:
                if position + 8 > stop:
                    raise ValueError("short strip header")
                flags, n = struct.unpack_from("<2I", chr_data, position)
                if flags > 0x1FF or not 0 < n <= 65536:
                    raise ValueError(f"invalid strip at {position:#x}")
                logical = n * (3 if flags & 8 else 1)
                indices = []
                position += 8
                for _ in range(logical):
                    if position + 4 > stop:
                        raise ValueError("short vertex record")
                    tag = u32(chr_data, position)
                    if 0x5FF00000 <= tag <= 0x5FFFFFFF:   # back-reference to an inline record
                        if position + 8 > stop:
                            raise ValueError("short vertex reference")
                        rel = struct.unpack_from("<i", chr_data, position + 4)[0]
                        target = position + 8 + rel
                        if target not in registered:
                            raise ValueError(f"vertex reference misses earlier record at {position:#x}")
                        indices.append(registered[target])
                        position += 8
                    else:
                        size = 56 if shader == -2 else 32
                        if position + size > stop:
                            raise ValueError("inline vertex crosses submesh boundary")
                        raw = chr_data[position:position + size]
                        xyz = struct.unpack_from("<3f", raw, 0)
                        if shader == -3:                    # packed normal: 3 signed bytes
                            normal = tuple(max(-1.0, v / 127.0) for v in struct.unpack_from("<3b", raw, 12))
                            uv = struct.unpack_from("<2f", raw, 24)
                        else:
                            normal = struct.unpack_from("<3f", raw, 12)
                            uv = struct.unpack_from("<2f", raw, size - 8)
                        if not all(math.isfinite(v) for v in (*xyz, *normal, *uv)):
                            raise ValueError(f"non-finite vertex at {position:#x}")
                        registered[position] = len(vertices)
                        indices.append(len(vertices))
                        vertices.append((*xyz, *normal, *uv))
                        position += size
                strips.append({"flags": flags, "count": n, "indices": indices})
                triangles.extend(_triangles(flags, indices))
            meshes.append({"offset": cursor, "texture_id": texture_id, "shader": shader,
                           "vertices": vertices, "strips": strips, "triangles": triangles})
            vertex_total += sum(len(s["indices"]) for s in strips)
            tri_total += len(triangles)
            cursor = stop
        end = cursor
        if end + 8 > model_limit or u32(chr_data, end) != 0:
            raise ValueError(f"model {mid} has no end marker at {end:#x}")
        declared = u32(chr_data, end + 4)
        if declared != vertex_total:
            raise ValueError(f"model {mid} end-marker count {declared} != walked {vertex_total}")
        models.append({"id": mid, "offset": start, "global_flags": (gp0, gp1), "sphere": sphere,
                       "meshes": meshes, "vertex_count": vertex_total, "triangle_count": tri_total})
    total_v = sum(m["vertex_count"] for m in models)
    total_t = sum(m["triangle_count"] for m in models)
    return {"n_models": len(models), "n_submeshes": sum(len(m["meshes"]) for m in models),
            "n_vertices": total_v, "n_triangles": total_t, "models": models, **info}


# --------------------------------------------------------------------------- textures
def pvr_wrap(tex: dict, body: bytes) -> bytes:
    """Synthesize the PVRT chunk header the native BIN omits (payload bytes unchanged)."""
    if len(body) != tex["size"]:
        raise ValueError("texture body/descriptor size mismatch")
    return (b"PVRT" + struct.pack("<IBBHHH", len(body) + 8, tex["pixel"], tex["format"],
                                  0, tex["width"], tex["height"]) + body)


def decode_texture(tex: dict, bin_data: bytes):
    """One native BIN texture -> (width, height, RGBA bytes, description) via gbox.ninja."""
    from .ninja import pvr_decode
    body = bin_data[tex["offset"]:tex["offset"] + tex["size"]]
    return pvr_decode(pvr_wrap(tex, body))


# costume prefix -> (display name, aliases). Confirmed against the disc's arts_*.bin / *.mot tables
# (1ST_READ+0x16e7fc arts_*, +0x16e890 *_mot names: zack tina janlee ryu kasumi genfu bayman bass
# leifan ayane hika karate ind raido tengu sambo). KTE's display identity is unconfirmed.
FIGHTERS = [
    ("KAS", "Kasumi", ["Kasumi-chan", "DOA2 Kasumi"]),
    ("AYA", "Ayane", ["DOA2 Ayane"]),
    ("LEI", "Leifang", ["Lei Fang", "DOA2 Leifang"]),
    ("TIN", "Tina", ["Tina Armstrong", "DOA2 Tina"]),
    ("BAS", "Bass", ["Bass Armstrong", "DOA2 Bass"]),
    ("JAN", "Jann Lee", ["Jan Lee", "DOA2 Jann Lee"]),
    ("GEN", "Gen Fu", ["Genfu", "DOA2 Gen Fu"]),
    ("BAY", "Bayman", ["DOA2 Bayman"]),
    ("RYU", "Ryu Hayabusa", ["Ryu", "DOA2 Ryu"]),
    ("ZAC", "Zack", ["DOA2 Zack"]),
    ("HIK", "Helena", ["Helena Douglas", "DOA2 Helena"]),
    ("SAM", "Leon", ["DOA2 Leon"]),                       # arts_sam + sambo motion set
    ("TNG", "Tengu", ["Bankotsu-bo", "DOA2 Tengu"]),
    ("KTE", "KTE fighter", ["Ein", "Kasumi Alpha"]),      # costume family present; identity unconfirmed
]
# single-costume families that are not part of the selectable roster (boss/story variants)
VARIANTS = ["LOR", "MAM", "PDG", "WBA", "YTI"]
# motion files are named by the character's full nickname (1ST_READ+0x16e890: zack.mot tina.mot
# janlee.mot ryu.mot kasumi.mot genfu.mot bayman.mot bass.mot leifan.mot ayane.mot hika.mot
# karate.mot ind.mot raido.mot tengu.mot sambo.mot comon.mot). Only name-identical mappings here.
MOT_FILES = {"KAS": "KASUMI", "AYA": "AYANE", "LEI": "LEIFAN", "TIN": "TINA", "BAS": "BASS",
             "JAN": "JANLEE", "GEN": "GENFU", "BAY": "BAYMAN", "RYU": "RYU", "ZAC": "ZACK",
             "HIK": "HIKA", "TNG": "TENGU"}           # SAM/KTE motion names unconfirmed (sambo/karate/ind/raido)


def roster(disc_files: dict | None = None) -> list[dict]:
    """Costume entries from the disc listing (dict[str, tuple] like GDRom.files). With none, the
    static roster above."""
    import re
    fam: dict[str, list[str]] = {}
    if disc_files:
        for n in disc_files:
            m = re.match(r"^DOA2/([A-Z]+)(\d+)\.(?:CHR|SUP|BIN)$", n)
            if m and m.group(1) not in ("STAGE", "EFC", "FIX", "DV"):
                fam.setdefault(m.group(1), []).append(m.group(2))   # keep zero padding as-is
    out = []
    for pre, name, aliases in FIGHTERS:
        costumes = sorted(set(fam.get(pre, [])), key=int) or ["0"]
        out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": name, "aliases": aliases,
                    "kind": "character", "costumes": costumes})
    for pre in VARIANTS:
        if not fam or pre in fam:
            out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": f"{pre} (variant)",
                        "aliases": [], "kind": "variant", "costumes": sorted(set(fam.get(pre, ["0"])), key=int)})
    return out


# --------------------------------------------------------------------------- export
def export_assets(chr_data: bytes, bin_data: bytes, out_dir: str, name: str,
                  sup_data: bytes | None = None) -> dict:
    """Decode one costume's CHR + BIN into a UAP manifest, per-texture PNGs and a static .gltf
    (textures attached by native texture id; skeleton/weights are not in CHR - honest labels)."""
    import json as _json

    import numpy as np

    from .melee_models import write_gltf
    from .ninja import png as png_bytes

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meshes = parse_meshes(chr_data)
    textures = parse_textures(chr_data, len(bin_data))
    files = []
    pngs = {}
    arrays = {}
    for tex in textures:
        w, h, rgba, desc = decode_texture(tex, bin_data)
        arrays[tex["index"]] = np.frombuffer(rgba, np.uint8).reshape(h, w, 4)
        pngs[tex["index"]] = (w, h, rgba)
        fn = f"{name}_tex{tex['index']:02d}_{w}x{h}.png"
        (out / fn).write_bytes(png_bytes(w, h, rgba))
        files.append(fn)
    prims = []
    for model in meshes["models"]:
        groups: dict[int, dict] = {}
        for mesh in model["meshes"]:
            g = groups.setdefault(mesh["texture_id"], {"pos": [], "nrm": [], "uv": [], "tris": []})
            base_idx = len(g["pos"])
            for v in mesh["vertices"]:
                g["pos"].append(v[0:3]); g["nrm"].append(v[3:6]); g["uv"].append(v[6:8])
            g["tris"].extend((a + base_idx, b + base_idx, c + base_idx) for a, b, c in mesh["triangles"])
        for tid, g in sorted(groups.items()):
            if not g["tris"]:
                continue
            n = len(g["pos"])
            prims.append({"name": f"{name}_m{model['id']:02d}_t{tid}",
                          "pos": np.array(g["pos"], np.float32), "nrm": np.array(g["nrm"], np.float32),
                          "uv": np.array(g["uv"], np.float32), "tris": np.array(g["tris"], np.int32),
                          "J": np.zeros((n, 4), np.uint16), "W": np.tile([1.0, 0, 0, 0], (n, 1)).astype(np.float32),
                          "tex": arrays.get(tid)})
    gltf = out / f"{name}.gltf"
    write_gltf(gltf, [{"parent": -1, "world": np.eye(4, dtype=np.float32)}], prims, 1.0, name)
    files.append(gltf.name)
    manifest = {
        "uap_version": "0.1", "name": name,
        "source": {"game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
                   "extraction_method": "gbox.doa2_chars (meshes + textures decoded)"},
        "coordinate_system": {"up": "Y", "forward": "-Z", "handedness": "right"},
        "geometry_facts": {"n_models": meshes["n_models"], "n_submeshes": meshes["n_submeshes"],
                           "n_vertices": meshes["n_vertices"], "n_triangles": meshes["n_triangles"],
                           "model_ptr_base": f"{meshes['ptr_base']:#x}"},
        "texture_facts": {"n_textures": len(textures),
                          "formats": sorted({(t["pixel"], t["format"]) for t in textures}),
                          "bin_bytes": sum(t["capacity"] for t in textures)},
        "skeleton_note": "rig is NOT stored in CHR (word[4] is the texture count; bones live in the "
                         "SUP/ACS supplement route) - weights intentionally absent from the glTF",
        "confidence": {"entity": "verified", "geometry": "verified", "materials": "verified",
                       "textures": "verified", "skeleton": "missing", "skin_weights": "missing",
                       "animations": "missing", "source_identity": "verified"},
    }
    (out / "manifest.json").write_text(_json.dumps(manifest, indent=1))
    files.append("manifest.json")
    return {"files": files, "manifest": manifest, "meshes": meshes, "textures": textures}


def export(gdi: str, out_dir: str, key: str, costume: str = "0") -> dict:
    """Extract one fighter's costume asset set read-only from the owned disc: containers plus
    decoded meshes and textures (UAP manifest + PNGs + static glTF)."""
    from .gdrom import GDRom

    disc = GDRom(gdi)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    costume = costume.zfill(2) if len(costume) == 1 else costume     # disc names are <KEY><NN>
    stem = f"{key}{costume}"
    files = []
    for ext in ("BIN", "CHR", "SUP"):
        data = disc.read(f"DOA2/{stem}.{ext}")
        (out / f"{stem}.{ext}").write_bytes(data)
        files.append(f"{stem}.{ext}")
    r = export_assets(disc.read(f"DOA2/{stem}.CHR"), disc.read(f"DOA2/{stem}.BIN"), str(out),
                      f"doa2_{key.lower()}_{costume}")
    manifest = r["manifest"]
    manifest["provenance"] = [{"file": f"DOA2/{stem}.{e}", "bytes": len(disc.read(f"DOA2/{stem}.{e}"))}
                              for e in ("BIN", "CHR", "SUP")]
    mot = MOT_FILES.get(key, key)
    if disc.files.get(f"DOA2/{mot}.MOT"):
        manifest["source"]["resource_ids"] = [f"DOA2/{stem}.{e}" for e in ("BIN", "CHR", "SUP")] + [f"DOA2/{mot}.MOT"]
    (out / "manifest.json").write_text(__import__("json").dumps(manifest, indent=1))
    return {"files": files + r["files"], "manifest": manifest}
