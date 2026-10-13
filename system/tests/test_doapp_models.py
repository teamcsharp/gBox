"""gbox.doapp_models: Dead Or Alive ++ model container / mesh / TIM parsers. Synthetic data, plus a skip-if-absent
check on the owned ROMs (GBOX_DOAPP_ROMS = directory with doapp.zip + coh1002m.zip; decodes the program, ~40 s)."""

import os
import struct

import pytest

from gbox import doapp_inventory as D
from gbox import doapp_models as M

OWNED = os.environ.get("GBOX_DOAPP_ROMS", "")
needs_roms = pytest.mark.skipif(not (OWNED and os.path.isfile(os.path.join(OWNED, "doapp.zip"))),
                                reason="set GBOX_DOAPP_ROMS to the directory with doapp.zip + coh1002m.zip")


def _tim(clut_xy=(0, 480), img=(640, 0, 4, 8), bpp_flag=0):
    clut = struct.pack("<IHHHH", 12 + 32, *clut_xy, 16, 1) + b"\0" * 32
    x, y, w, h = img
    pix = b"\x11" * (w * h * 2)
    image = struct.pack("<IHHHH", 12 + len(pix), x, y, w, h) + pix
    return struct.pack("<II", 0x10, 8 | bpp_flag) + clut + image


def _model(sections, tims=(_tim(),)):
    body = b""
    for s in range(M.SECTION_COUNT):
        rec = sections.get(s)
        if rec is None:
            body += struct.pack("<I", 0)
            continue
        dest, payload = rec
        body += struct.pack("<II", dest, len(payload)) + payload
        body += b"\0" * (-len(body) % 4)
    head = 4 + len(body)
    return struct.pack("<I", head) + body + b"".join(tims)


def test_container_walk_and_tims():
    m = _model({1: (0x3C, b"\1\0" * 13), 2: (0x56, b"\0\0" * 13)}, tims=(_tim(), _tim(img=(700, 0, 2, 2))))
    secs = M.raw_sections(m)
    assert [s["index"] for s in secs] == list(range(14))
    assert secs[1]["dest"] == 0x3C and secs[1]["length"] == 26 and not secs[1]["packed"]
    t = M.tims(m)
    assert len(t) == 2 and t[0]["bpp"] == 4 and t[0]["clut"]["y"] == 480 and t[1]["image"]["x"] == 700
    assert t[0]["offset"] == M.tim_offset(m) and t[1]["offset"] == t[0]["offset"] + t[0]["size"]


def test_container_rejects_out_of_bounds():
    with pytest.raises(M.FormatError):
        M.tim_offset(struct.pack("<I", 0x1000) + b"\0" * 16)
    bad = struct.pack("<I", 0x20) + struct.pack("<II", 0x3C, 0x100) + b"\0" * 0x14 + _tim()
    with pytest.raises(M.FormatError):
        M.raw_sections(bad)
    truncated = _model({}, tims=(_tim()[:-8],))
    with pytest.raises(M.FormatError):
        M.tims(truncated)


def test_raw_walk_stops_at_the_first_packed_section():
    m = _model({1: (0x3C, b"\0" * 4), 3: (0x40, b"\0" * 8)})
    secs = M.raw_sections(m)
    assert secs[-1]["index"] == 3 and secs[-1]["packed"]


def _mesh(groups, vertices):
    hdr = 16 + sum(4 + 4 * len(g) for g in groups)
    chunk_at = hdr
    out_groups, chunks = [], b""
    for g in groups:
        offs = []
        for count, kind in g:
            offs.append(chunk_at + len(chunks))
            chunks += struct.pack("<HH", count, kind) + b"\0" * 12
        out_groups.append(offs)
    vtx = hdr + len(chunks)
    head = struct.pack("<IIII", M.MESH_MARKER, hdr, vtx, len(groups))
    for offs in out_groups:
        head += struct.pack(f"<I{len(offs)}I", len(offs), *offs)
    return head + chunks + b"".join(struct.pack("<3hh", *v, 0) for v in vertices)


def test_parse_mesh_groups_chunks_vertices():
    sec = _mesh([[(2, 0x801B), (1, 0x8019)], [(3, 0x805A)]], [(1, -2, 3), (4, 5, -6), (7, 8, 9)])
    m = M.parse_mesh(sec)
    assert len(m["groups"]) == 2 and m["vertices"] == [(1, -2, 3), (4, 5, -6), (7, 8, 9)]
    assert [c["kind"] for c in m["chunks"][0]] == [0x801B, 0x8019] and m["chunks"][1][0]["count"] == 3


def test_parse_mesh_rejects_bad_headers():
    sec = bytearray(_mesh([[(1, 0x801B)]], [(0, 0, 0)]))
    with pytest.raises(M.FormatError):
        M.parse_mesh(b"\x41" + bytes(sec[1:]))
    broken = bytearray(sec)
    struct.pack_into("<I", broken, 20, 0x10000)          # chunk offset outside
    with pytest.raises(M.FormatError):
        M.parse_mesh(bytes(broken))
    with pytest.raises(M.FormatError):
        M.parse_mesh(bytes(sec[:-3]))                    # vertex block not whole SVECTORs
    with pytest.raises(M.FormatError):
        M.chunk_header(bytes(sec), len(sec))


def _u16s(values):
    return struct.pack(f"<{len(values)}H", *values)


def test_batches_bones_and_body_variants():
    counts = [0] * (M.SLOT_ENTRIES * M.MESH_SLOTS)
    starts = [0] * len(counts)
    for i, (c, s) in enumerate([(10, 0), (5, 10), (5, 15), (2, 20), (2, 22), (2, 24), (2, 26), (3, 28), (3, 31)]):
        counts[i], starts[i] = c, s
    counts[13], starts[13] = 7, 0                         # slot 1 (section 4): one batch on bone 4
    b = M.batches(_u16s(counts), _u16s(starts), 0, 34)
    assert [x["bone"] for x in b] == [0, 1, 2, 6, 7, 12, 13, 4, 8]
    b10 = M.batches(_u16s(counts), _u16s(starts), 0, 34, groups=10)
    assert [x["bone"] for x in b10] == [0, 1, 2, 6, 7, 12, 13, 3, 9]
    assert M.batches(_u16s(counts), _u16s(starts), 1, 7) == [{"part": 0, "first": 0, "count": 7, "bone": 4}]
    assert M.batches(_u16s(counts[:13]), _u16s(starts[:13]), 3, 0) == []
    with pytest.raises(M.FormatError):
        M.batches(_u16s(counts), _u16s(starts), 0, 30)    # batch runs past the vertex block
    with pytest.raises(M.FormatError):
        M.batches(_u16s(counts), _u16s(starts), 8, 30)


def test_unpack_refuses_short_program_image():
    with pytest.raises(M.FormatError):
        M.unpack_model(_model({}), b"\0" * 1024)


@needs_roms
def test_owned_models_expand_and_every_vertex_has_a_bone():
    banked, ram, _ = D.decode_owned(OWNED)
    for name, costume in (("tina", 0), ("gen fu", 0)):
        f = D.fighter(name)
        model = D.read_file(banked, f["models"][costume])
        s = M.model_summary(model, ram)
        assert s["tims"] > 40 and s["meshes"]
        for slot, mesh in s["meshes"].items():
            assert mesh["covered"] == mesh["vertices"] > 0
            assert all(b["bone"] is not None and 0 <= b["bone"] <= 26 for b in mesh["batches"])
    tina = M.model_summary(D.read_file(banked, D.fighter("tina")["models"][0]), ram)
    assert [b["bone"] for b in tina["meshes"][0]["batches"]] == [0, 1, 2, 6, 7, 12, 13]
    assert tina["meshes"][0]["vertices"] == 348
    genfu = M.model_summary(D.read_file(banked, D.fighter("gen fu")["models"][0]), ram)
    assert [b["bone"] for b in genfu["meshes"][0]["batches"]][-2:] == [3, 9]
