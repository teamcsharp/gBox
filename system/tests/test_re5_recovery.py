"""Offline tests for the disabled RE5 recovery-progress helper (request #2984). No live memory is touched."""
import struct

import pytest

from gbox.mercs.titles import re5_recovery as RC

SP, PL, BTN, MAIN, GS, PARAM, STEP, PROF, CTRL = (0x3883_69C0, 0x303F_8A00, 0x35CB_5CA0, 0x3000_0020, 0x31EE_C3F0,
                                                   0x3883_63D0, 0x3800_1000, 0x3887_9660, 0x3500_0000)
DT = 0.03333336114883423


class Mem:
    def __init__(self):
        self.b = {}
        self.on_read = None
        self.reads = 0
        self.writes = []

    def put(self, a, data):
        for i, x in enumerate(data):
            self.b[a + i] = x

    def u32(self, a, v):
        self.put(a, struct.pack(">I", v))

    def f32(self, a, v):
        self.put(a, struct.pack(">f", v))

    def rd(self, a, n):
        self.reads += 1
        if self.on_read:
            self.on_read(self, self.reads)
        return bytes(self.b.get(a + i, 0) for i in range(n))

    def write(self, a, data):
        self.writes.append((a, data))
        self.put(a, data)
        return True


def dying(progress=2.0, **_):
    m = Mem()
    for a, sig in RC.SIGNATURES.items():
        m.put(a, sig)
    m.u32(RC.S_PLAYER, SP); m.u32(SP + 0x28, PL); m.u32(SP + RC.SPLAYER_FLAGS, 0)
    m.u32(RC.S_MAIN, MAIN); m.u32(MAIN + RC.MAIN_GAMESYS, GS); m.u32(GS + RC.GAMESYS_MODE, 5)
    m.u32(MAIN + RC.MAIN_FLAGS, 0)
    m.put(PL + RC.P_HP, struct.pack(">hh", 1, 1000)); m.f32(PL + RC.P_PROGRESS, progress)
    m.u32(RC.S_PROFILE, PROF); m.u32(PROF + RC.PROFILE_INDEX, 0)
    m.u32(RC.S_PARAMETER, PARAM); m.u32(RC.S_TIMESTEP, STEP)
    m.f32(PARAM + RC.PARAM_THRESHOLD, 15.0); m.f32(PARAM + RC.PARAM_INCREMENT, 13.0)
    m.f32(STEP + 0x2C, DT); m.f32(PL + RC.P_SCALE, 1.0)
    m.u32(PL + RC.P_BUTTON, BTN)
    m.u32(BTN, RC.BUTTON_VT); m.u32(BTN + 4, PL)
    m.put(BTN + RC.BUTTON_ACTIVE, b"\1")
    m.u32(BTN + RC.BUTTON_PLAYER, 0); m.u32(BTN + RC.BUTTON_MODE, 5); m.u32(BTN + RC.BUTTON_INDEX, 25)
    m.u32(BTN + RC.BUTTON_GEN, 0x28)
    return m


def rejected(m, **kw):
    with pytest.raises(RC.Reject):
        RC.plan_nudge(m, **kw)


def test_valid_plan_survives_next_decay_with_margin():
    plan = RC.plan_nudge(dying())
    assert plan.threshold == 15.0 and plan.target > plan.threshold + plan.decay
    assert plan.target < plan.threshold + 1.0           # not a huge unrelated constant
    assert plan.target - plan.decay > plan.threshold


@pytest.mark.parametrize("hp", [1000, 510, 3, 0, -5])
def test_healthy_and_hp0_rejected(hp):
    m = dying(); m.put(PL + RC.P_HP, struct.pack(">hh", hp, 1000)); rejected(m)


def test_small_max_hp_rejected():
    m = dying(); m.put(PL + RC.P_HP, struct.pack(">hh", 1, 2)); rejected(m)


def test_unsupported_build_signature():
    m = dying(); m.put(0x864328, b"\0" * 4); rejected(m)


@pytest.mark.parametrize("mode", [0, 3, 4, 6])
def test_unsupported_game_mode(mode):
    m = dying(); m.u32(GS + RC.GAMESYS_MODE, mode); rejected(m)


@pytest.mark.parametrize("flag", ["main", "splayer", "player"])
def test_blocking_flags(flag):
    m = dying()
    {"main": lambda: m.u32(MAIN + RC.MAIN_FLAGS, 0x2000_0000), "splayer": lambda: m.u32(SP + RC.SPLAYER_FLAGS, 4),
     "player": lambda: m.u32(PL + RC.P_FLAGS, 4)}[flag]()
    rejected(m)


def test_stale_player_button_generation_unit():
    rejected(dying(), player=PL + 4)                       # stale player
    m = dying(); m.u32(PL + RC.P_BUTTON, 0); rejected(m)  # no button
    m = dying(); m.u32(BTN, 0x1234_5678); rejected(m)     # stale VT
    m = dying(); m.u32(BTN + RC.BUTTON_INDEX, 24); rejected(m)  # different unit/request
    m = dying(); m.u32(BTN + RC.BUTTON_MODE, 4); rejected(m)    # mode4 is a different handler
    m = dying(); m.put(BTN + RC.BUTTON_ACTIVE, b"\0"); rejected(m)
    m = dying(); m.put(BTN + RC.BUTTON_CONSUMED, b"\1"); rejected(m)
    m = dying(); m.u32(BTN + RC.BUTTON_PLAYER, 1); rejected(m)


def test_mismatched_owner():
    m = dying(); m.u32(BTN + 4, PL + 0x100); rejected(m)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_invalid_threshold_timestep_scale_progress(bad):
    for setter in (lambda m: m.f32(PARAM + RC.PARAM_THRESHOLD, bad), lambda m: m.f32(STEP + 0x2C, bad),
                   lambda m: m.f32(PL + RC.P_SCALE, bad), lambda m: m.f32(PL + RC.P_PROGRESS, bad),
                   lambda m: m.f32(PARAM + RC.PARAM_INCREMENT, bad)):
        m = dying(); setter(m); rejected(m)


def test_partner_and_other_paths_rejected():
    for off in (RC.P_PARTNER, RC.P_PARTNER2):
        m = dying(); m.u32(PL + off, 0x3100_0000); rejected(m)
    m = dying(); m.u32(PL + RC.P_MODE, 2); rejected(m)
    m = dying(); m.u32(PL + RC.P_CONTROLLER, CTRL); m.u32(CTRL + RC.CONTROLLER_BUSY, 1); rejected(m)
    m = dying(); m.u32(RC.S_PROFILE, 0); rejected(m)
    m = dying(); m.u32(PROF + RC.PROFILE_INDEX, 1); rejected(m)


def test_already_above_threshold_no_rewrite():
    m = dying(progress=15.5)
    with pytest.raises(RC.NotNeeded):
        RC.plan_nudge(m)
    assert RC.RecoveryNudge().step(m, m.write, 0.0) is RC.Outcome.NOT_NEEDED and not m.writes


def test_lifetime_change_between_reads_rejected():
    m = dying()
    n = {}

    def swap(mem, count):
        if count == 140:                                    # lands inside the second, confirming snapshot
            mem.u32(PL + RC.P_BUTTON, BTN + 0x400); mem.u32(BTN + 0x400, RC.BUTTON_VT); mem.u32(BTN + 0x404, PL)
            mem.put(BTN + 0x400 + RC.BUTTON_ACTIVE, b"\1")
            mem.u32(BTN + 0x400 + RC.BUTTON_MODE, 5); mem.u32(BTN + 0x400 + RC.BUTTON_INDEX, 25)
    first = Mem.rd
    base = dying(); base.rd(0, 0); total = base.reads
    m.on_read = swap
    # find the swap point just after the first snapshot by probing: the first snapshot is half of all reads
    m.on_read = lambda mem, c: swap(mem, 140) if c == (total_reads(m) // 2 + 3) else None
    result = RC.RecoveryNudge().step(m, m.write, 0.0)
    assert result is RC.Outcome.REJECTED and not m.writes


def total_reads(_m):
    probe = dying()
    RC.plan_nudge(probe)
    return probe.reads


def test_one_shot_and_pending_then_recovered():
    m = dying(); nudge = RC.RecoveryNudge(timeout_s=2.0)
    assert nudge.step(m, m.write, 10.0) is RC.Outcome.WRITTEN
    assert len(m.writes) == 1 and m.writes[0][0] == PL + RC.P_PROGRESS
    written = struct.unpack(">f", m.writes[0][1])[0]
    assert written - DT > 15.0
    assert nudge.step(m, m.write, 10.5) is RC.Outcome.PENDING        # no second write, even though still dying
    # engine completes: HP>1, request gone; the helper never restores the countdown
    m.put(PL + RC.P_HP, struct.pack(">hh", 3, 1000)); m.put(BTN + RC.BUTTON_ACTIVE, b"\0")
    m.f32(PL + RC.P_PROGRESS, 0.0)
    assert nudge.step(m, m.write, 11.0) is RC.Outcome.RECOVERED
    assert len(m.writes) == 1
    assert nudge.step(m, m.write, 12.0) is RC.Outcome.RECOVERED and len(m.writes) == 1


def test_timeout_is_a_failure_and_hp_alone_is_not_recovery():
    m = dying(); nudge = RC.RecoveryNudge(timeout_s=2.0)
    nudge.step(m, m.write, 0.0)
    m.put(PL + RC.P_HP, struct.pack(">hh", 3, 1000))                  # HP up but the request is still active
    assert nudge.step(m, m.write, 1.0) is RC.Outcome.PENDING
    assert nudge.step(m, m.write, 2.5) is RC.Outcome.TIMEOUT
    assert len(m.writes) == 1


def test_second_use_never_rewrites_and_failed_write_is_reported():
    m = dying(); nudge = RC.RecoveryNudge()
    nudge.step(m, m.write, 0.0); m.writes.clear()
    nudge2 = RC.RecoveryNudge()
    assert nudge2.step(m, lambda a, d: False, 0.0) is RC.Outcome.NOT_NEEDED   # already above threshold now
    m2 = dying(); n3 = RC.RecoveryNudge()
    assert n3.step(m2, lambda a, d: False, 0.0) is RC.Outcome.WRITE_FAILED
    assert n3.step(m2, m2.write, 1.0) is RC.Outcome.REJECTED and not m2.writes


def test_bad_timeout_and_nan_time():
    with pytest.raises(ValueError):
        RC.RecoveryNudge(timeout_s=float("nan"))
    m = dying()
    assert RC.RecoveryNudge().step(m, m.write, float("nan")) is RC.Outcome.REJECTED and not m.writes


def test_unreadable_memory_is_rejected_not_raised():
    class Boom(Mem):
        def rd(self, a, n):
            raise OSError("unreadable")
    assert RC.RecoveryNudge().step(Boom(), lambda a, d: True, 0.0) is RC.Outcome.REJECTED
