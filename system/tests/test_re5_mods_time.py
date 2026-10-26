"""RE5 timer operations, including the recorded native aGame -> HUD overwrite that defeated HUD-only bonuses."""
import struct
import pytest

from gbox import re5_mods_tool as T
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401

MAIN, GS, SU, HG = 0x3000_0020, 0x31EE_C3F0, 0x3100_0000, 0x3200_0000
AREA, GAME = 0x387E_CFE0, 0x31FD_D670


def with_round(m, clock=90.0, hourglass_seconds=30):
    m.u32(T.S_MAIN, MAIN)
    m.u32(MAIN + T.MAIN_GAMESYS, GS)
    m.u32(GS+0x58,2)
    m.f32(GS + T.GS_CLOCK, clock)
    m.f32(GS + T.GS_BONUS_TOTAL, 5.0)
    m.u32(T.S_AREA, AREA)
    m.u32(AREA, T.AREA_VT)
    m.u32(AREA + T.AREA_GAME, GAME)
    m.u32(GAME, T.GAME_VT)
    m.f32(GAME + T.GAME_CLOCK, clock)
    m.u32(T.S_UNIT, SU)
    m.u32(SU + T.UNIT_LINES + T.LINE_STRIDE * T.OM_LINE + T.LINE_FIRST, HG)
    m.u32(HG, T.HOURGLASS_VT)
    m.put(HG + T.HG_SECONDS, struct.pack(">h", hourglass_seconds))
    m.u32(T.MELEE_BONUS_SITE, T.MELEE_BONUS_ORIG)
    return m


def test_add_time_adds_to_the_clock_and_shows_the_bonus_on_the_hud():
    m = with_round(FakeRE5())
    r = T.run(m, "add_time", seconds=60)
    assert r["verified"] and r["clock_before"] == 90.0 and r["clock_after"] == 150.0 and r["added_seconds"] == 60
    assert struct.unpack(">i", m.read_memory(GS + T.GS_LAST_BONUS, 4))[0] == 60 and m.read_memory(GS + T.GS_SHOW_BONUS, 1) == b"\x01"
    assert m.rf(GAME + T.GAME_CLOCK) == 150.0
    assert m.rf(GS + T.GS_BONUS_TOTAL) == 5.0  # this offset is NOT the countdown in cGameSys
    m.f32(GS + T.GS_CLOCK, m.rf(GAME + T.GAME_CLOCK))  # native next-frame HUD publication
    assert T.run(m, "add_minute")["clock_after"] == 210.0                      # the alias, default a minute


def native_countdown(m, dt=.033):
    remaining = max(0.0, m.rf(GAME + T.GAME_CLOCK) - dt)
    m.f32(GAME + T.GAME_CLOCK, remaining)
    m.f32(GS + T.GS_CLOCK, remaining - dt)


def test_kill_bonus_survives_the_native_hud_refresh_and_is_counted_once():
    m=with_round(FakeRE5(), clock=60)
    T.run(m, 'kill_time', multiplier=10)
    T.maintain_kill_time(m)
    m.u32(GS + T.GS_KILLS, 2)
    result=T.maintain_kill_time(m)
    assert result['verified'] and result['added']==20
    for _ in range(30):native_countdown(m)
    assert 78 < m.rf(GS+T.GS_CLOCK) < 80
    assert T.maintain_kill_time(m)['added']==0
    assert (GS+T.GS_CLOCK,4) not in m.writes


def test_a_hud_only_write_disappears_on_the_recorded_native_update():
    m=with_round(FakeRE5(),clock=60)
    m.f32(GS+T.GS_CLOCK,70)
    native_countdown(m)
    assert m.rf(GS+T.GS_CLOCK)<60


@pytest.mark.parametrize('corrupt', ['area', 'owner', 'owner_state', 'clock', 'expired', 'story'])
def test_unknown_or_inactive_owner_never_falls_back_to_a_hud_only_write(corrupt):
    m=with_round(FakeRE5(),clock=60)
    if corrupt=='area':m.u32(AREA,0x1234)
    elif corrupt=='owner':m.u32(GAME,0x1234)
    elif corrupt=='owner_state':m.u32(GAME+T.GAME_CLOCK_STATE,1)
    elif corrupt=='clock':m.f32(GAME+T.GAME_CLOCK,30)
    elif corrupt=='story':m.u32(GS+0x58,0)
    else:m.f32(GS+T.GS_CLOCK,0)
    m.writes.clear()
    with pytest.raises(RuntimeError):T.add_time(T.RE5(m),10)
    assert m.writes==[]


def test_operator_ten_seconds_survives_an_older_round_profile():
    m=with_round(FakeRE5());g=T.RE5(m)
    assert T.run(m,'kill_time',multiplier=10,operator=True,g=g)['seconds']==10
    result=T.run(m,'kill_time',seconds=2,seconds_max=5,g=g)
    assert result['seconds']==result['seconds_max']==10


def test_time_bonus_multiplier_scales_the_standing_hourglasses_once_and_reads_the_melee_patch():
    m = with_round(FakeRE5(), hourglass_seconds=60)
    r = T.run(m, "time_bonus_multiplier", multiplier=10)
    assert r["verified"] and r["hourglasses"] == 1 and r["scaled"] == 1 and r["hourglass_seconds"] == [600]
    assert struct.unpack(">h", m.read_memory(HG + T.HG_SECONDS, 2))[0] == 600 and r["melee_bonus_x"] == 1.0
    r = T.run(m, "time_bonus_multiplier", multiplier=10)                        # already scaled: left alone
    assert r["scaled"] == 0 and struct.unpack(">h", m.read_memory(HG + T.HG_SECONDS, 2))[0] == 600
    m.u32(T.MELEE_BONUS_SITE, 0x38800032)                                       # li r4, 50: the boot patch at x10
    assert T.run(m, "time_bonus_multiplier", multiplier=10)["melee_bonus_x"] == 10.0


def test_a_doubled_hourglass_is_not_doubled_again():
    m = with_round(FakeRE5(), hourglass_seconds=30)
    r = T.run(m, "time_bonus_multiplier", multiplier=2)
    assert r["verified"] and r["scaled"] == 1 and r["hourglass_seconds"] == [60]
    r = T.run(m, "time_bonus_multiplier", multiplier=2)                         # 60 now, but this op wrote it
    assert r["verified"] and r["scaled"] == 0 and struct.unpack(">h", m.read_memory(HG + T.HG_SECONDS, 2))[0] == 60


# --- the stalemate controls (operator 2026-10-26): time taken away, the clock set, the bot's cut ---
def test_negative_add_time_takes_time_without_the_hud_notice_and_never_under_one_second():
    m = with_round(FakeRE5(), clock=90)
    r = T.run(m, "add_time", seconds=-30)
    assert r["verified"] and r["clock_before"] == 90.0 and r["clock_after"] == 60.0
    assert r["added_seconds"] == -30 and r["requested_seconds"] == -30 and not r["clamped"]
    assert m.rf(GAME + T.GAME_CLOCK) == 60.0
    assert (GS + T.GS_SHOW_BONUS, 1) not in m.writes and (GS + T.GS_LAST_BONUS, 4) not in m.writes   # no "+NN Sec."
    m.f32(GS + T.GS_CLOCK, 60.0)                                                 # the game's next-frame HUD copy
    r = T.run(m, "subtract_time", seconds=-3600)                                # the alias; far more than is left
    assert r["op"] == "add_time" and r["verified"] and r["clock_after"] == 1.0 and r["clamped"]
    assert r["added_seconds"] == -59 and "stopped at 1 s" in r["note"]
    assert m.rf(GAME + T.GAME_CLOCK) == 1.0 and (GS + T.GS_SHOW_BONUS, 1) not in m.writes
    for bad in (0, 3601, -3601):
        with pytest.raises(ValueError, match="-3600 .. 3600"):
            T.run(m, "add_time", seconds=bad)
    m.f32(GS + T.GS_CLOCK, 1.0)
    r = T.run(m, "add_time", multiplier=30)                                    # the panel's value as the multiplier
    assert r["verified"] and r["clock_after"] == 31.0 and r["added_seconds"] == 30
    assert struct.unpack(">i", m.read_memory(GS + T.GS_LAST_BONUS, 4))[0] == 30 and m.read_memory(GS + T.GS_SHOW_BONUS, 1) == b"\x01"


def test_set_time_sets_the_countdown_and_only_a_rise_shows_the_bonus_notice():
    m = with_round(FakeRE5(), clock=90)
    r = T.run(m, "set_time", seconds=5)
    assert r["verified"] and r["clock_before"] == 90.0 and r["clock_after"] == 5.0 and r["set_seconds"] == 5
    assert m.rf(GAME + T.GAME_CLOCK) == 5.0 and (GS + T.GS_SHOW_BONUS, 1) not in m.writes
    m.f32(GS + T.GS_CLOCK, 5.0)
    r = T.run(m, "set_clock", multiplier=300)                                   # the alias; the panel's value
    assert r["op"] == "set_time" and r["verified"] and r["clock_after"] == 300.0
    assert struct.unpack(">i", m.read_memory(GS + T.GS_LAST_BONUS, 4))[0] == 295 and m.read_memory(GS + T.GS_SHOW_BONUS, 1) == b"\x01"
    for bad in (0, 3601, -5):
        with pytest.raises(ValueError, match="1 .. 3600"):
            T.run(m, "set_time", seconds=bad)
    with pytest.raises(ValueError, match="a number"):
        T.run(m, "set_time", seconds="soon")
    model = T.RE5ModsIn(session_id="w-1", op="add_time", seconds=-30)           # the job's input carries the seconds
    assert model.seconds == -30 and T.RE5ModsIn(session_id="w-1", op="status").seconds is None


def test_the_bots_set_clock_uses_the_owner_path_and_never_raises():
    m = with_round(FakeRE5(), clock=90)
    r = T.set_clock(m, 5)
    assert r["verified"] and r["clock_before"] == 90.0 and r["clock_after"] == 5.0 and m.rf(GAME + T.GAME_CLOCK) == 5.0
    assert (GS + T.GS_SHOW_BONUS, 1) not in m.writes
    m.f32(GS + T.GS_CLOCK, 5.0)
    assert T.set_clock(m, 0)["clock_after"] == 1.0                              # never at or under zero
    assert T.set_clock(FakeRE5(), 5) == {"verified": False, "reason": "no round"}
    m.u32(AREA, 0x1234)
    r = T.set_clock(m, 5)
    assert r["verified"] is False and "clock write unavailable" in r["reason"]


def test_status_reports_the_clock_and_the_clock_capabilities():
    m = with_round(FakeRE5(), clock=90)
    st = T.run(m, "status")["status"]
    assert st["merc_seconds_left"] == 90.0
    assert st["capabilities"]["add_time"]["available"] and st["capabilities"]["set_time"]["available"]
    assert T.run(FakeRE5(), "status")["status"]["merc_seconds_left"] is None
