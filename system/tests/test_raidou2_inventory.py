"""Raidou 2 PS2 inventory (#1507): DDS3 DDT tree, coverage, Atlus chunk/LB headers."""
import os
import struct
from pathlib import Path

import pytest

from gbox import raidou2_inventory as r2

ISO = Path(os.environ.get("GBOX_RAIDOU2_ISO", str(Path.home() / "gBox_alt/gbox-cache/ps2/999eb37d21991092/disc.iso")))


def _ddt(tree):
    """Build a DDT from {name: (sector, size) | {sub tree}} like the game's layout:
    each directory's children are one contiguous 12-byte record block."""
    out = [("", list(tree.items()))]
    child_at, pending = {}, [0]
    while pending:
        j = pending.pop(0)
        child_at[j] = len(out)
        for nm, v in out[j][1]:
            out.append((nm, list(v.items()) if isinstance(v, dict) else v))
            if isinstance(v, dict):
                pending.append(len(out) - 1)
    names, recs = bytearray(), bytearray()
    for j, (nm, v) in enumerate(out):
        off = 12 * len(out) + len(names)
        names += nm.encode() + b"\0"
        if isinstance(v, list):
            recs += struct.pack("<IIi", off, 12 * child_at[j], -len(v))
        else:
            recs += struct.pack("<IIi", off, v[0], v[1])
    return bytes(recs + names)


def _chunk(magic, body=b""):
    size = 16 + len(body)
    return struct.pack("<HHI4sI", r2.CHUNK_TYPES[magic], 0, size, magic, 0) + body


def _pad(b, a=0x40):
    return b + b"\0" * (-len(b) % a)


def test_ddt_tree_and_exact_tiling():
    ddt = _ddt({"model": {"battle": {"player.PB": (0, 4096)}, "a.LB": (2, 10)}, "font": {"f.tmx": (3, 2048)}})
    ents = r2.ddt_entries(ddt)
    assert sorted(ents) == [("font/f.tmx", 3, 2048), ("model/a.LB", 2, 10), ("model/battle/player.PB", 0, 4096)]
    cov = r2.coverage(ents, 4 * 2048)
    assert cov["exact_tiling"] and cov["gap_sectors"] == 0 and cov["files"] == 3
    assert not r2.coverage(ents + [("x", 1, 2048)], 4 * 2048)["exact_tiling"]


def test_ddt_rejects_bad_root_and_loops():
    with pytest.raises(ValueError):
        r2.ddt_entries(struct.pack("<IIi", 0, 0, 5))
    loop = struct.pack("<IIi", 0, 0, -1)  # root points at itself
    with pytest.raises(ValueError):
        r2.ddt_entries(loop + b"\0")


def test_pb_chunks_textures_model_motion():
    tmx = _chunk(b"TMX0", struct.pack("<HHHB", 1, 128, 64, 0x13) + b"\0" * 9 + b"\xab" * 32)
    txp_body = struct.pack("<II", 1, 0x40)
    txp_body += b"\0" * (0x40 - 16 - len(txp_body)) + tmx
    pb = _pad(_chunk(b"PIB0", struct.pack("<iIII", -2, 0x14, 1, 0) + b"\0" * 4))
    pb += _pad(_chunk(b"TXP0", txp_body))
    pb += _pad(_chunk(b"MD00", b"\x11" * 40))
    pb += _chunk(b"MT00", struct.pack("<II", 0x100, 12) + b"\0" * 8)
    cs = r2.pb_chunks(pb)
    assert [c["magic"] for c in cs] == ["PIB0", "TXP0", "MD00", "MT00"]
    assert cs[1]["textures"] == [{"w": 128, "h": 64, "psm": "PSMT8"}]
    s = r2._package_summary(cs)
    assert s["models"] == 1 and s["textures"] == 1 and s["motions"] == 12
    with pytest.raises(ValueError):
        r2.pb_chunks(b"\0" * 64)


def test_lb_header():
    h = struct.pack("<HHI4sI", 0x0101, 0, 0x5BF23, b"PBN\0", 0x776C0)
    assert r2.lb_header(h) == {"packed": 0x5BF23, "magic": "PBN", "unpacked": 0x776C0}
    assert r2.lb_header(b"\x01\x00" + b"\0" * 14) is None


@pytest.mark.skipif(not ISO.exists(), reason="owned Raidou 2 ISO not unpacked (GBOX_RAIDOU2_ISO)")
def test_owned_disc_inventory():
    m = r2.build_manifest(ISO, source_sha256="x")
    assert m["system_cnf"][0] == "BOOT2 = cdrom0:\\SLUS_218.45;1"
    cov = m["dds3"]["coverage"]
    assert cov["files"] == 10060 and cov["exact_tiling"] and cov["img_sectors"] == 887010
    (player,) = [c for c in m["characters"]["raidou_battle"] if c["path"].endswith("/player.PB")]
    assert player["chunks"] == ["PIB0", "TXP0", "MD00", "MT00"]
    assert player["textures"] == 11 and player["motions"] == 12
    assert m["character_counts"]["devil_battle_lb"] == 559


def test_truncated_inputs_raise_valueerror():
    import io
    pb = _pad(_chunk(b"PIB0", b"\0" * 16))
    # a header whose declared size covers only 16 bytes: the MT00 count at +0x14 is past the buffer
    with pytest.raises(ValueError):
        r2.pb_chunks(pb + struct.pack("<HHI4sI", 8, 0, 16, b"MT00", 0))
    with pytest.raises(ValueError):
        r2.tmx_info(b"\0" * 0x16)
    pvd = bytearray(2048)
    pvd[1:6] = b"CD001"
    pvd[156 + 2:156 + 6] = struct.pack("<I", 17)
    pvd[156 + 10:156 + 14] = struct.pack("<I", 2048)
    rec = bytes([40]) + b"\0" * 39  # record length 40 but the image ends after 20 bytes
    img = bytes(16 * 2048) + bytes(pvd) + rec[:20]
    with pytest.raises(ValueError):
        r2.iso_files(io.BytesIO(img))
    with pytest.raises(ValueError):
        r2.iso_files(io.BytesIO(bytes(16 * 2048) + b"\1CD001"))
