"""Ocarina of Time: make Link or his sword bigger in the running game (#213 "make my sword three times bigger",
#216 "make Link 2x bigger"), on every N64 NTSC revision, against fake word-swapped RDRAM."""
import struct
import types

import pytest

from gbox import oot, oot_scale as S, tools

BASE = 0x80000000
VERSIONS = sorted(oot.LAYOUTS)


class Fake:
    """RDRAM as a 4 MB big-endian bytearray; read_memory / write_memory move 32-bit little-endian words like ParaLLEl."""

    def __init__(self, version="ntsc-1.0", entrance=0x211):
        self.m = bytearray(0x400000)
        self.version = version
        self.save, self.play = oot.LAYOUTS[version]
        self.put(self.save + 0x1C, b"ZELDAZ")
        self.put(self.save + oot.S_ENTRANCE, struct.pack(">I", entrance))
        self.put(self.play + oot.P_NEXT_ENTRANCE, struct.pack(">H", entrance))
        self.writes = []

    def put(self, a, data):
        self.m[a - BASE:a - BASE + len(data)] = data

    def get(self, a, n):
        return bytes(self.m[a - BASE:a - BASE + n])

    def read_memory(self, a, n):
        be = self.get(a, n)
        return b"".join(be[i:i + 4][::-1] for i in range(0, n, 4))

    def write_memory(self, a, data):
        self.writes.append((a, len(data)))
        self.put(a, b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4)))
        return {"written": len(data)}


def actor(ad, at, aid=0, cat=2, nxt=0, scale=0.01):
    ad.put(at, struct.pack(">hB", aid, cat))
    ad.put(at + S.A_SCALE, struct.pack(">3f", scale, scale, scale))
    ad.put(at + S.A_NEXT, struct.pack(">I", nxt))


def player_list(ad, head):
    ad.put(ad.play + S.PLAYER_HEAD, struct.pack(">I", head))


def object_slots(ad, *slots):
    """objectCtx.numEntries + slots[] {s16 id, pad, void* segment}."""
    base = ad.play + S.OBJECT_CTX_OFFSET if hasattr(S, "OBJECT_CTX_OFFSET") else ad.play + 0x117A4
    ad.put(base + 8, bytes([len(slots)]))
    for i, (oid, seg) in enumerate(slots):
        ad.put(base + 0x0C + S.OBJECT_SLOT * i, struct.pack(">h2xI", oid, seg))


# ---------------------------------------------------------------- Link's actor

@pytest.mark.parametrize("version", VERSIONS)
def test_player_list_walk_and_scale_write_per_revision(version):
    ad = Fake(version)
    link = 0x801F0000
    actor(ad, link)
    player_list(ad, link)
    assert S.player_actor(ad) == link
    assert S.link_scale(ad) == (pytest.approx(0.01),) * 3
    r = S.scale_link(ad, 2)
    assert r["verified"] and r["actor"] == hex(link) and r["scale"] == [0.02, 0.02, 0.02]
    assert ad.get(link + 0x50, 12) == struct.pack(">3f", 0.02, 0.02, 0.02)          # big-endian floats at Actor.scale
    for other in VERSIONS:                                                          # nothing landed at another revision's head
        if other != version:
            assert ad.get(oot.LAYOUTS[other][1] + S.PLAYER_HEAD, 4) == bytes(4)


def test_player_walk_skips_non_player_entries_and_refuses_garbage():
    ad = Fake()
    link, stray = 0x801F0000, 0x801E0000
    actor(ad, stray, aid=0x25, cat=4, nxt=link)                                     # not Link, points on to him
    actor(ad, link)
    player_list(ad, stray)
    assert S.player_actor(ad) == link
    actor(ad, stray, aid=0x25, cat=4, nxt=0)
    assert S.player_actor(ad) == 0
    with pytest.raises(RuntimeError, match="no Link actor"):
        S.scale_link(ad, 2)
    assert ad.get(stray + 0x50, 12) == struct.pack(">3f", 0.01, 0.01, 0.01)
    with pytest.raises(ValueError, match="out of range"):
        S.scale_link(ad, 500)


def test_hold_link_reapplies_after_link_is_recreated(monkeypatch):
    monkeypatch.setattr(S, "start", lambda sid: S.hold(sid))                        # no thread in tests
    ad = Fake("ntsc-1.2")
    link = 0x801F0000
    actor(ad, link)
    player_list(ad, link)
    r = S.hold_link(ad, "t", 2)
    assert r["hold"] and S.HOLDS["t"]["link"] == 2
    link2 = 0x80210000                                                              # scene change: a new Link at 0.01
    actor(ad, link2)
    player_list(ad, link2)
    S.tick(ad, S.HOLDS["t"])
    assert ad.get(link2 + 0x50, 12) == struct.pack(">3f", 0.02, 0.02, 0.02)
    assert S.HOLDS["t"]["applied"]["link"] == 1
    S.tick(ad, S.HOLDS["t"])
    assert S.HOLDS["t"]["applied"]["link"] == 1                                     # already right: no rewrite
    assert S.status("t")["link"] == 2
    r = S.hold_link(ad, "t", 1)
    assert not r["hold"] and "t" not in S.HOLDS
    assert ad.get(link2 + 0x50, 12) == struct.pack(">3f", 0.01, 0.01, 0.01)


# ---------------------------------------------------------------- the sword in Link's object

@pytest.mark.parametrize("version", VERSIONS)
def test_object_segment_lookup_per_revision(version):
    ad = Fake(version)
    object_slots(ad, (1, 0x80200000), (S.OBJECT_LINK_BOY, 0x80300000), (0x55, 0x80380000))
    assert S.object_segment(ad, S.OBJECT_LINK_BOY) == 0x80300000
    assert S.object_segment(ad, S.OBJECT_LINK_CHILD) == 0
    assert S.object_segment(ad, 1) == 0x80200000


def vtx(x, y, z):
    return struct.pack(">3hH2h4B", x, y, z, 0, 0, 0, 255, 255, 255, 255)


def dl(parts):
    """An F3DEX2 list: per part (texture or None, vertex offset, points, triangles)."""
    cmds = [(0xE7000000, 0)]
    for tex, voff, pts, tris in parts:
        if tex is None:
            cmds.append((0xD7000000, 0xFFFFFFFF))                                   # G_TEXTURE off
        else:
            cmds += [(0xD7000002, 0xFFFFFFFF), (0xFD100000, tex), (0xF3000000, 0x07000000)]
        n = len(pts)
        cmds.append((0x01000000 | n << 12 | n << 1, 0x06000000 | voff))
        for a, b, c in tris:
            cmds.append((0x05000000 | a * 2 << 16 | b * 2 << 8 | c * 2, 0))
    cmds.append((0xDF000000, 0))
    return b"".join(struct.pack(">II", *c) for c in cmds)


HAND_DL, HAND_VTX = 0x21F78, 0x10EE8                 # gLinkAdultLeftHandHoldingMasterSwordNearDL / ...Vtx
BACK_DL, BACK_VTX = 0x23160, 0x12E68                 # gLinkAdultMasterSwordAndSheathNearDL / ...Vtx
POMMEL = [(-800, 300, 0), (-700, 350, 0), (-600, 300, 0)]
BLADE = [(500, 300, 0), (3000, 300, 0), (3387, 320, 0)]
HAND = [(-300, 0, 0), (300, 500, 0), (0, 600, -300)]
SHEATH = [(-400, 0, 0), (2700, 0, 0), (2000, 100, 0)]
GUARD = [(-1500, 0, 0), (-1400, 50, 0), (-500, 0, 0)]
MOUTH = [(-390, 10, 0), (-380, -10, 0), (-300, 0, 0)]
SHIELD = [(0, 0, -500), (2500, 0, -500), (0, 1000, -500)]
TRI = [(0, 1, 2)]


def make_object():
    """object_link_boy-sized bytes with a synthetic hand list (pommel + blade + hand) and back list (sheath + guard +
    untextured mouth + metal-textured shield) at the real offsets, vertices inside the declared arrays."""
    obj = bytearray(S.OBJECT_SIZE[S.OBJECT_LINK_BOY])
    hand = [(0x0600D0B8, HAND_VTX, POMMEL, TRI), (S.METAL_TEX, HAND_VTX + 48, BLADE, TRI), (0x0600D738, HAND_VTX + 96, HAND, TRI)]
    back = [(0x0600DC38, BACK_VTX, SHEATH, TRI), (0x0600E438, BACK_VTX + 48, GUARD, TRI), (None, BACK_VTX + 96, MOUTH, TRI),
            (S.METAL_TEX, BACK_VTX + 144, SHIELD, TRI)]
    for d, off in ((hand, HAND_DL), (back, BACK_DL)):
        obj[off:off + len(dl(d))] = dl(d)
        for _tex, voff, pts, _t in d:
            for k, p in enumerate(pts):
                obj[voff + 16 * k:voff + 16 * k + 16] = vtx(*p)
    return bytes(obj)


ROWS = [S._row("adult", (1, 2), "hand", "gLinkAdultLeftHandHoldingMasterSwordNearDL", HAND_DL,
               ("gLinkAdultLeftHandHoldingMasterSwordNearVtx",), expect=()),
        S._row("adult", (1, 2, 3), "back", "gLinkAdultMasterSwordAndSheathNearDL", BACK_DL,
               ("gLinkAdultMasterSwordAndSheathNearVtx",), expect=())]


def test_table_matches_the_decomp_xml_and_the_retail_walk():
    assert len(S.DLS) == 34 and all(r["expect"] for r in S.DLS)                     # every list has its retail expectation
    assert all(n in S.VTX for r in S.DLS for n in r["vtx"])
    master = next(r for r in S.DLS if r["name"] == "gLinkAdultLeftHandHoldingMasterSwordNearDL")
    assert master["dl"] == 0x21F78 and S.VTX[master["vtx"][0]] == (0x10EE8, 186) and master["expect"] == (136, 50, -787, 3387)
    kokiri = next(r for r in S.DLS if r["name"] == "gLinkChildLeftFistAndKokiriSwordNearDL")
    assert kokiri["dl"] == 0x13F38 and S.VTX[kokiri["vtx"][0]] == (0xB1B0, 80)
    assert S.PLAYER_HEAD == 0x1C44 and S.A_SCALE == 0x50 and S.REACH_INDEX == {1: 2, 2: 1, 3: 3}


def test_sword_plan_classifies_pivots_scales_clamps_and_restores():
    obj = make_object()
    plan = S.sword_plan(obj, "adult", 2, ROWS)
    hand, back = plan["dls"]
    assert (hand["sword"], hand["other"], hand["conflicts"], hand["axis"]) == (6, 3, 0, 0)
    assert hand["extent"] == (-800, 3387) and hand["pivot"] == (-800.0, 316.7, 0.0)   # the pommel end, its slab's centre
    assert (back["sword"], back["other"]) == (9, 3) and back["pivot"] == (-1500.0, 25.0, 0.0)
    assert plan["vertices"] == 15 and plan["runs"] == [(HAND_VTX, 96), (BACK_VTX, 144)]
    assert plan["max_factor"] == 8.01 and plan["reach_pivot"] == -800.0
    scaled = S.scaled_bytes(plan, 3)
    tip = HAND_VTX + 48 + 32
    assert scaled[tip][:6] == struct.pack(">3h", 11761, 327, 0) and scaled[tip][6:] == obj[tip + 6:tip + 16]
    assert scaled[HAND_VTX][:6] == struct.pack(">3h", -800, 267, 0)                 # the pommel stays put on its axis
    assert HAND_VTX + 96 not in scaled and BACK_VTX + 144 not in scaled              # hand and shield vertices untouched
    assert S.scaled_bytes(plan, 1) == plan["orig"]
    with pytest.raises(ValueError, match="largest factor that fits is 8.01"):
        S.scaled_bytes(plan, 9)


def test_sword_plan_refuses_foreign_or_already_scaled_models():
    obj = bytearray(make_object())
    strict = [dict(ROWS[0], expect=(6, 3, -800, 3000)), ROWS[1]]
    with pytest.raises(RuntimeError, match="already scaled"):
        S.sword_plan(bytes(obj), "adult", 2, strict)
    stray = [dict(ROWS[0], vtx=("gLinkAdultSheathNearVtx",)), ROWS[1]]           # vertices outside the declared array
    with pytest.raises(RuntimeError, match="not the ROM's list"):
        S.sword_plan(bytes(obj), "adult", 2, stray)
    obj[HAND_DL:HAND_DL + 8] = struct.pack(">II", 0xDF000000, 0)                    # an empty list: no vertices at all
    with pytest.raises(RuntimeError, match="not the ROM's list"):
        S.sword_plan(bytes(obj), "adult", 2, ROWS)
    obj[HAND_DL:HAND_DL + 0x400] = bytes(0x400)                                       # nothing loaded there (G_NOOPs)
    with pytest.raises(RuntimeError, match="not the ROM's list"):
        S.sword_plan(bytes(obj), "adult", 2, ROWS)


def session(version, sword=2, age=0, seg=0x80300000):
    ad = Fake(version)
    ad.put(ad.save + 4, struct.pack(">I", age))
    ad.put(ad.save + oot.S_EQUIPS, struct.pack(">H", 0x1120 | sword))
    ad.put(seg, make_object())
    object_slots(ad, (1, 0x80200000), (S.OBJECT_LINK_BOY, seg))
    return ad


def reach_at(ad):
    at = S.REACH_AT.get(ad.version) or S.__dict__["OW"].VERSIONS[ad.version]["code_vram"] + 0x1000
    ad.put(at, S.REACH_ORIG)
    return at


@pytest.mark.parametrize("version", VERSIONS)
def test_apply_sword_writes_reach_reapplies_after_reload_and_restores(version, monkeypatch):
    monkeypatch.setattr(S, "start", lambda sid: S.hold(sid))
    ad = session(version)
    table = reach_at(ad)
    r = S.apply_sword(ad, "t", 3, rows=ROWS)
    assert r["verified"] and r["sword"] == "Master Sword" and r["age"] == "adult" and r["vertices"] == 15
    assert r["runs_written"] == 2 and r["runs_skipped"] == 0 and r["max_factor"] == 8.01 and r["hold"]
    seg = 0x80300000
    tip = seg + HAND_VTX + 48 + 32
    assert ad.get(tip, 6) == struct.pack(">3h", 11761, 327, 0)
    assert ad.get(seg + HAND_VTX + 96, 16) == vtx(*HAND[0])                         # the hand did not grow
    assert ad.get(seg + BACK_VTX + 144, 16) == vtx(*SHIELD[0])                      # nor the shield
    assert r["reach"]["table"] == hex(table) and r["reach"]["verified"]
    assert ad.get(table + 4, 4) == struct.pack(">f", -800 + (4000 + 800) * 3)      # pommel + (length - pommel) * 3
    assert ad.get(table, 4) == bytes(4) and ad.get(table + 8, 4) == struct.pack(">f", 3000.0)
    # scene change: the object comes back from ROM at another address
    seg2 = 0x80340000
    ad.put(seg2, make_object())
    object_slots(ad, (1, 0x80200000), (S.OBJECT_LINK_BOY, seg2))
    h = S.HOLDS["t"]
    S.tick(ad, h)
    assert h["applied"]["sword"] == 2 and ad.get(seg2 + HAND_VTX + 48 + 32, 6) == struct.pack(">3h", 11761, 327, 0)
    S.tick(ad, h)
    assert h["applied"]["sword"] == 2                                               # already scaled: nothing rewritten
    assert S.status("t")["sword"] == {"name": "Master Sword", "age": "adult", "factor": 3, "object": hex(seg2), "reach_table": hex(table)}
    r = S.apply_sword(ad, "t", 1, rows=ROWS)
    assert not r["hold"] and "t" not in S.HOLDS
    assert ad.get(seg2, len(make_object())) == make_object() and ad.get(table, 24) == S.REACH_ORIG


def test_sword_hold_follows_equipment_and_skips_half_loaded_objects(monkeypatch):
    monkeypatch.setattr(S, "start", lambda sid: S.hold(sid))
    ad = session("ntsc-1.0")
    reach_at(ad)
    S.apply_sword(ad, "t", 2, rows=ROWS)
    h = S.HOLDS["t"]
    seg = 0x80300000
    ad.put(ad.save + oot.S_EQUIPS, struct.pack(">H", 0x1123))                        # Biggoron's Sword equipped
    S.tick(ad, h)
    assert h["sword"]["key"] == ("adult", 3) and S.status("t")["sword"]["name"] == "Biggoron's Sword"
    assert ad.get(seg + HAND_VTX, 96) == make_object()[HAND_VTX:HAND_VTX + 96]       # the Master Sword grip is restored
    assert ad.get(seg + BACK_VTX, 16)[:6] != vtx(*SHEATH[0])[:6]                       # the sheath (shared list) stays big
    ad.put(seg + BACK_VTX + 8, b"\x55\x55")                                           # a half-written load: not ours, not ROM
    before = h["skipped"]
    S.tick(ad, h)
    assert h["skipped"] == before + 1
    S.release(ad, "t")
    assert "t" not in S.HOLDS


def test_apply_sword_refuses_without_sword_or_object():
    ad = session("ntsc-1.1", sword=0)
    with pytest.raises(RuntimeError, match="no sword equipped"):
        S.apply_sword(ad, "t", 2, rows=ROWS)
    ad = session("ntsc-1.1")
    object_slots(ad, (1, 0x80200000))
    with pytest.raises(RuntimeError, match="not loaded"):
        S.apply_sword(ad, "t", 2, rows=ROWS)
    assert "t" not in S.HOLDS


def test_reach_table_verification_and_values():
    ad = Fake("ntsc-1.2")
    at = S.REACH_AT["ntsc-1.2"]
    assert S.reach_table(ad, "ntsc-1.2", 2) == 0                                     # nothing there, nothing in the window
    ad.put(at, S.REACH_ORIG)
    assert S.reach_table(ad, "ntsc-1.2", 2) == at
    ad.put(at + 4, struct.pack(">f", 12000.0))                                      # our own patch of the Master Sword entry
    assert S.reach_table(ad, "ntsc-1.2", 2) == at and S.reach_table(ad, "ntsc-1.2", 3) == 0
    ad = Fake("ntsc-1.1")                                                           # no static address: found by content
    at = 0x800110A0 + 0x2000
    ad.put(at, S.REACH_ORIG)
    assert S.reach_table(ad, "ntsc-1.1", 1) == at
    assert S.reach_value(2, -787.0, 3) == pytest.approx(-787 + 4787 * 3) and S.reach_value(1, None, 1) == 3000.0


def test_zelda_oot_tool_routes_the_scale_ops(monkeypatch):
    monkeypatch.setattr(S, "start", lambda sid: S.hold(sid))
    ad = session("ntsc-1.0")
    link = 0x801F0000
    actor(ad, link)
    player_list(ad, link)
    tools.SESSIONS["t-oot"] = (ad, {"game_id": "g", "title": "Legend of Zelda, The: Ocarina of Time (USA)", "platform": "n64"})
    ctx = types.SimpleNamespace(config=None, artifact=lambda *a, **k: None, progress=lambda *a: None)
    f = getattr(tools.zelda_oot, "__wrapped__", tools.zelda_oot)
    run = lambda **kw: f(tools.OotIn(session_id="t-oot", **kw), ctx)["result"]       # noqa: E731
    try:
        assert run(op="scale", factor=2)["verified"] and ad.get(link + 0x50, 4) == struct.pack(">f", 0.02)
        assert run(op="scale_link", factor=3)["scale"] == [0.03, 0.03, 0.03]
        monkeypatch.setattr(S, "DLS", ROWS)
        r = run(op="scale_sword", factor=2, reach=False)
        assert r["verified"] and "reach" not in r and r["lists"] == [ROWS[0]["name"], ROWS[1]["name"]]
        st = run(op="scale_status")
        assert st["link"] == 3 and st["sword"]["factor"] == 2 and st["link_scale"] == [pytest.approx(0.03)] * 3
        assert run(op="scale_release")["released"] and "t-oot" not in S.HOLDS
        assert ad.get(link + 0x50, 4) == struct.pack(">f", 0.01)
        with pytest.raises(ValueError, match="scale_sword"):
            run(op="shrink")
    finally:
        tools.SESSIONS.pop("t-oot", None)
