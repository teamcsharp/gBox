"""GTA Vice City PS2 player swap writer (gbox/gta_vc_swap.py): synthetic checks always run; the real-disc round trip
runs when the owned image is unpacked on this machine."""
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import gta_rw as R
from gbox import gta3_swap as S3
from gbox import gta_vc_swap as S

ISO = Path.home() / "gbox-cache/ps2/0000000000000000/Grand Theft Auto - Vice City (USA).iso"
AMY = Path.home() / "gbox-cache/characters/sa2_amy_rose"


def _raster(w=64, h=64):
    """A headerless 8-bit raster (no GIF packets): pixels then a 256-entry palette."""
    hdr = struct.pack("<16I", w, h, 8, 0x2504, 0, 0, 0, 0, 0, 0, 0, 0, w * h, 1024, 0, 0)
    return R.Ps2Raster("t", "", w, h, 8, 0x2504, hdr, bytes(w * h + 1024))


def test_vc_roles_cover_required_body_roles():
    required = {"pelvis", "hip", "chest", "neck", "head",
                "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
    assert required <= set(S.VC_ROLES)


def test_vc_swap_imports_reuse_gta3_helpers():
    # The Vice City writer is a thin adapter over the proven GTA III writer.
    assert S.SECTOR == S3.SECTOR
    assert "S3" in S.build_mod.__code__.co_names
    assert S3 in S.build_mod.__globals__.values()


def test_raster_write_reads_back_the_new_image():
    img = np.zeros((64, 64, 4), np.uint8)
    img[..., 3] = 255
    img[:32, :, 0] = 250
    img[32:, :, 2] = 240
    out = S3.raster_write(_raster(), img)
    back = R.raster_rgba(out)
    assert np.abs(back[..., :3].astype(int) - img[..., :3]).mean() < 4


@pytest.mark.skipif(not ISO.exists() or not (AMY / "meta.json").exists(), reason="owned Vice City image / Amy not here")
def test_real_disc_player_swap_fits_and_round_trips(tmp_path):
    import json
    meta = json.loads((AMY / "meta.json").read_text())
    d = R.GtaDisc(ISO)
    try:
        orig = d.entry("player.dff")
        rig = S3.Rig(orig, roles=S.VC_ROLES)
        assert len(rig.frames) >= 1 and len(rig.atomics) >= 1
        r = S3.swap_files(d, AMY / meta["model"], meta["rig"]["roles"], tmp_path, roles=S.VC_ROLES)
        assert len(r["dff"]) <= d.slot_sectors("player.dff") * R.SECTOR
        assert len(r["txd"]) <= d.slot_sectors("player.txd") * R.SECTOR
        for k in ("dff", "txd"):
            root, tail = R.parse(r[k])
            assert root.to_bytes() + tail == r[k]
        parts = S3.dff_parts(r["dff"])
        assert sum(p["triangles"] for p in parts.values()) >= 100
        new_rig = S3.Rig(r["dff"], roles=S.VC_ROLES)
        assert [f["name"] for f in new_rig.frames] == [f["name"] for f in rig.frames]
        assert new_rig.atomics == rig.atomics
        back = R.raster_rgba(S3.txd_rasters(r["txd"])[0])
        assert np.abs(back[..., :3].astype(int) - r["atlas"][..., :3]).mean() < 4
        assert S3.Rig(d.entry("player.dff"), roles=S.VC_ROLES).raw == orig
    finally:
        d.close()
