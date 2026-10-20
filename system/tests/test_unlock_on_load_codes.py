"""#1986: Soul Calibur II launches with every character unlocked: its verified code profile is held in the session
once it runs (gbox/game_unlocks.py post_launch, tools._gcheat_hold), the way cheats op=add holds a code."""
import threading
import time

from gbox import game_unlocks as U, tools as T

SC2 = {"game_id": "201629ad498aba7b", "title": "Soul Calibur II (USA)", "platform": "gamecube"}


def test_the_sc2_profile_is_verified_and_its_codes_decrypt():
    prof = U.code_profile(SC2)
    assert prof and prof["profile"] == "sc2-gc-usa-action-replay-v1" and len(prof["codes"]) == 3
    assert U.code_profile(SC2 | {"platform": "wii"}) is None, "another platform's build is not this profile"
    assert U.code_profile({"game_id": "0000000000000000", "platform": "gamecube"}) is None
    assert U.code_profile({"game_id": "../../etc/passwd", "platform": "gamecube"}) is None
    from gbox import cheats as C
    for entry in prof["codes"]:
        ops, bad = C.decode("gamecube", "\n".join(entry["lines"]))
        assert ops and not bad, entry["desc"]
    assert U.profile_for(SC2)["verified"] is False, "the save-template path stays untouched: this game unlocks in RAM"


def test_post_launch_holds_every_code_and_reports_a_bad_one_without_failing():
    calls = []

    def hold(sid, lines, desc):
        calls.append((sid, tuple(lines), desc))
        if "Levels" in desc:
            raise ValueError("no code lines gBox can apply itself")
    out = U.post_launch("w-s1", SC2, hold)
    assert [c[2][:14] for c in calls] == ["All Characters", "Everything is ", "All Levels Unl"]
    assert out["state"] == "partial" and out["applied"] is True and len(out["held"]) == 2 and len(out["failed"]) == 1
    assert out["profile"] == "sc2-gc-usa-action-replay-v1" and "read_back" in out["evidence"]
    assert U.post_launch("w-s1", {"game_id": "0" * 16, "platform": "gamecube"}, hold) is None, "no profile: nothing held"


def test_gcheat_hold_registers_a_held_code_in_the_session():
    class Ad:
        def __init__(self):
            self.mem = {}
            self.writes = 0

        def read_memory(self, a, n):
            return bytes(self.mem.get(a + i, 0) for i in range(n))

        def write_memory(self, a, d):
            for i, b in enumerate(d):
                self.mem[a + i] = b
            self.writes += 1
    ad = Ad()
    sid = "test-hold-" + str(int(time.time()))
    T.SESSIONS[sid] = (ad, {"game_id": SC2["game_id"], "platform": "gamecube"})
    try:
        out = T._gcheat_hold(sid, ["DH6Z-D4P8-0A4BF", "R3DX-AMGV-49BQR"], "All Characters Unlocked")
        assert out == {"index": 0, "ops": 4, "unsupported": []}
        c = T.GCHEATS[sid][0]
        assert c["desc"] == "All Characters Unlocked" and c["on"].is_set() and len(c["ops"]) == 4
        for _ in range(50):
            if ad.read_memory(0x80402160, 8) == b"\x03" * 8:
                break
            time.sleep(0.05)
        assert ad.read_memory(0x80402160, 8) == b"\x03" * 8, "the loop wrote the flags"
    finally:
        for c in T.GCHEATS.pop(sid, []):
            c["on"].clear()
        T.SESSIONS.pop(sid, None)


def test_dreamcast_profiles_unlock_every_flag_and_decode():
    """2026-10-19: DOA2 LE and SoulCalibur held and read back on the i9-NUC; SoulCalibur covers its whole flag table."""
    from gbox import cheats as C, game_unlocks as G
    doa2 = G.code_profile({"game_id": "1de2e7634f3161ff", "platform": "dreamcast"})
    sc = G.code_profile({"game_id": "c747331797369f74", "platform": "dreamcast"})
    assert doa2 and sc and doa2["verified"] and sc["verified"]
    assert G.code_profile({"game_id": "c747331797369f74", "platform": "gamecube"}) is None, "platform must match"
    ops, bad = C.decode("dreamcast", "\n".join(l for c in sc["codes"] for l in c["lines"]))
    assert not bad and [a for _k, a, _d in ops][:20] == [0x8C336DFA + 4 * i for i in range(1, 21)]
    assert all(d == b"\x01\x00" for _k, _a, d in ops[:20]) and ops[20][1:] == (0x8C336E54, b"\xff\xff")
    ops, bad = C.decode("dreamcast", "\n".join(l for c in doa2["codes"] for l in c["lines"]))
    assert not bad and len(ops) == 4
