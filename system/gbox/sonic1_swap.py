"""Writer: re-draw the player of "Shadow In Sonic 1" (Mega Drive, Sonic 1 REV00 disassembly rebuild).

``characters op=use character=<sprites entry> game=<Shadow In Sonic 1> slot=sonic`` (or ``player``/``shadow``) re-draws
all 130 player mapping frames with a collection donor and writes a separate ROM mod (the owned ROM is never touched).

How (all addresses come from gbox.sonic1_inventory.locate, not constants):
* the 130 mapping frames (Map_Sonic, S1 5-byte pieces) are left byte-for-byte as they are, so every frame keeps its
  hit-box/animation/sprite geometry; only the *tile art* behind each frame changes;
* each frame's donor canvas is cut into the frame's own pieces (``slice_frame``), quantised to Pal_Sonic line 0
  (index 0 transparent) so the shared line-0 palette is never edited;
* the per-frame tile streams are rebuilt into a new Art (identical streams stored once), a new DPLC table with
  <=16-tile entries (fewer DMA-queue slots than before), both written into the ROM's 0xFF tail with the art not
  crossing a 128 KiB DMA bank, and the two code operands are patched: ``lea DPLC,a2`` and ``move.l #Art,d6`` in
  LoadSonicDynPLC; the header checksum is recomputed.

Limits kept: <=32 tiles/frame in levels (the hack's $F400 effect object follows the $F000 buffer), 12-bit tile
numbers, frame slots 0..129 unchanged.  Title/continue/ending Nemesis art and the special-stage Sonic are other
users of the player's look and are NOT touched by this writer (see sonic1_reader.nemesis_art).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from gbox import sonic1_analysis as A
from gbox import sonic1_inventory as I
from gbox import sonic1_reader as R

GAME_ID = "1fff93531f10c256"
GAME_IDS = {GAME_ID: "Shadow In Sonic 1 (genesis)"}
SLOTS = {"sonic", "player", "shadow", "sonic1_shadow"}
BANK = 0x20000                    # a DMA source must not cross a 128 KiB boundary
MAX_LEVEL_TILES = 32              # $F000 buffer .. $F400 effect object
MAX_ENTRY_TILES = 16              # one DPLC entry = one DMA transfer, 4 bits of count


class WriterError(RuntimeError):
    pass


def is_slot(slot: str) -> bool:
    return (slot or "").strip().lower() in SLOTS


# ------------------------------------------------------------------ geometry --

def frame_box(pieces: list[dict]) -> tuple[int, int, int, int]:
    x0 = min(p["x"] for p in pieces)
    y0 = min(p["y"] for p in pieces)
    x1 = max(p["x"] + 8 * p["w"] for p in pieces)
    y1 = max(p["y"] + 8 * p["h"] for p in pieces)
    return x0, y0, x1 - x0, y1 - y0


def slice_frame(canvas: np.ndarray, pieces: list[dict], n_tiles: int, keep: np.ndarray | None = None):
    """Cut a (h, w) index canvas (frame box origin) into the frame's stream tiles.

    Returns (tiles (n,8,8) uint8, conflicts).  ``keep`` supplies the tiles that no piece references (kept as is)."""
    x0, y0, _w, _h = frame_box(pieces)
    tiles = np.zeros((n_tiles, 8, 8), np.uint8) if keep is None else keep.copy()
    seen: dict[int, bytes] = {}
    conflicts = 0
    for p in pieces:
        for c in range(p["w"]):
            for r in range(p["h"]):
                t = p["tile"] + c * p["h"] + r
                if t >= n_tiles:
                    raise WriterError(f"piece references tile {t} but the frame streams {n_tiles}")
                cc = p["w"] - 1 - c if p["hflip"] else c
                rr = p["h"] - 1 - r if p["vflip"] else r
                px, py = p["x"] - x0 + cc * 8, p["y"] - y0 + rr * 8
                cell = canvas[py:py + 8, px:px + 8]
                if p["hflip"]:
                    cell = cell[:, ::-1]
                if p["vflip"]:
                    cell = cell[::-1, :]
                if t in seen and seen[t] != cell.tobytes():
                    conflicts += 1
                seen[t] = cell.tobytes()
                tiles[t] = cell
    return tiles, conflicts


def quantize_to_palette(rgba: np.ndarray, pal: list[tuple[int, int, int]]) -> np.ndarray:
    """RGBA -> palette indices 1..15 of Pal_Sonic (alpha < 128 -> 0)."""
    rgb = rgba[..., :3].astype(np.int32)
    cols = np.array(pal[1:16], np.int32)
    d = ((rgb[:, :, None, :] - cols[None, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1).astype(np.uint8) + 1
    idx[rgba[..., 3] < 128] = 0
    return idx


# --------------------------------------------------------------------- layout --

def chunk_cues(first: int, n: int) -> list[tuple[int, int]]:
    out = []
    while n > 0:
        k = min(n, MAX_ENTRY_TILES)
        out.append((first, k))
        first += k
        n -= k
    return out


def build_streams(streams: list[np.ndarray]):
    """Per-frame tile streams -> (art tiles bytes, cues per frame); identical streams are stored once."""
    store: dict[bytes, int] = {}
    art = bytearray()
    cues = []
    for s in streams:
        raw = A.pack_tiles([bytes(t.reshape(64)) for t in s])
        if raw not in store:
            store[raw] = len(art) // 32
            art += raw
        cues.append(chunk_cues(store[raw], len(s)))
    if len(art) // 32 > 0x1000:
        raise WriterError(f"{len(art) // 32} art tiles exceed the 12-bit DPLC tile number")
    return bytes(art), cues


def plan_layout(rom: bytes, dplc_len: int, art_len: int) -> tuple[int, int]:
    """(dplc_addr, art_addr) inside the 0xFF tail; art does not cross a 128 KiB bank, 32-byte aligned."""
    tail = int(A.free_tail(rom)["start"], 16)
    dplc = tail + (tail & 1)
    art = (dplc + dplc_len + 31) & ~31
    if art // BANK != (art + art_len - 1) // BANK:
        art = (art + BANK - 1) // BANK * BANK
    if art + art_len > len(rom):
        raise WriterError(f"no room: art would end at {art + art_len:#x}, ROM is {len(rom):#x} bytes")
    return dplc, art


def patch_sites(rom: bytes, loc: dict) -> tuple[int, int]:
    """Code operands of LoadSonicDynPLC: lea DPLC.l,a2 and move.l #Art,d6 (verified against the located tables)."""
    base = loc["dplc_loader"]
    code = rom[base:base + 0x80]
    lea = code.find(b"\x45\xf9" + struct.pack(">I", loc["dplc"]))
    mv = code.find(b"\x2c\x3c" + struct.pack(">I", loc["art"]))
    if lea < 0 or mv < 0:
        raise WriterError("LoadSonicDynPLC operands not found where the tables are")
    return base + lea + 2, base + mv + 2


# ---------------------------------------------------------------------- writer --

def write_player(rom: bytes, canvases: list | None) -> tuple[bytes, dict]:
    """Re-draw the player.  ``canvases[i]`` = (h, w) palette-index canvas of frame i in its frame box (None = keep).

    ``canvases=None`` is the no-op: tables are relocated with their original streams (renders identically)."""
    rom = bytes(rom)
    loc = I.locate(rom)
    p = R.read_player(rom)
    maps, cues, art = p["maps"], p["cues"], p["art"]
    n = len(maps)
    if canvases is not None and len(canvases) != n:
        raise WriterError(f"need {n} canvases, got {len(canvases)}")
    streams, conflicts = [], 0
    for i in range(n):
        raw = b"".join(art[32 * t:32 * (t + k)] for t, k in cues[i])
        old = np.frombuffer(b"".join(A.unpack_tiles(raw)), np.uint8).reshape(-1, 8, 8) if raw else np.zeros((0, 8, 8), np.uint8)
        if canvases is None or canvases[i] is None or not maps[i]:
            streams.append(old)
            continue
        t, c = slice_frame(np.asarray(canvases[i]), maps[i], len(old), keep=old)
        conflicts += c
        streams.append(t)
    too_big = [i for i, s in enumerate(streams) if len(s) > MAX_LEVEL_TILES]
    if too_big:
        raise WriterError(f"frames over {MAX_LEVEL_TILES} tiles: {too_big[:5]}")
    new_art, new_cues = build_streams(streams)
    dplc = A.encode_table([A.encode_frame_dplc(c) for c in new_cues])
    dplc_addr, art_addr = plan_layout(rom, len(dplc), len(new_art))
    lea_at, mv_at = patch_sites(rom, loc)
    out = bytearray(rom)
    out[dplc_addr:dplc_addr + len(dplc)] = dplc
    out[art_addr:art_addr + len(new_art)] = new_art
    out[lea_at:lea_at + 4] = struct.pack(">I", dplc_addr)
    out[mv_at:mv_at + 4] = struct.pack(">I", art_addr)
    old_sum = struct.unpack(">H", out[0x18E:0x190])[0]
    new_sum = A.fix_checksum(out)
    report = {"frames": n, "slice_conflicts": conflicts, "art_tiles": len(new_art) // 32,
              "art_addr": art_addr, "art_bytes": len(new_art), "dplc_addr": dplc_addr, "dplc_bytes": len(dplc),
              "patched": {"lea_dplc": lea_at, "move_art": mv_at}, "max_tiles": max(len(s) for s in streams),
              "max_entries": max(len(c) for c in new_cues), "checksum_old": old_sum, "checksum_new": new_sum,
              "old_tables": {"dplc": loc["dplc"], "art": loc["art"]}}
    return bytes(out), report


def changed_ranges(a: bytes, b: bytes) -> list[tuple[int, int]]:
    """Maximal byte ranges where the two ROMs differ (b may be longer)."""
    x = np.frombuffer(a, np.uint8)
    y = np.frombuffer(b[:len(a)], np.uint8)
    d = np.nonzero(x != y)[0]
    out = []
    for i in d:
        if out and i - out[-1][1] <= 1:
            out[-1] = (out[-1][0], int(i) + 1)
        else:
            out.append((int(i), int(i) + 1))
    if len(b) > len(a):
        out.append((len(a), len(b)))
    return out


def readback(rom: bytes) -> list:
    """The 130 frames as the game draws them, read back independently through the reader (locate() follows the
    patched LoadSonicDynPLC operands, so this uses the tables the new ROM really points at)."""
    p = R.read_player(rom)
    return [R.assemble(p["art"], m, c) for m, c in zip(p["maps"], p["cues"])]


def donor_canvases(rom: bytes, donor_rgba: list[np.ndarray]) -> list[np.ndarray]:
    """Donor RGBA frames -> one palette-index canvas per player frame (donor bottom-centre on the frame's feet)."""
    from . import clayfighter_swap as CF
    p = R.read_player(rom)
    pal = [tuple(c) for c in p["palette"]["rgb"]]
    boxes = [frame_box(m) if m else (0, 0, 8, 8) for m in p["maps"]]
    targets = [{"W": w, "H": h, "X": min(max(-x0, 0), w - 1), "Y": h - 1} for x0, y0, w, h in boxes]
    fitted = CF.fit_frames(targets, donor_rgba)
    return [quantize_to_palette(f, pal) for f in fitted]


def build_rom(rom: bytes, donor_rgba: list[np.ndarray]) -> tuple[bytes, dict]:
    return write_player(rom, donor_canvases(rom, donor_rgba))


# ------------------------------------------------------------ gBox integration --

def mod_name(meta: dict) -> str:
    return f"sonic1_{meta['slug']}_as_player"[:64]


def build_mod(cfg, game: dict, meta: dict, progress=lambda p, m: None, root: Path | None = None) -> dict:
    from . import characters as C, filemods
    from . import clayfighter_swap as CF
    from .models import CatalogEntry
    from .tools import rom_path
    root = root or C.library_root(cfg)
    src = rom_path(CatalogEntry.model_validate(game), cfg)
    progress(5, f"Reading {Path(src).name}")
    rom, info = I.read_rom(src)
    frames, how = CF.donor_frames(root / meta["slug"], meta)
    progress(30, f"Re-drawing 130 player frames with {meta['name']} ({len(frames)} donor frames: {how})")
    new, rep = build_rom(rom, frames)
    back = R.read_player(new)
    if back["frame_count"] != rep["frames"] or back["max_frame_tiles"] > MAX_LEVEL_TILES:
        raise WriterError("read-back of the new ROM failed")
    name = mod_name(meta)
    d = filemods.mod_dir(cfg, game["game_id"], name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    donor = re.sub(r"[^\w .()-]+", "", meta["name"]).strip()
    img = f"Shadow In Sonic 1 - {donor} as player.md"
    (d / img).write_bytes(new)
    mod_sha = hashlib.sha256(new).hexdigest()
    mj = {"name": name, "game_id": game["game_id"], "image": img, "title": f"{meta['name']} as the player",
          "files": ["@image: player art + DPLC (gbox.sonic1_swap)"], "built": time.time(),
          "characters": [meta["slug"]], "replaces": ["player (Shadow in the Sonic slot)"], "donor": how,
          "report": rep, "source_rom_sha256": info["rom_sha256"], "mod_sha256": mod_sha}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    return {"mod": name, "image": img, "report": rep, "donor": how, "mod_sha256": mod_sha}


def cast_slots() -> list[dict]:
    return [{"slot": "sonic", "name": "player (Shadow in the Sonic slot)", "kind": "player",
             "writer": "gbox.sonic1_swap"}]


def needs(game: dict) -> dict:
    return {"target": "the player's tile art + DPLC", "format": "S1 Map_Sonic/SonicDynPLC/Art_Sonic (uncompressed)",
            "steps": [], "have": "gbox/sonic1_swap.py: characters op=use slot=sonic"}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    from . import characters as C
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": "not Shadow In Sonic 1"}
    from . import filemods
    name, built = mod_name(meta), None
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    if inp.rebuild or not have:
        built = build_mod(ctx.config, game, meta, ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "sonic", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"re-draws all {built['report']['frames']} player frames ({built['donor']}); "
                              f"mappings, animations and palette line 0 are the game's own"})
    res = {"mod": name, "build": built, "replaces": f"player -> {meta['name']}", "slot": "sonic"}
    return res | {"status": "built" if built else "ready"}
