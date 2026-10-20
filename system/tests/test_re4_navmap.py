"""RE4 GC level data (gbox.re4_navmap): the room-archive codec, SAT / AEV / ITA / ESL / RTP readers, the layered grid,
the path planner and the tour, on synthetic rooms; plus the committed r400 map and, when the owned disc image is on
this node, r400 straight from the disc."""
import json
import math
import os
import random
import struct
from pathlib import Path

import pytest

from gbox import re4_navmap as N


# ---------------------------------------------------------------- a reference encoder for the room codec (test only)

def das_pack(data: bytes) -> bytes:
    """Exact inverse of N.das_unpack: the same adaptive models and LZP rings, coded with a big-integer range coder.
    Quadratic in the size - fine for the few KB used here."""
    A, B = N._Model(0x500), N._Model(0x100)
    low, R, t = 0, 256, 8                                 # [low, low + R) in units of 2^-t; t = bits the decoder read

    def put(m, s):
        nonlocal low, R, t
        if R <= 1 << 24:                                  # the decoder's normalisation (rng = R / 2)
            k = 8 if R > 1 << 16 else 16 if R > 1 << 8 else 24
            low, R, t = low << k, R << k, t + k
        r = R >> 15
        low += r * m.cs[s]
        R = (r * m.cf[s]) & ~1
        m.update(s)

    ring_i = [0] * 256
    ring_p = [[0] * 512 for _ in range(256)]
    ring_n = [[0] * 512 for _ in range(256)]
    o = last = 0
    while o < len(data):
        c = data[last] if o else 0
        best = (1, None, None)                            # (length, slot, kind)
        if o:
            for slot in range(512):
                ptr, n = ring_p[c][slot], ring_n[c][slot]
                if not n:
                    continue
                if n > best[0] and data[ptr:ptr + n] == data[o:o + n]:
                    best = (n, slot, "remembered")
                L = 0
                while o + L < len(data) and data[ptr + L] == data[o + L] and L < 70000:
                    L += 1
                if L > best[0] + 1:
                    best = (L, slot, "explicit")
        n, slot, kind = best
        if kind is None:
            put(A, 0x400 + data[o])
        elif kind == "remembered":
            put(A, 0x200 + ((slot - ring_i[c]) & 0x1FF))
        else:
            put(A, (slot - ring_i[c]) & 0x1FF)
            v = n + 1
            if 3 <= v <= 255:
                put(B, v)
            else:
                nb = 2 if v <= 0xFFFF else 3 if v <= 0xFFFFFF else 4
                put(B, 4 - nb)
                for i in range(nb - 1, -1, -1):
                    put(B, (v >> (8 * i)) & 0xFF)
        o += n
        if last < o - 1:
            c2 = data[last]
            k = ring_i[c2]
            ring_p[c2][k], ring_n[c2][k], ring_i[c2] = last + 1, n, (k + 1) & 0x1FF
            last = o - 1
    body = (low + R // 2).to_bytes(t // 8, "big")
    return f"{len(body):x}\t{len(data):x}\n".encode().ljust(0x20, b"\0") + body


def sample_bytes() -> bytes:
    rnd = random.Random(4)
    block = bytes(rnd.randrange(256) for _ in range(700))
    return (b"RE4 room data. " * 40 + bytes(range(256)) + block + bytes(rnd.randrange(256) for _ in range(1200))
            + block + b"\0" * 300 + b"SAT EAT AEV ITA " * 20)


def test_codec_round_trip_literals_matches_and_long_lengths():
    data = sample_bytes()
    packed = das_pack(data)
    assert len(packed) < len(data)                         # the repeats became matches
    assert N.das_unpack(packed) == data


def test_codec_rejects_garbage():
    with pytest.raises(ValueError):
        N.das_unpack(b"\x00" * 64)
    with pytest.raises(ValueError):                         # header claims more than the entry holds
        N.das_unpack(b"ffffff\t10\n".ljust(0x20, b"\0") + b"\x01\x02")


def test_room_files_unpack_a_udas_room_archive():
    from gbox import re4gc_models as M
    dat = M.dat_write([("SAT", b"collision" * 3), ("AEV", b"events!" * 5)])
    das = M.udas_write([{"type": 0, "entry": bytes(32), "data": das_pack(dat)},
                        {"type": 4, "entry": struct.pack(">I", 4) + bytes(28), "data": b"\0" * 64}])
    files = N.room_files(das)
    assert [e for e, _ in files] == ["SAT", "AEV"]
    assert files[0][1].startswith(b"collision" * 3) and files[1][1].startswith(b"events!" * 5)


# ---------------------------------------------------------------- synthetic rooms

def sat_bytes(tris, attrs=None) -> bytes:
    """[(p0, p1, p2)] -> a SAT file (vertices shared, edge vectors and normals as the game stores them)."""
    verts, vix, normals, edges, recs = [], {}, [], [], []
    for t, (a, b, c) in enumerate(tris):
        ids = []
        for p in (a, b, c):
            if p not in vix:
                vix[p] = len(verts)
                verts.append(p)
            ids.append(vix[p])
        d0 = [b[k] - a[k] for k in range(3)]
        d1 = [c[k] - b[k] for k in range(3)]
        n = (d0[1] * d1[2] - d0[2] * d1[1], d0[2] * d1[0] - d0[0] * d1[2], d0[0] * d1[1] - d0[1] * d1[0])
        ln = math.sqrt(sum(v * v for v in n)) or 1.0
        normals.append(tuple(v / ln for v in n))
        e0 = len(edges)
        edges += [tuple(d0), tuple(d1), tuple(a[k] - c[k] for k in range(3))]
        attr = attrs[t] if attrs else 0
        recs.append(struct.pack(">10H", *ids, t, e0, e0 + 1, e0 + 2, 0, attr >> 16, attr & 0xFFFF))
    body = struct.pack(">6H4H", 0x2000, len(verts), len(normals), len(edges), 0, len(tris), 0, 0, 0, 0)
    flt = b"".join(struct.pack(">3f", *p) for p in verts + normals + edges)
    return struct.pack(">II", 0x8001FF79, 8) + body + flt + b"".join(recs)


def floor(x0, z0, x1, z1, y):
    a, b, c, d = (x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0)
    return [(a, b, c), (a, c, d)]                        # normal +y with the game's winding


def wall(x0, z0, x1, z1, y0, y1):
    a, b, c, d = (x0, y0, z0), (x1, y0, z1), (x1, y1, z1), (x0, y1, z0)
    return [(a, b, c), (a, c, d)]


def col(parts):
    """[(triangles, attr)] -> sat_read() result."""
    tris, attrs = [], []
    for ts, attr in parts:
        tris += ts
        attrs += [attr] * len(ts)
    return N.sat_read(sat_bytes(tris, attrs))


def make_stage(parts, events=(), spawns=()):
    g = N.build_grid(col(parts))
    g.lr[:] = 2
    return N.Stage({"room": "r4ff", "grid": g, "events": list(events), "spawns": list(spawns), "walls": []})


def crossings(wps, start, z_line):
    """x where the polyline start -> waypoints crosses z = z_line."""
    pts = [start] + [(w.x, w.z) for w in wps]
    out = []
    for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
        if (z1 - z_line) * (z2 - z_line) < 0:
            out.append(x1 + (x2 - x1) * (z_line - z1) / (z2 - z1))
    return out


def test_sat_read_matches_the_triangles():
    c = col([(floor(0, 0, 1000, 1000, 0), 0), (wall(0, 500, 1000, 500, 0, 2000), 0x20)])
    assert c["tris"].shape == (4, 3)
    assert (c["normals"][:2, 1] > 0.99).all() and (abs(c["normals"][2:, 1]) < 1e-6).all()
    assert list(c["attr"]) == [0, 0, 0x20, 0x20]
    with pytest.raises(ValueError):
        N.sat_read(b"\0" * 64)


def test_path_goes_around_a_wall():
    st = make_stage([(floor(0, 0, 6000, 6000, 0), 0), (wall(0, 3000, 4600, 3000, 0, 2500), 0)])
    g = st["grid"]
    assert g.state_at(2000, 3000) == "wall" and g.state_at(2000, 1500) == "free" and g.state_at(9000, 0) == "void"
    w = N.path(st, (1000, 1000), (1000, 5000))
    assert w and (w[-1].x, w[-1].z) == (1000, 5000)
    assert all(x > 4600 for x in crossings(w, (1000, 1000), 3000))     # only through the gap
    assert len(w) <= 6                                                  # smoothed to a few legs
    assert N.path(st, (1000, 1000), (1000, 5000), smooth=False)[-1].z == 5000


def fence_stage():
    return make_stage([(floor(0, 0, 12000, 6000, 0), 0),
                       (wall(0, 3000, 2400, 3000, 0, 2500), 0),
                       (wall(2400, 3000, 4800, 3000, 0, 1000), 0x20),        # JUMP OVER fence ...
                       (wall(2400, 3000, 4800, 3000, 1000, 2400), 0x400),    # ... with its invisible top
                       (wall(4800, 3000, 10800, 3000, 0, 2500), 0)])         # gap at x 10800..12000


def test_path_vaults_the_fence_when_cheaper():
    st = fence_stage()
    assert st["grid"].state_at(3600, 3000) == "vault"
    w = N.path(st, (3600, 1000), (3600, 5000))
    assert [p.action for p in w].count("vault") == 1
    assert N.path_length(w, (3600, 1000)) < 6000
    around = N.path(st, (3600, 1000), (3600, 5000), vault_cost=1e9)
    assert not any(p.action for p in around)
    assert all(x > 10800 for x in crossings(around, (3600, 1000), 3000))
    assert N.path_length(around, (3600, 1000)) > 14000


def test_sight_sees_through_fences_not_walls():
    st = fence_stage()
    st["walls"] = [[2400, 3000, 4800, 3000, 0, 1000, 0x20], [4800, 3000, 10800, 3000, 0, 2500, 0]]
    st._walls = None
    assert N.sight(st, (3600, 1200, 1000), (3600, 1200, 5000))
    assert not N.sight(st, (3600, 800, 1000), (3600, 800, 5000), see_through=False)
    assert not N.sight(st, (6000, 1200, 1000), (6000, 1200, 5000))
    assert N.sight(st, (6000, 3000, 1000), (6000, 3000, 5000))           # over the wall top


def test_tour_orders_targets_by_path_cost():
    st = make_stage([(floor(-1000, -1000, 6000, 1000, 0), 0)])
    targets = [(3000, 0), (1000, 0), (2000, 0), (4000, 0)]
    assert N.tour(st, (0, 0), targets) == [1, 2, 0, 3]
    assert N.tour(st, (0, 0), targets + [(50000, 50000)]) == [1, 2, 0, 3]   # off the map: left out


def test_tour_exact_beats_greedy():
    st = make_stage([(floor(-6000, -1000, 6000, 1000, 0), 0)])
    # greedy from 0 would take 600 first and then cross back; the exact order sweeps one side first
    targets = [(-600, 0), (600, 0), (-5000, 0), (5000, 0)]
    order = N.tour(st, (0, 0), targets)
    pts = [(0, 0)] + [targets[i] for i in order]
    assert sorted(order) == [0, 1, 2, 3]
    assert sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) == pytest.approx(15000)    # greedy would be 16200


# ---------------------------------------------------------------- a whole synthetic room through build_stage

def event_bytes(magic: bytes, version: int, entries) -> bytes:
    out = magic + struct.pack(">HH", version, len(entries)) + bytes(8)
    for e in entries:
        b = bytearray(0x9C)
        struct.pack_into(">2f", b, 8, e["y"], e["h"])
        for k, (x, z) in enumerate(e["poly"]):
            struct.pack_into(">2f", b, 0x14 + 8 * k, x, z)
        b[0x34], b[0x35], b[0x36], b[0x38] = 3, e["type"], e.get("index", 0), e.get("trigger", 1)
        for off, fmt, vals in e.get("data", ()):
            struct.pack_into(fmt, b, off, *vals)
        out += bytes(b)
    return out


def square(cx, cz, r):
    return [(cx - r, cz - r), (cx + r, cz - r), (cx + r, cz + r), (cx - r, cz + r)]


def synthetic_room():
    sat = sat_bytes(*zip(*[(t, a) for ts, a in [
        (floor(0, 0, 10000, 10000, 0), 0),
        (floor(6000, 6000, 9000, 9000, 3000), 0),                              # a loft, reached by a ladder
        (wall(6000, 6000, 9000, 6000, 0, 3000), 0), (wall(9000, 6000, 9000, 9000, 0, 3000), 0),
        (wall(9000, 9000, 6000, 9000, 0, 3000), 0), (wall(6000, 9000, 6000, 6000, 0, 3000), 0),
        (wall(0, 0, 10000, 0, 0, 3000), 0), (wall(10000, 0, 10000, 10000, 0, 3000), 0),
        (wall(10000, 10000, 0, 10000, 0, 3000), 0), (wall(0, 10000, 0, 0, 0, 3000), 0)] for t in ts]))
    ladder = {"type": 0x10, "index": 1, "trigger": 2, "y": 0, "h": 1000, "poly": square(5700, 7500, 300),
              "data": [(0x5C, ">4f", (5700, 0, 7500, math.pi / 2)), (0x6C, ">b", (3,))]}
    pillar = {"type": 0, "index": 2, "trigger": 2, "y": 0, "h": 1500, "poly": square(2000, 8000, 600)}
    area = {"type": 4, "y": -500, "h": 4000, "poly": square(5000, 5000, 5000)}
    aev = event_bytes(b"AEV\0", 0x104, [area, ladder, pillar])

    def item(x, y, z, iid, amount):
        return {"type": 3, "y": 0, "h": 1000, "poly": square(0, 0, 10),
                "data": [(0x5C, ">3f", (x, y, z)), (0x78, ">HHH", (iid, 7, amount))]}
    ita = event_bytes(b"ITA\0", 0x105, [item(1000, 30, 1000, 0x73, 90), item(7500, 3030, 7500, 0x73, 30),
                                        item(2000, 1900, 8000, 0x75, 30), item(3000, 0, 2000, 0x04, 50),
                                        item(0, 0, 0, 0x06, 1)])
    esl = bytearray(32 * 3)
    for k, (x, z) in enumerate([(5000, 2000), (2000, 5000)]):
        struct.pack_into(">BBB", esl, 32 * k, 1, 0x16, 3)
        struct.pack_into(">HH3h3hH", esl, 32 * k + 8, 1800, 0, x // 10, 0, z // 10, 0, 0, 0, 0x4FF)
    struct.pack_into(">H", esl, 32 * 2 + 0x18, 0x400)                        # another room: ignored
    rtp = b"2RTP" + struct.pack(">5I", 2, 0, 0x18, 0x38, 0x40) + struct.pack(">3fHH", 5000, 0, 2000, 0, 1) \
        + struct.pack(">3fHH", 2000, 0, 5000, 1, 1) + struct.pack(">HHHH", 1, 424, 0, 424)
    return [("SAT", sat), ("AEV", aev), ("ITA", ita), ("RTP", rtp)], {"etc/omake09.esl": bytes(esl)}


def test_build_stage_end_to_end(tmp_path):
    files, esl = synthetic_room()
    d = N.build_stage(files, esl, "r4ff")
    p = tmp_path / "re4_r4ff_navmap.json"
    p.write_text(json.dumps(d))
    st = N.stage(path=p)
    kinds = sorted(e["kind"] for e in st["events"])
    assert kinds == ["area", "combo_bonus", "item", "ladder", "pickup_zone", "time_bonus", "time_bonus"]
    hg = st["hourglasses"]
    assert [(e["kind"], e["seconds"]) for e in hg] == [("time_bonus", 90), ("time_bonus", 30), ("combo_bonus", 30)]
    assert all(e["reachable"] for e in hg)
    combo = hg[2]
    assert combo["zone"]["trigger"] == "action" and combo["stand"][1] == 0.0             # take it from the floor
    assert N._in_poly(combo["stand"][0], combo["stand"][2], [tuple(q) for q in combo["zone"]["poly"]])
    ladder = next(e for e in st["events"] if e["kind"] == "ladder")
    assert ladder["top"] == [5700.0, 3000.0, 7500.0] and ladder["rungs"] == 3
    assert [s["pos"] for s in st["spawns"]] == [[5000.0, 0.0, 2000.0], [2000.0, 0.0, 5000.0]]
    assert all(s["reachable"] for s in st["spawns"]) and st["routes"]["links"] == [[0, 1]]
    w = N.path(st, hg[0], hg[1])                                                # ground -> loft
    assert [p.action for p in w].count("ladder") == 1 and abs(w[-1].y - 3000) < 1
    assert N.tour(st, (5000, 0, 5000)) and sorted(N.tour(st, (5000, 0, 5000))) == [0, 1, 2]
    assert st["grid"].state_at(7500, 7500, 3000) in ("free", "near")
    png = N.render(st, tmp_path / "r4ff.png", w, hg[0])
    assert png.stat().st_size > 1000


# ---------------------------------------------------------------- the real Village (r400)

COMMITTED = N.DATA_DIR / "re4_r400_navmap.json"
TIME_BONUS = {"ITA[0]": (-22781.6, -2687.9, 90), "ITA[1]": (8178.2, 17413.9, 90), "ITA[2]": (20286.8, -10569.3, 90),
              "ITA[6]": (1551.9, 20029.0, 30), "ITA[7]": (20156.3, 16035.9, 30)}
COMBO_ZONES = {"ITA[23]": (-20476, -5294), "ITA[25]": (-8452, -20283), "ITA[26]": (5592, 16384)}   # live RAM AEV


def check_r400(st):
    hg = {e["source"]: e for e in st["hourglasses"]}
    assert {k for k, e in hg.items() if e["kind"] == "time_bonus"} == set(TIME_BONUS)
    for k, (x, z, sec) in TIME_BONUS.items():
        assert (hg[k]["pos"][0], hg[k]["pos"][2], hg[k]["seconds"]) == (x, z, sec) and hg[k]["reachable"]
    for k, (x, z) in COMBO_ZONES.items():
        poly = hg[k]["zone"]["poly"]
        cx, cz = sum(p[0] for p in poly) / 4, sum(p[1] for p in poly) / 4
        assert math.dist((cx, cz), (x, z)) < 5 and hg[k]["zone"]["trigger"] == "action"
    assert not hg["ITA[23]"]["reachable"] and hg["ITA[25]"]["reachable"] and hg["ITA[26]"]["reachable"]
    ladder = [e for e in st["events"] if e["kind"] == "ladder"]
    assert len(ladder) == 1 and ladder[0]["source"] == "AEV[9]"
    assert len(st["spawns"]) == 130 and all(s["reachable"] for s in st["spawns"])
    bx, bz = st["bounds"]["x"], st["bounds"]["z"]
    for e in hg.values():
        assert bx[0] <= e["pos"][0] <= bx[1] and bz[0] <= e["pos"][2] <= bz[1]
    w = N.path(st, hg["ITA[0]"], hg["ITA[7]"])
    assert w and math.dist((w[-1].x, w[-1].z), (hg["ITA[7]"]["stand"][0], hg["ITA[7]"]["stand"][2])) < 1
    order = N.tour(st, hg["ITA[0]"])
    assert sorted(order) == sorted(i for i, e in enumerate(st["hourglasses"]) if e["reachable"])


@pytest.mark.skipif(not COMMITTED.is_file(), reason="profiles/gamedata/re4_r400_navmap.json not generated")
def test_committed_r400_map():
    st = N.stage("r400")
    assert st["room"] == "r400" and COMMITTED.stat().st_size < 1 << 20
    check_r400(st)


def _disc():
    cands = [os.environ.get("GBOX_RE4GC_DISC", "")]
    for root in (Path("D:/gBox/cache"), Path.home() / "gbox-cache", Path.home() / "gbox-cache/modbase"):
        for ext in ("gcz", "iso"):
            cands.append(str(root / "78ab9efa2e310db4" / f"Resident Evil 4 (USA) (Disc 1).{ext}"))
    return next((Path(c) for c in cands if c and Path(c).is_file()), None)


DISC = _disc()


@pytest.mark.skipif(DISC is None, reason="owned RE4 GC disc 1 image not on this node (set GBOX_RE4GC_DISC)")
def test_r400_from_the_disc(tmp_path):
    d = N.extract(DISC, "r400")
    assert d["source"]["room_file"] == "St4/r400.das" and d["source"]["esl_file"] == "etc/omake01.esl"
    assert d["collision"]["tris"] == 1290 and len(d["routes"]["nodes"]) == 113
    p = tmp_path / "re4_r400_navmap.json"
    p.write_text(json.dumps(d))
    check_r400(N.stage(path=p))
