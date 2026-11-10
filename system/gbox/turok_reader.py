"""Turok: Dinosaur Hunter (NTUE Rev B) — native asset reader (reader stage).

Exports one CGraphicObject's geometry (node hierarchy, parts, sections,
vertices, triangles), its texture-set references and the texture-set metadata
from the verified inventory to OBJ + JSON.

Verified against the owned NTUE Rev B build:
  zip  sha256 3b5df8341a02abc3216adc30d706debead51c307e0d61f2960c0402a69c6808f
  n64  sha256 d8c87aef86400ef8891d1933224d7b06bdebe688bb99a6923481db2a0d3ab31e
  z64  sha256 3f46508afd36173886f8a6ea65066663c431be9e1edb8d299356569d87e48bab

The ROM image is never modified; the reader only reads it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

from gbox import turok_analysis as ta
from gbox import turok_inventory as ti

ROM_SHA256_Z64 = (
    "3f46508afd36173886f8a6ea65066663c431be9e1edb8d299356569d87e48bab"
)

# UV derivation is a HYPOTHESIS until the cart loader xref is proven: the
# CROM section carries a texture scale (mult_u/mult_v) and the vertex texture
# coordinate is an s16 stage coordinate.
NO_TEXSET = 0xFFFFFFFF  # CROM section with no texture set

UV_STAGE = 32768.0
UV_MULT_REF = 8192.0


def _texset_id(sec: dict):
    """Texture-set index of a section, or None when the CROM has no texture."""
    t = sec.get("info", {}).get("texset")
    return None if t is None or int(t) == NO_TEXSET else int(t)


def _uv(tc: int, mult: int) -> float:
    return (float(tc) / UV_STAGE) * (float(mult) / UV_MULT_REF)


def _texset_map(inv: dict) -> dict:
    out = {}
    for s in inv.get("texture_sets", {}).get("sets", []):
        out[s.get("i")] = s
    return out


def build_obj(geom: dict, source_sha256: str | None = None) -> str:
    """Render a decoded geometry tree as Wavefront OBJ text.

    Pure function: no ROM access, so it can be tested on synthetic fixtures.
    """
    lines = []
    if source_sha256:
        lines.append(f"# source rom sha256 {source_sha256}")
    v_base = 1
    for ni, node in enumerate(geom.get("nodes", [])):
        for pi, part in enumerate(node.get("parts") or []):
            for si, sec in enumerate(part.get("sections") or []):
                info = sec.get("info", {})
                texset = info.get("texset")
                verts = sec.get("vertices") or []
                tris = sec.get("triangles") or []
                lines.append(
                    f"# node {ni} part {pi} section {si} texset {texset} "
                    f"matflags {info.get('matflags')} verts {len(verts)} tris {len(tris)}"
                )
                lines.append(f"g node_{ni}_part_{pi}_section_{si}")
                lines.append(f"usemtl mat_tex{texset if texset is not None else 'none'}")
                mu = info.get("mult_u") or 0
                mv = info.get("mult_v") or 0
                for v in verts:
                    lines.append(f"v {float(v[0])} {float(v[1])} {float(v[2])}")
                    tu = v[4] if len(v) > 4 else 0
                    tv = v[5] if len(v) > 5 else 0
                    lines.append(f"vt {_uv(tu, mu):.6f} {1.0 - _uv(tv, mv):.6f}")
                for t in tris:
                    a, b, c = int(t[0]), int(t[1]), int(t[2])
                    lines.append(
                        f"f {v_base + a}/{v_base + a} {v_base + b}/{v_base + b} "
                        f"{v_base + c}/{v_base + c}"
                    )
                v_base += len(verts)
    return "\n".join(lines) + "\n"


def build_mtl(geom: dict, texture_files: dict | None = None) -> str:
    lines = ["# Turok NTUE Rev B materials"]
    seen = set()
    for node in geom.get("nodes", []):
        for part in node.get("parts") or []:
            for sec in part.get("sections") or []:
                texset = _texset_id(sec)
                if texset in seen:
                    continue
                seen.add(texset)
                lines.append(f"newmtl mat_tex{texset if texset is not None else 'none'}")
                lines.append("Ka 1.000 1.000 1.000")
                lines.append("Kd 1.000 1.000 1.000")
                if texset is not None and texture_files and texset in texture_files:
                    lines.append(f"map_Kd {texture_files[texset]}")
                lines.append("")
    return "\n".join(lines) + "\n"


def summarize(res: dict, inv: dict, index: int, source_sha256: str) -> dict:
    geom = res.get("geometry", {})
    tsets = _texset_map(inv)
    sections = []
    total_v = total_t = 0
    for ni, node in enumerate(geom.get("nodes", [])):
        for pi, part in enumerate(node.get("parts") or []):
            for si, sec in enumerate(part.get("sections") or []):
                info = sec.get("info", {})
                tris = sec.get("triangles") or []
                nv = len(sec.get("vertices") or [])
                max_idx = max((max(int(t[0]), int(t[1]), int(t[2])) for t in tris), default=-1)
                meta = tsets.get(_texset_id(sec), {})
                sections.append({
                    "node": ni, "part": pi, "section": si,
                    "texset": _texset_id(sec),
                    "texset_format": meta.get("format"),
                    "texset_bitmaps": meta.get("bitmaps"),
                    "texset_palettes": meta.get("palettes"),
                    "matflags": info.get("matflags"),
                    "mult_u": info.get("mult_u"),
                    "mult_v": info.get("mult_v"),
                    "n_vertices": nv,
                    "n_triangles": len(tris),
                    "triangle_max_index": max_idx,
                })
                total_v += nv
                total_t += len(tris)
    return {
        "object": index,
        "source_rom_sha256": source_sha256,
        "n_nodes": len(geom.get("nodes", [])),
        "node_tree": [
            {"node": ni, "child_node_indices": node.get("child_node_indices", []),
             "part_indices": node.get("part_indices", [])}
            for ni, node in enumerate(geom.get("nodes", []))
        ],
        "total_vertices": total_v,
        "total_triangles": total_t,
        "texture_sets": sorted({s["texset"] for s in sections if s["texset"] is not None}),
        "sections": sections,
        "anim_error": res.get("anim_error"),
    }


# Texture-set format codes (see gbox.turok_inventory.TEXTURE_FORMATS)
_FMT_CI8 = 0
_FMT_CI4 = 1
_FMT_CI4_IA = 3
_FMT_MM16 = 4

# Sub-blob header is [u32 type=1, u32 ?, u32 size, u32 0] — 16 bytes.
_SUB_BLOB_HDR = 16


def _rgba5551(c: int) -> tuple[int, int, int, int]:
    r = ((c >> 11) & 0x1F) * 255 // 31
    g = ((c >> 6) & 0x1F) * 255 // 31
    b = ((c >> 1) & 0x1F) * 255 // 31
    a = 255 if (c & 1) else 0
    return (r, g, b, a)


def _palette_from_blob(pal_blob: bytes, n_entries: int) -> list[tuple[int, int, int, int]]:
    """Parse a CI4 (16) or CI8 (256) RGBA5551 palette from the (header-stripped) blob."""
    pal = pal_blob[: n_entries * 2]
    out = []
    for i in range(n_entries):
        c = struct.unpack_from(">H", pal, i * 2)[0]
        out.append(_rgba5551(c))
    return out


def _first_bitmap_frame(bm_blob: bytes, npix: int, code: int) -> bytes:
    """Strip the bitmap blob header; animated sets ([count, offsets...]) yield frame 0."""
    if len(bm_blob) <= _SUB_BLOB_HDR:
        return bm_blob
    first = struct.unpack_from(">I", bm_blob, 0)[0]
    if first == 1:
        return bm_blob[_SUB_BLOB_HDR:]
    # frame table: u32 count then u32 offsets relative to the blob start
    n_frames = first
    if 1 < n_frames < 4096 and len(bm_blob) >= 8:
        off0 = struct.unpack_from(">I", bm_blob, 4)[0]
        if 0 < off0 < len(bm_blob):
            return bm_blob[off0:]
    return bm_blob[_SUB_BLOB_HDR:]


def decode_texset_blobs(fmt_blob: bytes, bm_blob: bytes, pal_blob: bytes,
                        fmt_code: int | None = None) -> dict:
    """Decode one texture set's format/bitmap/palette blobs into RGBA pixels.

    Pure function (no ROM access) so it can be tested on synthetic blobs.
    Returns {"format", "width", "height", "rgba", "palette"} where rgba is a
    bytes object of length width*height*4.
    """
    if fmt_code is None:
        fmt_code = struct.unpack_from(">B", fmt_blob)[0]
    code = fmt_code
    # fmt blob layout: [format(1), pad(1), w_shift(1), h_shift(1), 0xff, 0, 0, 0]
    fmt, _pad, ws, hs = struct.unpack_from(">BBBB", fmt_blob, 0)
    w = 1 << ws
    h = 1 << hs
    pal_blob_d = pal_blob[_SUB_BLOB_HDR:] if len(pal_blob) > _SUB_BLOB_HDR else pal_blob
    bm_blob_d = _first_bitmap_frame(bm_blob, w * h, code)

    if code == _FMT_CI8:
        n_pal = 256
        palette = _palette_from_blob(pal_blob_d, n_pal)
        # 8-bit indices, one per byte
        idx = list(bm_blob_d[: w * h])
        rgba = bytearray()
        for i in idx:
            rgba.extend(palette[i])
    elif code in (_FMT_CI4, _FMT_CI4_IA):
        n_pal = 16
        if code == _FMT_CI4_IA:
            # IA16 palette entries: high byte intensity, low byte alpha
            palette = []
            for i in range(n_pal):
                v = struct.unpack_from(">H", pal_blob_d, i * 2)[0]
                palette.append((v >> 8, v >> 8, v >> 8, v & 0xFF))
        else:
            palette = _palette_from_blob(pal_blob_d, n_pal)
        # 4-bit indices, two per byte (high nibble first)
        pixels = w * h
        rgba = bytearray()
        for i in range(pixels):
            byte = bm_blob_d[i >> 1]
            nibble = (byte >> 4) if (i & 1) == 0 else (byte & 0x0F)
            rgba.extend(palette[nibble])
        palette = palette
    elif code == _FMT_MM16:
        # mip-mapped RGBA5551: level 0 (w*h big-endian u16) comes first
        palette = []
        rgba = bytearray()
        for i in range(w * h):
            rgba.extend(_rgba5551(struct.unpack_from(">H", bm_blob_d, i * 2)[0]))
    else:
        raise ValueError(f"unhandled texture set format code {code}")
    return {
        "format": ti.TEXTURE_FORMATS.get(code, str(code)),
        "format_code": code,
        "width": w,
        "height": h,
        "rgba": bytes(rgba),
        "palette": palette,
    }


def decode_texset(rom: bytes, tid: int) -> dict:
    """Locate and decode texture set *tid* from an owned z64 ROM."""
    ts_base = ti.CART_ROOT_OFFSET + ti.parse_indexed(rom, ti.CART_ROOT_OFFSET)[3][0]
    blocks = ti.parse_indexed(rom, ts_base)
    rel, size = blocks[tid]
    blob = rom[ts_base + rel: ts_base + rel + size]
    dec = ti.decode_rnc(blob)
    sub = ti.parse_indexed(dec, 0)
    fmt_blob = dec[sub[0][0]: sub[0][0] + sub[0][1]]
    bm_blob = dec[sub[1][0]: sub[1][0] + sub[1][1]]
    pal_blob = dec[sub[2][0]: sub[2][0] + sub[2][1]]
    d = decode_texset_blobs(fmt_blob, bm_blob, pal_blob)
    d["texset"] = tid
    return d


def png_bytes(width: int, height: int, rgba: bytes) -> bytes:
    """Encode an RGBA8 buffer as a minimal 8-bit PNG (no external deps)."""

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def export_texset_pngs(rom: bytes, inv: dict, out_dir: Path, texset_ids: list[int]) -> dict:
    """Decode each texset to a PNG and return {tid: filename}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for tid in texset_ids:
        try:
            d = decode_texset(rom, tid)
        except ValueError:  # unknown format codes are skipped
            continue
        name = f"texset_{tid}.png"
        (out_dir / name).write_bytes(png_bytes(d["width"], d["height"], d["rgba"]))
        result[tid] = name
    return result


def export_object(rom: bytes, inv: dict, index: int, out_dir: Path) -> dict:
    obj = inv["graphic_objects"]["objects"][index]
    res = ta.decode_object(rom, obj)
    geom = res.get("geometry", {})
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(rom).hexdigest()
    obj_path = out_dir / f"object_{index}.obj"
    mtl_path = out_dir / f"object_{index}.mtl"
    obj_path.write_text(build_obj(geom, sha))

    # Decode texsets to PNG and feed the names into the MTL so map_Kd works.
    tids = sorted({t for t in _all_texset_ids(geom) if t is not None})
    tex_pngs = export_texset_pngs(rom, inv, out_dir, tids) if tids else {}
    mtl_path.write_text(build_mtl(geom, tex_pngs))

    summary = summarize(res, inv, index, sha)
    summary["obj_file"] = obj_path.name
    summary["mtl_file"] = mtl_path.name
    summary["texset_pngs"] = {str(k): v for k, v in tex_pngs.items()}
    sp = out_dir / f"object_{index}_summary.json"
    sp.write_text(json.dumps(summary, indent=2) + "\n")
    summary["summary_file"] = sp.name
    return summary


def _all_texset_ids(geom: dict) -> list[int | None]:
    out = []
    for node in geom.get("nodes", []):
        for part in node.get("parts") or []:
            for sec in part.get("sections") or []:
                out.append(_texset_id(sec))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Turok NTUE Rev B native asset reader")
    ap.add_argument("rom", help="path to rom.z64 (read-only)")
    ap.add_argument("--object", type=int, default=64)
    ap.add_argument("--out", default="turok_export")
    ap.add_argument("--list", action="store_true", help="list object node/section counts")
    args = ap.parse_args(argv)

    rom = Path(args.rom).read_bytes()
    sha = hashlib.sha256(rom).hexdigest()
    print(f"ROM {args.rom} sha256 {sha}")
    if sha != ROM_SHA256_Z64:
        print(f"WARNING: expected {ROM_SHA256_Z64}")
    inv = ti.inventory(rom)
    if args.list:
        for o in inv["graphic_objects"]["objects"][:200]:
            print(o["i"], o)
        return 0
    summary = export_object(rom, inv, args.object, Path(args.out))
    print(json.dumps({k: v for k, v in summary.items() if k != "sections"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
