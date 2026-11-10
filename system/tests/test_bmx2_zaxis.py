"""Focused tests for the Z-Axis container reader (gbox/bmx2_zaxis.py)."""

import importlib.util
import pathlib
import struct
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_MODULE = _HERE.parent / "gbox" / "bmx2_zaxis.py"
_spec = importlib.util.spec_from_file_location("bmx2_zaxis", _MODULE)
z = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = z
_spec.loader.exec_module(z)


def _chunk(tag: str, payload: bytes) -> bytes:
    return tag.encode("latin-1") + struct.pack("<I", len(payload)) + payload


def _mobo_payload(data: bytes) -> bytes:
    for chunk in z.top_chunks(data):
        if chunk.tag == "TGPT":
            for sub in z.walk(chunk.payload, 0):
                if sub.tag == "MOBO":
                    return sub.payload
    raise AssertionError("no MOBO chunk")


def _sample_model() -> bytes:
    """A miniature model: 2 vertices, 1 triangle, 2 named bones."""
    tgph = struct.pack("<IIHHHHHH", 0, 0x062404CB, 38, 0, 16, 3, 2, 0)
    mobo = b""
    for name in (b"Hips", b"Chest"):
        record = bytearray(52)
        record[28:28 + len(name)] = name
        mobo += bytes(record)
    part = _chunk("TGPH", tgph) + _chunk("MOBO", mobo)
    part += _chunk("TGVP", struct.pack("<6f", 0.0, 0.0, 0.0, 1.0, 2.0, 3.0))
    part += _chunk("TGVN", struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0))
    part += _chunk("TGVU", struct.pack("<4f", 0.0, 0.0, 1.0, 1.0))
    part += _chunk("TGVI", struct.pack("<3H", 0, 1, 0))
    model = _chunk("TXRH", struct.pack("<IHH", 0x08ECE0F3, 256, 256) + b"\x00" * 8 + b"MIRRASTREETID3\x00")
    model += _chunk("TGPT", part)
    return model


def test_walk_reads_tag_size_payload():
    data = _chunk("TGEO", b"1234") + _chunk("TMTB", b"56")
    chunks = z.top_chunks(data)
    assert [c.tag for c in chunks] == ["TGEO", "TMTB"]
    assert chunks[0].payload == b"1234"
    assert chunks[1].size == 2


def test_walk_stops_at_garbage():
    data = b"not-a-tag-at-all" + struct.pack("<I", 4) + b"abcd"
    assert z.walk(data, 0) == []


def test_find_and_texture_header():
    header = z.find(_sample_model(), "TXRH")
    assert header is not None and header.tag == "TXRH"
    parsed = z.parse_txrh(header.payload)
    assert parsed["width"] == 256 and parsed["height"] == 256
    assert parsed["name"].startswith("MIRRASTREETID3")


def test_bone_table_and_mesh_counts():
    data = _sample_model()
    assert z.parse_mobo(_mobo_payload(data)) == ["Hips", "Chest"]
    summary = z.mesh_summary(data)
    assert summary["vertices"] == 2
    assert summary["index_words"] == 3
    assert summary["bone_count"] == 38
    assert summary["bone_names"] == ["Hips", "Chest"]


def test_tgph_and_indices():
    data = _sample_model()
    for chunk in z.top_chunks(data):
        if chunk.tag != "TGPT":
            continue
        for sub in z.walk(chunk.payload, 0):
            if sub.tag == "TGPH":
                head = z.parse_tgph(sub.payload)
                assert head["bone_count"] == 38
                assert head["named_bones"] == 16
            if sub.tag == "TGVI":
                assert z.parse_tgvi(sub.payload) == [0, 1, 0]


def test_deep_chunks_finds_nested_mesh():
    """A model whose TGPT hides inside a TGEO container is still found."""
    data = _sample_model()
    nested = _chunk("TGEO", data)
    summary = z.mesh_summary(nested)
    assert summary["vertices"] == 2
    assert summary["bone_names"] == ["Hips", "Chest"]


def test_archive_members_reads_zdir_index():
    data = _chunk("ZDIR", b"/ASSETS/MOTIE/MOVIE01.ES\x00/ASSETS/MOTIE/MOVIE02.ES\x00")
    assert z.archive_members(data) == ["/ASSETS/MOTIE/MOVIE01.ES", "/ASSETS/MOTIE/MOVIE02.ES"]


def test_list_members_reports_tags():
    members = z.list_members(_sample_model())
    assert [m[0] for m in members] == ["TXRH", "TGPT"]


def test_real_rider_file_if_present():
    """Real DMIRRA/PLAYER.ZIT from the owned disc (set BMX2_PLAYER_ZIT); skipped otherwise."""
    import hashlib
    import os
    path = os.environ.get("BMX2_PLAYER_ZIT")
    if not path or not os.path.exists(path):
        return
    data = pathlib.Path(path).read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        "97b8d0e33ee67257af59110b22e7b9e9b34ddb118f4a171338206f8055721a79")
    assert [c.tag for c in z.top_chunks(data)] == ["FMDL"]
    summary = z.mesh_summary(data)
    assert summary["vertices"] == 1227
    assert summary["bone_count"] == 38
    assert len(summary["bone_names"]) == 16 and summary["bone_names"][0] == "Hips"
    assert summary["parts"][0]["tgvi_is_plain_triangle_list"] is False


def test_wrapped_fmdl_modl():
    data = _chunk("FMDL", _chunk("MODL", _sample_model()))
    assert z.mesh_summary(data)["vertices"] == 2
