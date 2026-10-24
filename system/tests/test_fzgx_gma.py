import struct
from pathlib import Path

import pytest

from gbox.fzgx_gma import FzgxFormatError, check_pair, gx_size, parse_gma, parse_tpl

GCZ = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/F-Zero GX (USA).gcz")


def _synth_gma(tex_idx=(0,)):
    names = b"TEST".ljust(16, b"\0")
    base = 8 + 8 + len(names)
    g = bytearray(0x40 + 0x20 * len(tex_idx))
    g[0:4] = b"GCMF"
    struct.pack_into(">I4fHHH", g, 4, 5, 0, 0, 0, 1.0, len(tex_idx), 1, 0)
    struct.pack_into(">I", g, 0x20, len(g))
    for k, t in enumerate(tex_idx):
        struct.pack_into(">H", g, 0x40 + k * 0x20 + 6, t)
    return struct.pack(">II", 1, base) + struct.pack(">II", 0, 0) + names + bytes(g)


def _synth_tpl(n=1):
    data0 = (4 + n * 0x10 + 0x1F) & ~0x1F
    hdr = struct.pack(">I", n) + b"".join(
        struct.pack(">IIHHI", 0xE, data0 + i * 0x200, 32, 32, 0x00011234) for i in range(n))
    return hdr.ljust(data0, b"\0") + bytes(0x200 * n)


def test_gx_size():
    assert gx_size(0xE, 32, 32) == 0x200
    assert gx_size(0x6, 4, 4) == 64
    with pytest.raises(FzgxFormatError):
        gx_size(0x2F, 1, 1)


def test_synthetic_pair():
    r = check_pair(_synth_gma((0, 1)), _synth_tpl(2))
    assert r == {"models": ["TEST"], "textures": 2, "max_tex_index": 1}


def test_texture_index_out_of_range():
    with pytest.raises(FzgxFormatError):
        check_pair(_synth_gma((3,)), _synth_tpl(2))


def test_bad_magic():
    b = bytearray(_synth_gma())
    b[0x20:0x24] = b"XXXX"
    with pytest.raises(FzgxFormatError):
        parse_gma(bytes(b))


@pytest.mark.skipif(not GCZ.exists(), reason="owned F-Zero GX GCZ not mounted")
def test_owned_arrow_500():
    from gbox.gcdisc import GCDisc
    d = GCDisc(str(GCZ))
    gma, tpl = d.read("chara/arrow_500.gma"), d.read("chara/arrow_500.tpl")
    m = parse_gma(gma)[0]
    assert m.name == "ARROW_c_hara"
    assert (m.gcmf.texture_refs, m.gcmf.matrix_count, m.gcmf.header_size) == (17, 15, 0x540)
    texs = parse_tpl(tpl)
    assert len(texs) == 16 and texs[0].fmt == 0xE and texs[0].offset == 0x120
    assert texs[-1].offset + texs[-1].size <= len(tpl)
    assert check_pair(gma, tpl)["textures"] == 16


@pytest.mark.skipif(not GCZ.exists(), reason="owned F-Zero GX GCZ not mounted")
def test_owned_all_chara_vehicle_parse():
    from gbox.gcdisc import GCDisc
    d = GCDisc(str(GCZ))
    n = 0
    for p in d.files:
        if p.split("/")[0] in ("chara", "vehicle", "vehicle_parts"):
            if p.endswith(".gma"):
                parse_gma(d.read(p)); n += 1
            elif p.endswith(".tpl"):
                parse_tpl(d.read(p))
    assert n == 143 + 125 + 525
