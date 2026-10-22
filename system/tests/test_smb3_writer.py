"""Tests for gbox.smb3_writer: SMB3 (NES) player sprite writer (#1328).

Synthetic tests need no ROM.  Owned-ROM tests use GBOX_SMB3_SRC (default: the gBox cache copy of the owned
hyperspin zip) and skip when it is absent.  They prove: an unedited sheet is a byte-identical no-op for every
power-up, a changed donor patches exactly the planned CHR tiles (PRG/header/unreferenced tiles untouched,
independent read-back through the reader), conflicts are reported, the shared Kuribo page is protected, and the
ordinary characters op=use route reaches the writer and records the mod hash.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("capstone")

from gbox import smb3_inventory as inv  # noqa: E402
from gbox import smb3_sprites as spr  # noqa: E402
from gbox import smb3_writer as W  # noqa: E402

SRC = Path(os.environ.get("GBOX_SMB3_SRC", str(Path.home() / "gbox-cache/213e4208929ec3e9/source.zip")))
SRC_SHA256 = "4938974428c867c5ec074b8853b496f91bd82014c2cddf9245a6d1a77eb39cfd"
needs_rom = pytest.mark.skipif(not SRC.is_file(), reason="owned SMB3 source not cached")


# ------------------------------------------------------------------------------------------------ synthetic

def test_apply_edits_and_diff_ranges():
    chr_ = bytes(range(256)) * 16
    t = bytes([0xAA] * 16)
    new = W.apply_edits(chr_, {(0, 3): t, (0, 4): t})
    assert new[48:80] == t * 2 and len(new) == len(chr_)
    assert W.diff_ranges(chr_, new) == [(48, 80)] or all(48 <= s and e <= 80 for s, e in W.diff_ranges(chr_, new))
    assert W.diff_ranges(chr_, chr_) == []
    with pytest.raises(ValueError):
        W.apply_edits(chr_, {(999, 0): t})
    with pytest.raises(ValueError):
        W.apply_edits(chr_, {(0, 0): b"short"})


def test_slots_and_suits():
    assert W.suits_for("player") == list(inv.POWERUPS)
    assert W.suits_for("player:fire") == ["fire"]
    assert W.is_slot("player:hammer") and not W.is_slot("player:cape") and not W.is_slot("fighter:x")


def test_sheet_validation(tmp_path):
    from PIL import Image
    Image.new("RGB", (216, 288)).save(tmp_path / "rgb.png")
    with pytest.raises(ValueError):
        W.sheet_to_frames(tmp_path / "rgb.png")
    im = Image.new("P", (10, 10))
    im.save(tmp_path / "small.png")
    with pytest.raises(ValueError):
        W.sheet_to_frames(tmp_path / "small.png")
    im = Image.new("P", (216, 288), 5)
    im.putpalette([i * 7 % 256 for i in range(3 * 16)])
    im.save(tmp_path / "hi.png")
    with pytest.raises(ValueError):
        W.sheet_to_frames(tmp_path / "hi.png")


def test_quantize_rgba_fits_bottom_centre_and_snaps_to_palette():
    import numpy as np
    img = np.zeros((40, 20, 4), np.uint8)
    img[5:35, 2:18] = (250, 20, 20, 255)
    q = W.quantize_rgba(img, [(248, 0, 0), (0, 0, 248), (0, 248, 0)])
    assert len(q) == 32 and len(q[0]) == 24
    vals = {v for r in q for v in r}
    assert vals == {0, 1}
    cols = [x for x in range(24) if any(r[x] for r in q)]
    assert any(q[31]) and cols[0] + cols[-1] in (22, 23)          # touches the bottom, centred horizontally


def test_writer_registered_and_routed():
    from gbox import char_coverage as cov
    game = {"game_id": W.GAME_ID, "title": "Super Mario Bros. 3", "platform": "nes"}
    w = cov.writer_for(game)
    assert w and w["writer"] == "gbox.smb3_writer" and w["routed"] is True
    assert "player" in w["slots"]


# ------------------------------------------------------------------------------------------------ owned ROM

@pytest.fixture(scope="module")
def ex():
    return spr.SMB3Sprites(SRC)


@needs_rom
def test_noop_roundtrip_every_suit_byte_identical(ex):
    assert ex.source["sha256"] == SRC_SHA256
    for suit in inv.POWERUPS:
        frames = W.sheet_to_frames(ex.sheet_png(suit))
        plan = W.plan_edits(ex, suit, frames)
        assert not plan["edits"] and not plan["changed_frames"] and not plan["conflicts"]
        assert W.apply_edits(ex.chr, plan["edits"]) == ex.chr


@needs_rom
def test_noop_mod_is_byte_identical_to_the_source(ex, tmp_path):
    frames = {s: W.sheet_to_frames(ex.sheet_png(s)) for s in inv.POWERUPS}
    man = W.write_mod(SRC, frames, tmp_path)
    from gbox import smb3_inventory as I
    data, _ = I.read_source(SRC)
    assert (tmp_path / f"{W.TITLE}.nes").read_bytes() == data
    assert man["mod"]["chr_changed_bytes"] == 0 and man["ranges"] == []


@needs_rom
def test_changed_donor_patches_only_planned_tiles(ex, tmp_path):
    frames = W.sheet_to_frames(ex.sheet_png("small"))
    swapped = [[[{1: 3, 3: 1}.get(v, v) for v in r] for r in f] for f in frames]
    man = W.write_mod(SRC, {"small": swapped}, tmp_path)
    m = man["mod"]
    assert m["header_identical"] and m["prg_identical"] and m["chr_length_identical"]
    assert m["only_planned_tiles_changed"] and m["unreferenced_untouched"] and m["intended_tiles_written"]
    assert m["changed_tiles"] > 100 and not man["conflicts"]
    # independent read-back: the reader's decoder on the mod shows the swapped colours, PRG-driven map unchanged
    mod = tmp_path / f"{W.TITLE}.nes"
    rb = spr.SMB3Sprites(mod)
    assert rb.tables["frames"] == ex.tables["frames"] and rb.prg == ex.prg
    got = rb.suit_frames("small")
    want = [[[{1: 3, 3: 1}.get(v, v) for v in r] for r in f] for f in ex.suit_frames("small")]
    # frames that draw the Kuribo shared page keep those tiles as shipped
    shoe = {f for f in range(inv.FRAMES) if any(
        inv.pattern_page(ex.tables["root_pages"]["small"] + ex.tables["page_off"][f], p, ex.shoe_page)[0] == ex.shoe_page
        for p in ex.tables["frames"][f] if p != inv.HIDDEN)}
    assert shoe
    assert all(got[f] == want[f] for f in range(inv.FRAMES) if f not in shoe)
    assert rb.chr[ex.shoe_page * 64 * 16:(ex.shoe_page + 1) * 64 * 16] == ex.chr[ex.shoe_page * 64 * 16:(ex.shoe_page + 1) * 64 * 16]
    assert {s["frame"] for s in man["shared_page_skipped"]} <= shoe
    # frog shares small's pages: its art changed where it draws the same tiles
    assert rb.suit_frames("frog") != ex.suit_frames("frog")
    # the owned zip and its sha are unchanged
    assert spr.inv.read_source(SRC)[1]["sha256"] == SRC_SHA256


@needs_rom
def test_conflicting_edits_are_reported_not_merged(ex):
    frames = W.sheet_to_frames(ex.sheet_png("big"))
    pl0 = W.plan_edits(ex, "big", frames)
    key = None
    for f in range(inv.FRAMES):                       # find a tile drawn by two frames and edit them differently
        tiles = {(pg, t) for _s, _p, pg, t in W._slot_tiles(ex, "big", f)}
        for g in range(f + 1, inv.FRAMES):
            both = tiles & {(pg, t) for _s, _p, pg, t in W._slot_tiles(ex, "big", g)}
            both = {k for k in both if k[0] != ex.shoe_page}
            if both:
                key = (f, g)
                break
        if key:
            break
    assert key and not pl0["edits"]
    f, g = key
    for h, v in ((f, 1), (g, 2)):
        for slot, _p, pg, t in W._slot_tiles(ex, "big", h):
            sx, sy = slot % 3 * 8, slot // 3 * 16
            for y in range(16):
                for x in range(8):
                    frames[h][sy + y][sx + x] = v
    plan = W.plan_edits(ex, "big", frames)
    assert plan["conflicts"] and all(c["kept_from_frame"] == f for c in plan["conflicts"] if c["frame"] == g)


@needs_rom
def test_hidden_slot_pixels_are_dropped_and_reported(ex):
    frames = W.sheet_to_frames(ex.sheet_png("small"))
    target = next(f for f in range(inv.FRAMES) if inv.HIDDEN in ex.tables["frames"][f])
    slot = ex.tables["frames"][target].index(inv.HIDDEN)
    sx, sy = slot % 3 * 8, slot // 3 * 16
    frames[target][sy][sx] = 3
    plan = W.plan_edits(ex, "small", frames)
    assert plan["dropped"] == [{"frame": target, "x": sx, "y": sy}] and not plan["edits"]


@needs_rom
def test_use_route_builds_a_recorded_mod_from_a_donor_entry(ex, tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image
    from types import SimpleNamespace
    from gbox import characters as C, filemods, tools
    monkeypatch.setattr(tools, "rom_path", lambda entry, cfg: SRC)
    root = tmp_path / "characters"
    d = root / "donor"
    d.mkdir(parents=True)
    sheet = np.zeros((40, 90, 4), np.uint8)
    for i, c in enumerate(((240, 30, 30), (30, 30, 240), (30, 200, 30))):
        sheet[4:36, 4 + i * 30:24 + i * 30] = (*c, 255)
    Image.fromarray(sheet, "RGBA").save(d / "s.png")
    meta = {"kind": "sprites", "name": "Donor Guy", "slug": "donor", "model": "s.png"}
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    game = {"game_id": W.GAME_ID, "title": "Super Mario Bros. 3", "platform": "nes", "source_paths": ["x.zip"],
            "format": "zip", "profile_id": "nes"}
    r = W.build_mod(cfg, game, meta, "player:small", root=root)
    assert r["mod"] == "smb3_donor_as_small" and r["suits"] == ["small"]
    out = filemods.mod_dir(cfg, W.GAME_ID, r["mod"])
    img = out / r["image"]
    import hashlib
    assert hashlib.sha256(img.read_bytes()).hexdigest() == r["report"]["mod_sha256"]
    assert r["report"]["source_sha256"] == SRC_SHA256 and r["report"]["changed_tiles"] > 0
    man = json.loads((out / "manifest.json").read_text())
    assert man["mod"]["prg_identical"] and man["donor"] == "Donor Guy"
    assert (out / ".gbox-mod.json").is_file() and (out / "preview.png").is_file()
    assert spr.SMB3Sprites(img).tables["frames"] == ex.tables["frames"]
