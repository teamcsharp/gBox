"""Sonic Adventure (DC) character reader (gbox.sa1_chars): PRS, basic NJS_MODEL meshsets (tris / quads / strips with
per-corner UVs, textured and colour-only materials), the node tree -> skinned glTF, SA1's body roles + the synthetic
chest bone on a synthetic flat humanoid, overlay load addresses, the DEDICATED registration; then the owned disc
(skipped without it): every roster character exports as a rigged, textured GLB whose roles feed the Crazy Taxi parts."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C, ninja, sa1_chars as S, uap
from gbox.sa1_inventory import KEY, Exe

GID = "1a3f4cd416db9ffd"


def _gdi() -> Path | None:
    cands = [os.environ.get("GBOX_SA1_GDI"), Path.home() / f"gbox-cache/dc/{GID}/disc.gdi",
             f"//10.89.1.246/ehm_eckx/samples/gbox-cache/dc/{GID}/disc.gdi",
             f"//10.89.1.246/ehm_eckx/gBox_alt/gbox-cache/dc/{GID}/disc.gdi"]
    for c in cands:
        try:
            if c and Path(c).is_file():
                return Path(c)
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- a synthetic 1ST_READ image

class Img:
    """Bump allocator over a little-endian SH-4 image loaded at `key`."""

    def __init__(self, key=KEY, size=0x8000):
        self.key, self.d, self.o = key, bytearray(size), 0x40

    def put(self, data: bytes) -> int:
        a = self.o
        self.d[a:a + len(data)] = data
        self.o = (a + len(data) + 3) & ~3
        return self.key + a

    def model(self, pts, meshsets, mats=(), normals=None) -> int:
        """meshsets: [(kind, mat, [mesh index lists / strips], uvs)]; strips are (flip, [idx])."""
        pp = self.put(b"".join(struct.pack("<3f", *p) for p in pts))
        nn = self.put(b"".join(struct.pack("<3f", *n) for n in normals)) if normals else 0
        mm = self.put(b"".join(struct.pack("<IIfII", col, 0, 0.0, tex, fl) for col, tex, fl in mats)) if mats else 0
        rows = []
        for kind, mat, meshes, uvs in meshsets:
            if kind in (0, 1):
                raw = b"".join(struct.pack(f"<{len(m)}H", *m) for m in meshes)
            else:
                raw = b"".join(struct.pack("<H", len(m) | (0x8000 if f else 0)) + struct.pack(f"<{len(m)}H", *m)
                               for f, m in meshes)
            mp = self.put(raw)
            up = self.put(b"".join(struct.pack("<hh", *uv) for uv in uvs)) if uvs else 0
            rows.append(struct.pack("<HHIIIII", kind << 14 | mat, len(meshes), mp, 0, 0, 0, up))
        ms = self.put(b"".join(rows))
        return self.put(struct.pack("<IIiIIHH4f", pp, nn, len(pts), ms, mm, len(meshsets), len(mats), 0, 0, 0, 1))

    def obj(self, model=0, pos=(0, 0, 0), flags=0x17, child=0, sib=0, ang=(0, 0, 0)) -> int:
        return self.put(struct.pack("<II3f3i3fII", flags, model, *pos, *ang, 1, 1, 1, child, sib))

    def link(self, node: int, child: int = 0, sib: int = 0):
        o = node - self.key
        if child:
            struct.pack_into("<I", self.d, o + 0x2C, child)
        if sib:
            struct.pack_into("<I", self.d, o + 0x30, sib)

    def exe(self) -> Exe:
        return Exe(bytes(self.d), self.key)


TEX = 0x00200000


def test_prs_round_trip_and_pvm_order():
    data = bytes(range(256)) * 8 + b"SONIC" * 100 + bytes(300)
    assert ninja.prs_decompress(ninja.prs_compress(data)) == data


def test_basic_model_tris_quads_strips_uvs_and_materials():
    im = Img()
    pts = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)]
    m = im.model(pts, [
        (0, 0, [[0, 1, 2]], [(0, 0), (255, 0), (0, 255)]),                      # one triangle, per-corner UVs
        (1, 1, [[0, 1, 2, 3]], []),                                              # one quad -> two triangles
        (3, 0, [(False, [0, 1, 2, 3]), (True, [1, 4, 3])], [(i * 10, 0) for i in range(7)]),   # strips, one flipped
    ], mats=[(0xFF808080, 3, TEX), (0xFF00FF00, 9, 0)])
    bm = S.basic_model(im.exe(), m)
    assert len(bm["points"]) == 5 and bm["normals"] is None
    assert bm["materials"][0]["tex"] == 3 and bm["materials"][1]["tex"] is None        # no USE_TEXTURE: colour only
    assert bm["materials"][1]["color"] == [0.0, 1.0, 0.0, 1.0]
    f = bm["faces"]
    assert [(mat, tuple(c[0] for c in cs)) for mat, cs in f] == [
        (0, (0, 1, 2)), (1, (0, 1, 2)), (1, (1, 3, 2)), (0, (0, 1, 2)), (0, (2, 1, 3)), (0, (4, 1, 3))]
    assert [c[1] for c in f[0][1]] == [[0, 0], [1, 0], [0, 1]]
    assert f[5][1][0] == (4, [50 / 255, 0.0])                       # flipped 2nd strip: (b, a, c), b = corner #5


def _humanoid():
    """SA1-shaped flat humanoid, in the game's frame (faces -X, left = +Z): root -> body; the body holds the torso
    mesh, the head (a mesh node under a neck), two 3-joint arms (shoulder y 1, elbow 0, wrist -1 + hand mesh) and two
    3-joint legs (hip y -1, knee -2.5, ankle -4 + shoe mesh)."""
    im = Img()
    tri = lambda c, s=0.3: im.model([(c[0] - s, c[1] - s, c[2]), (c[0] + s, c[1] - s, c[2]), (c[0], c[1] + s, c[2])],
                                    [(0, 0, [[0, 1, 2]], [])], mats=[(0xFFFFFFFF, 0, TEX)])
    root, body = im.obj(flags=0x07), im.obj(flags=0x07)
    im.link(root, child=body)
    torso = im.obj(im.model([(0, -1, 0.5), (0, -1, -0.5), (0, 1, 0), (0.3, 0.9, 0)],
                            [(1, 0, [[0, 1, 2, 3]], [])], mats=[(0xFFFFFFFF, 1, TEX)]))
    neck = im.obj(pos=(0, 1.5, 0), flags=0x06)
    head = im.obj(im.model([(0, 0, -0.5), (0, 0, 0.5), (0, 1.5, 0)], [(0, 0, [[0, 1, 2]], [])],
                           mats=[(0xFFFFFFFF, 2, TEX)]))
    im.link(neck, child=head)
    kids = [torso, neck]
    for z in (1.0, -1.0):                                   # arms
        sh, el, wr = im.obj(pos=(0, 1, z), flags=0x06), im.obj(pos=(0, -1, 0), flags=0x06), im.obj(pos=(0, -1, 0), flags=0x06)
        hand = im.obj(tri((0, -0.4, 0)))
        im.link(sh, child=el)
        im.link(el, child=wr)
        im.link(wr, child=hand)
        kids.append(sh)
    for z in (0.4, -0.4):                                   # legs
        hp, kn, an = im.obj(pos=(0, -1, z), flags=0x06), im.obj(pos=(0, -1.5, 0), flags=0x06), im.obj(pos=(0, -1.5, 0), flags=0x06)
        shoe = im.obj(tri((0, -0.5, 0)))
        im.link(hp, child=kn)
        im.link(kn, child=an)
        im.link(an, child=shoe)
        kids.append(hp)
    im.link(body, child=kids[0])
    for a, b in zip(kids, kids[1:]):
        im.link(a, sib=b)
    return im.exe(), root


def test_tree_bones_face_z_and_skinned_manifest(tmp_path):
    ex, root = _humanoid()
    t = S.Tree(ex, root, S.FACE_Z)
    assert len(t.bones) == 2 + 1 + 2 + 2 * 4 + 2 * 4
    W = t.world()
    sh_l = next(i for i, b in enumerate(t.bones) if b["parent"] == 1 and abs(W[i][1, 3] - 1) < 1e-6 and W[i][0, 3] > 0)
    assert np.allclose(W[sh_l][:3, 3], [1, 1, 0])               # game +Z (left) -> glTF +X after FACE_Z
    roles = t.body_roles()
    assert set(roles) == {"hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                          "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
    names = [b["name"] for b in t.bones]
    W = t.world()
    at = lambda r: W[names.index(roles[r])][:3, 3]
    assert roles["hip"] == "node001" and roles["chest"] == "chest"
    assert at("l_upper")[0] > 0 > at("r_upper")[0] and at("l_thigh")[0] > 0 > at("r_thigh")[0]
    assert [round(at(f"l_{k}")[1], 3) for k in ("upper", "fore", "hand")] == [1, 0, -1]
    assert [round(at(f"r_{k}")[1], 3) for k in ("thigh", "shin", "foot")] == [-1, -2.5, -4]
    assert np.allclose(at("chest"), [0, 0, 0])                  # halfway between the leg (-1) and shoulder (1) anchors
    ci = names.index("chest")
    assert {t.bones[names.index(roles[r])]["parent"] for r in ("l_upper", "r_upper")} == {ci}
    neck = t.bones[names.index(roles["head"])]["parent"]
    assert t.bones[neck]["parent"] == ci                        # the head hangs from the chest too (via its neck)
    torso = [c for tris in t.tris.values() for tri in tris for c in tri if c[2]["joints"][0][0] in (2, ci)]
    assert {c[2]["joints"][0][0] for c in torso if c[2]["pos"][1] > 0} == {ci}   # upper torso -> chest
    assert {c[2]["joints"][0][0] for c in torso if c[2]["pos"][1] < 0} == {2}
    # the re-parented skeleton keeps every joint where it was (world positions unchanged)
    before = S.Tree(ex, root, S.FACE_Z).world()
    after = t.world()
    assert all(np.allclose(before[i][:3, 3], after[i][:3, 3]) for i in range(len(before)))
    m = S.to_manifest(t, "synthetic", {"game": "test"}, [None] * 3)
    glb = tmp_path / "h.glb"
    glb.write_bytes(uap.to_glb(m, tmp_path))
    gl = C._load(glb)[0]
    assert len(gl["skins"][0]["joints"]) == len(t.bones)
    from gbox import crazy_taxi as ct
    segs = ct.donor_segments(glb, ct.resolve_roles(roles), roles)
    assert all(len(segs[p][2]) for p in ("koshi", "mune", "atama", "te_l", "te_r", "kakato_l", "kakato_r"))


def test_roles_refuse_a_tree_without_legs():
    im = Img()
    root = im.obj(im.model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, [[0, 1, 2]], [])], mats=[(0, 0, TEX)]))
    with pytest.raises(ValueError, match="leg"):
        S.Tree(im.exe(), root, S.FACE_Z).body_roles()


def test_overlay_key_from_the_pvm_table_and_from_pointer_clusters():
    key = 0x0C900000
    im = Img(key, 0x2000)
    name = im.put(b"SUPERSONIC\0\0")
    tl = im.put(struct.pack("<II", key + 0x1000, 73))
    im.put(struct.pack("<II", name, tl))                       # {char *name, NJS_TEXLIST *}
    blob = bytes(im.d)
    assert S.overlay_key(blob, "SUPERSONIC") == key
    im2 = Img(0x0CB00000, 0x2000)
    for i in range(40):                                        # pointers spread over the whole module
        im2.put(struct.pack("<I", 0x0CB00000 + 0x40 + (0x1FF0 - 0x40) * i // 39))
    assert S.overlay_key(bytes(im2.d)) == 0x0CB00000


def test_dedicated_registration_and_roster():
    sa1 = next(r for r in C.DEDICATED if r[0] == "sa1")
    assert sa1[1]("sonic adventure (usa)", "dreamcast") and sa1[1]("sonic adventure (japan)", "dreamcast")
    assert not sa1[1]("sonic adventure 2 (usa)", "dreamcast") and not sa1[1]("sonic adventure dx", "gamecube")
    assert not next(r for r in C.DEDICATED if r[0] == "sa2")[1]("sonic adventure (usa)", "dreamcast")
    ros = sa1[2]()
    assert [e["slug"] for e in ros] == ["sa1_sonic", "sa1_tails", "sa1_knuckles", "sa1_amy", "sa1_big", "sa1_e102",
                                        "sa1_super_sonic", "sa1_tikal"]
    assert all(e["kind"] == "character" for e in ros) and "sonic" not in {e["slug"] for e in ros}   # SA2 owns "sonic"
    assert next(e for e in ros if e["key"] == "e102")["name"] == "E-102 Gamma"


# ---------------------------------------------------------------- the owned disc

@pytest.fixture(scope="module")
def gdi():
    g = _gdi()
    if g is None:
        pytest.skip("owned Sonic Adventure (USA) GD-ROM not reachable (GBOX_SA1_GDI / cache / share)")
    return str(g)


EXPECT = {  # key: (source file, root, bones incl. chest, triangles)
    "sonic": ("1ST_READ.BIN", 0x8C1CE76C, 74, 1001), "tails": ("1ST_READ.BIN", 0x8C25F968, 69, 997),
    "knuckles": ("1ST_READ.BIN", 0x8C35B094, 74, 981), "amy": ("1ST_READ.BIN", 0x8C4C7C3C, 79, 1000),
    "big": ("1ST_READ.BIN", 0x8C52F298, 74, 1134), "e102": ("1ST_READ.BIN", 0x8C42CC34, 78, 970),
    "super_sonic": ("SONICADV/B_CHAOS7.PRS", 0x0C909D2C, 74, 1046),
    "tikal": ("SONICADV/TIKAL_PROG.PRS", 0x0CB09818, 104, 948),
}


@pytest.mark.parametrize("key", list(EXPECT))
def test_real_character_exports_rigged_textured_glb(gdi, key, tmp_path):
    from gbox import crazy_taxi as ct
    glb = S.export(gdi, str(tmp_path), key)
    man = json.loads((tmp_path / "manifest.json").read_text())
    src, root, bones, tris = EXPECT[key]
    assert man["source"]["files"][0] == src and man["source"]["root"] == f"0x{root:08X}"
    assert len(man["skeleton"]) == bones and sum(len(m["indices"]) // 3 for m in man["meshes"]) == tris
    tex = [m["texture"] for m in man["materials"] if m["texture"]]
    assert len(tex) >= 8 and all((tmp_path / t).is_file() for t in tex)
    roles = man["source"]["body_roles"]
    segs = ct.donor_segments(glb, ct.resolve_roles(roles), roles)
    assert all(len(s[2]) for s in segs.values()), {p: len(s[2]) for p, s in segs.items()}
    for a, b in (("te_l", "te_r"), ("kakato_l", "kakato_r"), ("momo_l", "momo_r")):
        assert len(segs[a][2]) and len(segs[b][2])
    gl = C._load(glb)[0]
    assert gl["images"] and gl["skins"][0]["joints"]
    h = 0
    for me in gl["meshes"]:
        for pr in me["primitives"]:
            a = gl["accessors"][pr["attributes"]["POSITION"]]
            h = max(h, a["max"][1])
    assert h > 0
