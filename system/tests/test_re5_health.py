"""Bounded health maintenance follows the live player without reviving stale or dead allocations."""
import struct

import pytest

from gbox import re5_mods_tool as T
from test_re5_mods import FakeRE5, PLAYER, SPLAYER, fresh_originals  # noqa: F401


def health(m, hp=600, maximum=1000, player=PLAYER):
    m.put(player + T.P_HP, struct.pack(">hh", hp, maximum))


def read_health(m, player=PLAYER):
    return struct.unpack(">hh", m.read_memory(player + T.P_HP, 4))


def test_health_is_opt_in_refilled_every_snapshot_and_restored_when_disabled():
    m = FakeRE5()
    health(m)
    assert not T.maintain_health(m)["unlimited_health"] and not m.writes
    assert T.run(m, "unlimited_life")["verified"]
    assert read_health(m) == (T.HEALTH_MAX, T.HEALTH_MAX)
    health(m, 28000, T.HEALTH_MAX)
    snap = {"player": {"ptr": PLAYER, "hp": 28000, "hp_max": T.HEALTH_MAX}}
    assert T.maintain_health(m, snap)["refilled"]
    assert snap["player"]["hp"] == T.HEALTH_MAX and read_health(m)[0] == T.HEALTH_MAX
    writes = list(m.writes)
    assert T.maintain_health(m, snap)["verified"] and m.writes == writes
    result = T.run(m, "unlimited_health", on=False)
    assert result["restored"] and not result["status"]["unlimited_health"]
    assert read_health(m) == (1000, 1000)  # Disable the boost, without restoring historical injuries.
    health(m, 500)
    assert not T.maintain_health(m)["active"] and read_health(m) == (500, 1000)


def test_health_follows_respawn_and_revert_never_writes_the_previous_player():
    m = FakeRE5()
    health(m)
    T.run(m, "unlimited_health")
    new_player = PLAYER + 0x10000
    m.u32(SPLAYER + 0x28, new_player)
    health(m, 300, 800, new_player)
    m.writes.clear()
    assert T.maintain_health(m)["verified"]
    assert m.writes == [(new_player + T.P_HP, 4)]
    assert T.run(m, "revert_all")["reverted"]["health"]
    assert read_health(m, new_player) == (800, 800)
    assert read_health(m) == (T.HEALTH_MAX, T.HEALTH_MAX)


@pytest.mark.parametrize("hp,maximum", [(0, 1000), (-1, 1000), (1001, 1000), (1, 0), (1, -1)])
def test_dead_or_invalid_health_is_never_written(hp, maximum):
    m = FakeRE5()
    health(m, hp, maximum)
    result = T.run(m, "unlimited_health")
    assert result["unlimited_health"] and not result["active"] and not m.writes
    health(m, 1000, 1000)  # The next real spawn is protected without enabling the cheat again.
    assert T.maintain_health(m)["active"]


def test_full_signed_health_range_stays_in_bounds():
    m = FakeRE5()
    health(m, 1, 32767)
    assert T.run(m, "unlimited_health")["verified"]
    assert read_health(m) == (32767, 32767)


def test_snapshot_and_current_player_must_agree():
    m = FakeRE5()
    health(m)
    T.run(m, "unlimited_health")
    health(m, 500, T.HEALTH_MAX)
    m.writes.clear()
    assert not T.maintain_health(m, {"player": {"ptr": PLAYER + 4}})["active"]
    m.u32(SPLAYER + 0x28, PLAYER + 1)
    assert not T.maintain_health(m)["active"] and not m.writes


def test_player_change_between_read_and_write_abandons_the_write(monkeypatch):
    m = FakeRE5()
    health(m)
    g = T.RE5(m)
    g.orig["health"] = {"on": True}
    players = iter([PLAYER, PLAYER + 0x10000])
    monkeypatch.setattr(T, "_health_player", lambda g: next(players))
    assert not T._maintain_health(g)["active"] and not m.writes


def test_wrong_build_and_failed_readback_do_not_claim_health_was_maintained(monkeypatch):
    m = FakeRE5()
    health(m)
    T.run(m, "unlimited_health")
    health(m, 500, T.HEALTH_MAX)
    m.writes.clear()
    m.u32(T.DEF_TABLE, 0)
    assert not T.maintain_health(m)["verified"] and not m.writes
    m.u32(T.DEF_TABLE, T.DEF_SIGNATURE[0])
    monkeypatch.setattr(m, "write_memory", lambda *a: None)
    snap = {"player": {"ptr": PLAYER, "hp": 500, "hp_max": T.HEALTH_MAX}}
    assert not T.maintain_health(m, snap)["verified"]
    assert snap["player"]["hp"] == 500 and read_health(m)[0] == 500
