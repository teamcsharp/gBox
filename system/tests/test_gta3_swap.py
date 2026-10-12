"""GTA III PS2 player swap writer (gbox/gta3_swap.py): synthetic checks always run; the real-disc round trip runs when
the owned image is unpacked on this machine."""
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import gta_rw as R
from gbox import gta3_swap as S

ISO = Path.home() / "gbox-cache/ps2/265819390074bb4e/Grand Theft Auto III (USA, Canada).iso"
AMY = Path.home() / "gbox-cache/characters/sa2_amy_rose"


def _raster(w=64, h=64):
    """A headerless 8-bit raster (no GIF packets): pixels then a 256-entry palette."""
    hdr = struct.pack("<16I", w, h, 8, 0x2504, 0, 0, 0, 0, 0, 0, 0, 0, w * h, 1024, 0, 0)
    return R.Ps2Raster("t", "", w, h, 8, 0x2504, hdr, bytes(w * h + 1024))


def test_roles_cover_every_ped_frame_and_retarget_key():
    frames = {"swaist", "smid", "storso", "shead", "supperarml", "slowerarml", "slhand", "supperarmr", "slowerarmr",
              "srhand", "supperlegl", "slowerlegl", "sfootl", "supperlegr", "slowerlegr", "sfootr"}
    assert set(S.GTA3_ROLES.values()) == frames
    assert {"pelvis", "hip", "chest", "neck", "head", "l_hand", "r_foot"} <= set(S.GTA3_ROLES)


def test_raster_write_reads_back_the_new_image():
    img = np.zeros((64, 64, 4), np.uint8)
    img[..., 3] = 255
    img[:32, :, 0] = 250
    img[32:, :, 2] = 240
    out = S.raster_write(_raster(), img)
    back = R.raster_rgba(out)
    assert np.abs(back[..., :3].astype(int) - img[..., :3]).mean() < 4


def test_weld_merges_shared_corners():
    p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    n = np.tile([0, 0, 1.0], (6, 1))
    uv = np.array([[0, 0], [1, 0], [0, 1], [1, 0], [1, 1], [0, 1]], float)
    P, N, U, T = S._weld(p, n, uv, np.arange(6).reshape(2, 3))
    assert len(P) == 4 and T.shape == (2, 3)
    assert np.allclose(P[T].reshape(-1, 3), p)


@pytest.mark.skipif(not ISO.exists() or not (AMY / "meta.json").exists(), reason="owned GTA III image / Amy not here")
def test_real_disc_player_swap_fits_and_round_trips(tmp_path):
    import json
    meta = json.loads((AMY / "meta.json").read_text())
    d = R.GtaDisc(ISO)
    try:
        orig = d.entry("player.dff")
        rig = S.Rig(orig)
        assert len(rig.frames) == 17 and len(rig.atomics) == 16
        r = S.swap_files(d, AMY / meta["model"], meta["rig"]["roles"], tmp_path)
        assert len(r["dff"]) <= d.slot_sectors("player.dff") * R.SECTOR
        assert len(r["txd"]) <= d.slot_sectors("player.txd") * R.SECTOR
        for k in ("dff", "txd"):                               # the written files parse and re-serialise identically
            root, tail = R.parse(r[k])
            assert root.to_bytes() + tail == r[k]
        parts = S.dff_parts(r["dff"])
        assert len(parts) == 16 and sum(p["triangles"] for p in parts.values()) >= 1000
        assert parts["Shead"]["triangles"] > 100                  # the head really moved onto Shead
        new_rig = S.Rig(r["dff"])                                 # frames / atomics untouched -> animations still bind
        assert [f["name"] for f in new_rig.frames] == [f["name"] for f in rig.frames]
        assert new_rig.atomics == rig.atomics
        assert np.allclose([f["world"] for f in new_rig.frames], [f["world"] for f in rig.frames])
        back = R.raster_rgba(S.txd_rasters(r["txd"])[0])
        assert np.abs(back[..., :3].astype(int) - r["atlas"][..., :3]).mean() < 4
        assert S.Rig(d.entry("player.dff")).raw == orig            # the source image is never written
    finally:
        d.close()


def test_swap_covers_the_prison_skin():
    # #1311 live: a fresh game's Callahan Bridge / Kuruma drive runs on the PLAYERP skin, so it must be written too
    assert S.SKINS[0] == "player" and "playerp" in S.SKINS


@pytest.mark.skipif(not ISO.exists() or not (AMY / "meta.json").exists() or not Path("/usr/bin/blender").exists(),
                    reason="owned GTA III image / Amy / native Blender not here")
def test_real_disc_prison_skin_swap_fits(tmp_path):
    import json
    meta = json.loads((AMY / "meta.json").read_text())
    d = R.GtaDisc(ISO)
    try:
        orig = d.entry("playerp.dff")
        rig = S.Rig(orig)
        r = S.swap_files(d, AMY / meta["model"], meta["rig"]["roles"], tmp_path, "/usr/bin/blender", skin="playerp")
        assert r["skin"] == "playerp" and set(r["orig_sha256"]) == {"playerp.dff", "playerp.txd"}
        assert len(r["dff"]) <= d.slot_sectors("playerp.dff") * R.SECTOR
        assert len(r["txd"]) <= d.slot_sectors("playerp.txd") * R.SECTOR
        for k in ("dff", "txd"):
            root, tail = R.parse(r[k])
            assert root.to_bytes() + tail == r[k]
        new_rig = S.Rig(r["dff"])
        assert [f["name"] for f in new_rig.frames] == [f["name"] for f in rig.frames]
        assert new_rig.atomics == rig.atomics
        assert sum(p["triangles"] for p in S.dff_parts(r["dff"]).values()) >= 600      # 33-sector slot: ~670 tris after decimation
        assert S.Rig(d.entry("playerp.dff")).raw == orig
    finally:
        d.close()
