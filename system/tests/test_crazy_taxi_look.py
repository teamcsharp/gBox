"""gbox.crazy_taxi_look: the v2 Crazy Taxi driver writer (donor textures in a per-driver atlas, full-detail parts that
grow, per-part frames). Synthetic: archives that grow, .tex and atlas round trips, the growable part encoder and its
validator, strips, the frame and prop rules. Owned disc (GBOX_CT_ISO + a donor library entry in GBOX_CT_DONOR, e.g.
D:/gBox/research/lib/sa1_sonic): a whole driver written and validated, and the memory it adds."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import crazy_taxi as ct
from gbox import crazy_taxi_look as L

ISO = Path(os.environ.get("GBOX_CT_ISO", "/home/ehm_eckx/gbox-cache/modbase/bc02bb68790ce2e7/Crazy Taxi (USA).iso"))
DONOR = Path(os.environ.get("GBOX_CT_DONOR", "/home/ehm_eckx/gbox-cache/characters/sa1_sonic"))

BOX = [(x, y, z) for x in (0.0, 4.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
TRIS = [t for a, b, c, d in QUADS for t in ((a, b, c), (a, c, d))]


def _list(tris, vat=2):
    dl = bytearray(bytes([0x90 | vat]) + struct.pack(">H", 3 * len(tris)))
    for t in tris:
        for i in t:
            dl += struct.pack(">3H", i, i, 0)
    return bytes(dl + b"\0" * ((0x20 - len(dl) % 0x20) % 0x20))


def _part(groups=(0, 0, 1), tex=("white.tex", "TY_plyrA_face1.tex", "TY_plyrA_hada1.tex")) -> bytes:
    """A driver-style part: header, POS/NRM/TEX0, a state record + one draw record per `groups` entry (its draw
    group), VAT 2 lists, a texture table of 0x2c-byte entries."""
    centre = (2.0, 0.0, 0.0)
    local = np.asarray(BOX, float) - centre
    radius = float(np.linalg.norm(local, axis=1).max())
    scale = radius * 256 / 32767
    V, first = len(BOX), 0x120
    nrec = 1 + len(groups)
    mat = 0x200
    dl_base = (mat + 0x24 * nrec + 0x1F) & ~0x1F
    lists = [_list(TRIS[4 * k:4 * k + 4]) for k in range(len(groups))]
    tex_off = dl_base + sum(len(x) for x in lists)
    b = bytearray(tex_off + 0x2C * len(tex) + 0x10)
    struct.pack_into(">ff", b, 0, 1.0, radius)
    struct.pack_into(">I", b, 0x10, len(tex))
    struct.pack_into(">3I", b, 0x14, 1 + sum(1 for g in groups if g == 0), sum(1 for g in groups if g == 1), 0)
    struct.pack_into(">3f", b, 0x20, *centre)
    struct.pack_into(">3f", b, 0x2C, scale, scale, scale)
    struct.pack_into(">II", b, 0x38, 1, 2)
    struct.pack_into(">8I", b, 0x60, 0, 6, 6, 0, 0, 4, 0, 0)
    pos_off, nrm_off, tex0 = first, first + 6 * V, first + 12 * V
    struct.pack_into(">I", b, 0xCC, pos_off)
    struct.pack_into(">I", b, 0xD0, nrm_off)
    struct.pack_into(">I", b, 0xDC, tex0)
    struct.pack_into(">4I", b, 0x110, mat, first, dl_base, tex_off)
    for i, p in enumerate(local):
        struct.pack_into(">3h", b, pos_off + 6 * i, *(int(round(c * 256 / scale)) for c in p))
        struct.pack_into(">3h", b, nrm_off + 6 * i, *(int(round(c * 16384)) for c in p / np.linalg.norm(p)))
    struct.pack_into(">2h", b, tex0, 64, 64)
    struct.pack_into(">I", b, mat, L.STATE_RECORD)
    at = dl_base
    order = sorted(range(len(groups)), key=lambda k: groups[k])
    for slot, k in enumerate(order):
        rec = mat + 0x24 * (1 + slot)
        struct.pack_into(">9I", b, rec, at, len(lists[k]), 1 + k % (len(tex) - 1), 0xC, 0xD, 0xE, 3, 0, 0x617FB2FF)
        b[at:at + len(lists[k])] = lists[k]
        at += len(lists[k])
    for i, n in enumerate(tex):
        b[tex_off + 0x2C * i:tex_off + 0x2C * i + len(n)] = n.encode()
    return bytes(b + b"\0" * ((0x20 - len(b) % 0x20) % 0x20))


def _canon(t):
    k = min(range(3), key=lambda i: t[i])
    return t[k:] + t[:k]


# ------------------------------------------------------------------------------------------- archives and textures

def test_archive_round_trip_alignment_and_growth():
    entries = [("a.tex", b"\1" * 0x40), ("b.shp", b"\2" * 0x60), ("c.shp", b"\3" * 0x20)]
    data = L.write_archive(entries)
    assert L.archive_data_start(3) == 0xE0 and len(data) == 0xE0 + 0xC0     # 0x10 + 3*0x44 = 0xdc -> 0xe0
    assert L.read_archive(data) == entries
    # polDC0.all's 1586 records: the loader's (count * 0x44 + 0x2f) & ~0x1f puts the first blob at 0x1a560
    assert L.archive_data_start(1586) == 0x1A560 and L.archive_data_start(454) == 0x78C0
    grown = L.replace_entries(data, {"b.shp": b"\4" * 0x400, "c.shp": b""})
    assert L.read_archive(grown) == [("a.tex", b"\1" * 0x40), ("b.shp", b"\4" * 0x400), ("c.shp", b"")]
    with pytest.raises(ValueError):
        L.replace_entries(data, {"nope.shp": b""})
    with pytest.raises(ValueError):
        L.write_archive([("x", b"\0" * 0x21)])


def test_tex_round_trip_flat_cells_are_exact():
    img = np.zeros((16, 32, 4), np.uint8)
    img[..., 3] = 255
    img[:8, :8, :3] = (8, 66, 189)            # every value on the RGB565 grid survives CMPR exactly
    img[:8, 8:16, :3] = (255, 255, 255)
    img[8:, :, :3] = (231, 28, 33)
    tmpl = struct.pack(">7I", 64, 64, 0, L.GX_CMPR, 1, 1, 0) + b"\0" * 0x44 + b"\0" * 0x800
    blob = L.make_tex(img, tmpl)
    info = L.tex_info(blob)
    assert (info["w"], info["h"], info["fmt"], info["wrap_s"], info["mip"]) == (32, 16, L.GX_CMPR, 1, 0)
    assert len(blob) % 0x20 == 0 and len(blob) == 0x60 + L.tex_data_size(32, 16, L.GX_CMPR)
    out = L.tex_rgba(blob)
    for (y, x), want in (((2, 2), (8, 66, 189)), ((4, 12), (255, 255, 255)), ((12, 20), (231, 28, 33))):
        assert np.abs(out[y, x, :3].astype(int) - want).max() <= 4
    rgba8 = L.make_tex(img, None, L.GX_RGBA8)
    assert np.array_equal(L.tex_rgba(rgba8)[..., :3], img[..., :3])
    with pytest.raises(ValueError):
        L.make_tex(np.zeros((12, 12, 4), np.uint8))


def test_atlas_maps_every_material_onto_its_own_texels():
    rng = np.random.default_rng(3)
    stripes = np.zeros((16, 16, 4), np.uint8)
    stripes[..., 3] = 255
    stripes[:, :8, :3] = (255, 0, 0)
    stripes[:, 8:, :3] = (0, 0, 255)
    mats = [{"tex": None, "colour": (0, 255, 0, 255)},
            {"tex": stripes, "colour": (255, 255, 255, 255)},
            {"tex": np.full((8, 8, 4), 200, np.uint8), "colour": (255, 128, 255, 255)},      # uniform -> flat
            {"tex": rng.integers(0, 255, (32, 32, 4), dtype=np.uint8), "colour": (255, 255, 255, 255)}]
    ranges = {0: (0, 0, 0, 0), 1: (0.0, 0.0, 2.0, 1.0), 2: (0.1, 0.1, 0.9, 0.9), 3: (0.0, 0.0, 1.0, 1.0)}
    img, regs = L.build_atlas(mats, ranges)
    H, W = img.shape[:2]
    assert regs[0].flat and regs[2].flat and not regs[1].flat and regs[1].tiles_u == 2
    assert regs[2].colour == (200, 100, 200)
    tex = L.tex_rgba(L.make_tex(img))

    def sample(uv):
        q = np.rint(np.asarray(uv) * L.UV_SCALE) / L.UV_SCALE      # the TEX0 s16/128 grid the game reads
        return tex[int(q[1] * H), int(q[0] * W), :3].astype(int)

    assert np.abs(sample(L.atlas_uv(regs[0], [(0.3, 0.7)], W, H)[0]) - (0, 255, 0)).max() <= 4
    assert np.abs(sample(L.atlas_uv(regs[2], [(0.5, 0.5)], W, H)[0]) - (200, 101, 200)).max() <= 6
    # the stripes repeat over the two UV tiles the material spans
    for u, want in ((0.25, (255, 0, 0)), (0.75, (0, 0, 255)), (1.25, (255, 0, 0)), (1.75, (0, 0, 255))):
        assert np.abs(sample(L.atlas_uv(regs[1], [(u, 0.5)], W, H)[0]) - want).max() <= 8
    # no two regions (gutters included) overlap
    boxes = [(r.x - r.gutter, r.y - r.gutter, r.x + r.w + r.gutter, r.y + r.h + r.gutter) for r in regs.values()]
    for i, a in enumerate(boxes):
        assert 0 <= a[0] and 0 <= a[1] and a[2] <= W and a[3] <= H
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


# ------------------------------------------------------------------------------------------- the part encoder

def test_stripify_keeps_every_triangle_and_its_winding():
    rng = np.random.default_rng(0)
    grid = [(r * 9 + c, r * 9 + c + 1, (r + 1) * 9 + c) for r in range(8) for c in range(8)] + \
           [(r * 9 + c + 1, (r + 1) * 9 + c + 1, (r + 1) * 9 + c) for r in range(8) for c in range(8)]
    tris = [tuple(int(x) for x in t) for t in rng.permutation(np.asarray(grid))]
    strips, singles = L.stripify(tris)
    got = []
    for s in strips:
        for n in range(len(s) - 2):
            got.append((s[n], s[n + 1], s[n + 2]) if n % 2 == 0 else (s[n + 1], s[n], s[n + 2]))
    got += singles
    assert sorted(map(_canon, got)) == sorted(map(_canon, tris))
    assert sum(len(s) for s in strips) + 3 * len(singles) < 3 * len(tris) * 0.75      # strips pay off


def test_encode_part_grows_dedupes_and_validates():
    template = _part(groups=(0, 1))
    rng = np.random.default_rng(1)
    n = 600                                         # far more than the stock arrays hold
    pos = rng.normal(0, 3, (n, 3)) + (2, 0, 0)
    nrm = rng.normal(0, 1, (n, 3))
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    uv = rng.random((n, 2))
    pos[300:] = pos[:300]                           # repeated positions are stored once
    tris = [tuple(int(x) for x in rng.choice(n, 3, replace=False)) for _ in range(900)]
    names = ["white.tex", "TY_plyrA_face1.tex", "TY_plyrA_face1.tex"]
    scale = L.fit_scale(template, pos)
    blob = L.encode_part(template, pos, nrm, uv, [tris, []], name="MP_YH_plyrA_atama.shp", tex_index=[1, 1],
                         tex_names=names, scale=scale, material_colour=0xFFFFFFFF)
    assert len(blob) > len(template) and len(blob) % 0x20 == 0
    st = L.check_part(template, blob, "x", {"white.tex", "TY_plyrA_face1.tex"})
    assert st["triangles"] == 900 + 1               # the empty record draws one zero-area triangle
    counts = L.array_counts(blob)
    assert counts["pos"] < 300 + 6 and counts["tex"] <= n + 8       # array_counts includes the 32-byte padding
    assert L.texture_names(blob) == names
    draws = [r for r in L.records(blob) if not r.state]
    assert [r.group for r in draws] == [0, 1] and all(r.vat == 2 and r.tex == 1 for r in draws)
    assert all(struct.unpack_from(">I", blob, r.at + 0x20)[0] == 0xFFFFFFFF for r in draws)
    assert abs(struct.unpack_from(">f", blob, 0x2C)[0] - scale) < 1e-6 * scale       # f32
    assert abs(struct.unpack_from(">f", blob, 4)[0] - scale * 32767 / 256) < 1e-4
    # decoded triangles are the input triangles, same winding, within quantisation
    sh = ct.read_shape(blob, "x")
    P = np.asarray(sh.positions(8))
    attrs = L.attrs_of(blob)
    got = sorted(_canon(tuple(tuple(np.round(P[c["pos"]], 1)) for c in t))
                 for t in ct.decode_dl(blob[draws[0].dl_off:draws[0].dl_off + draws[0].dl_size], attrs))
    want = sorted(_canon(tuple(tuple(np.round(pos[i], 1)) for i in t)) for t in tris)
    assert len(got) == len(want)
    assert sum(a == b for a, b in zip(got, want)) > 0.95 * len(want)
    UVd = np.asarray(sh.uv) * 2                     # read_shape divides by 256; TEX0 is s16 / 128
    assert UVd.min() >= -1e-6 and UVd.max() <= 1 + 1e-6


def test_check_part_rejects_what_would_hang_or_garble_the_gpu():
    template = _part(groups=(0, 1))
    pos = np.asarray(BOX, float)
    nrm = np.tile([0, 1.0, 0], (len(BOX), 1))
    uv = np.zeros((len(BOX), 2))
    blob = L.encode_part(template, pos, nrm, uv, [TRIS, []], name="p")
    L.check_part(template, blob, "p", {"white.tex", "TY_plyrA_face1.tex", "TY_plyrA_hada1.tex"})
    with pytest.raises(ValueError, match="texture"):                     # the fix-up loops forever on this
        L.check_part(template, blob, "p", {"white.tex"})
    r = [x for x in L.records(blob) if not x.state][0]
    bad = bytearray(blob)
    bad[r.dl_off] = 0x90                                                 # VAT 0 instead of the stock VAT 2
    with pytest.raises(ValueError, match="VAT"):
        L.check_part(template, bytes(bad), "p")
    bad = bytearray(blob)
    struct.pack_into(">H", bad, r.dl_off + 3, 0x7FFF)                     # a position index past the array
    with pytest.raises(ValueError, match="indexes"):
        L.check_part(template, bytes(bad), "p")
    bad = bytearray(blob)
    struct.pack_into(">I", bad, r.at, r.dl_off + 1)                       # a pointer into the middle of a list
    with pytest.raises(ValueError):
        L.check_part(template, bytes(bad), "p")
    bad = bytearray(blob)
    struct.pack_into(">I", bad, 0x3C, 3)                                  # the header's VAT pair changed
    with pytest.raises(ValueError, match="header"):
        L.check_part(template, bytes(bad), "p")
    with pytest.raises(ValueError, match="range"):                       # no silent wrap past the s16 range
        L.encode_part(template, pos * 100, nrm, uv, [TRIS, []], name="p")


def test_v1_writer_and_its_validator_still_hold():
    """The same-size v1 path (pedestrians, fares) is untouched: encode_shape still passes gbox.crazy_taxi.check_written
    on a part that the record parser and the v2 validator also accept."""
    template = _part(groups=(0, 0))
    rng = np.random.default_rng(2)
    pos = np.asarray(BOX, float) + rng.normal(0, 0.01, (len(BOX), 3))
    blob = ct.encode_shape(template, pos, pos / np.linalg.norm(pos, axis=1, keepdims=True), TRIS[:8], "v1",
                           chunks=[TRIS[:4], TRIS[4:8]])
    ct.check_written(template, blob, "v1")
    L.check_part(template, blob, "v1")


# ------------------------------------------------------------------------------------------- frames and props

def _stick_donor(prop: bool = False) -> L.Donor:
    """A stick figure facing +Z: hips, chest, head, arms hanging, legs with a shoe joint below the 'foot' role joint
    (the SA1 layout), each joint carrying a small box; optionally a big prop held 6 forearms from the right wrist."""
    J = {"hip": (0, 0, 0), "chest": (0, 0.1, 0), "head": (0, 1.0, 0),
         "l_upper": (0.6, 0.8, 0), "l_fore": (0.6, 0.3, 0), "l_hand": (0.6, -0.2, 0),
         "r_upper": (-0.6, 0.8, 0), "r_fore": (-0.6, 0.3, 0), "r_hand": (-0.6, -0.2, 0),
         "l_thigh": (0.3, -0.3, 0), "l_shin": (0.3, -1.3, 0), "l_foot": (0.3, -2.0, 0),
         "r_thigh": (-0.3, -0.3, 0), "r_shin": (-0.3, -1.3, 0), "r_foot": (-0.3, -2.0, 0),
         "l_ankle": (0.3, -2.4, 0), "l_toe": (0.3, -2.6, 0.5), "r_ankle": (-0.3, -2.4, 0), "r_toe": (-0.3, -2.6, 0.5)}
    names = list(J)
    parent = {"hip": -1, "chest": "hip", "head": "chest", "l_upper": "chest", "l_fore": "l_upper",
              "l_hand": "l_fore", "r_upper": "chest", "r_fore": "r_upper", "r_hand": "r_fore", "l_thigh": "hip",
              "l_shin": "l_thigh", "l_foot": "l_shin", "r_thigh": "hip", "r_shin": "r_thigh", "r_foot": "r_shin",
              "l_ankle": "l_foot", "l_toe": "l_ankle", "r_ankle": "r_foot", "r_toe": "r_ankle"}
    P, T, O, M = [], [], [], []
    owners = [n for n in names if n not in ("l_toe", "r_toe")]
    for j, n in enumerate(names):
        if n not in owners:
            continue
        c = np.asarray(J[n], float) + ((0, 0, 0.12) if n.endswith("ankle") else (0, 0, 0))
        base = len(P)
        for dx in (-0.05, 0.05):
            for dy in (-0.05, 0.05):
                for dz in (-0.05, 0.05):
                    P.append(c + (dx, dy, dz))
                    O.append(j)
        for a, b, cc, d in QUADS:
            T += [(base + a, base + b, base + cc), (base + a, base + cc, base + d)]
            M += [0, 0]
    if prop:
        j = names.index("r_hand")
        base = len(P)
        for k in range(4):
            P.append(np.asarray(J["r_hand"]) + (0.1 * k, -3.0, 0.1 * (k % 2)))
            O.append(j)
        T += [(base, base + 1, base + 2), (base + 1, base + 3, base + 2)]
        M += [1, 1]
    roles = {r: names.index(r) for r in names[:15]}
    part_role = ct.resolve_roles({r: r for r in roles})
    d = L.Donor(np.asarray(P, float), np.tile([0, 1.0, 0], (len(P), 1)), np.zeros((len(P), 2)), np.asarray(T),
                np.asarray(M), np.asarray(O), [{"tex": None, "colour": (255, 0, 0, 255)},
                                              {"tex": None, "colour": (0, 0, 255, 255)}],
                np.asarray([J[n] for n in names], float),
                [names.index(parent[n]) if parent[n] != -1 else -1 for n in names],
                {p: roles[r] for p, r in part_role.items()})
    d.fwd = L.facing(d)
    return d


def _measures():
    m = {k: 1.0 for k in ("hips", "chest", "chest_width", "chest_depth", "head_height")}
    m["head_top"] = 1.0
    for s in "lr":
        m.update({f"thigh_{s}": 4.0, f"shin_{s}": 4.0, f"sole_{s}": 1.0, f"upper_{s}": 2.0, f"fore_{s}": 2.5,
                  f"hand_{s}": 2.0})
    m["legs"] = 9.0
    m["chest"] = 5.0
    m["hips"] = 1.5
    m["chest_width"] = 3.4
    return m


def test_frames_follow_the_in_game_axes():
    d = _stick_donor()
    assert d.fwd.tolist() == [0.0, 0.0, 1.0]                 # toes point +Z
    assert L.ankle_joint(d, d.role_joint["kakato_l"]) == 15  # the shoe joint below the 'foot' role joint
    po = L.assign_parts(d)
    maps, info = L.part_maps(d, po, _measures())
    J = d.joints
    F, U = np.array([0, 0, 1.0]), np.array([0, 1.0, 0])
    R = np.cross(F, U)                                        # the character's right (-X here)

    def axis(part, v):
        return maps[part].A @ v / np.linalg.norm(maps[part].A @ v)

    for p in ("koshi", "mune", "atama", "kata_l", "ude_r", "momo_l", "sune_r", "kakato_l", "te_r"):
        assert axis(p, R)[2] > 0.99, p                        # z is the character's right in every part
    assert axis("mune", U)[0] > 0.99 and axis("koshi", U)[0] < -0.99     # mune up from the waist, koshi down
    assert axis("atama", F)[0] > 0.99 and axis("atama", U)[1] > 0.99     # face along x, crown along y
    assert axis("kakato_l", F)[1] > 0.99 and axis("kakato_l", U)[0] < -0.99
    for p in ("momo_l", "sune_l", "kata_r", "ude_r"):
        assert axis(p, -U)[0] > 0.99 and axis(p, F)[1] > 0.99, p       # bone down along x, forward along y
    # bones keep their joints: the knee lands one thigh length down the thigh's x, the elbow one upper arm down
    assert np.allclose(maps["momo_l"].points([J[d.role_joint["sune_l"]]])[0], (4.0, 0, 0), atol=1e-6)
    assert np.allclose(maps["kata_r"].points([J[d.role_joint["ude_r"]]])[0], (2.0, 0, 0), atol=1e-6)
    # every map is a proper rotation times a positive scale, so the winding rule is global
    assert all(np.linalg.det(m.A) > 0 for m in maps.values())
    assert info["g"] > 0 and info["head"] <= 1.0


def test_held_props_are_dropped_and_gloves_kept():
    d = _stick_donor(prop=True)
    po = L.assign_parts(d)
    assert (po[d.mat == 1] == "").all()                       # the far prop rides nothing
    assert (po == "te_r").sum() == 12                         # the hand's own box stays
    assert set(po[d.mat == 0]) >= {"koshi", "atama", "te_l", "te_r", "kakato_l", "kakato_r", "sune_l"}


# ------------------------------------------------------------------------------------------- owned disc

def _owned():
    if not ISO.exists() or not (DONOR / "meta.json").exists():
        pytest.skip("owned Crazy Taxi ISO (GBOX_CT_ISO) and a donor (GBOX_CT_DONOR) needed")
    from gbox.gcdisc import GCDisc
    disc = GCDisc(ISO)
    return disc.read(ct.BANK), disc.read(L.TEXBANK), json.loads((DONOR / "meta.json").read_text())


def test_owned_disc_driver_is_written_whole_and_fits_the_heap():
    bank, tex, meta = _owned()
    nb, nt, rep = L.write_driver(bank, tex, DONOR / meta["model"], meta["rig"]["roles"], "A")
    names = {n for n, _ in L.read_archive(nt)} | {"white.tex"}
    old, new = dict(L.read_archive(bank)), dict(L.read_archive(nb))
    assert list(old) == list(new)                             # names and order kept
    changed = [n for n in old if old[n] != new[n]]
    assert changed and all(n.startswith("MP_YH_plyrA_") for n in changed)
    for n in changed:
        L.check_part(old[n], new[n], n, names)
        assert L.texture_names(new[n])[1:] == [L.ATLAS["A"]] * (len(L.texture_names(new[n])) - 1)
    assert rep["triangles"] >= 0.9 * rep["donor_triangles"]
    # a 256x256 CMPR atlas, and the bank + textures grow far less than the ~400 KB the game is known to absorb
    # (v2a's unwelded triangle lists added 723 KB and the attract demo's malloc of recAdvAC.bin returned NULL)
    assert rep["atlas"]["size"][0] <= 512
    assert (len(nb) - len(bank)) + (len(nt) - len(tex)) < 64 * 1024
    atlas = L.tex_rgba(dict(L.read_archive(nt))[L.ATLAS["A"]])
    assert atlas.shape[:2] == tuple(reversed(rep["atlas"]["size"]))
    others = {n: b for n, b in L.read_archive(nt) if n != L.ATLAS["A"]}
    assert all(dict(L.read_archive(tex))[n] == b for n, b in others.items())   # shared textures untouched
