"""Def Jam: Vendetta PS2 SLUS_206.39 reader (#1305): synthetic WRS/VIF round trips + owned-ISO pins."""
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import defjam_vendetta_ps2 as D

ISO = Path.home() / "gbox-cache" / "deabd11481aa5a0c" / "source.iso"
ELF_SHA256 = "d071213bce13a1fe8ef2f7b241f6cb1da20e66b78b7776f23299ce81b51cb28d"


def _qf(*v):
    return struct.pack("<4f", *v)


def _model(base=0x200, nodes=1, geo_delta=0):
    """3 single-bone vertices + 1 two-bone vertex, one 4-vertex strip: 2 CCW triangles facing +z."""
    q = [struct.pack("<4I", 3, 1, 1, 0x8000)]
    for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0)):
        q += [_qf(0.5, 0.5, 1.0, 0.0), _qf(0, 0, 1, 1.0), _qf(*p, 1.0)]
    q += [_qf(0.5, 0.5, 1.0, 1.0), _qf(0, 0, 1, 1.0), _qf(1, 1, 0, 1.0), struct.pack("<IfIf", 64, 0.25, 72, 0.75)]
    words = [4, base + 1, base + 4, base + 7, base + 10]
    words += [0] * (-len(words) % 4)
    data = b"".join(q) + struct.pack(f"<{len(words)}I", *words)
    n = len(data) // 16
    vif = struct.pack("<I", 0x6C008000 | (n << 16)) + data + struct.pack("<II", 0x11000000, 0x15000000)
    geo = (0x20 + nodes * D.NODE_SIZE + 0x7F) & ~0x7F
    head = struct.pack("<3I", geo + geo_delta, len(vif), nodes).ljust(0x20, b"\0")
    rec = struct.pack("<16f", *np.eye(4).ravel()) * 2
    recs = (rec + b"\0" * (D.NODE_SIZE - len(rec))) * nodes
    return (head + recs).ljust(geo, b"\0") + vif


def _wrs(slots):
    out = bytearray(b"WRS " + b"\0" * 12 + b"\xff" * 4 * D.WRS_SLOTS)
    struct.pack_into("<f", out, 8, 1.0)
    for i in sorted(slots):
        while len(out) % 16:
            out.append(0)
        struct.pack_into("<I", out, 0x10 + 4 * i, len(out) - (0x10 + 4 * i))   # self-relative slot offset
        out += slots[i]
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def test_batch_vertices_weights_and_strip_winding():
    m = D.parse_model(_model())
    assert len(m["positions"]) == 4 and m["weighted"] == 1 and m["batches"] == 1
    assert m["tri_index"].tolist() == [[0, 1, 2], [2, 1, 3]]
    assert m["matrices"][3] == (64, 72) and m["weights"][3] == (0.25, 0.75)
    assert D.winding(m) == 1.0
    assert m["triangles"][0] == ((0, 0, 0), (1, 1, 1), (2, 2, 2))


@pytest.mark.parametrize("base", [0, 0x100, 0x300])
def test_strip_addresses_use_any_double_buffer_base(base):
    assert D.parse_model(_model(base=base))["tri_index"].tolist() == [[0, 1, 2], [2, 1, 3]]


def test_unmapped_strip_address_and_bad_geometry_offset_raise():
    with pytest.raises(D.FormatError):
        D.parse_model(_model(base=0x180))
    with pytest.raises(D.FormatError):
        D.parse_model(_model(geo_delta=0x80))


def test_wrs_slots_are_self_relative_and_named():
    b = _wrs({1: _model(), 3: _model()})
    w = D.parse_wrs(b)
    assert w["size"] == len(b) and w["scale"] == 1.0
    assert w["slots"][1]["start"] == 0x90 and w["slots"][1]["end"] == w["slots"][3]["start"]
    assert (w["slots"][1]["name"], w["slots"][3]["name"]) == ("body", "face")
    with pytest.raises(D.FormatError):
        D.parse_wrs(b"XXXX" + b[4:])


def test_extract_wrs_writes_body_and_body2_glbs(tmp_path):
    r = D.extract_wrs(_wrs({1: _model(), 2: _model(), 3: _model()}), tmp_path / "x.glb", "x")
    assert r["verified"] and Path(r["glb"]).read_bytes()[:4] == b"glTF"
    assert Path(r["glb_body2"]).name == "x_body2.glb" and Path(r["glb_body2"]).read_bytes()[:4] == b"glTF"
    face = next(p for p in r["parts"] if p["role"] == "face")
    assert face["verified"] and face["placed"] is False and "x_face" not in r["exported"]


def test_file_table_found_by_content_including_short_tail():
    counts = [3, 5, 2, 7] * 5
    pairs, pos = [], 0
    for c in counts:
        pairs += [pos, c]
        pos += c
    elf = b"\x7fELF" + b"\0" * 0x3C + struct.pack(f"<{len(pairs)}I", *pairs) + struct.pack("<2I", 0x10, 0)
    assert D.file_table(elf, pos * 2048) == list(zip(pairs[::2], pairs[1::2]))
    assert len(D.file_table(elf, (pos + 1) * 2048)) == len(counts)          # data.bin may end one sector later
    with pytest.raises(D.FormatError):
        D.file_table(elf, (pos + 64) * 2048)


def test_registered_for_ps2_only():
    from gbox import characters as C
    entry = next(d for d in C.DEDICATED if d[0] == "defjam_vendetta_ps2")
    assert entry[1]("def jam - vendetta", "ps2") and not entry[1]("def jam - vendetta", "gamecube")
    ros = entry[2]()
    assert len(ros) == 58 and ros[0]["key"] == "wrs198" and ros[-1]["data_index"] == 255


@pytest.mark.skipif(not ISO.exists(), reason="owned SLUS_206.39 ISO not staged")
def test_owned_iso_identity_and_fighter_198(tmp_path):
    disc = D.Iso(ISO)
    ident = D.identify(disc)
    assert ident["exact_build"] and ident["files"] == 293 and ident["elf_sha256"] == ELF_SHA256
    kinds = [e["kind"] for e in D.entries(disc)]
    assert kinds.count("fighter") == 58 and kinds[198:256] == ["fighter"] * 58
    r = D.extract_index(disc, 198, tmp_path / "djv_ps2_wrs198.glb")
    body = {p["role"]: p for p in r["parts"]}
    assert r["verified"] and (body["body"]["vertices"], body["body"]["triangles"]) == (1145, 1194)
    assert (body["body2"]["vertices"], body["body2"]["triangles"]) == (1563, 1627)
    assert body["body"]["winding"] >= 0.99 and 21.5 < r["height"] < 22.5
