"""Path of Neo .dcn_11 geometry reader (gbox.pon_models): sections, part names, the A_DMAPAK vertex batches (16.16
positions, UVs whose low bits carry VU strip-slot addresses, scattered triangle strips) on synthetic files, and the
owned PS2 disc when it is reachable."""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import pon_models as M


def _owned():
    for p in (os.environ.get("GBOX_PON_PS2_CHD"),
              "/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation 2/roms/USA/Matrix, The - Path of Neo (USA).chd",
              "//10.89.1.125/HyperSpin Attraction/Arcade/collections/Sony Playstation 2/roms/USA/"
              "Matrix, The - Path of Neo (USA).chd"):
        if p and Path(p).is_file():
            return Path(p)
    return None


def _addr_float(x: float, addr: int) -> int:
    return (struct.unpack("<I", struct.pack("<f", x))[0] & 0xffff0000) | addr


def batch(verts, nloop):
    """verts: (x, y, z, u, v, slot_a, slot_b) -> one UNPACK V4-32 vertex batch (header + 2 qw per vertex)."""
    out = struct.pack("<4I", len(verts), 3, 0, 0x8000 | nloop)
    for x, y, z, u, v, sa, sb in verts:
        a0 = M.SLOT0 + M.SLOT_QW * sa
        a1 = 0 if sb is None else M.SLOT0 + M.SLOT_QW * sb
        out += struct.pack("<3if", int(x * 65536), int(y * 65536), int(z * 65536), 60 * 4096.0)
        out += struct.pack("<4I", _addr_float(u, a0), _addr_float(v, a1), _addr_float(1.0, 0x3c), 0)
    return out


def dcn11(name="neo.dcn_11", part_names=("head", "legs"), batches=(), extra_unpack=True):
    """A .dcn_11: 0x40 head, _HEADER_, PATCHOBJ (name + part records), A_DMAPAK (ref tags), REFS____, batch data."""
    po = bytearray(0x60 + 4 * len(part_names) + 0x40 * len(part_names))
    po[0:8] = b"PATCHOBJ"
    po[0x14:0x24] = name.encode()[:16].ljust(16, b"\0")
    struct.pack_into("<I", po, 0x58, len(part_names))
    rec0 = 0x60 + 4 * len(part_names)
    for i, pn in enumerate(part_names):
        struct.pack_into("<I", po, 0x60 + 4 * i, 0x20 + rec0 + 0x40 * i)     # BASE-relative: PATCHOBJ is at 0x60
        po[rec0 + 0x40 * i:rec0 + 0x40 * i + 8] = pn.encode()[:8].ljust(8, b"\0")
    po = bytes(po)
    po = po[:8] + struct.pack("<2I", len(po), 1) + po[16:]
    hdr = b"_HEADER_" + struct.pack("<2I", 0x20, 1) + b"\0" * 16
    n_tags = len(batches) + (1 if extra_unpack else 0) + (1 if batches else 0)
    dma_size = 16 + 16 * (2 * n_tags + 1)
    refs = b"REFS____" + struct.pack("<2I", 0x20, 1) + b"\0" * 16
    sec_end = 0x40 + len(hdr) + len(po) + dma_size + len(refs)
    data_at, tags, blobs = sec_end, b"", b""
    if extra_unpack:                                   # a 3-qw matrix unpack: not a vertex batch
        blob = struct.pack("<4I", 1, 0, 0, 0) * 3
        tags += struct.pack("<4I", 0x30000003, data_at - 0x40, 0, 0x6c038000) + struct.pack("<4I", 0x60000000, 0, 0, 0)
        blobs += blob
        data_at += len(blob)
    first = None
    for b in batches:
        qwc = len(b) // 16
        tags += struct.pack("<4I", 0x30000000 | qwc, data_at - 0x40, 0, 0x6c008000 | (qwc & 0xff) << 16)
        tags += struct.pack("<4I", 0x60000000, 0, 0, 0)
        first = first or (qwc, data_at)
        blobs += b
        data_at += len(b)
    if first:                                          # a second chain referencing the first batch again
        tags += struct.pack("<4I", 0x30000000 | first[0], first[1] - 0x40, 0, 0x6c008000 | (first[0] & 0xff) << 16)
        tags += struct.pack("<4I", 0x60000000, 0, 0, 0)
    dma = b"A_DMAPAK" + struct.pack("<2I", dma_size, 1) + b"\0" * 16 + tags
    dma = dma.ljust(dma_size, b"\0")
    head = struct.pack("<4I", sec_end - 0x40, 1, 1, sec_end) + b"\0" * 0x30
    return head + hdr + po + dma + refs + blobs


QUAD = [(0, 0, 0, 0.0, 1.0, 0, None), (1, 0, 0, 1.0, 1.0, 1, None), (0, 2, 0, 0.0, 0.0, 2, None),
        (1, 2, 0.5, 1.0, 0.0, 3, None)]


def test_sections_parts_and_name():
    d = dcn11(batches=[batch(QUAD, 4)])
    s = M.sections(d)
    assert list(s) == ["_HEADER_", "PATCHOBJ", "A_DMAPAK", "REFS____"]
    assert M.model_name(d) == "neo"
    assert M.parts(d) == ["head", "legs"]


def test_batches_skip_non_vertex_unpacks_and_duplicates():
    d = dcn11(batches=[batch(QUAD, 4), batch(QUAD[:3], 3)])
    bs = M.batches(d)
    assert [(b["vertices"], b["nloop"], b["eop"]) for b in bs] == [(4, 4, True), (3, 3, True)]


def test_strip_scatter_winding_and_fixed_point():
    m = M.mesh(dcn11(batches=[batch(QUAD, 4)]))
    assert m["positions"].tolist() == [[0, 0, 0], [1, 0, 0], [0, 2, 0], [1, 2, 0.5]]
    assert m["triangles"].tolist() == [[0, 1, 2], [2, 1, 3]]      # odd strip triangles flipped
    assert np.allclose(m["uvs"], [[0, 1], [1, 1], [0, 0], [1, 0]], atol=1e-3)
    assert m["height"] == 2.0


def test_second_slot_shares_a_vertex_and_gaps_restart_the_strip():
    # 3 source vertices fill 5 slots (vertex 0 also lands in slot 3); slot 4 unwritten
    v = [(0, 0, 0, 0, 0, 0, 3), (1, 0, 0, 0, 0, 1, None), (0, 1, 0, 0, 0, 2, None)]
    m = M.mesh(dcn11(batches=[batch(v, 6)]))
    # slots: 0 1 2 0 -1 -1 -> triangles (0,1,2), (1,2,0) flipped -> (2,1,0); the rest touch unwritten slots
    assert m["triangles"].tolist() == [[0, 1, 2], [2, 1, 0]]
    assert m["batches"][0]["unwritten"] == 2


def test_two_batches_offset_indices():
    m = M.mesh(dcn11(batches=[batch(QUAD, 4), batch(QUAD[:3], 3)]))
    assert len(m["positions"]) == 7
    assert m["triangles"].tolist()[-1] == [4, 5, 6]


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d[:0x48], "shorter"),
    (lambda d: struct.pack("<I", 0x7fffff) + d[4:], "outside the file"),
    (lambda d: d[:0x40] + b"bad_tag!" + d[0x48:], "bad section"),
    (lambda d: d[:0x60] + b"PATCHOBJ" + struct.pack("<I", 0xfffff) + d[0x6c:], "bad section"),
])
def test_bounds_errors(mutate, msg):
    with pytest.raises(M.FormatError, match=msg):
        M.batches(mutate(dcn11(batches=[batch(QUAD, 4)])))


def test_slot_outside_strip_and_missing_batches():
    with pytest.raises(M.FormatError, match="outside the strip"):
        M.mesh(dcn11(batches=[batch(QUAD, 3)]))
    with pytest.raises(M.FormatError, match="no vertex batch"):
        M.batches(dcn11(batches=[]))


def test_obj_export(tmp_path):
    s = M.to_obj(dcn11(batches=[batch(QUAD, 4)]), tmp_path / "neo.obj")
    txt = (tmp_path / "neo.obj").read_text().splitlines()
    assert s["vertices"] == 4 and s["triangles"] == 2
    assert sum(t.startswith("v ") for t in txt) == 4 and txt[-1] == "f 3/3 2/2 4/4"


@pytest.mark.skipif(_owned() is None, reason="owned Path of Neo CHD not reachable")
def test_owned_lobby_cast():
    from gbox.etm_inventory import open_disc
    from gbox.shiny_dfu import Dfu
    dfu = Dfu(open_disc(_owned()), variant="pon")
    files = M.level_model_files(dfu, "b1_lobby_dream")
    assert {"neo", "agentsmith", "agentsmith_lp", "police", "swat", "morpheus4"} <= set(files)
    neo = M.summary(files["neo"])
    assert neo["name"] == "neo" and "head" in neo["parts"]
    assert neo["triangles"] > 3000 and 2800 < neo["height"] < 3000
    lp = M.summary(files["agentsmith_lp"])
    assert lp["parts"] == ["head", "handL", "handR", "legs"] and lp["batches"] == 22 and lp["triangles"] == 649
    for name, data in files.items():                   # every character chunk of the level decodes
        M.summary(data)
