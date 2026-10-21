"""DMC3 SE (PS2) MOD geometry probe and SLUS_213.61 loader evidence (#1330)."""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox.dmc3_mod import NO_KICK, parse_mod, mod_stats, strip_triangles, to_obj

CACHE = Path.home() / "gBox_alt/gbox-cache/ps2/251d9887eb0ccfb3"
ISO = CACHE / "disc.iso"
SLUS = CACHE / "inventory/SLUS_213.61"


def _synthetic_mod() -> bytes:
    """One object, one 4-vertex strip mesh, a 2-bone skeleton."""
    vc = 4
    b = bytearray(0x400)
    b[0:4] = b"MOD "
    struct.pack_into("<fBBBBI", b, 4, 1.01, 0, 0, 0, 0, 0)
    struct.pack_into("<BBBBII", b, 0x10, 1, 2, 3, 1, 217, 0)
    struct.pack_into("<I", b, 0x1C, 0x300)
    struct.pack_into("<BBHII", b, 0x30, 1, 0x80, vc, 0x60, 1)
    struct.pack_into("<4f", b, 0x50, 0.5, 0.5, 0.0, 1.0)
    pos, nrm, uv, bones, flags = 0x90, 0xC0, 0xF0, 0x100, 0x110
    struct.pack_into("<HH", b, 0x60, vc, 2)
    struct.pack_into("<5I", b, 0x6C, pos, nrm, uv, bones, flags)
    struct.pack_into("<12f", b, pos, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0)
    struct.pack_into("<12f", b, nrm, *([0, 0, 1] * vc))
    struct.pack_into("<8h", b, uv, 0, 0, 4096, 0, 0, 4096, 4096, 4096)
    b[bones:bones + 16] = bytes([0, 8, 0, 0] * vc)
    struct.pack_into("<4H", b, flags, NO_KICK | 31, NO_KICK | 31, 31, 31)
    struct.pack_into("<4I", b, 0x300, 0x20, 0x28, 0x30, 0x40)
    b[0x320:0x322] = bytes([0xFF, 0])
    return bytes(b[:0x380])


def test_strip_triangles_honour_no_kick_and_alternate_winding():
    assert strip_triangles([NO_KICK, NO_KICK, 0, 0, NO_KICK, NO_KICK, 0]) == [(0, 1, 2), (2, 1, 3), (4, 5, 6)]
    assert strip_triangles([NO_KICK, NO_KICK, 0, NO_KICK, 0], base=10) == [(10, 11, 12), (12, 13, 14)]


def test_synthetic_mod_roundtrips_to_obj():
    m = parse_mod(_synthetic_mod())
    st = mod_stats(m)
    assert (st["objects"], st["meshes"], st["vertices"], st["triangles"], st["bones"]) == (1, 1, 4, 2, 2)
    assert st["outside_sphere"] == 0 and st["worst_normal_error"] == 0
    mesh = m["objects"][0]["meshes"][0]
    assert mesh["texture"] == 2 and mesh["uvs"][3] == (1.0, 1.0) and mesh["triangles"] == [(0, 1, 2), (2, 1, 3)]
    assert m["skeleton"]["parents"] == [0xFF, 0] and m["skeleton"]["ends_at"] == 0x380
    obj = to_obj(m, "t")
    assert obj.count("\nv ") == 4 and obj.count("\nf ") == 2 and "f 1/1/1 2/2/2 3/3/3" in obj


def test_rejects_bad_offsets():
    b = bytearray(_synthetic_mod())
    struct.pack_into("<I", b, 0x6C, 0x91)
    with pytest.raises(ValueError):
        parse_mod(bytes(b))
    with pytest.raises(ValueError):
        parse_mod(b"PAC\0" + bytes(60))


def _pl000() -> bytes:
    from gbox.dmc3_inventory import afs_read
    from gbox.gta_rw import iso_files
    with ISO.open("rb") as f:
        lba, size = iso_files(f)["GDATA.AFS"]
        a = afs_read(f, lba, size)
        assert a["names"][0] == "pl000.pac"
        o, z = a["entries"][0]
        f.seek(a["base"] + o)
        return f.read(z)


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC3 SE disc image not staged")
def test_owned_pl000_body_and_coat_geometry():
    from gbox.dmc3_inventory import pac_children
    pl = _pl000()
    ch = pac_children(pl)
    expect = {1: (17, 18, 5316, 3680, 24), 12: (6, 8, 828, 624, 33)}
    for slot, (objs, meshes, verts, tris, bones) in expect.items():
        o, z = ch[slot]
        m = parse_mod(pl[o:o + z])
        st = mod_stats(m)
        assert (st["objects"], st["meshes"], st["vertices"], st["triangles"], st["bones"]) == \
            (objs, meshes, verts, tris, bones)
        assert st["outside_sphere"] == 0 and st["worst_normal_error"] < 1e-4
        assert m["skeleton"]["ends_at"] == z  # 0x20-byte bone rows end exactly at the model end
        texs = {ms["texture"] for ob in m["objects"] for ms in ob["meshes"]}
        assert texs <= {0, 1, 2}  # pl000 child 0 texture bank holds three TIM2 pictures
        for ob in m["objects"]:
            for ms in ob["meshes"]:
                assert all(r[0] == 0 and all(x % 4 == 0 for x in r) for r in ms["bone_refs"])
                assert all(sum((f >> s) & 31 for s in (0, 5, 10)) == 31 for f in ms["flags"])


@pytest.mark.skipif(not SLUS.exists(), reason="owned SLUS_213.61 not extracted")
def test_slus_archive_mounts_and_model_classifier():
    from gbox.dmc3_slus import SLUS_SHA256, Elf, archive_mounts, magic_classifier
    data = SLUS.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SLUS_SHA256
    elf = Elf(data)
    assert (elf.entry, elf.va) == (0x100008, 0x100000)
    mounts = archive_mounts(elf)
    g, s = mounts["GData.afs"], mounts["SData.afs"]
    assert g["name_va"] == 0x58DE70 and g["function"] == 0x1AA8D0 and g["ptid"] == 0 and g["files"] == 3863
    assert s["ptid"] == 1 and s["files"] == 154 and s["mount_target"] == g["mount_target"] == 0x144DD0
    assert elf.callers(0x1AA8D0) == [0x1EDE60]
    cls = magic_classifier(elf)
    assert cls["function"] == 0x1A9870
    assert cls["tags"]["MOD "] == 0x10000000 and cls["tags"]["SHW "] == 0x60000000
    init = elf.function_summary(0x199070)
    assert 0x1A9870 in init["calls"]
    bases = {r for op, off, r in init["loads"] if op == "lbu" and off in (0x10, 0x11)}
    assert bases and all(("lbu", off, r) in init["loads"] for r in bases for off in (0x10, 0x11, 0x13))
    if ISO.exists():
        from gbox.dmc3_inventory import afs_read
        from gbox.gta_rw import iso_files
        with ISO.open("rb") as f:
            files = iso_files(f)
            counts = {n: len(afs_read(f, *files[n])["entries"]) for n in ("GDATA.AFS", "SDATA.AFS")}
        assert counts == {"GDATA.AFS": g["files"], "SDATA.AFS": s["files"]}
