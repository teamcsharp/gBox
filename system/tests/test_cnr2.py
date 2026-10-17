import struct

import pytest

from gbox import cnr2


def _fpk(entries):
    table = 0x10
    off = table + 0x30 * len(entries)
    body, rows = b"", b""
    for name, stored, size in entries:
        rows += name.encode().ljust(0x20, b"\0") + struct.pack(">4I", 0, off + len(body), len(stored), size)
        body += stored
    total = off + len(body)
    return struct.pack(">4I", 0x3F13, len(entries), table, total) + rows + body


def test_fpk_index_reads_table():
    d = _fpk([("chr/nrt/0000.seq", b"\x84\x00abc", 40), ("chr/nrt/0000.brplt", b"x" * 8, 8)])
    idx = cnr2.fpk_index(d)
    assert [e["name"] for e in idx] == ["chr/nrt/0000.seq", "chr/nrt/0000.brplt"]
    assert idx[0]["offset"] == 0x70 and idx[0]["stored"] == 5 and idx[0]["size"] == 40 and idx[0]["compressed"]
    assert not idx[1]["compressed"]
    assert d[idx[1]["offset"]:idx[1]["offset"] + 8] == b"x" * 8


def test_fpk_index_rejects_bad_size():
    d = _fpk([("a", b"1", 1)])
    with pytest.raises(ValueError):
        cnr2.fpk_index(d + b"\0")


def _group(names_ptrs):
    """Index group bytes with name/data pointers relative to the group start (filled by caller offsets)."""
    n = len(names_ptrs)
    g = struct.pack(">2I", 8 + 16 * (n + 1), n) + struct.pack(">4H2I", 0xFFFF, 0, 1, 0, 0, 0)
    for i, (name_rel, data_rel) in enumerate(names_ptrs):
        g += struct.pack(">4H2I", i, 0, 0, 0, name_rel, data_rel)
    return g


def _brres_with_mdl0():
    # layout: header 0x10 | root block at 0x10 ("root", size, group) | sub-group | MDL0 | bones group | names
    root = 0x10
    rg = root + 8                         # root group (1 folder)
    fg = rg + 8 + 32                      # folder group (1 model)
    mdl = fg + 8 + 32
    mdl_len = 0x10 + 13 * 4 + 4
    bg = mdl + mdl_len                    # bones group (2 bones)
    names = bg + 8 + 48
    strs = [b"3DModels(NW4R)", b"body", b"hip", b"spine"]
    name_at, cur = [], names
    blob = b""
    for s in strs:
        cur += 4
        name_at.append(cur)
        blob += struct.pack(">I", len(s)) + s + b"\0" * (4 - len(s) % 4)
        cur = names + len(blob)
    d = bytearray(b"\0" * (names + len(blob)))
    d[0:16] = b"bres\xfe\xff\0\0" + struct.pack(">IHH", len(d), root, 2)
    d[root:root + 8] = b"root" + struct.pack(">I", fg - root)
    d[rg:fg] = _group([(name_at[0] - rg, fg - rg)])
    d[fg:mdl] = _group([(name_at[1] - fg, mdl - fg)])
    secs = [0] * 13
    secs[1] = bg - mdl
    d[mdl:bg] = b"MDL0" + struct.pack(">2Ii", mdl_len, 11, -mdl) + struct.pack(">13i", *secs) + b"\0" * 4
    d[bg:names] = _group([(name_at[2] - bg, 0), (name_at[3] - bg, 0)])
    d[names:] = blob
    return bytes(d)


def test_brres_index_counts_mdl0_bones():
    idx = cnr2.brres_index(_brres_with_mdl0())
    body = idx["3DModels(NW4R)"]["body"]
    assert body["magic"] == "MDL0" and body["version"] == 11
    assert body["bones"] == 2 and body["bone_names"] == ["hip", "spine"]


def test_brres_index_rejects_little_endian():
    with pytest.raises(ValueError):
        cnr2.brres_index(b"bres\xff\xfe" + b"\0" * 32)


DISC = cnr2.Path.home() / "gbox-cache/modbase/00063327fc44eced/disc/DATA/files"


@pytest.mark.skipif(not (DISC / "chr/nrt/0000.brres").is_file(), reason="extracted RNYEDA disc not on this node")
def test_real_disc_naruto_costume():
    idx = cnr2.brres_index((DISC / "chr/nrt/0000.brres").read_bytes())
    m = idx["3DModels(NW4R)"]["0000"]
    assert m["version"] == 11 and m["bones"] == 91 and "nrt_tex01" in m["textures"]
    names = [e["name"] for e in cnr2.fpk_index((DISC / "fpack/chr/nrt/0000.fpk").read_bytes())]
    assert names[:2] == ["chr/nrt/0000.seq", "chr/nrt/0000.brres"] and len(names) == 25
    assert len(cnr2.characters(DISC)) == 44
