"""Soul Calibur II perfect-defence playbook (gbox.sc2_bot): RAM decoding, hit levels, the GI / guard / duck / step
decisions and their timing, punishing, the move book, and the RAM map it shares its addresses with."""
import json
import struct
from pathlib import Path

import pytest

from gbox import ram_map
from gbox import sc2_bot as S

FIXTURES = Path(__file__).parent / "fixtures" / "sc2_bot.json"
MAP = Path(__file__).resolve().parent.parent / "profiles" / "gamedata" / "GRSEAF-ram.json"


# -- a fake MEM1 holding two fighter structs -----------------------------------------------------------------------------
class Ram:
    def __init__(self):
        self.b = bytearray(0x1800000)

    def put(self, a, data):
        o = a - 0x80000000
        self.b[o:o + len(data)] = data

    def rd(self, a, n):
        o = (a & 0x1FFFFFF)
        return bytes(self.b[o:o + n])

    def fighter(self, base, *, side=1, back=0, crouch=0, hp=240.0, result=0, dist=1.5, m0=0, m1=S.NEUTRAL,
                f=0.0, speed=1.0, atk=None, connected=0, fighter=21, rounds=0, ctl=1, queued=None, queued_at=0.0,
                alt=()):
        """queued / alt: (move id, (flags, start, end) or None) continuations, built into a fake moveset."""
        self.put(base + S.SIDE, bytes([side]))
        moveset = 0x80800000 + (base & 0xFFFF) * 0x10
        self.put(base + S.MOVESET, struct.pack(">I", moveset))
        bank = moveset + 0x28                                   # bank 0: moves at 0x80900000, attacks at 0x80A00000
        self.put(bank + 8, struct.pack(">I", 0x80900000 + (base & 0xFFFF) * 0x10))
        self.put(bank + 0x10, struct.pack(">I", 0x80A00000 + (base & 0xFFFF) * 0x10))
        conts = [queued] + list(alt) + [None] * (3 - len(alt))
        for i, c in enumerate(conts[:4]):
            self.put(base + S.LAYER1 + S.L_QUEUED + 2 * i, struct.pack(">H", c[0] if c else S.NEUTRAL))
            if c:
                mv, rec = c
                moves, atks = 0x80900000 + (base & 0xFFFF) * 0x10, 0x80A00000 + (base & 0xFFFF) * 0x10
                self.put(moves + (mv & 0xFFF) * 0x60 + 0x58, struct.pack(">h", i if rec else -1))
                if rec:
                    self.put(atks + i * 0x60 + S.R_FLAGS, struct.pack(">HHhhh", rec[0], 1, rec[1], rec[2], 30))
        self.put(base + S.LAYER1 + S.L_QUEUED_AT, struct.pack(">f", queued_at))
        self.put(base + S.CTL, struct.pack(">I", ctl))
        self.put(base + S.F_BACK, bytes([back]))
        self.put(base + S.F_CROUCH, bytes([crouch]))
        self.put(base + S.F_CONNECTED, bytes([connected]))
        self.put(base + S.FIGHTER, struct.pack(">h", fighter))
        self.put(base + S.ROUNDS, bytes([rounds]))
        self.put(base + S.HP, struct.pack(">f", hp))
        self.put(base + S.RESULT, struct.pack(">i", result))
        self.put(base + S.DIST, struct.pack(">f", dist))
        self.put(base + S.LAYER0 + S.L_MOVE, struct.pack(">H", m0))
        self.put(base + S.LAYER1 + S.L_MOVE, struct.pack(">H", m1))
        self.put(base + S.LAYER1 + S.L_NOW, struct.pack(">f", f))
        self.put(base + S.LAYER1 + S.L_NEXT, struct.pack(">f", f + speed))
        rec = 0x81000000 + (base & 0xFFFF) * 0x10
        if atk is None:
            self.put(base + S.ATTACK, struct.pack(">I", 0))
        else:
            flags, start, end = atk
            self.put(base + S.ATTACK, struct.pack(">I", rec))
            self.put(rec + S.R_FLAGS, struct.pack(">HHhhh", flags, 1, start, end, 20))

    def fight(self, on=True):
        self.put(S.FIGHT, struct.pack(">H", 1 if on else 0))


def snap(p1=None, p2=None, fight=True):
    r = Ram()
    r.fight(fight)
    r.fighter(S.P1, **(p1 or {}))
    r.fighter(S.P2, **{"side": 0, **(p2 or {})})
    return S.snapshot(r.rd)


# -- hit levels ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("flags,kind", [(0x49, "high"), (0x09, "high"), (0x4B, "mid"), (0x6F, "mid"), (0x37, "low"),
                                        (0x13, "low"), (0x1B, "special_mid"), (0x5B, "special_mid"), (0x81, "throw"),
                                        (0xC1, "throw"), (0x03, "unblockable"), (0x43, "unblockable"),
                                        (0x00, "none"), (0x40, "none")])
def test_classify(flags, kind):
    assert S.classify(flags) == kind


def test_snapshot_decodes_both_fighters():
    s = snap({"hp": 228.0, "result": 4, "dist": 1.25, "m1": 0x8A, "f": 3.0}, {"atk": (0x49, 13, 15), "f": 7.0, "m1": 0xBF})
    assert s["fight"] and s["p1"]["hp"] == 228.0 and s["p1"]["result"] == 4 and s["p1"]["m1"] == 0x8A
    assert s["p1"]["dist"] == 1.25 and s["p2"]["dist"] == 1.5
    assert s["p2"]["atk"]["flags"] == 0x49 and s["p2"]["atk"]["start"] == 13 and s["p2"]["atk"]["end"] == 15
    assert s["p2"]["speed"] == pytest.approx(1.0)


def test_threat_timing_with_speed_and_connection():
    s = snap(p2={"atk": (0x4B, 21, 23), "f": 15.0, "speed": 1.5})
    th = S.threat(s["p2"])
    assert th["kind"] == "mid" and th["t"] == pytest.approx(4.0) and th["te"] == pytest.approx(16 / 3)
    assert S.threat(snap(p2={"atk": (0x4B, 21, 23), "f": 15.0, "connected": 1})["p2"]) is None    # already hit / guarded
    assert S.threat(snap(p2={"atk": (0x4B, 21, 23), "f": 24.0})["p2"]) is None                      # past its last frame
    assert S.threat(snap()["p2"]) is None


def test_no_fight_no_keys():
    assert S.Brain().decide(snap(fight=False), 0.0) == set()
    s = snap({"ctl": 3}, {"atk": (0x4B, 13, 15), "f": 8.0})          # the attract demo: the CPU drives P1
    assert not s["fight"] and S.Brain().decide(s, 0.0) == set()


LEAD = S.GI_AT                                     # no send latency measured: decide a GI this many frames ahead


def test_stand_ready_and_wait_for_the_gi():
    b = S.Brain()
    assert b.decide(snap(), 0.0) == set()                                          # nothing coming: no G held
    assert b.decide(snap(p2={"atk": (0x49, 30, 32), "f": 10.0}), 0.01) == set()    # 20 frames out, impactable: wait
    assert b.decide(snap({"m1": 0x21A3}), 0.02) == {S.G}                           # guard stun: keep guarding


def test_repel_a_high_with_one_press():
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x49, 13, 15), "f": 13 - LEAD - 1.0}), 0.0) == set()
    keys = b.decide(snap(p2={"atk": (0x49, 13, 15), "f": 13 - LEAD}), 0.017)
    assert keys == {"right", S.G} and b.phase == "press" and b.stats["gi_tried"] == 1   # 6G: P1 on the left
    assert b.decide(snap(p2={"atk": (0x49, 13, 15), "f": 13 - LEAD + 1}), 0.034) == {"right", S.G}
    assert b.phase == "gi"
    # the GI move shows: latency measured (frames after the game's own one)
    b.decide(snap({"m1": 0x8A, "f": 0.0}, {"atk": (0x49, 13, 15), "f": 13 - LEAD + 2}), 0.051)
    assert b.gi_lat == pytest.approx((0.051 - 0.017) * 60 - 1)


def test_a_held_guard_is_let_go_first():
    b = S.Brain()
    b.wanted = {S.G}                                                               # guarding when the attack comes
    lead = b.gi_lead(True)
    assert lead == pytest.approx(LEAD + S.REGRAB_S / S.FRAME_S)
    assert b.decide(snap(p2={"atk": (0x4B, 20, 22), "f": 20 - lead - 1}), 0.0) == {S.G}
    assert b.decide(snap(p2={"atk": (0x4B, 20, 22), "f": 20 - lead}), 0.02) == set() and b.phase == "regrab"
    assert b.decide(snap(p2={"atk": (0x4B, 20, 22), "f": 20 - lead + 1}), 0.03) == set()   # still letting go
    assert b.decide(snap(p2={"atk": (0x4B, 20, 22), "f": 20 - lead + 3}), 0.02 + S.REGRAB_S + 0.001) == {"right", S.G}


def test_forward_follows_the_side_and_the_back_turn():
    b = S.Brain()
    assert b.decide(snap({"side": 0}, {"side": 1, "atk": (0x4B, 13, 15), "f": 13 - LEAD}), 0.0) == {"left", S.G}
    assert S.directions({"side": 1, "back": 1, "m1": S.NEUTRAL}) == ("left", "right")      # facing away: flipped
    assert S.directions({"side": 1, "back": 1, "m1": 0x23AB, "screen_side": 0}) == ("left", "right")
    b = S.Brain()                                      # facing away: no GI (G turns P1 round), guard instead
    assert b.decide(snap({"side": 1, "back": 1}, {"atk": (0x4B, 13, 15), "f": 13 - LEAD}), 0.0) == {S.G}


def test_too_late_for_a_gi_guards_instead():
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x4B, 13, 15), "f": 12.0}), 0.0) == {S.G}       # one frame to impact
    assert b.decide(snap(p2={"atk": (0x37, 13, 15), "f": 12.0}), 0.0) == {"down", S.G}
    assert b.phase == "guard"


def test_gi_that_does_not_come_out_falls_back_to_the_guard():
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x37, 26, 27), "f": 26 - LEAD}), 0.0) == {"left", S.G}   # 4G
    assert b.decide(snap(p2={"atk": (0x37, 26, 27), "f": 26 - LEAD + 1}), 0.017) == {"left", S.G}
    keys = b.decide(snap({"m0": 7}, {"atk": (0x37, 26, 27), "f": 26 - LEAD + 4}), 0.017 + S.GI_CONFIRM_S + 0.01)
    assert keys == {"down", S.G} and b.stats["gi_failed"] == 1                      # no parry move: crouch guard


def test_low_is_parried_from_standing_and_crouch_guarded_otherwise():
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x37, 26, 27), "f": 10.0}), 0.0) == set()      # stand until it is time
    assert b.decide(snap(p2={"atk": (0x37, 26, 27), "f": 26 - LEAD}), 0.05) == {"left", S.G}   # 4G: back = left
    b = S.Brain()                                                                     # already crouching: crouch guard
    assert b.decide(snap({"crouch": 1}, {"atk": (0x37, 26, 27), "f": 26 - LEAD}), 0.0) == {"down", S.G}
    b = S.Brain()                                                                     # busy (guard stun): crouch guard
    assert b.decide(snap({"m1": 0x21B2}, {"atk": (0x37, 26, 27), "f": 10.0}), 0.0) == {"down", S.G}


def test_throws_are_ducked_and_repelled_from_a_stagger():
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x81, 15, 15), "f": 1.0}), 0.0) == set()
    assert b.decide(snap(p2={"atk": (0x81, 15, 15), "f": 15 - S.DUCK_LEAD}), 0.05) == {"down", S.G}
    assert b.stats["ducks"] == 1
    b = S.Brain()
    keys = b.decide(snap({"m1": 0x23AB, "f": 45.0, "back": 1}, {"atk": (0x81, 15, 15), "f": 15 - LEAD}), 0.0)
    # the back-turn of the parried stagger does not flip forward (live: 6G from 0x23AB with the screen side's forward
    # came out as a Repel at every frame, the side-XOR-back key as a Parry)
    assert b.gi_dirs == "fwd" and keys == {"right", S.G}


def test_unblockables_are_sidestepped():
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x03, 50, 52), "f": 10.0}), 0.0) == set()
    assert b.decide(snap(p2={"atk": (0x03, 50, 52), "f": 50 - S.STEP_LEAD}), 0.1) == {"up"}
    assert b.stats["steps"] == 1


def test_unblockable_that_misses_a_crouching_fighter_is_ducked():
    # Astaroth's 0x41 thrust: hits standing / downed only, no guard bits: crouch under it instead of sidestepping
    assert S.classify(0x41) == "unblockable"
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x41, 50, 52), "f": 10.0}), 0.0) == set()
    assert b.decide(snap(p2={"atk": (0x41, 50, 52), "f": 50 - S.DUCK_LEAD}), 0.1) == {"down", S.G}
    assert b.stats["ducks"] == 1 and b.stats["steps"] == 0
    # one that reaches a crouching fighter (0x03) is still sidestepped
    b = S.Brain()
    assert b.decide(snap(p2={"atk": (0x03, 50, 52), "f": 50 - S.STEP_LEAD}), 0.0) == {"up"}


def test_no_gi_when_busy_far_or_flagged():
    for p1, p2 in (({"m1": 0x21A3}, {}), ({}, {"dist": S.GI_RANGE + 0.5}), ({}, {"atk": (0x14B, 13, 15)})):
        b = S.Brain()
        p2 = {"atk": (0x4B, 13, 15), "f": 13 - LEAD, **p2}
        assert b.decide(snap(p1, p2), 0.0) == {S.G}, (p1, p2)


def test_no_gi_on_slow_windups_and_long_active_windows():
    b = S.Brain()                                                  # clock at a tenth of the speed: guard it
    assert b.decide(snap(p2={"atk": (0x6F, 14, 16), "f": 13.6, "speed": 0.1}), 0.0) == {S.G}
    b = S.Brain()                                                  # active 24-34: it can land anywhere in it
    assert b.decide(snap(p2={"atk": (0x37, 24, 34), "f": 24 - LEAD}), 0.0) == {"down", S.G}


def test_a_gi_waits_again_when_the_attack_slows_down():
    b = S.Brain()
    b.wanted = {S.G}
    lead = b.gi_lead(True)
    assert b.decide(snap(p2={"atk": (0x6F, 14, 16), "f": 14 - lead}), 0.0) == set() and b.phase == "regrab"
    # by the press the move winds up at 0.1 a frame: not yet (no keys), no GI counted
    assert b.decide(snap(p2={"atk": (0x6F, 14, 16), "f": 14 - lead + 1, "speed": 0.1}), S.REGRAB_S + 0.01) == set()
    assert b.phase == "guard" and b.stats["gi_tried"] == 0


def test_queued_follow_up_is_timed_before_it_starts():
    # P2 in a move at frame 10 that hands over to 0x168 at frame 14; 0x168 hits on its own frame 2: 6 frames away
    s = snap(p2={"m1": 0x167, "f": 10.0, "queued": (0x168, (0x7F, 2, 9)), "queued_at": 14.0})
    th = S.threat(s["p2"])
    assert th["queued"] and th["move"] == 0x168 and th["t"] == pytest.approx(6.0) and th["kind"] == "special_mid"
    s = snap(p2={"m1": S.NEUTRAL, "f": 40.0, "queued": (0x14E, (0x4B, 25, 27)), "queued_at": 8.0})
    assert S.threat(s["p2"])["t"] == pytest.approx(25.0)                     # from neutral it starts at once


def test_gi_a_queued_attack_once():
    b = S.Brain()
    p2q = {"m1": 0x167, "f": 14.0 - (LEAD - 2), "queued": (0x168, (0x7F, 2, 5)), "queued_at": 14.0}
    assert b.decide(snap(p2=p2q), 0.0) == {"right", S.G} and b.gi_ptr is not None
    # it starts: same record, now current, 1 frame in: no second GI for it
    p2c = {"m1": 0x168, "f": 1.0, "atk": (0x7F, 2, 5)}
    r = Ram()
    r.fight(True)
    r.fighter(S.P1)
    r.fighter(S.P2, side=0, **p2c)
    # the current record must be the queued one: point +0x1690 at it
    rec = 0x80A00000 + (S.P2 & 0xFFFF) * 0x10
    r.put(S.P2 + S.ATTACK, struct.pack(">I", rec))
    r.put(rec + S.R_FLAGS, struct.pack(">HHhhh", 0x7F, 1, 2, 5, 30))
    b.decide(S.snapshot(r.rd), 0.05)
    assert b.stats["gi_tried"] == 1 and b.gi_inst == b.inst


def test_long_active_window_is_timed_on_the_learned_contact_frame():
    book = S.MoveBook(cautious=False)
    b = S.Brain(book=book)
    p2 = {"atk": (0x37, 24, 34), "f": 24 - LEAD, "m1": 0x14A, "fighter": 1}
    assert b.decide(snap(p2=p2), 0.0) == {"down", S.G}                      # first sight: crouch guard it
    for at in (7, 7, 8):
        book.contact(1, 0x14A, at)                                          # it reached P1 7-8 frames in
    b = S.Brain(book=book)
    assert b.decide(snap(p2=p2), 0.0) == set()                              # not yet: it lands at 31
    assert b.decide(snap(p2=dict(p2, f=31 - LEAD)), 0.02) == {"left", S.G}  # parry timed on frame 31


def test_step_out_of_a_string_whose_next_part_is_unblockable():
    b = S.Brain()
    # the current part (a mid) is 1 frame from hitting: too late to impact; the next part is unblockable
    p2 = {"m1": 0x168, "f": 1.0, "atk": (0x7F, 2, 9), "queued": (0x169, (0x47, 3, 9)), "queued_at": 9.0}
    assert b.decide(snap(p2=p2), 0.0) == {"up"} and b.stats["steps"] == 1
    # nothing current, the queued part unblockable: step when it is close
    b = S.Brain()
    p2 = {"m1": 0x167, "f": 2.0, "queued": (0x169, (0x47, 3, 9)), "queued_at": 9.0}
    assert b.decide(snap(p2=p2), 0.0) == {"up"}
    # an unblockable only among the alternatives (the continuation on a hit) counts too
    p2 = {"m1": 0x17B, "f": 20.0, "queued": (0x17C, (0x4B, 38, 42)), "alt": [(0x17D, (0x43, 3, 6))], "queued_at": 23.0}
    assert S.queued_unblockable(snap(p2=p2)["p2"])["t"] == pytest.approx(6.0)


def test_staggered_p1_tries_a_gi_even_late():
    b = S.Brain()
    assert b.decide(snap({"m1": 0x23A4, "f": 30.0}, {"atk": (0x49, 13, 15), "f": 12.0}), 0.0) == {"right", S.G}


def test_landed_gi_is_punished_once_p1_can_act():
    b = S.Brain()
    b.decide(snap(p2={"atk": (0x49, 13, 15), "f": 13 - LEAD}), 0.0)
    b.decide(snap(p2={"atk": (0x49, 13, 15), "f": 9.0}), 0.02)
    assert b.decide(snap({"m1": 0x8A, "f": 4.0, "result": 11}, {"m1": 0x2000, "dist": 1.2}), 0.1) == set()
    assert b.phase == "punish" and b.stats["gi"] == 1
    assert b.decide(snap({"m1": 0x8C, "f": 10.0}, {"m1": 0x23A4, "f": 6.0, "dist": 1.2}), 0.2) == set()
    assert b.decide(snap({"m1": 0x8C, "f": float(S.GI_ACT_FRAME)}, {"m1": 0x23A4, "f": 20.0, "dist": 1.2}), 0.45) \
        == set(S.PUNISH_KEYS)
    assert b.stats["punishes"] == 1
    # no G while the punish is starting (G cancels it), then G again once it is out
    assert b.decide(snap({"m1": 0xC8, "f": 2.0, "atk": None}, {"m1": 0x23A4, "f": 23.0}), 0.6) == set()


def test_hits_and_guards_are_counted():
    b = S.Brain()
    b.decide(snap(), 0.0)
    b.decide(snap({"result": 1}), 0.02)
    b.decide(snap({"result": 4, "hp": 228.0}, {"atk": (0x49, 13, 15), "f": 14.0}), 0.04)
    assert b.stats["guards"] == 1 and b.stats["hits_taken"] == 1 and b.stats["damage_taken"] == pytest.approx(12.0)


def test_sender_applies_the_newest_keys_off_the_poll_thread():
    import threading
    import time as _t
    sent, gate = [], threading.Event()

    def slow_send(rows):
        gate.wait(1.0)
        sent.append(rows)
    k = S.Sender(slow_send)
    k.hold({S.G})
    k.hold({"right", S.G})                                   # newer wish while the first send still runs
    gate.set()
    for _ in range(100):
        if k.held == {"right", S.G}:
            break
        _t.sleep(0.01)
    k.close()
    downs = [e["key"] for rows in sent for e in rows if e["down"]]
    assert k.held == set() and "right" in downs and downs.count(S.G) == 1


def test_move_book_stops_impacting_feints():
    book = S.MoveBook(cautious=False)
    assert book.ok(21, 0x13C, 1.0)
    book.record(21, 0x13C, False, 0.6)
    assert book.ok(21, 0x13C, 1.0)
    book.record(21, 0x13C, False, 0.6)
    assert not book.ok(21, 0x13C, 1.0)                     # missed twice and never landed: guard it
    for _ in range(9):
        book.record(21, 0xBF, True, 1.4)
    book.record(21, 0xBF, False, 2.2)
    assert book.ok(21, 0xBF, 1.5) and not book.ok(21, 0xBF, 2.0)   # beyond where it ever landed
    b = S.Brain(book=book)
    assert b.decide(snap(p2={"atk": (0x4B, 22, 24), "f": 22 - S.GI_LEAD, "m1": 0x13C, "fighter": 21}), 0.0) == {S.G}


def test_move_book_learns_reach_from_attacks_it_did_not_impact():
    book = S.MoveBook(cautious=False)
    for _ in range(4):
        book.observe(21, 0x140, True, 1.4)                 # guarded from 1.4
    book.observe(21, 0x140, False, 2.1)                    # met nothing from 2.1
    assert book.ok(21, 0x140, 1.5) and not book.ok(21, 0x140, 1.9)
    book.observe(21, 0x13C, False, 0.7)
    book.observe(21, 0x13C, False, 0.8)                    # never touched P1 even close in: a feint
    assert not book.ok(21, 0x13C, 0.6)


def test_brain_books_attacks_that_end_untouched():
    b = S.Brain()
    b.wanted = {S.G}
    # a far attack the brain only guards (P1 busy), decided at 1.6, that ends without touching P1, then another
    for f in (0.0, 10.0, 14.0, 16.0):
        b.decide(snap({"m1": 0x21A3}, {"atk": (0x4B, 20, 22), "f": f, "m1": 0x140, "dist": 1.6}), f / 60)
    b.decide(snap({"m1": 0x21A3}, {"m1": 0x141, "dist": 1.6}), 0.5)
    assert b.book.moves[S.MoveBook.key(21, 0x140)]["none"] == 1


def test_cautious_book_guards_a_move_until_it_has_reached_p1(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"moves": {S.MoveBook.key(21, 0xBF): {"land": 3, "miss": 0, "contact": 2, "none": 0,
                                                                       "reach": 1.6}}}), encoding="utf-8")
    book = S.MoveBook(tmp_path / "mine.json", seed=seed)
    assert not book.ok(21, 0x140, 1.0)                     # never seen: guard it first
    assert book.ok(21, 0xBF, 1.5) and not book.ok(21, 0xBF, 1.9)    # from the seed: impact within its reach
    book.observe(21, 0x140, True, 1.2)                     # guarded once from 1.2: impact it from there
    assert book.ok(21, 0x140, 1.2) and not book.ok(21, 0x140, 1.6)
    b = S.Brain(book=S.MoveBook(cautious=True))
    assert b.decide(snap(p2={"atk": (0x4B, 13, 15), "f": 13 - LEAD, "m1": 0x150}), 0.0) == {S.G}


def test_move_book_judges_by_distance():
    book = S.MoveBook(cautious=True)
    for _ in range(3):
        book.observe(11, 0x15E, True, 1.6)                 # Ivy's whip reaches P1 from 1.6 ...
    book.record(11, 0x15E, False, 0.9)                     # ... but a GI up close met nothing, twice
    book.record(11, 0x15E, False, 0.85)
    assert book.ok(11, 0x15E, 1.55) and not book.ok(11, 0x15E, 0.9)


def test_move_book_round_trip(tmp_path):
    p = tmp_path / "learned" / "movebook.json"
    book = S.MoveBook(p)
    book.record(21, 0xF0, True, 1.1)
    book.save()
    assert S.MoveBook(p).moves == book.moves


def test_play_holds_keys_and_presses_on_between_fights():
    r = Ram()
    r.fighter(S.P1)
    r.fighter(S.P2, side=0)
    r.fight(True)
    sent, now, polls = [], [0.0], [0]

    def stopped():
        polls[0] += 1
        if polls[0] == 3:
            r.fight(False)
        return polls[0] > 400

    def sleep(s):
        now[0] += s
    r.fighter(S.P1, m1=0x21A3)                                # guard stun: guard
    stats = S.play(None, sent.append, stopped, sleep=sleep, clock=lambda: now[0], m=r, learn_dir=None,
                   brain=S.Brain(), threaded=False)
    downs = [e["key"] for rows in sent for e in rows if e["down"]]
    assert downs[0] == S.G and S.A in downs                       # guard in the fight, A on the screens after it
    assert stats["fights"] == 1 and stats["menu_presses"] >= 1


def test_matches_by_game_id():
    assert S.matches(None, {"platform": "gamecube", "game_id": "201629ad498aba7b"})
    assert not S.matches(None, {"platform": "dreamcast", "game_id": "201629ad498aba7b"})


# -- the RAM map: the bot's offsets are the map's fields -----------------------------------------------------------------
def test_ram_map_loads_and_agrees_with_the_bot():
    assert ram_map.check(MAP) == []
    m = ram_map.load(MAP)
    f = m.fields
    for who, base in (("p1", S.P1), ("p2", S.P2)):
        assert f[f"{who}.hp"].address == base + S.HP
        assert f[f"{who}.hit_result"].address == base + S.RESULT
        assert f[f"{who}.distance"].address == base + S.DIST
        assert f[f"{who}.side"].address == base + S.SIDE
        assert f[f"{who}.back_turned"].address == base + S.F_BACK
        assert f[f"{who}.crouching"].address == base + S.F_CROUCH
        assert f[f"{who}.attack_connected"].address == base + S.F_CONNECTED
        assert f[f"{who}.fighter"].address == base + S.FIGHTER
        assert f[f"{who}.rounds"].address == base + S.ROUNDS
        assert f[f"{who}.move"].address == base + S.LAYER1 + S.L_MOVE
        assert f[f"{who}.move_stance"].address == base + S.LAYER0 + S.L_MOVE
        assert f[f"{who}.move_frame"].address == base + S.LAYER1 + S.L_NOW
        assert f[f"{who}.move_next_frame"].address == base + S.LAYER1 + S.L_NEXT
        assert f[f"{who}.guard_impact"].address == base + S.GI_TYPE
        assert f[f"{who}.move_queued"].address == base + S.LAYER1 + S.L_QUEUED
        assert f[f"{who}.move_queued_at"].address == base + S.LAYER1 + S.L_QUEUED_AT
        assert f[f"{who}.moveset"].address == base + S.MOVESET
        assert f[f"{who}.control"].address == base + S.CTL
        assert f[f"{who}.attack"].address == base + S.ATTACK
        for name, off in (("flags", S.R_FLAGS), ("kind", S.R_KIND), ("start", S.R_START), ("end", S.R_END),
                          ("damage", S.R_DAMAGE)):
            assert (f[f"{who}_attack.{name}"].base, f[f"{who}_attack.{name}"].offsets) == (base + S.ATTACK, [off])
    assert f["game.frame"].address == S.FRAME and f["game.fight"].address == S.FIGHT
    assert ram_map.resolve("201629ad498aba7b") == "GRSEAF" and ram_map.resolve("e08e8a0c1b3c9060") == "GRSEAF"


def test_ram_map_reads_a_snapshot():
    r = Ram()
    r.fight(True)
    r.fighter(S.P1, hp=200.0, result=11, m1=0x8A)
    r.fighter(S.P2, side=0, atk=(0x37, 26, 27), f=20.0, fighter=21)
    v = ram_map.load(MAP).read(r.rd)
    assert v["p1.hp"] == 200.0 and v.label("p1.hit_result") == "Guard Impacted it (repel)"
    assert v["p2_attack.flags"] == 0x37 and v["p2_attack.start"] == 26 and v.label("p2.fighter") == "Raphael"


# -- recorded RAM (the live game) ----------------------------------------------------------------------------------------
class ReadsMem:
    """RAM recorded on the Spark (every read snapshot() made at that poll, address -> bytes): serves those reads only."""

    def __init__(self, reads):
        self.regions = [(int(a, 16), bytes.fromhex(h)) for a, h in reads]

    def rd(self, a, n):
        for base, b in self.regions:
            if base <= a and a + n <= base + len(b):
                return b[a - base:a - base + n]
        raise KeyError(f"{a:#x}+{n} was not recorded")


def cases():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["name"])
def test_recorded_moment(case):
    s = S.snapshot(ReadsMem(case["reads"]).rd)
    for k, v in case["p1"].items():
        assert s["p1"][k] == pytest.approx(v), k
    for k, v in case["p2"].items():
        assert s["p2"][k] == pytest.approx(v), k
    th = S.threat(s["p2"])
    if case["threat"]:
        assert th["kind"] == case["threat"]["kind"] and th["t"] == pytest.approx(case["threat"]["t"])
    if case["phase_before"] == "guard":                     # a fresh brain in the same state decides the same
        from types import SimpleNamespace
        b = S.Brain()
        b.out = SimpleNamespace(held=set(case["held_before"]), applied_at=0.0, latency_s=case["out_latency_s"])
        b.wanted, b.gi_lat = set(case["held_before"]), case["gi_lat"]
        keys = b.decide(s, 0.0)
        assert sorted(keys) == case["keys"] and b.phase == case["phase_after"], case["name"]
