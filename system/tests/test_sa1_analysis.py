import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import sa1_analysis as A
from gbox.sa1_inventory import KEY, Exe

GDI = Path(os.environ.get("GBOX_SA1_GDI", Path.home() / "gBox_alt/gbox-cache/dc/1a3f4cd416db9ffd/disc.gdi"))
EXE_SHA = "45bc5d3c25dcfe2cc2c5701311d46783f33e4daa44a951cd9896724d66f0367a"


def _img(size=0x400):
    return bytearray(size)


def test_pc_relative_literal_and_function_bounds():
    d = _img()
    code = [0x2FE6, 0x4F22, 0xD101, 0x0009, 0x000B, 0x0009]   # push r14; sts.l pr; mov.l @(1,PC),r1; nop; rts; nop
    struct.pack_into("<6H", d, 0x10, *code)
    # mov.l at pc=KEY+0x14: lit = (pc & ~3) + 4 + 1*4 = KEY+0x1C
    struct.pack_into("<I", d, 0x1C, KEY + 0x200)
    c = A.Code(Exe(bytes(d)), code_end=0x40)
    assert c.loads[KEY + 0x200] == [KEY + 0x14]
    assert c.function(KEY + 0x14) == (KEY + 0x10, KEY + 0x18)
    assert (KEY + 0x14, KEY + 0x200) in c.literals(c.function(KEY + 0x14))


def test_pvm_texlist_row():
    d = _img()
    d[0x100:0x106] = b"SONIC\0"
    struct.pack_into("<II", d, 0x200, KEY + 0x100, KEY + 0x300)     # {name, texlist}
    struct.pack_into("<II", d, 0x300, KEY + 0x340, 28)              # NJS_TEXLIST {textures, nbTexture}
    t = A.pvm_texlists(Exe(bytes(d)), ["SONIC"])
    assert t == {"SONIC": {"entry": KEY + 0x200, "texlist": KEY + 0x300, "count": 28}}


def _model(d, at, pts, strips_kind, mesh):
    struct.pack_into("<IIiIIHH", d, at, KEY + at + 0x40, 0, len(pts), KEY + at + 0x80, 0, 1, 0)
    for i, p in enumerate(pts):
        struct.pack_into("<3f", d, at + 0x40 + 12 * i, *p)
    struct.pack_into("<HHI", d, at + 0x80, strips_kind << 14, 1, KEY + at + 0xA0)
    struct.pack_into(f"<{len(mesh)}H", d, at + 0xA0, *mesh)


def test_strip_winding_and_quads():
    d = _img(0x800)
    sq = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
    _model(d, 0x100, sq, 3, [4, 0, 1, 2, 3])                    # one strip, 4 verts
    _model(d, 0x300, sq, 3, [0x8000 | 4, 0, 1, 2, 3])           # reversed winding flag
    _model(d, 0x500, sq, 1, [0, 1, 2, 3])                       # one quad
    ex = Exe(bytes(d))
    assert A.model_tris(ex, KEY + 0x100)[1] == [(0, 1, 2), (2, 1, 3)]
    assert A.model_tris(ex, KEY + 0x300)[1] == [(1, 0, 2), (1, 2, 3)]
    assert A.model_tris(ex, KEY + 0x500)[1] == [(0, 1, 2), (1, 3, 2)]


def test_tree_mesh_applies_parent_translation_and_bams_rotation():
    d = _img(0x800)
    _model(d, 0x400, [(1, 0, 0), (0, 1, 0), (0, 0, 1)], 0, [0, 1, 2])
    # root at 0x100: pos (0,10,0), child 0x140: rotate 90 deg about Z (0x4000 BAMS), model 0x400
    struct.pack_into("<II3f3i3fII", d, 0x100, 0, 0, 0, 10, 0, 0, 0, 0, 1, 1, 1, KEY + 0x140, 0)
    struct.pack_into("<II3f3i3fII", d, 0x140, 0, KEY + 0x400, 0, 0, 0, 0, 0, 0x4000, 1, 1, 1, 0, 0)
    m = A.tree_mesh(Exe(bytes(d)), KEY + 0x100)
    assert m["parents"] == [-1, 0] and m["triangles"] == [(0, 1, 2)]
    v = [tuple(round(c, 5) for c in p) for p in m["vertices"]]
    assert v == [(0, 11, 0), (-1, 10, 0), (0, 10, 1)]


@pytest.fixture(scope="module")
def exe():
    if not GDI.exists():
        pytest.skip("owned Sonic Adventure (USA) GD-ROM cache not present")
    from gbox.gdrom import GDRom
    d = GDRom(str(GDI)).read("1ST_READ.BIN")
    assert hashlib.sha256(d).hexdigest() == EXE_SHA
    return Exe(d)


def test_real_character_map(exe):
    m = A.character_map(exe)
    want = {"sonic": (0x8C1C6C94, 28, 0x8C1CE76C), "tails": (0x8C257C54, 24, 0x8C25F968),
            "knuckles": (0x8C3537D8, 22, 0x8C35B094), "amy": (0x8C4BF3AC, 53, 0x8C4C7C3C),
            "big": (0x8C525FB0, 36, 0x8C52F298), "e102": (0x8C423454, 35, 0x8C42CC34)}
    for slug, (tl, n, root) in want.items():
        c = m[slug]
        assert (c["texlist"], c["textures"], c["root"]) == (tl, n, root), slug
        assert c["max_texture_id"] < n and c["evidence"]
    assert m["sonic"]["variants"] == [0x8C1D630C]
    assert m["tails"]["variants"] == [0x8C26769C, 0x8C26F3A8]
    assert m["knuckles"]["variants"] == [0x8C36286C, 0x8C36C084]
    e = m["sonic"]["evidence"][0]        # njSetTexture(&SONIC texlist) fn -> draw fn -> Sonic tree node
    assert (e["function"], e["texlist_load"], e["calls"], e["value"]) == (0x8C0AE17A, 0x8C0AE1FA, 0x8C0B2170,
                                                                          0x8C1C8454)
    assert m["eggman"]["root"] is None   # NPC: no player-sized tree


def test_real_sonic_bind_mesh(exe):
    mesh = A.tree_mesh(exe, 0x8C1CE76C)
    assert len(mesh["parents"]) == 73 and len(mesh["parts"]) == 28
    assert (len(mesh["vertices"]), len(mesh["triangles"])) == (635, 1001)
    ys = [v[1] for v in mesh["vertices"]]
    assert 9 < max(ys) - min(ys) < 11
