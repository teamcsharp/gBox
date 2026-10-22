"""Focused tests for gbox.re6_inventory: XEX identity, arc classification, roster crosscheck."""

import json
import struct
import tempfile
from pathlib import Path

from gbox.re6_inventory import TITLE_ID, classify_arcs, crosscheck, sample_arc_headers, xex_info


def _fake_xex(title_off=0x3134, build=b"BH6MasterRelease_...", endian="little"):
    d = bytearray(0x4000)
    d[0:4] = b"XEX2"
    struct.pack_into("<I", d, 4, 0x1000000)          # module flags
    struct.pack_into("<I", d, 8, 0x500000)           # header size (XGD3-style)
    struct.pack_into("<I", d, 16, 0x110)             # security offset
    struct.pack_into(">I" if endian == "big" else "<I", d, title_off, TITLE_ID)
    d[0x180:0x180 + len(build)] = build
    return bytes(d)


def test_xex_info_fields():
    info = xex_info(_fake_xex())
    assert info["magic"] == "XEX2"
    assert info["module_flags"] == "0x1000000"
    assert info["title_id"] == hex(TITLE_ID)
    assert info["title_id_offset"] == 0x3134
    assert info["build_string"] == "BH6MasterRelease_..."


def test_xex_info_big_endian_title_id():
    # the owned disc stores the title id big-endian; the parser must find it either way
    info = xex_info(_fake_xex(endian="big"))
    assert info["title_id_offset"] == 0x3134
    assert info["title_id_endian"] == "big"


def test_xex_info_rejects_non_xex():
    try:
        xex_info(b"\x00" * 64)
    except ValueError as e:
        assert "XEX2" in str(e)
    else:
        raise AssertionError("non-XEX accepted")


def test_classify_arcs_families():
    files = {
        "/nativeXenon/arc/X360/uPl00LeonUsa.arc": (0, 1),
        "/nativeXenon/arc/X360/uPl00HeadLeonUsa.arc": (1, 1),
        "/nativeXenon/arc/X360/uPl00AcHeadLeonAsia.arc": (2, 1),
        "/nativeXenon/arc/X360/uPl06AdaA.arc": (3, 1),
        "/nativeXenon/arc/X360/uPlTex0010_0.arc": (4, 1),
        "/nativeXenon/arc/X360/uEm1000.arc": (5, 1),
        "/nativeXenon/arc/X360/uWp0000.arc": (6, 1),
        "/nativeXenon/arc/X360/uSm1001.arc": (7, 1),
        "/nativeXenon/arc/X360/uPl07HeadHelper.arc": (8, 1),
        "/nativeXenon/arc/X360/Collection_eng.arc": (9, 1),
        "/nativeXenon/system/foo.bin": (10, 1),
    }
    cls = classify_arcs(files)
    assert cls["families"]["uPl_hero"] == 4
    assert cls["families"]["uEm"] == 1
    assert cls["families"]["uWp"] == 1
    assert cls["families"]["uS"] == 1
    assert cls["families"]["uPlTex"] == 1
    assert cls["families"]["uPl_helper"] == 1
    assert cls["hero_parts"]["00"]["Head"] == ["uPl00HeadLeonUsa.arc"]
    assert cls["hero_parts"]["00"]["Body"] == ["uPl00LeonUsa.arc"]
    assert cls["hero_parts"]["06"]["Body"] == ["uPl06AdaA.arc"]
    assert cls["hero_costumes"]["00"] == ["Asia", "Usa"]


def test_crosscheck_flags_missing_costume():
    costs = {"00": ["Usa", "Asia", "Omake00", "Omake01"], "02": ["Europe", "Asia", "Bad", "Omake00", "Omake01", "Omake02"]}
    out = crosscheck(costs)
    assert out["leon"]["missing"] == ["Omake02"]
    assert out["leon"]["extra"] == []
    assert out["chris"]["missing"] == []
    assert out["ada"]["missing"] == ["A", "B", "Carla", "Omake00", "Omake01", "Omake02"]  # absent from disc dict


def test_sample_arc_headers_reads_header_only():
    with tempfile.TemporaryDirectory() as td:
        iso = Path(td) / "iso.bin"
        # one fake arc file whose first 8 bytes are a \0CRA header, at offset 0x1000
        head = struct.pack(">4sHH", b"\0CRA", 0x11, 5)
        iso.write_bytes(b"\x00" * 0x1000 + head + b"\x00" * 0x2000)

        class FakeXDVD:
            files = {"/nativeXenon/arc/X360/fake.arc": (0x1000, 0x2000)}

            def __init__(self):
                self.f = open(iso, "rb")

        fx = FakeXDVD()
        try:
            out = sample_arc_headers(fx, ["/nativeXenon/arc/X360/fake.arc"])
        finally:
            fx.f.close()                                    # Windows can't remove the temp dir with the file open
        assert out[0]["magic"] == "\x00CRA"
        assert out[0]["version"] == 0x11
        assert out[0]["entries"] == 5
        assert out[0]["size"] == 0x2000


def test_manifest_json_schema():
    man = {"game": "Resident Evil 6", "platform": "xbox360", "title_id": hex(TITLE_ID),
           "source": {"path": "x", "size": 1, "sha256": None},
           "executable": {}, "disc": {}, "arcs": {}, "launch": {}}
    blob = json.dumps(man)
    back = json.loads(blob)
    for key in ("game", "platform", "title_id", "source", "executable", "disc", "arcs", "launch"):
        assert key in back
