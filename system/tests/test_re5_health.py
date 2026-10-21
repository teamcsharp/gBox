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


def recovery_state(m):
    from gbox.mercs.titles import re5_ps3 as R
    health(m, 1)
    m.f32(PLAYER + R.P_DYING_TIMER, 6.74)
    m.u32(PLAYER + R.P_RECOVER_BUTTON, 0x328E1FE0)
    m.u32(0x328E1FE0, R.QTE_BUTTON_VT)
    m.u32(0x328E1FE0 + 4, PLAYER)         # no selected manager or visible glyph is needed to preserve recovery


def test_direct_health_enable_and_maintenance_wait_for_hidden_recovery_without_writing():
    m = FakeRE5()
    recovery_state(m)
    result = T.run(m, "unlimited_health")
    assert result["unlimited_health"] and result["resuscitating"] and not result["active"] and not m.writes
    snap = {"player": {"ptr": PLAYER, "hp": 1, "hp_max": 1000}}
    result = T.maintain_health(m, snap)
    assert result["resuscitating"] and not result["verified"] and read_health(m) == (1, 1000)
    assert snap["player"]["hp"] == 1 and not m.writes
    health(m, 1000)                     # the game's actual recovery callback completed
    assert T.maintain_health(m, snap)["active"] and snap["player"]["hp"] == T.HEALTH_MAX


def test_health_rechecks_a_new_recovery_or_death_before_refill(monkeypatch):
    for dying in (True, False):
        T.ORIG.clear()
        m = FakeRE5()
        health(m, 500)
        original = T._health_player
        calls = [0]
        def transition(g):
            calls[0] += 1
            if calls[0] == 2:
                recovery_state(m) if dying else health(m, 0)
            return original(g)
        monkeypatch.setattr(T, "_health_player", transition)
        result = T.run(m, "unlimited_health")
        assert not result["active"] and not m.writes
        assert read_health(m)[0] == (1 if dying else 0)
        if dying:
            assert result["resuscitating"]
        monkeypatch.setattr(T, "_health_player", original)


def test_unreadable_hidden_recovery_never_becomes_permission_to_refill(monkeypatch):
    from gbox.mercs.titles import re5_ps3 as R
    m = FakeRE5()
    recovery_state(m)
    T.run(m, "unlimited_health")
    read = m.read_memory
    def unreadable(address, size):
        if address == PLAYER + R.P_DYING_TIMER:
            raise OSError("lost recovery page")
        return read(address, size)
    monkeypatch.setattr(m, "read_memory", unreadable)
    assert not T.maintain_health(m)["active"] and not m.writes


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


def hit_layout(m, player=PLAYER, table=0x304F1F00, node_base=0x30500000):
    for address, signature in T.IMMUNITY_SIGNATURES.items():
        m.put(address, signature)
    m.put(player + T.P_HIT_LIST, struct.pack(">7I", 0x0163B530, table, 0, 0, player, 4, 3))
    nodes = [node_base + i * 0x100 for i in range(3)]
    m.put(table, struct.pack(">3I", *nodes))
    for node, kind, enabled in zip(nodes, (1, 0, 1), (1, 1, 0)):
        m.u32(node + T.HIT_NODE_TYPE, kind)
        m.put(node + T.HIT_NODE_ENABLE, bytes([enabled]))
    m.u32(player + T.P_MUTEKI, 0xA0000024)
    m.u32(player + T.P_HIT_STATE, 0x10041000)
    return table, nodes


def ru32(m, address):
    return struct.unpack(">I", m.read_memory(address, 4))[0]


def test_verified_muteki_mirrors_game_setter_and_restores_only_owned_bits_and_nodes():
    m = FakeRE5()
    health(m)
    _, nodes = hit_layout(m)
    assert not T.maintain_health(m)["unlimited_health"] and not m.writes
    result = T.run(m, "unlimited_health")
    assert result["hit_immunity"] and result["immunity_verified"] and result["immunity_colliders"] == 2
    assert result["status"]["hit_immunity"]
    assert ru32(m, PLAYER + T.P_MUTEKI) == 0xA0000014
    assert ru32(m, PLAYER + T.P_HIT_STATE) == 0x10001000
    assert [m.read_memory(n + T.HIT_NODE_ENABLE, 1)[0] for n in nodes] == [0, 1, 0]
    allowed = {PLAYER + T.P_HP, PLAYER + T.P_MUTEKI, PLAYER + T.P_HIT_STATE,
               nodes[0] + T.HIT_NODE_ENABLE}
    assert {address for address, _ in m.writes} == allowed  # No code writes or outgoing-hit edits.
    writes = list(m.writes)
    assert T.maintain_health(m)["hit_immunity"] and m.writes == writes
    m.u32(PLAYER + T.P_MUTEKI, ru32(m, PLAYER + T.P_MUTEKI) | 0x100)
    m.u32(PLAYER + T.P_HIT_STATE, ru32(m, PLAYER + T.P_HIT_STATE) | 0x80)
    result = T.run(m, "unlimited_health", on=False)
    assert result["immunity_restored"] and result["verified"]
    assert ru32(m, PLAYER + T.P_MUTEKI) == 0xA0000124
    assert ru32(m, PLAYER + T.P_HIT_STATE) == 0x10041080
    assert [m.read_memory(n + T.HIT_NODE_ENABLE, 1)[0] for n in nodes] == [1, 1, 0]


@pytest.mark.parametrize("signature_address", list(T.IMMUNITY_SIGNATURES))
def test_immunity_requires_each_exact_signature_but_health_refill_remains_available(signature_address):
    m = FakeRE5()
    health(m)
    hit_layout(m)
    m.put(signature_address, b"\xff")
    result = T.run(m, "unlimited_health")
    assert result["verified"] and not result["hit_immunity"]
    assert "signatures did not match" in result["immunity_reason"]
    assert m.writes == [(PLAYER + T.P_HP, 4)]


@pytest.mark.parametrize("invalid", ["owner", "count", "capacity", "table", "node", "enable"])
def test_invalid_hit_layout_keeps_health_only_without_partial_immunity_writes(invalid):
    m = FakeRE5()
    health(m)
    table, nodes = hit_layout(m)
    if invalid == "owner":
        m.u32(PLAYER + T.P_HIT_LIST + 0x10, PLAYER + 4)
    elif invalid == "count":
        m.u32(PLAYER + T.P_HIT_LIST + 0x18, 5)
    elif invalid == "capacity":
        m.u32(PLAYER + T.P_HIT_LIST + 0x14, 129)
    elif invalid == "table":
        m.u32(PLAYER + T.P_HIT_LIST + 4, 0x3FFFFFFC)
    elif invalid == "node":
        m.u32(table, 0x3FFFFF80)
    else:
        m.put(nodes[2] + T.HIT_NODE_ENABLE, b"\x02")
    result = T.run(m, "unlimited_health")
    assert result["verified"] and not result["hit_immunity"]
    assert m.writes == [(PLAYER + T.P_HP, 4)]


def test_immunity_follows_respawn_and_never_restores_previous_player_nodes():
    m = FakeRE5()
    health(m)
    _, old_nodes = hit_layout(m)
    assert T.run(m, "unlimited_health")["hit_immunity"]
    new = PLAYER + 0x10000
    m.u32(SPLAYER + 0x28, new)
    health(m, player=new)
    _, new_nodes = hit_layout(m, new, 0x30600000, 0x30601000)
    m.writes.clear()
    assert T.maintain_health(m)["hit_immunity"]
    assert T.run(m, "unlimited_health", on=False)["immunity_restored"]
    assert all(address != PLAYER + T.P_MUTEKI and address not in
               {n + T.HIT_NODE_ENABLE for n in old_nodes} for address, _ in m.writes)
    assert m.read_memory(new_nodes[0] + T.HIT_NODE_ENABLE, 1) == b"\x01"


def test_changed_collision_entry_is_not_written_or_restored(monkeypatch):
    m = FakeRE5()
    health(m)
    table, nodes = hit_layout(m)
    original_check = T._hit_list_current
    def change_entry(g, pl, header, index=None, node=None):
        if index == 0:
            m.u32(table, nodes[1])  # The current entry is now an outgoing attack record.
        return original_check(g, pl, header, index, node)
    monkeypatch.setattr(T, "_hit_list_current", change_entry)
    result = T.run(m, "unlimited_health")
    assert not result["hit_immunity"] and "entry changed" in result["immunity_reason"]
    assert not any(address == nodes[0] + T.HIT_NODE_ENABLE for address, _ in m.writes)
    monkeypatch.setattr(T, "_hit_list_current", original_check)
    m.writes.clear()
    T.run(m, "unlimited_health", on=False)
    assert not any(address == nodes[0] + T.HIT_NODE_ENABLE for address, _ in m.writes)


def test_failed_immunity_readback_does_not_claim_protection_and_preserves_health(monkeypatch):
    m = FakeRE5()
    health(m)
    hit_layout(m)
    write = m.write_memory
    monkeypatch.setattr(m, "write_memory", lambda address, data:
                        None if address == PLAYER + T.P_MUTEKI else write(address, data))
    result = T.run(m, "unlimited_health")
    assert result["verified"] and not result["hit_immunity"]
    assert "readback failed" in result["immunity_reason"]
    assert read_health(m) == (T.HEALTH_MAX, T.HEALTH_MAX)


def test_death_during_hit_list_read_prevents_all_immunity_writes(monkeypatch):
    m = FakeRE5()
    health(m)
    hit_layout(m)
    read_list = T._hit_list
    def death_after_list(g, pl):
        result = read_list(g, pl)
        health(m, 0, T.HEALTH_MAX)
        return result
    monkeypatch.setattr(T, "_hit_list", death_after_list)
    result = T.run(m, "unlimited_health")
    assert not result["hit_immunity"]
    assert m.writes == [(PLAYER + T.P_HP, 4)]
    assert read_health(m)[0] == 0


def test_replacement_hit_list_never_restores_predecessors_node_bytes():
    m = FakeRE5()
    health(m)
    table, nodes = hit_layout(m)
    assert T.run(m, "unlimited_health")["hit_immunity"]
    replacement = table + 0x1000
    m.u32(PLAYER + T.P_HIT_LIST + 4, replacement)
    m.put(replacement, struct.pack(">3I", *nodes))  # Allocator reused node addresses, with new semantics.
    m.writes.clear()
    result = T.run(m, "unlimited_health", on=False)
    assert result["verified"] and result["immunity_restore_skipped"]
    assert not any(address == nodes[0] + T.HIT_NODE_ENABLE for address, _ in m.writes)
