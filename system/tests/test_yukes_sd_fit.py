"""SmackDown! 2 writer fit (#603, Toni "a bit mangled"): the donor must become one welded mesh per slot chunk with every
vertex on its own bone, like the stock wrestlers, not a closed-off shell per bone that tears open at every joint when
the wrestler moves. Synthetic: a stock-shaped template EMD (The Rock's chunk/bone layout) and a tube-built donor."""
import json
import struct

import numpy as np

from gbox import yukes_sd as y

# The Rock's first-variant chunks: [(bone, vertices)], primitives (read from ED1H/ED1B/ED1L.PAC group 0)
ROCK = {"ED1H.PAC": [([(3, 8), (4, 94)], 104)],
        "ED1B.PAC": [([(0, 10), (1, 12), (2, 10), (3, 8), (5, 5), (12, 5)], 39),
                     ([(1, 2), (2, 2), (5, 5), (6, 19), (7, 7), (8, 6), (9, 3), (10, 10)], 54),
                     ([(8, 6), (11, 42)], 49),
                     ([(1, 2), (2, 2), (12, 5), (13, 19), (14, 7), (15, 6), (16, 3), (17, 10)], 52),
                     ([(15, 6), (18, 42)], 50)],
        "ED1L.PAC": [([(19, 14), (20, 3), (21, 17), (22, 9), (23, 10), (24, 8)], 59),
                     ([(0, 39), (19, 6), (20, 3), (25, 14), (26, 3), (27, 17), (28, 9), (29, 10), (30, 8)], 109)]}


def _emd(chunks, room: int = 3) -> dict:
    """room: primitive multiplier standing in for the variant chunks (faces, hand poses) the real EMDs also hold."""
    blobs = []
    for groups, nprims in chunks:
        nprims *= room
        gs = [(b, [(i, b, 0, 0, 0, 4096) for i in range(n)]) for b, n in groups]
        nv = sum(n for _b, n in groups)
        tris = [((k % nv, (k + 1) % nv, (k + 2) % nv), ((0, 0), (1, 0), (0, 1))) for k in range(nprims)]
        blobs.append(y.chunk_build(0x7FC0, 0x9, gs, tris))
    head = b"EMD " + struct.pack("<6H", 0x10, 32, 0x110, 0, 8, len(blobs)) + bytes(32 * 8)
    slots = b"".join(struct.pack("<HH", k, 1) if k < len(blobs) else bytes(4) for k in range(8))
    desc, data = b"", b""
    for c, work in blobs:
        c += bytes((-len(c)) % 4)
        desc += struct.pack("<4H", len(data) // 4, len(c) // 4, 1, work)
        data += c
    return y.emd_parse(head + slots + desc + data)


def _tmpl() -> dict:
    return {f: {"emd": _emd(ch), "tims": []} for f, ch in ROCK.items()}


def _tube(path, ring_bones, radius, sides=8):
    """Rings along a polyline (one per path point) -> P, F, J (a closed-side tube, open at both ends)."""
    P, J, F = [], [], []
    path = np.asarray(path, float)
    for i, (c, b) in enumerate(zip(path, ring_bones)):
        d = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        d /= np.linalg.norm(d)
        b1 = np.cross(d, [0, 0, 1.0])
        b1 /= np.linalg.norm(b1)
        b2 = np.cross(d, b1)
        for k in range(sides):
            a = 2 * np.pi * k / sides
            P.append(c + radius * (np.cos(a) * b1 + np.sin(a) * b2))
            J.append(b)
    for i in range(len(path) - 1):
        for k in range(sides):
            a, b, c, d = i * sides + k, i * sides + (k + 1) % sides, (i + 1) * sides + k, (i + 1) * sides + (k + 1) % sides
            F += [(a, b, c), (b, d, c)]
    return np.array(P), np.array(F), np.array(J)


def _lerp(a, b, n):
    return [a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False)]


def _donor(T):
    """Left arm (upper 6, fore 8, hand 11), torso (the retarget's pelvis 0 / chest 2 by height), left leg (19, 21, 23)."""
    parts = []
    hand_end = T[11] + (T[11] - T[8]) * 0.4
    arm = _lerp(T[6], T[8], 3) + _lerp(T[8], T[11], 3) + _lerp(T[11], hand_end, 2) + [hand_end]
    parts.append(_tube(arm, [6] * 3 + [8] * 3 + [11] * 3, 35))
    bottom, top = T[0] - [0, 120, 0], T[3]
    torso = _lerp(bottom, top, 6) + [top]
    split = T[0][1] + 0.5 * (T[2][1] - T[0][1])
    parts.append(_tube(torso, [0 if p[1] < split else 2 for p in torso], 120))
    leg = _lerp(T[19], T[21], 3) + _lerp(T[21], T[23], 3) + [T[23]]
    parts.append(_tube(leg, [19] * 3 + [21] * 3 + [23], 60))
    P, F, J, base = [], [], [], 0
    for p, f, j in parts:
        P.append(p); F.append(f + base); J.append(j)
        base += len(p)
    return np.concatenate(P), np.concatenate(F), np.concatenate(J)


def _boundary_edges(P, F) -> int:
    _u, inv = np.unique(np.round(np.asarray(P, float), 1), axis=0, return_inverse=True)
    Fw = inv.reshape(-1)[np.asarray(F)]
    e = np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), 1)
    _e, cnt = np.unique(e, axis=0, return_counts=True)
    return int((cnt == 1).sum())


def _cut(tmp_path):
    T = y.target_skeleton(None)["T"]
    P, F, J = _donor(T)
    N = P - P.mean(0)
    mats = [{"tex": None, "color": (200, 200, 200, 255)}]
    geo, rep = y.cut_slots(P, N, np.zeros((len(P), 2)), F, np.zeros(len(F), int), J, T, _tmpl(), mats, tmp_path, None,
                           lambda p, m: None)
    return P, F, geo, rep


def _drawn(geo, W):
    """Every slot chunk as the game draws it (slot_chunk's bone-local vertices through the bone matrices W)."""
    Ps, Fs, base = [], [], 0
    for s, g in geo.items():
        corners = [(list(q), [(0, 0)] * 3) for q in g["F"]]
        groups, tris = y.slot_chunk(g, corners, y.rest_world(None), 0)
        for b, vs in groups:
            R, t = W[b]
            Ps += [y.G @ (R @ np.array(v[:3], float) + t) for v in vs]
        Fs += [[base + i for i in idx] for idx, _uv in tris]
        base += sum(len(vs) for _b, vs in groups)
    return np.array(Ps), np.array(Fs)


def _bend(W, bone, deg):
    """Rotate a bone's subtree about its own origin (an elbow bend)."""
    t = np.radians(deg)
    Q = np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
    kids = {bone}
    for k in range(31):
        if y.PARENT[k] in kids:
            kids.add(k)
    piv = W[bone][1].copy()
    return [(Q @ R, Q @ (tt - piv) + piv) if k in kids else (R, tt) for k, (R, tt) in enumerate(W)]


def test_joints_are_spanned_inside_one_chunk(tmp_path):
    _P, _F, geo, rep = _cut(tmp_path)
    spans = lambda s: {tuple(sorted(set(geo[s]["bone"][q].tolist()))) for q in geo[s]["F"]}   # noqa: E731
    assert (6, 8) in spans("larm")                         # the elbow stretches between the upper arm and forearm
    assert (8, 11) in spans("lhand")                       # the wrist between the forearm and the hand
    assert (19, 21) in spans("lleg")                       # the knee
    assert any(len(b) > 1 for b in spans("torso"))         # the waist bands
    assert all(v["dropped"] == 0 for k, v in rep.items() if k.startswith("slot_"))


def test_a_point_copied_into_two_chunks_has_one_bone(tmp_path):
    _P, _F, geo, _rep = _cut(tmp_path)
    seen = {}
    for g in geo.values():
        for p, b in zip(np.round(g["P"], 1), g["bone"]):
            assert seen.setdefault(tuple(p), int(b)) == int(b)


def test_no_seams_open_when_the_joints_bend(tmp_path):
    """The defect: per-bone shells are closed at rest only because their rings coincide; bending the elbow and knee
    pulls them apart (new open edges). One mesh per chunk keeps exactly the donor's own open edges (the tube ends)."""
    P, F, geo, _rep = _cut(tmp_path)
    W0 = y.rest_world(None)
    rest = _drawn(geo, W0)
    bent = _drawn(geo, _bend(_bend(_bend(W0, 8, -90), 21, 70), 1, 25))
    assert _boundary_edges(*rest) == _boundary_edges(P, F) == 3 * 2 * 8
    assert _boundary_edges(*bent) == _boundary_edges(P, F)


def test_per_bone_shells_tear_open_control():
    """Control for the test above: the first writer's cut (each face to its majority bone, every shell's vertices on
    that one bone) is closed at rest and tears open at the elbow, wrist, knee and waist once they bend."""
    T = y.target_skeleton(None)["T"]
    P, F, J = _donor(T)
    vb = y.vertex_bones(P, J, T)
    fb = np.array([np.bincount(vb[f]).argmax() for f in F])
    shells = {}
    for b in sorted(set(fb.tolist())):
        used, Fl = np.unique(F[fb == b], return_inverse=True)
        shells[b] = {"P": P[used], "N": P[used], "F": Fl.reshape(-1, 3), "bone": np.full(len(used), b)}
    W0 = y.rest_world(None)
    rest = _drawn(shells, W0)
    bent = _drawn(shells, _bend(_bend(_bend(W0, 8, -90), 21, 70), 1, 25))
    assert _boundary_edges(*rest) == 48
    assert _boundary_edges(*bent) > 48 + 4 * 8


def test_resolve_bones_moves_one_corner_up_the_chain():
    allowed = y.slot_allowed(_tmpl())
    F = np.array([[0, 1, 2], [3, 4, 5]])
    vb = np.array([1, 19, 19, 4, 3, 2])                    # waist + thigh; head + neck + chest: no chunk binds either
    out = y.resolve_bones(F, vb, allowed)
    assert out.tolist() == [0, 19, 19, 3, 3, 2]            # the waist corner onto the pelvis, the head corner on the neck
    assert all(any(set(out[f].tolist()) <= a for a in allowed.values()) for f in F)
    # a corner moved onto a helper bone (a clavicle has no slot of its own) still finds its chunk (Eggman: KeyError 5)
    assert y.face_slots(np.array([[5, 5, 2], [5, 5, 6], [19, 0, 0], [11, 8, 8]]), allowed).tolist() == \
        ["torso", "larm", "rleg", "lhand"]


def test_emd_size_is_what_build_entry_writes(tmp_path):
    _P, _F, geo, _rep = _cut(tmp_path)
    tmpl = _tmpl()
    W = y.rest_world(None)
    for f in y.PART_FILES:
        emd = tmpl[f]["emd"]
        new, counts = {}, {}
        for i, ch in y._first_chunks(emd):
            s = y.chunk_slot(ch)
            g = geo.get(s)
            groups, tris = y.slot_chunk(g, [(list(q), [(0, 0)] * 3) for q in g["F"]] if g else [], W, y.SLOT_BONES[s][0])
            new[i] = y.chunk_build(ch["clut"], ch["tpage"], *y._like(ch, groups, tris), keep_empty=True)
            counts[s] = ({b: len(v) for b, v in groups}, len(tris))
        built = y.emd_build(emd, new)
        assert y.emd_size(emd, counts) == len(built) <= len(emd["raw"])


def test_slot_budgets_fill_each_file_room():
    tmpl = _tmpl()
    caps = y.slot_budgets(tmpl)
    for f in y.PART_FILES:
        emd = tmpl[f]["emd"]
        counts = {}
        for s in y.FILE_SLOTS[f]:                          # the slot's vertices over its own bones
            bs = y.SLOT_BONES[s]
            counts[s] = ({b: caps[s][0] // len(bs) + (k == 0) * (caps[s][0] % len(bs)) for k, b in enumerate(bs)}, caps[s][1])
        assert 0.8 * len(emd["raw"]) < y.emd_size(emd, counts) <= len(emd["raw"])
    assert all(v <= 128 for v, _f in caps.values())


def test_old_fits_are_rebuilt(tmp_path):
    (tmp_path / ".gbox-mod.json").write_text(json.dumps({"name": "sd2_lcs_toni_as_the_rock", "triangles": [414]}))
    assert not y.built_current(tmp_path)                   # the per-bone shell build (no "fit") is stale
    (tmp_path / ".gbox-mod.json").write_text(json.dumps({"name": "x", "fit": y.FIT_VERSION}))
    assert y.built_current(tmp_path)
    assert not y.built_current(tmp_path / "missing")
