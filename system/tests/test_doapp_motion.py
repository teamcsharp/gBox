"""gbox.doapp_motion: DOA++ motion bank format (synthetic) and the game's own evaluator (owned ROMs, skip-if-absent:
GBOX_DOAPP_ROMS = directory with doapp.zip + coh1002m.zip; decodes the program, ~40 s)."""

import os
import struct

import pytest

from gbox import doapp_inventory as D
from gbox import doapp_motion as DM

OWNED = os.environ.get("GBOX_DOAPP_ROMS", "")
needs_roms = pytest.mark.skipif(not (OWNED and os.path.isfile(os.path.join(OWNED, "doapp.zip"))),
                                reason="set GBOX_DOAPP_ROMS to the directory with doapp.zip + coh1002m.zip")


def _seg0(frames, a, start):
    """type 0 segment: frames in bits 3..11, accel high nibble in h0 bits 12..15, low 16 bits in h2."""
    a &= 0xFFFFF
    h0 = (frames << 3) | ((a >> 16) << 12)
    return struct.pack("<HhH", h0, start, a & 0xFFFF)


def _seg4(frames, start):
    return struct.pack("<Hh", (frames << 3) | 4, start)


def _seg2(extra, a, start):
    return struct.pack("<hh", (start & -4) | 2, ((a << 1) & -8) | extra)


def _end(value):
    return struct.pack("<h", (value & -4) | 3)


def _bank(frames=4, half=False, events=b""):
    """A one-motion bank: rotation / limb tracks, a 15-curve block, optional twist events (record word 8)."""
    head = bytearray(DM.MOTION_LIST + 8)
    for k in range(4):
        struct.pack_into("<I", head, DM.IK_OFFSETS + 4 * k, 0x404 * k)
        struct.pack_into("<h", head, 0x404 * k + 2, 100 + k)
    rec_at = len(head)
    body = bytearray(4 * DM.RECORD_WORDS)
    nt = frames // 2 + 1 if half else frames
    words = []
    # rotation tracks 2, 0, 1 (the order the game's data uses), then curves, then limbs
    tracks = {}
    for k in (2, 0, 1):
        tracks[k] = rec_at + len(body)
        for f in range(nt):
            body += struct.pack("<I", DM.encode_rot((10 * f + 2 * k) & 0xFFE, (40 * f + 4 * k) & 0xFFC, 6 * f))
    curves = rec_at + len(body)
    blk = bytearray(2 * DM.CURVES)
    for k in range(DM.CURVES):
        struct.pack_into("<h", blk, 2 * k, len(blk) // 2)
        if k == 0:
            data = _seg0(frames - 1, 0, 400) + _end(800)            # root x: 100 -> 200 (values are x4)
        elif k == 1:
            data = _seg4(frames - 1, 3000) + _end(3000)             # root y flat 750
        else:
            data = _seg2(0, 8, 40 * k) + _end(40 * k + 400)
        blk += data
    body += blk
    body += b"\0" * (-len(body) % 4)
    limbs = []
    for k in range(4):
        limbs.append(rec_at + len(body))
        for f in range(nt):
            body += DM.encode_limb(4 * f, 8 * k, 12, 1000 + 4 * f)
    body += b"\0" * (-len(body) % 4)
    ev = 0
    if events:
        ev = rec_at + len(body)
        body += events
    words = [tracks[0], tracks[1], tracks[2], *limbs, curves, ev]
    struct.pack_into(f"<{DM.RECORD_WORDS}I", body, 0, *words)
    struct.pack_into("<I", head, DM.MOTION_LIST, rec_at)
    return bytes(head + body)


def test_track_codecs_round_trip():
    for x, y, z in ((0, 0, 0), (4094, 4092, 4094), (332, 4, 36)):
        assert DM.decode_rot(DM.encode_rot(x, y, z)) == (x, y, z)
    assert DM.decode_limb(DM.encode_limb(4092, 0, 1908, 3328)) == (4092, 0, 1908, 3328)
    assert DM.decode_limb(bytes([0xFF, 0xC0, 0, 0, 0])) == (4092, 0, 0, 0)
    with pytest.raises(DM.MotionError):
        DM.encode_rot(1, 0, 0)
    with pytest.raises(DM.MotionError):
        DM.decode_limb(b"\0" * 4)


def test_curve_segments_land_on_their_end_values():
    data = _seg0(10, -48, 400) + _seg2(1, 4, 1000) + _seg4(3, 2000) + struct.pack("<h", 1201) + _end(80)
    segs = DM.curve_segments(data, 0)
    assert [s["type"] for s in segs] == [0, 2, 4, 1, 3]
    assert [s["frames"] for s in segs] == [10, 4, 3, 1, 0]
    assert segs[0]["a"] == -48 and segs[1]["a"] == 4 and segs[1]["start"] == 1000 and segs[3]["start"] == 1200
    v = DM.curve_values(data, 0, 22)
    assert v[0] == 100 and v[10] == 250 and v[13] == 437 and v[14] == 500 and v[17] == 300 and v[18] == 20 and v[21] == 20
    # type 0: ((a t + b) t >> 10) + start / 4 with b = ((end - start) << 8) / frames - a frames (truncating)
    b = int(((1000 - 400) << 8) / 10) + 48 * 10
    assert v[3] == ((-48 * 3 + b) * 3 >> 10) + 100


def test_parse_bank_and_channels_full_rate():
    data = _bank(frames=4)
    bank = DM.parse_bank(data)
    assert [t[1] for t in bank["ik_tables"]] == [100, 101, 102, 103]
    m = bank["motions"][0]
    assert m["frames"] == 4 and m["track_frames"] == 4 and not m["half_rate"] and m["extra"] is None
    ch = DM.channels(data, m)
    assert len(ch) == 4
    assert ch[2]["rot"][1] == (22, -84, 12)                   # facing +1: (x, -y, z)
    assert ch[3]["limbs"][0] == (12, -24, 12, 1012)           # limb 0 reads record word 6 (the 4th track)
    assert ch[0]["limbs"][3][1] == 0 and ch[0]["limbs"][1][1] == -8
    assert ch[0]["root"] == (0, 750, 0) and ch[3]["root"][0] == 100
    assert ch[0]["targets"][0] == (30, 40, 50)                 # header curves 3..5 -> limb 0 target


def test_half_rate_midpoints_and_twist_keys():
    events = struct.pack("<HHhH", 0x8000 | 2, 0x4000 | 1, 777 << 4, 0x7777)
    data = _bank(frames=6, half=True, events=events)
    m = DM.parse_bank(data)["motions"][0]
    assert m["half_rate"] and m["track_frames"] == 4
    ch = DM.channels(data, m)
    assert ch[0]["rot"][0] == (0, 0, 0) and ch[2]["rot"][0] == (10, -40, 6)
    assert ch[1]["rot"][0] == (5, -20, 3)                     # midpoint of frames 0 and 1
    assert ch[1]["limbs"][1][3] == 777                        # the key at counter 3 (tick 1) overrides limb 1's twist
    assert ch[3]["limbs"][1][3] == 1006 and ch[1]["limbs"][0][3] == 1002
    wrap = DM.TwistEvents(struct.pack("<H", 0x7777), 0)
    wrap.advance(5)
    assert wrap.pending == [None] * 4


def test_parse_bank_rejects_damage():
    data = bytearray(_bank())
    struct.pack_into("<I", data, DM.IK_OFFSETS + 4, 0x400)
    with pytest.raises(DM.MotionError):
        DM.parse_bank(bytes(data))
    data = bytearray(_bank())
    struct.pack_into("<I", data, DM.MOTION_LIST, len(data) + 4)
    with pytest.raises(DM.MotionError):
        DM.parse_bank(bytes(data))
    with pytest.raises(DM.MotionError):
        DM.curve_segments(_seg4(3, 0) * 3, 0, limit=3)


@pytest.fixture(scope="module")
def owned():
    banked, ram, _ = D.decode_owned(OWNED)
    return banked, ram


@needs_roms
def test_owned_python_decode_matches_the_games_stepper(owned):
    banked, ram = owned
    rig = DM.Rig(ram, banked, D.fighter("tina"), 0)
    assert len(rig.motions) == 265 and rig.motions[0]["frames"] == 105 and not rig.motions[0]["half_rate"]
    assert rig.motions[1]["half_rate"] and rig.motions[1]["track_frames"] == 26
    for m in (0, 1, 3, 200):
        mo = rig.motions[m]
        ch = DM.channels(rig.bank, mo)
        rig.play(m)
        for f in range(mo["frames"]):
            rig.tick()
            st, c = rig.state(), ch[f]
            assert [tuple(r) for r in st["rot"][:3]] == c["rot"], (m, f)
            for k in range(4):
                assert tuple(st["rot"][DM.LIMB_WORDS[k]]) == c["limbs"][k][:3], (m, f, k)
                assert st["twist"][k] == c["limbs"][k][3], (m, f, k)
                assert tuple(st["targets"][k]) == c["targets"][k], (m, f, k)
            assert st["root"][1] == c["root"][1]


@needs_roms
def test_owned_rest_pose_is_a_standing_fighter(owned):
    banked, ram = owned
    rig = DM.Rig(ram, banked, D.fighter("kasumi"), 0)
    pose = rig.rest_pose()
    t = {b: pose[b][1] for b in range(15)}
    assert -1500 < t[1][1] < t[0][1] < t[2][1] < -500          # head above torso above pelvis (y down)
    assert t[3][1] > -150 and t[9][1] > -150                   # feet at the ground
    assert t[8][0] > t[14][0] and t[6][0] > t[12][0]               # left (+x) vs right shoulders and hips
    assert any(pose[b][0] != (0,) * 9 for b in range(15, 19))   # Kasumi's ponytail chain ran
    assert rig.hand_shapes().keys() == {2, 4}
