"""Reader: editable, import-ready export of the Sonic 1 (Mega Drive) player in
"Shadow In Sonic 1", a Sonic 1 REV00 disassembly rebuild whose player is Shadow
in the Sonic slot (object 01).

This is the reader stage of the readiness pipeline.  It reuses the two modules
that already reverse the game through its own code (PR #58):

* ``gbox.sonic1_inventory`` -- finds Map_Sonic / SonicDynPLC / Art_Sonic /
  Pal_Sonic / Ani_Sonic through the code that references them (every address
  moved vs stock Sonic 1);
* ``gbox.sonic1_analysis`` -- the animation rules (the walk/run slope-angle
  frame offsets), the other Sonic art a full swap must also cover, and the
  byte-identical Map/DPLC/Art re-encoder a writer starts from.

On top of those, this module:

* exports every mapping frame as an 8-bit indexed PNG (Pal_Sonic line 0,
  index 0 = transparent) plus a ``manifest.json`` with each frame's pieces,
  DPLC cues, bbox and origin -- the exact data ``encode_frame_map`` /
  ``encode_frame_dplc`` / ``pack_tiles`` re-encode, so a writer can load the
  export, edit pixels or pieces, and write the tables back byte-exactly;
* exports the 33-script animation map with the walk/run angle expansion
  (``sonic1_analysis.animation_rules``: walk +0/6/12/18, run +0/8/16/24);
* decodes the Sonic graphics outside the DPLC set (title, continue, signpost,
  lives icon, ending) through the Nemesis decoder
  (``gbox.formats.sega_md.nemesis_decompress``) at the addresses
  ``sonic1_analysis.sonic_art_users`` reports;
* registers a ``characters.DEDICATED`` reader (``sonic1_shadow``) so the
  collection pipeline can pull Shadow from the owned ROM.

CLI: ``python -m gbox.sonic1_reader ROM --out DIR [--nemesis DIR]``
"""
from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

import numpy as np

from gbox import sonic1_analysis as A
from gbox import sonic1_inventory as I
from gbox.formats import sega_md as M

VERSION = "1.0"
READER_VERSION = 1
EXTRACTOR = "sonic1_shadow"
SLOT = "sonic"                       # Shadow replaces object 01, the player slot
NAME = "Shadow"


class ReaderError(ValueError):
    pass


# --------------------------------------------------------------- indexed PNG --

def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def indexed_png(w: int, h: int, indices: bytes, palette: list[tuple[int, int, int]]) -> bytes:
    """An 8-bit indexed PNG: palette line 0 (16 colours), index 0 transparent."""
    if w <= 0 or h <= 0 or len(indices) != w * h or len(palette) != 16 or any(v > 15 for v in indices):
        raise ReaderError("indexed_png needs w*h indices and a 16-colour palette")
    raw = b"".join(b"\x00" + indices[y * w:(y + 1) * w] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    plte = b"".join(bytes(c) for c in palette)
    trns = bytes([0] + [255] * 15)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr) + _chunk(b"PLTE", plte) + _chunk(b"tRNS", trns)
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


# ------------------------------------------------------------- frame assembly --

def _stream_tiles(art: bytes, cues: list[tuple[int, int]]):
    """The tiles one frame's DPLC streams, as an (n, 8, 8) index array."""
    if any(t < 0 or n <= 0 or 32*(t+n) > len(art) for t, n in cues):
        raise ReaderError('DPLC cue exceeds the native art extent')
    raw = b"".join(art[32 * t:32 * (t + n)] for t, n in cues)
    return M.tiles_to_indices(raw)


def assemble(art: bytes, pieces: list[dict], cues: list[tuple[int, int]]):
    """One mapping frame -> (indices bytes, x0, y0, w, h); index 0 = transparent.

    Same rules the VDP sprite list applies: pieces are drawn first-piece-on-top,
    a piece's sub-tiles are column-major, flips mirror both the sub-tile
    placement and the pixels inside each tile, and a colour index of 0 never
    overwrites the piece drawn beneath it."""
    tiles = _stream_tiles(art, cues)
    if not pieces:
        return None
    if any(not 1 <= p['w'] <= 4 or not 1 <= p['h'] <= 4 or p['tile'] < 0 for p in pieces):
        raise ReaderError('Invalid native sprite dimensions or tile index')
    x0 = min(p["x"] for p in pieces)
    y0 = min(p["y"] for p in pieces)
    x1 = max(p["x"] + 8 * p["w"] for p in pieces)
    y1 = max(p["y"] + 8 * p["h"] for p in pieces)
    w, h = x1 - x0, y1 - y0
    img = np.zeros((h, w), np.uint8)
    for p in reversed(pieces):                    # first piece has the top priority
        for c in range(p["w"]):
            for r in range(p["h"]):
                t = p["tile"] + c * p["h"] + r
                if t >= len(tiles):
                    raise ReaderError("Mapping references an unstreamed tile")
                tile = tiles[t]
                if p["hflip"]:
                    tile = tile[:, ::-1]
                if p["vflip"]:
                    tile = tile[::-1, :]
                cc = p["w"] - 1 - c if p["hflip"] else c
                rr = p["h"] - 1 - r if p["vflip"] else r
                px = p["x"] - x0 + cc * 8
                py = p["y"] - y0 + rr * 8
                region = img[py:py + 8, px:px + 8]
                mask = tile != 0
                region[mask] = tile[mask]
    return img.tobytes(), x0, y0, w, h


# ------------------------------------------------------------------ decoding --

def read_player(src) -> dict:
    """Decode the player (Shadow in the Sonic slot) from a ROM / zip / bytes."""
    if isinstance(src, (bytes, bytearray)):
        import hashlib
        d = bytes(src)
        info = {"container": None, "member": None, "rom_sha256": hashlib.sha256(d).hexdigest(), "rom_size": len(d)}
    else:
        d, info = I.read_rom(src)
    loc = I.locate(d)
    maps = I.mapping_frames(d, loc["mappings"])
    cues = I.dplc_frames(d, loc["dplc"])
    if len(maps) != len(cues):
        raise ReaderError(f"{len(maps)} mapping frames but {len(cues)} DPLC frames")
    tiles_n = max((t + n for f in cues for t, n in f), default=0)
    art = d[loc["art"]:loc["art"] + 32 * tiles_n]
    if len(art) != 32 * tiles_n:
        raise ReaderError("Truncated native art")
    pal = I.palette(d, loc["palette"])
    frame_tiles = [sum(n for _, n in f) for f in cues]
    an = A.animation_rules(d, loc, A.call_map(d), frame_tiles)
    hdr = I.header(d)
    title = (hdr["title_overseas"] or hdr["title_domestic"]).upper()
    return {
        "engine": "sonic1-md", "name": "Shadow" if "SHADOW" in title else "Sonic",
        "source": info, "header": hdr,
        "tables": {"mappings": loc["mappings"], "dplc": loc["dplc"], "art": loc["art"],
                   "art_tiles": tiles_n, "palette": loc["palette"], "palette_index": loc.get("palette_index"),
                   "animations": loc["animations"], "vram": loc["vram"],
                   "dplc_loader": loc["dplc_loader"], "mapping_refs": loc["mapping_refs"]},
        "palette": {"line": 0, "rgb": [list(c) for c in pal], "addr": loc["palette"]},
        "maps": maps, "cues": cues, "art": art, "art_bytes": len(art),
        "frame_count": len(maps), "max_frame_tiles": max(frame_tiles),
        "animation": an,
    }


def export(src, out: Path | str) -> dict:
    """Write ``frames/frame_NNN.png`` (indexed) + ``manifest.json`` for all frames."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    p = read_player(src)
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    # animation map: per script the reachable mapping frames after the angle offsets
    scripts = []
    walk_offs = p["animation"]["walk"]["angle_offsets"]
    run_offs = p["animation"]["run"]["angle_offsets"]
    walk_id = p["animation"]["walk"]["anim"]
    run_id = p["animation"]["run"]["anim"]
    for s in p["animation"]["script_list"]:
        offs = walk_offs if s["id"] == walk_id else run_offs if s["id"] == run_id else [0]
        reach = sorted({f + o for f in s["frames"] for o in offs if f + o < len(p["maps"])})
        scripts.append({**s, "angle_offsets": offs, "reachable_frames": reach})
    frames = []
    for i, (pieces, cue) in enumerate(zip(p["maps"], p["cues"])):
        r = assemble(p["art"], pieces, cue)
        rec = {"id": i, "pieces": pieces, "dplc": cue, "tiles": sum(n for _, n in cue),
               "bbox": None, "origin": None, "png": None}
        if r is not None:
            idx, x0, y0, w, h = r
            png = indexed_png(w, h, idx, p["palette"]["rgb"])
            name = f"frames/frame_{i:03d}.png"
            (out / name).write_bytes(png)
            rec.update({"bbox": [x0, y0, x0 + w, y0 + h], "origin": [-x0, -y0],
                        "png": name, "sha256": __import__("hashlib").sha256(png).hexdigest()})
        frames.append(rec)
    t = p["tables"]
    tables = {
        "mappings": f"0x{t['mappings']:06x}", "dplc": f"0x{t['dplc']:06x}",
        "art": f"0x{t['art']:06x}", "art_tiles": t["art_tiles"],
        "palette": f"0x{t['palette']:06x}", "palette_index": t["palette_index"],
        "animations": f"0x{t['animations']:06x}", "vram": f"0x{t['vram']:04x}",
        "dplc_loader": f"0x{t['dplc_loader']:06x}",
        "mapping_refs": [f"0x{r:06x}" for r in t["mapping_refs"]],
    }
    manifest = {
        "tool": f"gbox.sonic1_reader {VERSION}", "engine": "sonic1-md",
        "name": p["name"], "slot": SLOT, "object": "01 (player)",
        "source": p["source"], "header": p["header"], "tables": tables,
        "palette": {**p["palette"], "addr": f"0x{p['palette']['addr']:06x}"},
        "frames": frames, "frame_count": len(frames),
        "max_frame_tiles": max(f["tiles"] for f in frames),
        "animations": {
            "count": len(scripts), "scripts": scripts,
            "walk": p["animation"]["walk"], "run": p["animation"]["run"],
            "reachable_frames": p["animation"]["reachable_frames"],
            "unreachable_frames": p["animation"]["unreachable_frames"],
        },
        "writer_hint": "frames[].pieces and frames[].dplc re-encode byte-identically via "
                       "gbox.sonic1_analysis.encode_frame_map / encode_frame_dplc; frames[].png "
                       "is the assembled frame on Pal_Sonic line 0 with index 0 transparent.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


# -------------------------------------------------------------- other art -----

def nemesis_art(src) -> list[dict]:
    """Decode the Sonic graphics outside the DPLC set (title / continue / signpost /
    lives / ending) at the addresses sonic1_analysis.sonic_art_users reports."""
    d, _info = I.read_rom(src)
    loc = I.locate(d)
    plcs = A.plc_lists(d)[1]
    loads = A.nemesis_loads(d)[1]
    out = []
    seen = set()
    for u in A.sonic_art_users(d, plcs, loads):
        art = int(u["art"], 16)
        if art in seen:                            # Nem_MiniSonic serves two roles
            continue
        seen.add(art)
        try:
            tiles = M.nemesis_decompress(d, art)
        except M.CodecError as e:
            raise ReaderError(f"{u['role']}: Nemesis decode failed: {e}") from e
        out.append({"role": u["role"], "art": u["art"], "vram": u["vram"],
                    "tiles": u["tiles"], "decoded_bytes": len(tiles),
                    "decoded_sha256": __import__("hashlib").sha256(tiles).hexdigest()})
    return out


# ------------------------------------------------------- DEDICATED reader ----

def title_test(t: str, p: str) -> bool:
    t = (t or "").strip().lower()
    return p == "genesis" and "shadow" in t and "sonic" in t


def roster() -> list[dict]:
    return [{"key": "shadow", "slug": "sonic1_shadow", "name": "Shadow (Shadow In Sonic 1)",
             "char": "shadow", "game": "sonic1", "slot": SLOT,
             "aliases": ["Shadow", "Shadow In Sonic 1 Shadow", "sonic1_shadow"],
             "kind": "character"}]


def extract_run(ctx, game: dict, entry: dict, work) -> dict:
    """characters op=collect / extract: Shadow's frames + clips from the catalog ROM."""
    from .models import CatalogEntry
    from .tools import rom_path
    src = rom_path(CatalogEntry.model_validate(game), ctx.config)
    p = read_player(src)
    if p["name"] != "Shadow":
        raise ReaderError(f"{Path(src).name} is {p['name']}, not the Shadow build")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    # overview sheet (RGBA, all frames) is the collection "model" image
    sheet = I.sprite_sheet(p["art"], p["maps"], p["cues"], p["palette"]["rgb"])
    (work / "overview.png").write_bytes(sheet)
    export(src, work)
    animations = [
        {"clip": f"anim_{s['id']:02x}", "name": f"animation {s['id']:#04x}",
         "frames": s["reachable_frames"], "duration_frames": s["duration"],
         "end": s["end"], "kind": "animation"}
        for s in export_scripts(p)
    ]
    return {"files": [work / "overview.png", work / "frames", work / "manifest.json"],
            "roles": {}, "kind": "sprites", "tool": f"gbox.sonic1_reader {VERSION}",
            "source_files": [f"{Path(src).name}: mappings 0x{p['tables']['mappings']:x}, "
                             f"DPLC 0x{p['tables']['dplc']:x}, art 0x{p['tables']['art']:x}, "
                             f"animations 0x{p['tables']['animations']:x}"],
            "notes": f"{p['frame_count']} mapping frames + {p['animation']['scripts']} animations "
                     f"decoded from the ROM; import-ready pieces/DPLC in manifest.json. Other Nemesis art is available through nemesis_art",
            "extra": {"picture": "2d", "sonic1_shadow_reader": READER_VERSION, "animations": animations,
                      "sonic1_reader": {"version": READER_VERSION, "game": "sonic1",
                                        "character": "shadow", "slot": SLOT,
                                        "rom": p["source"]}}}


def export_scripts(p: dict) -> list[dict]:
    """The animation map with the walk/run angle expansion (for extract_run's meta)."""
    walk_offs = p["animation"]["walk"]["angle_offsets"]
    run_offs = p["animation"]["run"]["angle_offsets"]
    walk_id, run_id = p["animation"]["walk"]["anim"], p["animation"]["run"]["anim"]
    out = []
    for s in p["animation"]["script_list"]:
        offs = walk_offs if s["id"] == walk_id else run_offs if s["id"] == run_id else [0]
        reach = sorted({f + o for f in s["frames"] for o in offs if f + o < len(p["maps"])})
        out.append({**s, "reachable_frames": reach})
    return out


# ---------------------------------------------------------------------- CLI --

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sonic 1 (Mega Drive) player reader (Shadow In Sonic 1)")
    ap.add_argument("rom")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nemesis", help="also write the Nemesis art manifest here")
    a = ap.parse_args(argv)
    man = export(a.rom, a.out)
    print(f"{man['name']}: {man['frame_count']} frames, {man['animations']['count']} animations "
          f"-> {a.out}/manifest.json")
    if a.nemesis:
        art = nemesis_art(a.rom)
        Path(a.nemesis).write_text(json.dumps(art, indent=1))
        print(f"{len(art)} Nemesis art blobs -> {a.nemesis}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
