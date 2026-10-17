"""Burnout Revenge (Xbox 360) inventory module tests.

Pure functions only (xex_info / classify_vehicles / detect_formats) so the suite runs
without the owned 3.8 GB disc image.
"""

import struct
import zlib
from io import BytesIO

from gbox.burnout_revenge_inventory import (
    TITLE_ID, classify_vehicles, detect_formats, xex_info,
)


def _xex(build=b"Burnout4_External.pe", title_id=TITLE_ID):
    data = bytearray(0x3000)
    data[:4] = b"XEX2"
    struct.pack_into(">II", data, 4, 1, len(data))
    struct.pack_into(">II", data, 16, 0x98, 1)
    struct.pack_into(">II", data, 24, 0x00040006, 0x17c0)
    struct.pack_into(">I", data, 0x17cc, title_id)
    data[0x16C4:0x16C4 + len(build)] = build
    return bytes(data)


def test_xex_info_parses_title_and_build():
    info = xex_info(_xex())
    assert info["magic"] == "XEX2"
    assert info["title_id"] == f"{TITLE_ID:#x}"
    assert info["title_id_offset"] == 0x17CC
    assert info["build_string"] == "Burnout4_External.pe"


def test_xex_info_rejects_non_xex():
    try:
        xex_info(b"not an xex")
    except ValueError as e:
        assert "not an XEX2" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_classify_vehicles_groups_roster():
    files = {
        "pveh/high/us/Car1A.bgv": (1, 10),
        "pveh/high/us/Car1A.hwb": (1, 10),
        "pveh/high/us/Car1Aa.gin": (1, 10),
        "pveh/high/us/Car1Ad.gin": (1, 10),
        "pveh/low/eu/Car2S1.bgv": (1, 10),
        "pveh/low/eu/Car2S1d.gin": (1, 10),
        "pveh/traf/us/Car01.btv": (1, 10),
        "pveh/traf/eu/Car01.btv": (1, 10),
        "tracks/us/l1_v1/Gamedata.bgd": (1, 10),
        "data/Global.txd": (1, 10),          # not a vehicle
    }
    roster = classify_vehicles(files)
    assert set(roster["cars"]) == {"Car1A", "Car2S1"}
    assert roster["cars"]["Car1A"]["bgv"] == ["high/us"]
    assert roster["cars"]["Car1A"]["gin"] == ["high/usa", "high/usd"]
    assert roster["cars"]["Car2S1"]["bgv"] == ["low/eu"]
    assert roster["traffic"] == {"Car01": ["eu", "us"]}
    assert roster["tracks"] == ["l1_v1"]


class _FakeXDVD:
    def __init__(self, files):
        self.files = files
        self.f = BytesIO()

    def seek(self, off):
        self.f.seek(off)

    def read(self, n):
        return self.f.read(n)


def test_detect_formats_reads_magics():
    # lay each sample at its own offset inside one backing buffer, like real XDVD files
    blobs = [
        ("/pveh/high/us/Car1A.bgv", zlib.compress(b"\x00\x00\x00\x25" + b"\x00" * 64)),
        ("/pveh/high/us/Car1A.hwb", b"DNBW" + b"\x00" * 60),
        ("/pveh/high/us/Car1Aa.gin", b"Gnsu20" + b"\x00" * 58),
        ("/data/Global.txd", b"\xbc\xde\xed\x81" + b"\x00" * 60),
    ]
    buf = bytearray()
    files = {}
    for path, blob in blobs:
        files[path] = (len(buf), len(blob))
        buf += blob
    d = _FakeXDVD(files)
    d.f = BytesIO(bytes(buf))
    out = detect_formats(d, [
        "/pveh/high/us/Car1A.bgv", "/pveh/high/us/Car1A.hwb",
        "/pveh/high/us/Car1Aa.gin", "/data/Global.txd", "/missing.bin",
    ])
    assert "zlib" in out[0]["kind"]
    assert out[1]["kind"] == "DNBW rig buffer"
    assert "Gnsu" in out[2]["kind"]
    assert "TXD" in out[3]["kind"]
    assert out[4]["error"] == "not on disc"


def test_title_id_bytes_outside_execution_info_do_not_identify_the_game():
    import pytest
    data = bytearray(_xex(title_id=0x12345678))
    struct.pack_into(">I", data, 0x2000, TITLE_ID)
    with pytest.raises(ValueError, match="execution info"):
        xex_info(bytes(data))


def test_corrupt_zlib_is_reported_as_invalid():
    disc = _FakeXDVD({"bad.bgv": (0, 8)})
    disc.f = BytesIO(b"\x78\xdabroken")
    assert detect_formats(disc, ["bad.bgv"])[0]["kind"] == "invalid zlib stream"
