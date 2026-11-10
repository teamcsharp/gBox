"""Focused tests for gbox.halo_cea_inventory: XEX identity parsing, asset classification,
and (when GBOX_HALO_CEA_ISO points at the owned disc) the full manifest."""
import os
import struct

import pytest

from gbox import halo_cea_inventory as h


def test_xex_info_parses_header():
    data = bytearray(0x4000)
    data[:4] = b"XEX2"
    struct.pack_into("<I", data, 4, 0x1000000)          # module_flags
    struct.pack_into("<I", data, 8, 0x400000)           # header_size
    struct.pack_into("<I", data, 16, 0x1000)            # security_offset
    # embed the big-endian title id in the header area
    struct.pack_into(">I", data, 0x40, h.TITLE_ID)
    info = h.xex_info(bytes(data))
    assert info["magic"] == "XEX2"
    assert info["title_id"] == hex(h.TITLE_ID)
    assert info["title_id_endian"] == "big"


def test_xex_info_rejects_non_xex():
    with pytest.raises(ValueError):
        h.xex_info(b"NOTXEX2....")


def test_classify_routes_engines():
    files = {
        "/maps_original/a10.map": (0, 1),
        "/maps_original/d40.map": (0, 1),
        "/maps_original/ui.map": (0, 1),
        "/maps/cex_beaver_creek.map": (0, 1),
        "/maps/shared.map": (0, 1),
        "/maps/mainmenu.map": (0, 1),
        "/paks360/pak_stream.s3dpak": (0, 1),
        "/paks360/a10.s3dpak": (0, 1),
        "/shaders/foo.fx": (0, 1),
        "/sounds/x.fsb": (0, 1),
        "/maps/images/x.blf": (0, 1),
        "/default.xex": (0, 1),
        "/ReachTU1.xex": (0, 1),
    }
    c = h.classify(files)
    assert set(c["classic_map"]) == {"a10.map", "d40.map", "ui.map"}
    assert set(c["anniv_map"]) == {"cex_beaver_creek.map", "shared.map", "mainmenu.map"}
    assert set(c["s3dpak"]) == {"pak_stream.s3dpak", "a10.s3dpak"}
    assert c["shader"] == ["foo.fx"]
    assert c["fmod_fsb"] == ["x.fsb"]
    assert c["blf"] == ["x.blf"]
    assert set(c["xex"]) == {"default.xex", "ReachTU1.xex"}


@pytest.mark.skipif(not os.environ.get("GBOX_HALO_CEA_ISO"), reason="owned disc path not set")
def test_real_disc_manifest():
    iso = os.environ["GBOX_HALO_CEA_ISO"]
    man = h.inventory(iso)
    assert man["executable"]["magic"] == "XEX2"
    assert man["executable"]["sha256"]
    assert man["disc"]["files"] > 0
    assert man["counts"]["classic_map"] >= 1
    assert man["counts"]["s3dpak"] >= 1
    assert man["counts"]["anniv_map"] >= 1
