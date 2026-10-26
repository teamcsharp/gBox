"""Marvel vs. Capcom 2 (Dreamcast) DEDICATED-style sprite reader (#1315 reader stage).

Each fighter is a 2D sprite package in ``PLxx_DAT.BIN``.  This module decodes the
owned USA disc's 59 character DAT files and exports an editable sprite artifact:

  * ``<slug>.parts.png``   – a packed atlas of every unique 4bpp part (palette 0)
  * ``<slug>.sprites.png`` – a packed atlas of every assembled sprite frame
  * ``<slug>.json``        – manifest with parts, sprites, animations and palette banks
  * ``<slug>.glb``         – a one-plane glTF preview so the character library can render it

The glTF is not rigged (2D fighter); it is only a preview.  Real native character
replacement is a follow-up writer stage that re-encodes a donor's parts back into the
DAT slot format.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from . import mvc2_dat as M
from .gdrom import GDRom
from .mvc2_inventory import ROSTER

GAME_ID = "02db6d37c0e20375"
DAT_PATH = "PL{id:02X}_DAT.BIN"
READER_VERSION = 1
mvc2_reader = READER_VERSION


def _dat_bytes(gdi: str | Path, cid: int) -> bytes:
    """Read a character's PLxx_DAT.BIN straight from the GD-ROM (read-only)."""
    return GDRom(str(gdi)).read(DAT_PATH.format(id=cid))


def _cid_name(cid: int) -> tuple[str, str]:
    name = ROSTER[cid]
    slug = "mvc2_" + name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
    return name, slug


def _pack_shelves(rects: list[tuple[int, int, int]], max_width: int = 4096) -> tuple[int, int, list[tuple[int, int]]]:
    """Shelf pack rectangles (w, h, id) with a max shelf width. Returns (atlas_w, atlas_h, [(x, y), ...])."""
    if not rects:
        return 0, 0, []
    order = rects                                         # positions are returned in the caller's tile order
    rects = sorted(rects, key=lambda r: (-r[1], -r[0]))
    shelves: list[tuple[int, int, list[tuple[int, int, int]]]] = []
    for rid, w, h in ((r[2], r[0], r[1]) for r in rects):
        placed = False
        for i, (sh, sw, items) in enumerate(shelves):
            if sh >= h and sw + w <= max_width:
                shelves[i] = (sh, sw + w, items + [(rid, sw, 0)])
                placed = True
                break
        if not placed:
            shelves.append((h, w, [(rid, 0, 0)]))
    atlas_w = min(max_width, max((sw for _, sw, _ in shelves), default=0))
    y = 0
    positions: dict[int, tuple[int, int]] = {}
    for h, _w, items in shelves:
        for rid, x, _ in items:
            positions[rid] = (x, y)
        y += h
    return atlas_w, y, [positions[r[2]] for r in order]


def _build_atlas(tiles: list[tuple[int, int, int, bytes]], name: str,
                 apply_alpha: bool = True) -> tuple[bytes, int, int, list[tuple[int, int]]]:
    """Build a PNG atlas from a list of (id, w, h, rgba_bytes). Returns PNG bytes, w, h, positions."""
    from PIL import Image
    rects = [(tile[1], tile[2], i) for i, tile in enumerate(tiles)]
    aw, ah, positions = _pack_shelves(rects)
    if aw == 0:
        return b"", 0, 0, []
    img = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
    for i, (_, w, h, rgba) in enumerate(tiles):
        x, y = positions[i]
        if len(rgba) != w * h * 4:
            rgba += b"\x00\x00\x00\x00" * (w * h - len(rgba) // 4)
        tile = Image.frombytes("RGBA", (w, h), rgba[: w * h * 4])
        img.paste(tile, (x, y), tile)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), aw, ah, positions


def _rgba_for_part(dat: bytes, sel: int, bank: int = 0) -> tuple[bytes, int, int]:
    """Decode one part with a palette bank to RGBA bytes."""
    idx, w, h = M.part_indices(dat, sel)
    pal = M.palette_bank(dat, bank)
    rgba = bytearray(w * h * 4)
    for i, c in enumerate(idx):
        r, g, b, a = pal[c]
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    return bytes(rgba), w, h


def _render_sprite_rgba(dat: bytes, sprite_id: int, bank: int = 0) -> tuple[bytes, int, int]:
    """Assemble a sprite to RGBA bytes."""
    w, h, rgba = M.render_sprite(dat, sprite_id, bank)
    if w == 0 or h == 0:
        return b"", 1, 1
    return rgba, w, h


def decode_character(gdi: str | Path, cid: int) -> dict:
    """Decode one character DAT into a structured dict (no files written)."""
    dat = _dat_bytes(gdi, cid)
    tab = M.dat_sections(dat)
    n_parts = M.part_count(dat)
    n_sprites = struct.unpack_from("<I", dat, tab[1])[0] // 4 if tab[1] else 0
    anim = M.animation_groups(dat, cid)

    parts = []
    for i in range(n_parts):
        _, _, _, w, h = M.part_geom(dat, i)
        parts.append({"id": i, "w": w, "h": h})

    sprites = []
    for i in range(n_sprites):
        recs = M.sprite_records(dat, i)
        if recs:
            xs = [r["dx"] for r in recs]
            ys = [r["dy"] for r in recs]
            w = max(xs) - min(xs) + max((M.part_geom(dat, r["part"])[3] for r in recs), default=0)
            h = max(ys) - min(ys) + max((M.part_geom(dat, r["part"])[4] for r in recs), default=0)
        else:
            w = h = 0
        sprites.append({
            "id": i,
            "w": int(w),
            "h": int(h),
            "parts": [{"part": r["part"], "dx": r["dx"], "dy": r["dy"],
                       "flip": r["flip"], "flipy": r["flipy"]} for r in recs],
        })

    palette = []
    pal_base = tab[2]
    pal_size = (tab[3] or len(dat)) - pal_base if tab[2] else 0
    n_banks = max(1, pal_size // 32)
    for b in range(min(n_banks, 2048)):
        palette.append([{"r": r, "g": g, "b": b_, "a": a}
                        for r, g, b_, a in M.palette_bank(dat, b)])

    name, slug = _cid_name(cid)
    return {
        "meta": {"game_id": GAME_ID, "cid": cid, "name": name, "slug": slug,
                 "dat_sha256": hashlib.sha256(dat).hexdigest(),
                 "n_parts": n_parts, "n_sprites": n_sprites, "n_anim_groups": len(anim)},
        "parts": parts,
        "sprites": sprites,
        "animations": anim,
        "palette": palette,
    }


def export_character(gdi: str | Path, cid: int, out_dir: str | Path,
                     bank: int = 0, sprites: bool = True, parts: bool = True,
                     progress=lambda p, m: None) -> dict:
    """Export editable PNG atlases and a JSON manifest for one character."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    progress(10, f"Decoding PL{cid:02X}_DAT.BIN structure")
    manifest = decode_character(gdi, cid)
    dat = _dat_bytes(gdi, cid)
    slug = manifest["meta"]["slug"]

    part_tiles = []
    part_png = sprite_png = None
    if parts:
        progress(30, "Decoding parts")
        for p in manifest["parts"]:
            rgba, w, h = _rgba_for_part(dat, p["id"], bank)
            part_tiles.append((p["id"], w, h, rgba))
        png, aw, ah, positions = _build_atlas(part_tiles, f"{slug}_parts")
        part_png = out / f"{slug}.parts.png"
        part_png.write_bytes(png)
        for p, (x, y) in zip(manifest["parts"], positions):
            p["atlas_x"] = x
            p["atlas_y"] = y
        manifest["atlas"] = {"parts": {"file": part_png.name, "w": aw, "h": ah}}

    sprite_tiles = []
    if sprites:
        progress(50, "Rendering sprites")
        for s in manifest["sprites"]:
            rgba, w, h = _render_sprite_rgba(dat, s["id"], bank)
            sprite_tiles.append((s["id"], w, h, rgba))
        png, aw, ah, positions = _build_atlas(sprite_tiles, f"{slug}_sprites")
        sprite_png = out / f"{slug}.sprites.png"
        sprite_png.write_bytes(png)
        for s, (x, y) in zip(manifest["sprites"], positions):
            s["atlas_x"] = x
            s["atlas_y"] = y
        manifest["atlas"]["sprites"] = {"file": sprite_png.name, "w": aw, "h": ah}

    json_path = out / f"{slug}.json"
    json_path.write_text(json.dumps(manifest, indent=1))

    glb_path = out / f"{slug}.glb"
    preview = (sprite_png or part_png)
    if preview is None:
        raise ValueError("export at least one of parts or sprites")
    build_preview_glb(preview, glb_path)

    progress(90, "Wrote atlases + manifest + preview glb")
    # The sprite atlas is the collection "model" (2D art); the GLB stays beside it as the 3D preview.
    # files[0] must be the PNG: add() classifies PNG models as kind "sprites" and renders a real preview
    # from the sheet, while a GLB-first entry is mis-classified as a rigless "character" and never reaches done.
    model_png = sprite_png or part_png
    rest = [glb_path, json_path] + [p for p in (part_png, sprite_png) if p and p != model_png]
    return {
        "files": [model_png] + rest,
        "manifest": manifest,
        "work": out,
    }


def build_preview_glb(image: Path, out: Path) -> Path:
    """Minimal glTF 2.0 binary: a single double-sided plane with ``image`` as baseColorTexture."""
    image = Path(image)
    # Plane: 2x2 units, centered, facing +Z
    positions = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]
    uvs = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    indices = [0, 1, 2, 0, 2, 3]

    pos_bytes = struct.pack("<" + "3f" * len(positions), *[c for p in positions for c in p])
    uv_bytes = struct.pack("<" + "2f" * len(uvs), *[c for uv in uvs for c in uv])
    idx_bytes = struct.pack("<" + "H" * len(indices), *indices)

    blob = bytearray(pos_bytes)
    blob += b"\x00" * (-len(blob) % 4)
    uv_off = len(blob)
    blob += uv_bytes
    blob += b"\x00" * (-len(blob) % 4)
    idx_off = len(blob)
    blob += idx_bytes
    blob += b"\x00" * (-len(blob) % 4)

    gl = {
        "asset": {"version": "2.0", "generator": "gbox.mvc2_chars"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "sprite_plane"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                                     "indices": 2, "material": 0, "mode": 4}]}],
        "materials": [{"pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0,
                                                 "baseColorTexture": {"index": 0}},
                       "alphaMode": "BLEND", "doubleSided": True}],
        "textures": [{"source": 0}],
        "images": [{"uri": image.name, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3",
             "max": [1.0, 1.0, 0.0], "min": [-1.0, -1.0, 0.0]},
            {"bufferView": 1, "componentType": 5126, "count": 4, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 6, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes)},
            {"buffer": 0, "byteOffset": uv_off, "byteLength": len(uv_bytes)},
            {"buffer": 0, "byteOffset": idx_off, "byteLength": len(idx_bytes)},
        ],
        "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
                    + struct.pack("<II", len(js), 0x4E4F534A)
                    + js
                    + struct.pack("<II", len(blob), 0x004E4942)
                    + bytes(blob))
    return out


def roster() -> list[dict]:
    """DEDICATED roster: all 59 character IDs (0x00-0x3A)."""
    out = []
    for cid, name in enumerate(ROSTER):
        _, slug = _cid_name(cid)
        out.append({"key": f"{cid:02X}", "slug": slug, "name": name,
                    "aliases": [name, f"MVC2 {name}", f"PL{cid:02X}"],
                    "kind": "character"})
    return out


def _dc_gdi(ctx, game: dict) -> Path:
    """Resolve a Dreamcast gdi path for this exact game: the shared resolver first (GDI/CDI, CHD via chdman),
    then the 7z/zip archives this title ships in."""
    from . import characters as CH
    try:
        return CH._dc_gdi(ctx, game)
    except Exception:                                     # no GDI/CHD through the shared path: try the archives below
        pass
    cached = Path(ctx.config.cache) / "dc" / game["game_id"] / "disc.gdi"
    if cached.exists():
        return cached
    paths = game.get("source_paths") or []
    for p in paths:
        pp = Path(p)
        if pp.suffix.lower() == ".gdi":
            return pp
        if pp.suffix.lower() in (".7z", ".zip"):
            from .mvc2_inventory import unpack_7z
            return unpack_7z(pp, cached.parent)
    raise FileNotFoundError(f"No MVC2 disc image for {game['game_id']}")


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """DEDICATED runner for the characters tool: export one MVC2 fighter."""
    from pathlib import Path
    cid = int(e["key"], 16)
    gdi = _dc_gdi(ctx, game)
    work = Path(work)
    res = export_character(gdi, cid, work, progress=ctx.progress)
    return {
        "files": res["files"],
        "tool": "gbox.mvc2_chars",
        "source_files": [f"PL{cid:02X}_DAT.BIN"],
        "roles": {},
        "kind": "sprites",
        "extra": {"picture": "2d", "mvc2_reader": READER_VERSION,
                  "mvc2": {"version": READER_VERSION, "game": "mvc2", "cid": cid,
                           "source_file": f"PL{cid:02X}_DAT.BIN"}},
        "notes": "2D sprite fighter: parts atlas + sprite atlas + JSON manifest. "
                 "No rig/retarget map yet; native replacement is a follow-up DAT writer stage.",
    }


def coverage(gdi: str | Path) -> dict:
    """Decode every PLxx_DAT.BIN and report per-character parse coverage."""
    gdi = str(gdi)
    g = GDRom(gdi)
    dats = sorted(fn for fn in g.files if fn.endswith("_DAT.BIN") and fn.startswith("PL"))
    results = []
    for fn in dats:
        cid = int(fn[2:4], 16)
        try:
            dat = g.read(fn)
            tab = M.dat_sections(dat)
            n_parts = M.part_count(dat)
            n_sprites = struct.unpack_from("<I", dat, tab[1])[0] // 4 if tab[1] else 0
            anim = M.animation_groups(dat, cid)
            results.append({"cid": cid, "name": ROSTER[cid], "ok": True,
                            "n_parts": n_parts, "n_sprites": n_sprites,
                            "n_anim_groups": len(anim)})
        except Exception as exc:
            results.append({"cid": cid, "name": ROSTER[cid] if cid < len(ROSTER) else "?",
                            "ok": False, "error": str(exc)})
    ok = [r for r in results if r["ok"]]
    return {"total": len(dats), "parsed": len(ok), "failed": [r for r in results if not r["ok"]],
            "results": results}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MVC2 DC character sprite reader")
    ap.add_argument("gdi", type=Path, help="path to disc.gdi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("export")
    a.add_argument("--cid", type=lambda s: int(s, 16), default=0, help="character ID in hex (default 00)")
    a.add_argument("--out", type=Path, default=Path("."))
    b = sub.add_parser("coverage")
    args = ap.parse_args(argv)
    if args.cmd == "export":
        res = export_character(args.gdi, args.cid, args.out)
        print(json.dumps({"files": [str(f) for f in res["files"]],
                          "meta": res["manifest"]["meta"]}, indent=2))
    else:
        print(json.dumps(coverage(args.gdi), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
