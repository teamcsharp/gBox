"""Writer tests for the Sonic 1 (Mega Drive) player in "Shadow In Sonic 1" (gbox.sonic1_swap).

Owned-ROM tests use ~/gbox-cache/1fff93531f10c256/source.zip (identified by ROM SHA-256) and skip without it."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from gbox import sonic1_analysis as A
from gbox import sonic1_inventory as I
from gbox import sonic1_reader as R
from gbox import sonic1_swap as W

CACHE = Path(os.environ.get("GBOX_ROM_CACHE", Path.home() / "gbox-cache"))
OWNED_ROM_SHA256 = "a22564d49d28bfab70e2046b1c08d7a6a19f6bf4183491e0280ef916fb4863ce"


def _owned() -> tuple[bytes, Path]:
    p = CACHE / "1fff93531f10c256" / "source.zip"
    if not p.is_file():
        pytest.skip(f"owned ROM not cached at {p}")
    d, info = I.read_rom(p)
    if info["rom_sha256"] != OWNED_ROM_SHA256:
        pytest.skip("not the owned Shadow In Sonic 1 build")
    return d, p


def _donor_frames() -> list[np.ndarray]:
    """A visibly different synthetic donor: 6 RGBA poses (a striped capsule that changes width per pose)."""
    out = []
    for k in range(6):
        f = np.zeros((48, 32, 4), np.uint8)
        w = 10 + 3 * k
        f[4:46, 16 - w // 2:16 + w // 2] = (230, 40 + 30 * k, 40, 255)
        f[10:16, 4:28] = (240, 240, 240, 255)
        f[20::6, 8:24] = (20, 20, 20, 255)
        out.append(f)
    return out


# ------------------------------------------------------------------ pure units

def test_chunk_cues_respects_entry_limit():
    assert W.chunk_cues(10, 27) == [(10, 16), (26, 11)]
    assert W.chunk_cues(0, 3) == [(0, 3)]
    assert W.chunk_cues(5, 0) == []


def test_quantize_uses_line0_only_and_alpha_is_index_zero():
    pal = [(0, 0, 0)] + [(c * 16, c * 16, c * 16) for c in range(1, 16)]
    img = np.zeros((2, 2, 4), np.uint8)
    img[0, 0] = (250, 250, 250, 255)
    img[0, 1] = (255, 255, 255, 10)
    q = W.quantize_to_palette(img, pal)
    assert q[0, 0] == 15 and q[0, 1] == 0 and q.min() == 0 and q.max() <= 15


def test_slice_frame_handles_flips_and_detects_conflicts():
    piece = {"x": 0, "y": 0, "w": 1, "h": 1, "tile": 0, "hflip": True, "vflip": False}
    canvas = np.arange(64, dtype=np.uint8).reshape(8, 8) % 16
    t, c = W.slice_frame(canvas, [piece], 1)
    assert c == 0 and (t[0] == canvas[:, ::-1]).all()          # the tile is stored un-flipped
    two = [piece, dict(piece, x=8, hflip=False)]               # same tile, different pixels -> conflict
    _, c2 = W.slice_frame(np.concatenate([canvas, canvas[::-1]], 1), two, 1)
    assert c2 == 1


def test_plan_layout_never_crosses_a_dma_bank():
    rom = bytes(0x8D036) + bytes([0xFF]) * (0x100000 - 0x8D036)
    d, a = W.plan_layout(rom, 854, 76352)
    assert a % 32 == 0 and a // W.BANK == (a + 76352 - 1) // W.BANK and a >= d + 854
    d, a = W.plan_layout(rom, 854, 100000)                    # too big for the rest of bank 4 -> next bank
    assert a % W.BANK == 0 and a >= 0xA0000


def test_is_slot():
    assert W.is_slot("sonic") and W.is_slot("Player") and not W.is_slot("enemies")


# --------------------------------------------------------------------- owned ROM

def test_noop_roundtrip_renders_identically_and_changes_only_enumerated_ranges():
    rom, _ = _owned()
    new, rep = W.write_player(rom, None)
    a, b = W.readback(rom), W.readback(new)
    assert len(a) == 130 and a == b                           # every frame renders pixel-identically
    loc = I.locate(rom)
    ranges = W.changed_ranges(rom, new)
    sites = rep["patched"]
    allowed = [(0x18E, 0x190), (sites["lea_dplc"], sites["lea_dplc"] + 4), (sites["move_art"], sites["move_art"] + 4)]
    tail = int(A.free_tail(rom)["start"], 16)
    for lo, hi in ranges:
        assert any(lo >= x and hi <= y for x, y in allowed) or lo >= tail, (hex(lo), hex(hi))
    # the original Map/DPLC/Art are untouched, the ROM keeps its size
    assert new[loc["mappings"]:loc["art"]] == rom[loc["mappings"]:loc["art"]]
    assert len(new) == len(rom)
    assert rep["max_tiles"] == 27 and rep["max_entries"] <= 2 and rep["slice_conflicts"] == 0
    chk = bytearray(new)
    assert A.fix_checksum(chk) == int.from_bytes(new[0x18E:0x190], "big")
    assert new[0x18E:0x190] == chk[0x18E:0x190]


def test_reslicing_the_original_render_is_semantically_a_noop():
    rom, _ = _owned()
    frames = W.readback(rom)
    canv = [None if f is None else np.frombuffer(f[0], np.uint8).reshape(f[4], f[3]) for f in frames]
    new, rep = W.write_player(rom, canv)
    assert rep["slice_conflicts"] == 0
    assert W.readback(new) == frames


def test_changed_donor_is_read_back_and_unrelated_bytes_survive():
    rom, _ = _owned()
    new, rep = W.build_rom(rom, _donor_frames())
    before, after = W.readback(rom), W.readback(new)
    assert len(after) == 130
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    assert len(changed) >= 120                                # the player really looks different
    for x, y in zip(before, after):                           # same frame boxes: geometry untouched
        if x and y:
            assert x[1:] == y[1:]
    assert rep["max_tiles"] <= W.MAX_LEVEL_TILES and rep["max_entries"] <= 2
    loc = I.locate(rom)
    assert new[loc["mappings"]:loc["dplc"]] == rom[loc["mappings"]:loc["dplc"]]     # Map_Sonic byte-identical
    tail = int(A.free_tail(rom)["start"], 16)
    assert new[:tail][:0x18E] == rom[:0x18E] and new[0x190:0x1448F] == rom[0x190:0x1448F]
    assert new[0x14492:0x144A7] == rom[0x14492:0x144A7] and new[0x144AA:tail] == rom[0x144AA:tail]
    # every drawn pixel index stays inside Pal_Sonic line 0
    assert all(max(f[0]) <= 15 for f in after if f)
    # the patched loader points at the relocated tables and the art does not cross a bank
    back = I.locate(new)
    assert back["dplc"] == rep["dplc_addr"] and back["art"] == rep["art_addr"]
    assert rep["art_addr"] // W.BANK == (rep["art_addr"] + rep["art_bytes"] - 1) // W.BANK


def test_build_rom_is_deterministic():
    rom, _ = _owned()
    a, _ = W.build_rom(rom, _donor_frames())
    b, _ = W.build_rom(rom, _donor_frames())
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_build_mod_writes_the_mod_with_its_hash(tmp_path, monkeypatch):
    rom, src = _owned()
    from gbox import characters as C, filemods, tools
    from gbox import clayfighter_swap as CF
    from gbox import models
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "lib")
    monkeypatch.setattr(filemods, "mod_dir", lambda cfg, gid, name: tmp_path / "mods" / gid / name)
    monkeypatch.setattr(tools, "rom_path", lambda entry, cfg: src)
    monkeypatch.setattr(models.CatalogEntry, "model_validate", classmethod(lambda cls, g: g))
    monkeypatch.setattr(CF, "donor_frames", lambda d, m: (_donor_frames(), "synthetic"))
    meta = {"slug": "donor_x", "name": "Donor X", "kind": "sprites"}
    r = W.build_mod(None, {"game_id": W.GAME_ID}, meta)
    d = tmp_path / "mods" / W.GAME_ID / r["mod"]
    img = (d / r["image"]).read_bytes()
    mj = json.loads((d / ".gbox-mod.json").read_text())
    assert hashlib.sha256(img).hexdigest() == r["mod_sha256"] == mj["mod_sha256"]
    assert mj["source_rom_sha256"] == OWNED_ROM_SHA256 and img != rom
    assert (CACHE / "1fff93531f10c256" / "source.zip").is_file()      # the owned source was not modified
    assert I.read_rom(src)[1]["rom_sha256"] == OWNED_ROM_SHA256


# ------------------------------------------------------------------ registration

def test_registered_writer_and_route():
    from gbox import char_coverage as CC
    row = next(r for r in CC.WRITERS if r[0] == "sonic1_swap")
    assert "sonic" in row[1]
    game = {"game_id": W.GAME_ID, "title": "Shadow In Sonic 1", "platform": "genesis"}
    w = CC.writer_for(game)
    assert w and w["writer"] == "gbox.sonic1_swap" and w["routed"]
    assert {"sonic"} <= {s["slot"] for s in CC.cast_slots(game)}
    assert CC.extractor_for(game)[0] == "sonic1_shadow"
