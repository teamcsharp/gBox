"""Writer: native CMCK slot reimport into the owned Illbleed (USA) C04.NJ, plus the
isolated GD-ROM mod.

no-op roundtrip byte-identical; a changed donor replaces only the target slot
(big VQ, the slot's own pix fmt, allocated extent preserved) while NJCM and the
other four slots stay byte-identical; the isolated mod GDI is deterministic
across two builds.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest
import gbox.illbleed_chars as ic
from gbox.illbleed_chars import GAME_ID

from gbox import illbleed_chars as ic

GDI = os.environ.get("GBOX_ILLBLEED_GDI") or str(
    Path.home() / "gbox-cache/dc/81a90290abc15a37/disc.gdi")
if not Path(GDI).is_file():
    GDI = "/home/ehm_eckx/gBox_alt/gbox-cache/dc/81a90290abc15a37/disc.gdi"

pytestmark = pytest.mark.skipif(not Path(GDI).is_file(), reason="owned disc cache required")


def _donor_gradient(w: int, h: int) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.uint8)
    r = np.clip((x.astype(np.int32) * 255) // max(w - 1, 1), 0, 255).astype(np.uint8)
    g = np.clip((y.astype(np.int32) * 255) // max(h - 1, 1), 0, 255).astype(np.uint8)
    a = np.full((h, w), 255, np.uint8)
    return np.stack([r, g, np.full((h, w), 160, np.uint8), a], -1)


def test_writer_noop_roundtrip():
    data, slots = ic.load_character(GDI, "C04")
    assert len(slots) == 5
    for i in range(5):
        assert ic.replace_slot(data, i, slots[i]) == data, f"slot {i} no-op roundtrip failed"


def test_writer_changed_donor():
    data, slots = ic.load_character(GDI, "C04")
    w, h, rgba, _desc = ic.pvr_slot_decode(slots[0])
    donor = _donor_gradient(w, h)
    swapped = ic.swap_vq_body(data, 0, donor)
    assert len(swapped) == len(data)
    w2, h2, rgba2, _ = ic.pvr_slot_decode(ic.cmck_slots(swapped)[0])
    assert (w2, h2) == (w, h)
    a = np.frombuffer(rgba2, np.uint8).reshape(h2, w2, 4).astype(np.int32)
    b = donor.reshape(h, w, 4).astype(np.int32)
    mse = float(np.mean((a - b) ** 2))
    psnr = 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)
    assert psnr > 30.0, f"slot0 readback PSNR {psnr:.2f} dB (donor mismatch)"
    for i in range(1, 5):
        assert ic.cmck_slots(swapped)[i] == slots[i], f"slot {i} touched by the swap"


def test_writer_isolated_mod_deterministic(tmp_path):
    data, slots = ic.load_character(GDI, "C04")
    w, h, _rgba, _desc = ic.pvr_slot_decode(slots[0])
    donor = _donor_gradient(w, h)
    m1 = ic.build_mod(GDI, "C04", 0, donor, tmp_path / "a")
    m2 = ic.build_mod(GDI, "C04", 0, donor, tmp_path / "b")
    assert m1.read_bytes() == m2.read_bytes()


def test_routed_use_builds_recorded_mod(tmp_path, monkeypatch):
    # characters.py op=use routes 81a90290abc15a37 to illbleed_chars.use; with the
    # recorded gradient donor the routed path must reproduce the published mod
    # byte-for-byte (sha256 1b8e939b...).
    import gbox.characters as C
    donor = _donor_gradient(512, 512)  # C04 slot0 is 512x512 on the owned disc
    ctx = type("Ctx", (), {})()
    cfg = type("Cfg", (), {}); cfg.cache = str(tmp_path)
    ctx.config = cfg
    posts = []
    monkeypatch.setattr(C, "_api", lambda *a, **kw: posts.append((a[1], a[2], kw.get("json"))) or {})
    monkeypatch.setattr(C, "_dc_gdi", lambda c, g: Path(GDI))
    monkeypatch.setattr(C, "library_root", lambda cfg=None: tmp_path)
    monkeypatch.setattr(ic, "_donor_from_meta", lambda ctx, meta: donor)
    meta = {"slug": "jorg", "name": "Jorg", "source": {"game_id": "0000000000000000"}}
    game = {"game_id": GAME_ID, "title": "Illbleed (USA)"}
    inp = type("Inp", (), {"slot": "player", "launch": False, "rebuild": True})()
    res = ic.use(ctx, meta, game, inp)
    assert res["status"] == "built"
    assert res["replaces"].startswith("C04")
    from gbox import filemods
    # patch_gdi writes out_dir/<name>.gdi and build_mod passes a name that
    # already ends in .gdi -> the on-disk descriptor is *.gdi.gdi (the
    # recorded mod sha256 1b8e939b... was captured on exactly that file)
    mod = filemods.mod_dir(cfg, GAME_ID, "illbleed_jorg") / "illbleed_c04_slot0_mod.gdi.gdi"
    assert hashlib.sha256(mod.read_bytes()).hexdigest() == "1b8e939b2324ab49dc30a1e2a1503ab37ef478b61a5b7488e26861cb6d79bc39"
    assert posts and posts[0][1] == "/api/characters/jorg/targets"
    assert posts[0][2]["mod"] == "illbleed_jorg" and posts[0][2]["slot"] == "C04"
