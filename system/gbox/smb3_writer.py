"""Super Mario Bros. 3 (NES) player sprite writer: edited sheets -> patched CHR -> a separate iNES mod (#1328).

The reader (``gbox.smb3_sprites``) exports per power-up an indexed 4-colour sheet of the 81 player frames
(9x9 cells of 24x32 px; index 0 transparent, 1..3 the suit palette).  Every cell is six 8x16 sprite patterns
(3 columns x 2 rows) and every pattern is two stacked 8x8 2bpp CHR tiles at (page, tile), tile+1.  This
module turns edited cells back into those tiles.

Rules the writer keeps:
  * only cells that DIFFER from the ROM's own rendering are written (so an unedited sheet is a byte-identical
    no-op) and only the referenced (page, tile) of a visible slot is touched; the 7-9 unreferenced non-blank
    tiles per page, every PRG byte, the iNES header and the other 64+ pages stay as shipped;
  * a tile drawn at several slots/frames can hold only one picture: the first edit in frame order wins and
    every later disagreeing edit is reported as a conflict (never silently merged);
  * pixels over a hidden ($F1) slot have no tile and are dropped (reported);
  * the Kuribo's-shoe page ($0B tiles $28-$2D) is shared with the Goomba-in-shoe object, so it is read-only
    unless ``allow_shared`` is set;
  * Small and Frog (root $50) and Big and Fire (root $54) share CHR pages: editing one edits the other's
    art wherever both draw the same tile; palettes still come from the suit.
The grow override immediates ($D249/$D24F) are only relevant when pages are relocated; this writer never moves
a page, so PRG is untouched.  MMC3 has no CHR checksum.  The original ROM is only read.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from . import smb3_analysis as ana
from . import smb3_inventory as inv
from . import smb3_sprites as spr

VERSION = "1.0"
GAME_ID = "213e4208929ec3e9"
GAME_IDS = {GAME_ID: "Super Mario Bros. 3 (USA)"}
TITLE = "Super Mario Bros. 3 (USA)"
CELL_W, CELL_H = 24, 32
SLOTS = ("player",) + tuple(f"player:{s}" for s in inv.POWERUPS)


# ------------------------------------------------------------------------------------------------ sheets

def sheet_to_frames(png: bytes | Path) -> list[list[list[int]]]:
    """An (edited) indexed sheet PNG -> 81 frames of 32 rows x 24 colour indices (0..3)."""
    from PIL import Image
    im = Image.open(io.BytesIO(png) if isinstance(png, (bytes, bytearray)) else png)
    if im.mode != "P":
        raise ValueError("the sheet must be an indexed (palette) PNG as exported by gbox.smb3_sprites")
    w, h = spr.SHEET_COLS * CELL_W, spr.SHEET_ROWS * CELL_H
    if im.size != (w, h):
        raise ValueError(f"sheet must be {w}x{h}, got {im.size[0]}x{im.size[1]}")
    px = im.tobytes()
    if px and max(px) > 3:
        raise ValueError("sheet uses palette indices above 3 (a 2bpp tile holds 0..3)")
    frames = []
    for f in range(inv.FRAMES):
        ox, oy = (f % spr.SHEET_COLS) * CELL_W, (f // spr.SHEET_COLS) * CELL_H
        frames.append([list(px[(oy + y) * w + ox: (oy + y) * w + ox + CELL_W]) for y in range(CELL_H)])
    return frames


def frames_to_sheet_png(ex: spr.SMB3Sprites, suit: str, frames) -> bytes:
    colours = ex.rules["by_suit"][suit]["mario"]["colours"]
    palette = [(0, 0, 0)] + [ana.nes_rgb(c) for c in colours]
    w, h = spr.SHEET_COLS * CELL_W, spr.SHEET_ROWS * CELL_H
    idx = bytearray(w * h)
    for f, img in enumerate(frames):
        ox, oy = (f % spr.SHEET_COLS) * CELL_W, (f // spr.SHEET_COLS) * CELL_H
        for y, row in enumerate(img):
            idx[(oy + y) * w + ox: (oy + y) * w + ox + CELL_W] = bytes(row)
    return spr.indexed_png_bytes(w, h, bytes(idx), palette)


# ------------------------------------------------------------------------------------------------ planning

def _slot_tiles(ex, suit, f):
    """(slot, pattern, page, tile) of every visible slot of one frame of one suit."""
    root = ex.tables["root_pages"][suit]
    page = root + ex.tables["page_off"][f]
    out = []
    for slot, p in enumerate(ex.tables["frames"][f]):
        if p == inv.HIDDEN:
            continue
        pg, t = inv.pattern_page(page, p, ex.shoe_page)
        if pg is not None:
            out.append((slot, p, pg, t))
    return out


def plan_edits(ex: spr.SMB3Sprites, suit: str, frames, allow_shared: bool = False) -> dict:
    """Compare edited frames with the ROM's own cells -> {(page, tile): 16 bytes} plus a report."""
    if suit not in inv.POWERUPS:
        raise ValueError(f"unknown power-up {suit!r}; one of {', '.join(inv.POWERUPS)}")
    if len(frames) != inv.FRAMES:
        raise ValueError(f"expected {inv.FRAMES} frames, got {len(frames)}")
    orig = ex.suit_frames(suit)
    edits: dict[tuple[int, int], bytes] = {}
    owner: dict[tuple[int, int], int] = {}
    conflicts, dropped, shared_skipped, changed_frames = [], [], [], []
    for f in range(inv.FRAMES):
        new = frames[f]
        if new == orig[f]:
            continue
        changed_frames.append(f)
        visible = set()
        for slot, _p, pg, t in _slot_tiles(ex, suit, f):
            sx, sy = slot % 3 * 8, slot // 3 * 16
            for half in (0, 1):
                visible.add((sx, sy + half * 8))
                rows = [new[sy + half * 8 + y][sx:sx + 8] for y in range(8)]
                key = (pg, t + half)
                if pg == ex.shoe_page and not allow_shared:
                    if rows != [orig[f][sy + half * 8 + y][sx:sx + 8] for y in range(8)]:
                        shared_skipped.append({"frame": f, "page": pg, "tile": t + half})
                    continue
                enc = spr.encode_tile(rows)
                if enc == bytes(ex.chr[(pg * 64 + t + half) * 16:(pg * 64 + t + half) * 16 + 16]) and key not in edits:
                    continue
                if key in edits:
                    if edits[key] != enc:
                        conflicts.append({"frame": f, "page": pg, "tile": t + half, "kept_from_frame": owner[key]})
                    continue
                edits[key] = enc
                owner[key] = f
        for y in range(CELL_H):
            for x in range(CELL_W):
                if new[y][x] and (x // 8 * 8, y // 8 * 8) not in visible:
                    dropped.append({"frame": f, "x": x, "y": y})
                    break
            else:
                continue
            break
    return {"edits": edits, "owner": owner, "conflicts": conflicts, "dropped": dropped,
            "shared_skipped": shared_skipped, "changed_frames": changed_frames}


def apply_edits(chr_: bytes, edits: dict) -> bytes:
    out = bytearray(chr_)
    for (pg, t), tile in edits.items():
        o = (pg * 64 + t) * 16
        if len(tile) != 16 or o + 16 > len(out):
            raise ValueError(f"tile edit out of range: page {pg} tile {t}")
        out[o:o + 16] = tile
    return bytes(out)


def diff_ranges(a: bytes, b: bytes) -> list[tuple[int, int]]:
    """Maximal changed byte ranges [start, end) between two equal-length images."""
    if len(a) != len(b):
        raise ValueError("length differs")
    out, start = [], None
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y and start is None:
            start = i
        elif x == y and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(a)))
    return out


# ------------------------------------------------------------------------------------------------ mod build

def build_rom(ex: spr.SMB3Sprites, new_chr: bytes) -> bytes:
    """The owned image with CHR replaced; header, trainer and PRG are copied verbatim."""
    data, _info = inv.read_source(ex.source["path"])
    hdr = inv.parse_ines(data)
    start = 16 + (512 if data[6] & 4 else 0) + data[4] * inv.PRG_UNIT
    if len(new_chr) != len(ex.chr) or data[start:start + len(ex.chr)] != ex.chr:
        raise ValueError("CHR length/offset mismatch against the source image")
    out = data[:start] + new_chr + data[start + len(new_chr):]
    assert len(out) == len(data) and hdr["mapper"] == 4
    return out


def verify_mod(ex: spr.SMB3Sprites, mod: bytes, edits: dict, tmp: Path) -> dict:
    """Independent read-back: parse the mod with the reader's own decoder and compare with the source."""
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    p = tmp / "readback.nes"
    p.write_bytes(mod)
    data, _ = inv.read_source(ex.source["path"])
    mhdr = inv.parse_ines(mod)
    prg, chr_ = inv.split(mod, mhdr)
    ranges = diff_ranges(ex.chr, chr_)
    all_chr_tiles = {(o // 16 // 64, o // 16 % 64) for s, e in ranges for o in range(s - s % 16, e, 16)}
    ref = ex.referenced_tiles()
    return {
        "size": len(mod), "sha256": hashlib.sha256(mod).hexdigest(),
        "header_identical": mod[:16] == data[:16], "prg_identical": prg == ex.prg,
        "chr_length_identical": len(chr_) == len(ex.chr),
        "chr_changed_ranges": len(ranges), "chr_changed_bytes": sum(e - s for s, e in ranges),
        "changed_tiles": len(all_chr_tiles),
        "only_planned_tiles_changed": all_chr_tiles <= set(edits),
        "unreferenced_untouched": all(t in ref.get(pg, set()) for pg, t in all_chr_tiles),
        "intended_tiles_written": all(
            chr_[(pg * 64 + t) * 16:(pg * 64 + t) * 16 + 16] == tile for (pg, t), tile in edits.items()),
    }


# ------------------------------------------------------------------------------------------------ donor fitting

def _palette_rgb(ex, suit):
    return [ana.nes_rgb(c) for c in ex.rules["by_suit"][suit]["mario"]["colours"]]


def quantize_rgba(img, palette) -> list[list[int]]:
    """RGBA (any size) -> 24x32 indices: crop to the opaque bbox, fit inside the cell keeping aspect (bottom
    centre, as the hotspot), alpha >= 128 -> nearest of the three suit colours."""
    import numpy as np
    from . import clayfighter_swap as cf
    a = cf._crop(np.asarray(img, np.uint8))
    if a.shape[0] <= 1 and a.shape[1] <= 1:
        return [[0] * CELL_W for _ in range(CELL_H)]
    s = min(CELL_W / a.shape[1], CELL_H / a.shape[0])
    w, h = max(1, round(a.shape[1] * s)), max(1, round(a.shape[0] * s))
    r = cf._resize(a, w, h)
    pal = np.array(palette, np.int32)
    out = [[0] * CELL_W for _ in range(CELL_H)]
    ox, oy = (CELL_W - w) // 2, CELL_H - h
    for y in range(h):
        for x in range(w):
            if r[y, x, 3] >= 128:
                d = ((pal - r[y, x, :3].astype(np.int32)) ** 2).sum(1)
                out[oy + y][ox + x] = int(d.argmin()) + 1
    return out


def fit_donor(ex: spr.SMB3Sprites, suit: str, donor_rgba: list, frames: list[int] | None = None) -> list:
    """Dealt donor RGBA frames -> 81 SMB3 frames (unlisted / empty target frames stay as shipped)."""
    from . import clayfighter_swap as cf
    pal = _palette_rgb(ex, suit)
    orig = ex.suit_frames(suit)
    targets = frames if frames is not None else [f for f in range(inv.FRAMES) if any(any(r) for r in orig[f])]
    deal = cf.deal(len(targets), len(donor_rgba))
    out = [[list(r) for r in fr] for fr in orig]
    for f, d in zip(targets, deal):
        out[f] = quantize_rgba(donor_rgba[d], pal)
    return out


def mod_name(meta: dict, suit: str) -> str:
    return f"smb3_{meta.get('slug', 'donor')}_as_{suit}"[:64]


def write_mod(src, suit_frames: dict, out_dir, allow_shared: bool = False) -> dict:
    """Edited frames per suit -> <out_dir>/<TITLE>.nes + manifest.json.  Returns the manifest."""
    ex = spr.SMB3Sprites(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    edits, owner, per_suit = {}, {}, {}
    conflicts, dropped, shared = [], [], []
    for suit, frames in suit_frames.items():
        plan = plan_edits(ex, suit, frames, allow_shared)
        for key, tile in plan["edits"].items():
            if key in edits and edits[key] != tile:
                conflicts.append({"suit": suit, "page": key[0], "tile": key[1], "kept_suit": owner[key]})
                continue
            edits[key] = tile
            owner[key] = suit
        conflicts += [dict(c, suit=suit) for c in plan["conflicts"]]
        dropped += [dict(d, suit=suit) for d in plan["dropped"]]
        shared += [dict(d, suit=suit) for d in plan["shared_skipped"]]
        per_suit[suit] = {"changed_frames": len(plan["changed_frames"]), "tiles": len(plan["edits"])}
    new_chr = apply_edits(ex.chr, edits)
    mod = build_rom(ex, new_chr)
    rb = verify_mod(ex, mod, edits, out_dir / "_readback")
    (out_dir / "_readback" / "readback.nes").unlink(missing_ok=True)
    (out_dir / "_readback").rmdir()
    (out_dir / f"{TITLE}.nes").write_bytes(mod)
    manifest = {"tool": f"gbox.smb3_writer {VERSION}", "game_id": GAME_ID, "title": TITLE,
                "source_sha256": ex.source["sha256"], "identity": ex.ident, "mod": rb,
                "suits": per_suit, "conflicts": conflicts, "dropped_pixels": dropped,
                "shared_page_skipped": shared,
                "ranges": [[s, e] for s, e in diff_ranges(ex.chr, new_chr)],
                "note": "CHR-only mod: PRG, header, unreferenced tiles and the original image are unchanged"}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


# ------------------------------------------------------------------------------------------------ gBox route

def suits_for(slot: str) -> list[str]:
    s = (slot or "player").strip().lower()
    if s in ("player", "mario", "luigi"):
        return list(inv.POWERUPS)
    s = s.split(":", 1)[-1]
    if s not in inv.POWERUPS:
        raise ValueError(f"unknown slot {slot!r}; use one of {', '.join(SLOTS)}")
    return [s]


def is_slot(slot: str) -> bool:
    try:
        suits_for(slot)
        return True
    except ValueError:
        return False


def needs(game: dict) -> dict:
    return {"target": "Mario's player sprite CHR tiles", "format": "NES 2bpp tiles in MMC3 CHR pages $00-03/$40-57",
            "steps": [], "have": "gbox/smb3_writer.py: characters op=use slot=player[:small|big|fire|leaf|frog|tanooki|hammer]"}


def build_mod(cfg, game: dict, meta: dict, slot: str = "player", progress=lambda p, m: None,
              root: Path | None = None) -> dict:
    """The donor collection entry's frames replace Mario's in a separate mod dir (the source is only read)."""
    import shutil
    import time
    from . import characters as C
    from . import clayfighter_swap as cf
    from . import filemods
    from .models import CatalogEntry
    from .tools import rom_path
    root = root or C.library_root(cfg)
    src = rom_path(CatalogEntry.model_validate(game), cfg)
    suits = suits_for(slot)
    progress(10, "reading the donor frames")
    donor, how = cf.donor_frames(Path(root) / meta["slug"], meta)
    ex = spr.SMB3Sprites(src)
    name = mod_name(meta, "all" if len(suits) > 1 else suits[0])
    progress(40, f"fitting {len(donor)} donor frames into 24x32 / 3-colour cells")
    fitted = {s: fit_donor(ex, s, donor) for s in suits}
    d = filemods.mod_dir(cfg, GAME_ID, name)
    if d.exists():
        shutil.rmtree(d)
    progress(70, "writing the CHR-patched iNES mod")
    man = write_mod(src, fitted, d)
    rb = man["mod"]
    if not (rb["header_identical"] and rb["prg_identical"] and rb["intended_tiles_written"]
            and rb["only_planned_tiles_changed"]):
        raise RuntimeError(f"read-back check failed: {rb}")
    (d / "preview.png").write_bytes(frames_to_sheet_png(ex, suits[0], fitted[suits[0]]))
    man.update({"donor": meta.get("name"), "donor_frames": len(donor), "donor_source": how, "slot": slot})
    (d / "manifest.json").write_text(json.dumps(man, indent=1))
    mj = {"name": name, "game_id": GAME_ID, "image": f"{TITLE}.nes", "title": f"{meta['name']} as Mario",
          "files": ["@image: player CHR tiles (gbox.smb3_writer)"], "built": time.time(),
          "characters": [meta["slug"]], "replaces": [f"Mario ({', '.join(suits)})"], "donor": how,
          "report": {"mod_sha256": rb["sha256"], "changed_tiles": rb["changed_tiles"],
                     "conflicts": len(man["conflicts"]), "source_sha256": man["source_sha256"]}}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    return {"mod": name, "image": f"{TITLE}.nes", "report": mj["report"], "donor": how, "suits": suits}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for SMB3 (NES): slot player[:<power-up>] -> mod smb3_<slug>_as_<suit|all>."""
    from . import characters as C
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": f"not {TITLE}"}
    suits = suits_for(inp.slot)
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    name, built = mod_name(meta, "all" if len(suits) > 1 else suits[0]), None
    if not C.library_root(ctx.config).is_dir():               # not the control plane: build there, launch here
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        j = C._job(ctx, "characters", {"op": "use", "character": inp.character, "game_id": gid, "slot": inp.slot,
                                       "rebuild": inp.rebuild, "launch": False}, cp, 1800)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        name, built = r["mod"], r.get("build")
    else:
        from . import filemods
        have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
        if inp.rebuild or not have:
            built = build_mod(ctx.config, game, meta, inp.slot, ctx.progress)
            C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                   json={"game_id": gid, "slot": inp.slot, "mod": name, "nodes": [C.HOST_OS],
                         "notes": f"Mario ({', '.join(suits)}) CHR tiles re-drawn from {meta['name']}; "
                                  f"PRG unchanged; unverified in game"})
    res = {"mod": name, "build": built, "replaces": f"Mario ({', '.join(suits)}) -> {meta['name']}",
           "slot": inp.slot}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(92, f"Launching {TITLE} (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    from .sm64_swap import _wait
    lj = _wait(ctx, lj, 600)
    ok = lj.get("state") == "succeeded"
    msg = (f"{TITLE} is running with Mario re-drawn as {meta['name']} (mod {name})." if ok else
           f"Mod {name} built but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": (built and "built+launched" or "launched") if ok else "built, launch failed",
                  "launch": {"job": lj.get("id"), "state": lj.get("state"), "node": node,
                             "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")},
                  "message": msg}
