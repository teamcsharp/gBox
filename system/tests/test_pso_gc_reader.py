"""PSO Episode I & II (GC) reader (gbox.pso_gc): synthetic containers, big-endian Ninja, DOL texture tables, routing.
The owned-disc checks run only when GBOX_PSO_GC_ISO (or the cached image) is present; no game data is in the repo."""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import ninja, pso_gc as G, pso_player

ISO = Path(os.environ.get("GBOX_PSO_GC_ISO", Path.home() / "gBox_alt/gbox-cache" / "gc" / "436e0bb84d5337d1" / "disc.iso"))


# ------------------------------------------------------------------ GSL

def _gsl(files: dict[str, bytes], table_area: int = 0x800) -> bytes:
    head = bytearray(table_area)
    body = bytearray()
    for i, (n, b) in enumerate(files.items()):
        head[i * 0x30:i * 0x30 + len(n)] = n.encode()
        struct.pack_into(">II", head, i * 0x30 + 0x20, (table_area + len(body)) // 0x800, len(b))
        body += b + bytes((-len(b)) % 0x800)
    return bytes(head + body)


def test_gsl_parse_and_identical_rebuild():
    data = _gsl({"a.bml": b"A" * 100, "b.gvm": b"B" * 3000, "c.bin": b"C" * 5})
    assert [(n, s) for n, _o, s in G.gsl_entries(data)] == [("a.bml", 100), ("b.gvm", 3000), ("c.bin", 5)]
    assert G.gsl_files(data)["b.gvm"] == b"B" * 3000
    assert G.gsl_build(data, {}) == data


def test_gsl_replace_grows_and_relocates_the_rest():
    data = _gsl({"a.bml": b"A" * 100, "b.gvm": b"B" * 300})
    new = G.gsl_build(data, {"a.bml": b"Z" * 5000})
    f = G.gsl_files(new)
    assert f["a.bml"] == b"Z" * 5000 and f["b.gvm"] == b"B" * 300
    assert all(o % 0x800 == 0 for _n, o, _s in G.gsl_entries(new))


def test_gsl_rejects_entries_past_the_end():
    data = bytearray(_gsl({"a.bml": b"A" * 10}))
    struct.pack_into(">I", data, 0x24, 0x10000)
    with pytest.raises(ValueError):
        G.gsl_entries(bytes(data))


# ------------------------------------------------------------------ BML (big-endian header, 0x20 / 0x800 alignment)

def _bml(entries: list[tuple[str, bytes, bytes | None]], align: int, e: str = ">") -> bytes:
    n = len(entries)
    start = pso_player.bml_start(n)
    head = bytearray(start)
    struct.pack_into(e + "I", head, 4, n)
    body = bytearray()
    for i, (name, raw, tex) in enumerate(entries):
        c = ninja.prs_compress(raw)
        t = ninja.prs_compress(tex) if tex else b""
        h = 0x40 + 0x40 * i
        head[h:h + len(name)] = name.encode()
        struct.pack_into(e + "5I", head, h + 0x20, len(c), 0, len(raw), len(t), len(tex or b""))
        body += c + bytes((-len(c)) % align)
        if t:
            body += t + bytes((-len(t)) % align)
    return bytes(head + body)


@pytest.mark.parametrize("align", [0x20, 0x800])
def test_bml_big_endian_round_trip_keeps_alignment(align):
    data = _bml([("x.nj", b"NJCM" + bytes(300), b"GVMH" + bytes(64)), ("y.njm", b"NMDM" + bytes(40), None)], align)
    assert pso_player.bml_align(data, ">") == align
    assert G.bml_build(data, {}) == data
    body, tex = G.bml_entry(data, "X.NJ")
    assert body[:4] == b"NJCM" and tex[:4] == b"GVMH"
    new = G.bml_build(data, {"x.nj": b"NJCM" + bytes(900)})
    assert G.bml_entry(new, "x.nj")[0] == b"NJCM" + bytes(900)
    assert G.bml_entry(new, "y.njm")[0] == b"NMDM" + bytes(40)


def test_bml_header_grows_past_0x800_for_many_entries():
    ents = [(f"m{i:02d}.njm", b"NMDM" + bytes([i]) * 20, None) for i in range(40)]
    data = _bml(ents, 0x20)
    assert pso_player.bml_start(40) == 0x1000
    assert G.bml_build(data, {}) == data
    assert G.bml_entry(data, "m39.njm")[0] == b"NMDM" + bytes([39]) * 20


# ------------------------------------------------------------------ GVR / GVM

def _gvr(fmt: int, w: int, h: int, texels: bytes, flags: int = 0, gbix: int | None = 7) -> bytes:
    body = bytes([0, 0, flags, fmt]) + struct.pack(">HH", w, h) + texels
    out = b"GVRT" + struct.pack("<I", len(body)) + body
    return (b"GBIX" + struct.pack("<I", 8) + struct.pack(">I", gbix) + bytes(4) + out) if gbix is not None else out


def test_gvr_rgb5a3_decode():
    # one 4x4 tile: opaque pure red everywhere
    red = (1 << 15) | (31 << 10)
    chunk = _gvr(5, 4, 4, struct.pack(">16H", *([red] * 16)))
    hd = G.gvr_header(chunk)
    assert (hd["fmt"], hd["w"], hd["h"], hd["gbix"]) == (5, 4, 4, 7)
    px = G.gvr_decode(chunk)
    assert px.shape == (4, 4, 4) and (px[..., 0] == 255).all() and (px[..., 1] == 0).all() and (px[..., 3] == 255).all()


def test_gvm_entries_follow_the_header():
    a = _gvr(5, 4, 4, bytes(32), gbix=None)
    b = _gvr(14, 8, 8, bytes(32), gbix=None)
    names = ["tex_a", "tex_b"]
    hdr = b""
    for i, n in enumerate(names):
        hdr += struct.pack(">H", i) + n.encode().ljust(28, b"\0") + bytes(8)
    data = b"GVMH" + struct.pack("<I", 4 + len(hdr)) + struct.pack(">HH", 0x0F, 2) + hdr + a + b
    ents = G.gvm_entries(data)
    assert [n for n, _c in ents] == names and ents[0][1] == a and ents[1][1] == b


# ------------------------------------------------------------------ big-endian Ninja: vertex chunks are u32-swapped

def _be_model(pos, tris):
    nrm = np.tile([0, 1.0, 0], (len(pos), 1))
    vl, pl, c, r = ninja.cnk_model_lists(np.asarray(pos, float), nrm, tris, 3, b"", e=">", base=5)
    nd = [{"flags": 0x17, "trs": struct.pack(">3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": None}]
    data, _root, ptrs = ninja.write_tree(nd, {0: (vl, pl, c, r)}, 0, ">")
    return b"NJCM" + struct.pack("<I", len(data)) + data + ninja.pof0(ptrs), vl


def test_gc_vertex_chunk_word_is_count_high_base_low():
    f, vl = _be_model([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))])
    assert struct.unpack_from(">I", vl, 4)[0] == (3 << 16) | 5        # u32 count << 16 | base, big-endian
    nj = G.read_nj(f)
    assert sorted(nj.vbuf) == [5, 6, 7]
    assert nj.vbuf[6]["pos"] == pytest.approx([1, 0, 0])
    assert list(nj.tris) == [3] and len(nj.tris[3]) == 1


def test_little_endian_vertex_word_unchanged():
    nrm = np.tile([0, 1.0, 0], (3, 1))
    vl, pl, c, r = ninja.cnk_model_lists(np.eye(3), nrm, [((0, 1, 2), ((0, 0),) * 3)], 0, b"", base=2)
    assert struct.unpack_from("<HH", vl, 4) == (2, 3)                  # Dreamcast layout: base, count


# ------------------------------------------------------------------ PsoV3.dol texture tables (synthetic DOL)

class _DolBuilder:
    BASE = 0x80400000

    def __init__(self):
        self.data = bytearray()

    def at(self) -> int:
        return self.BASE + len(self.data)

    def string(self, s: str) -> int:
        a = self.at()
        self.data += s.encode() + b"\0"
        self.data += bytes((-len(self.data)) % 4)
        return a

    def words(self, *ws) -> int:
        a = self.at()
        for w in ws:
            self.data += struct.pack(">I", w)
        return a

    def texlist(self, names: list[str]) -> int:
        ptrs = [self.string(n) for n in names]
        arr = self.words(*ptrs)
        return self.words(arr, len(ptrs))

    def dol(self) -> bytes:
        hdr = bytearray(0x100)
        struct.pack_into(">I", hdr, 0x1C, 0x100)                 # data section 0: file offset
        struct.pack_into(">I", hdr, 0x64, self.BASE)            # its address
        struct.pack_into(">I", hdr, 0xAC, len(self.data))       # its size
        return bytes(hdr + self.data)


def test_class_tables_follow_the_game_pointers():
    B = _DolBuilder()
    afs_names = ["pxtZc_01g_t_core", "pxtAb_01z_w_huku1", "pxtAf_01b_w_kao1", "pxtAh_01z_w_kami1"]
    name_ptrs = B.words(*[B.string(n) for n in afs_names])
    afs_str = B.string("PLATEX.AFS")
    B.words(0xC8, len(afs_names), afs_str, name_ptrs)            # {id, count, afs name, names}
    body_tl = B.texlist(["pxtZc_01g_t_core", "pxtAb_01z_w_huku1"])
    head_tl = B.texlist(["pxtAf_01b_w_kao1"])
    hair_tls = [B.texlist(["pxtAh_01z_w_kami1"])] + [0] * 9
    hair_files = B.words(*[B.string(f"plAhai{i:02d}.nj") for i in range(10)])
    cap_files = B.words(*([0] * 10))
    head_file = B.words(B.string("plAhed00.nj"))
    head_tls = B.words(head_tl)
    hair_tl_arr = B.words(*hair_tls)
    body_str = B.string("plAbdy00.nj")
    B.words(0x00120004, 0x50000, 0x000A0100, 0x01000100, hair_files, cap_files, head_file, body_str, hair_tl_arr,
            head_tls, body_tl)
    t = G.class_tables(B.dol())
    assert list(t) == ["A"]
    a = t["A"]
    assert a["afs"] == afs_names and a["body"] == ["pxtZc_01g_t_core", "pxtAb_01z_w_huku1"]
    assert a["head_files"] == ["plAhed00.nj"] and a["heads"] == [["pxtAf_01b_w_kao1"]]
    assert a["hair_files"][3] == "plAhai03.nj" and a["cap_files"] == [""] * 10
    assert a["hairs"][0] == ["pxtAh_01z_w_kami1"] and a["hairs"][1] == []


# ------------------------------------------------------------------ roster / routing

def test_dedicated_routing_takes_ep1_2_not_ep3():
    from gbox import characters as C
    names = lambda t: [n for n, test, _r, _x in C.DEDICATED if test(t.lower(), "gamecube")]
    assert names("Phantasy Star Online Episode I & II Plus (USA)") == ["pso_gc"]
    assert names("Phantasy Star Online Episode I & II (USA)") == ["pso_gc"]
    assert names("Return To Ragol V1.0.3") == ["pso_gc"]
    assert names("Phantasy Star Online Episode III - C.A.R.D. Revolution (USA)") == []
    assert "pso_gc" in C.READER_VERSIONS


def test_roster_classes_and_enemies():
    ros = G.roster()
    chars = [e for e in ros if e["kind"] == "character"]
    enemies = [e for e in ros if e["kind"] == "enemy"]
    assert [e["key"] for e in chars] == list(G.LETTERS) and len(chars) == 12
    assert len(enemies) == len(G.ENEMIES) and all(e["slot"].startswith("enemy:") for e in enemies)
    assert len({e["slug"] for e in ros}) == len(ros)
    assert G.letter("HUcast") == "C" and G.letter("fomar") == "L" and G.letter("x") == "X"


# ------------------------------------------------------------------ the owned disc (skipped without it)

needs_disc = pytest.mark.skipif(not ISO.exists(), reason="owned PSO GC image not present")


@needs_disc
def test_disc_every_class_has_18_roles_and_textures(tmp_path):
    disc = G.open_disc(ISO)
    for L in G.LETTERS:
        roles = G.class_roles(disc.read(f"pl{L}bdy00.nj"), L)
        assert len(roles) == 18
        m, info = G.build_player(disc, L)
        assert not info["missing"] and len(info["textures"]) >= 4


@needs_disc
def test_disc_booma_export(tmp_path):
    disc = G.open_disc(ISO)
    glb, info = G.export_enemy(disc, "booma", tmp_path)
    assert glb.stat().st_size > 0 and "gsl_forest01.gsl" in info["homes"]
    assert {"hip", "chest", "head", "l_thigh", "r_thigh"} <= set(G.enemy_joint_roles(info))
