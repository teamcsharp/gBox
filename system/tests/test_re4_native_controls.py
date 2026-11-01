"""RE4 live control guards, truthful receipts, and automatic weapon policy."""
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gbox import re_games as R, re_mods_tool as M, re4_merc_bot as B
from gbox.mercs.titles import re4_gc_native as N


class Memory:
    def __init__(self):
        self.data, self.writes = {}, []
    def rd(self, a, n):
        return bytes(self.data.get(a+i, 0) for i in range(n))
    def wr(self, a, data):
        self.writes.append((a, bytes(data)))
        self.data.update({a+i: b for i, b in enumerate(data)})
    def put(self, a, fmt, *values):
        self.wr(a, struct.pack(fmt, *values))


@pytest.fixture
def native(monkeypatch):
    mem = Memory()
    ad = SimpleNamespace(proc=SimpleNamespace(pid=11, poll=lambda: None), paused=False,
                         read_memory=mem.rd, write_memory=mem.wr)
    M.STATE.pop(id(ad), None)
    monkeypatch.setattr(N, "process_identity", lambda a: (a.proc.pid, 100))
    monkeypatch.setattr(M, "install_weapon_code", lambda g: None)
    monkeypatch.setattr(M, "install_blasts", lambda g: None)
    monkeypatch.setattr(M.time, "sleep", lambda _: None)
    pg, pl, arr = 0x8027F7D0, 0x80500000, 0x80600000
    mem.wr(0x80000000, R.GAME_ID)
    mem.put(R.P_GLOBAL, ">I", pg)
    mem.put(R.P_PLAYER, ">I", pl)
    mem.put(pg + 0x20, ">B", 3)
    mem.put(pg + R.G_ROOM, ">H", 0x400)
    mem.put(pg + R.G_HP, ">h", 1200)
    mem.put(R.MERC_TIMER, ">I", 3600)
    mem.put(N.VI_COUNT, ">I", 100)
    mem.put(R.ITEM_MGR + 0x14, ">I", arr)
    mem.put(R.ITEM_MGR + 0x1C, ">I", 1)
    mem.put(R.ITEM_MGR + 0x10, ">H", 0x29)
    ids = (0x29, 0x2C, 0x2D, 0x94, 0x2E, 0x2F, 0x35, 0x37, 0x41)
    for k, iid in enumerate(ids):
        mem.put(R.WEAPON_TBL + k*R.WEAPON_SZ, ">HBBBxH", iid, 0, k+1, 0, 0x00)
    mem.wr(R.FIRE_RATE_TBL, R.FIRE_RATE_ORIG)
    mem.wr(R.FIREPOWER_TBL, R.FIREPOWER_ORIG)
    mem.put(pg + 0x4FBC, ">B", 1)
    def row(iid, loaded=12):
        mem.wr(arr, struct.pack(">HHBBBBHBBBB", iid, 1, 1, 0, 0, 0, loaded, 0, 0, 0, 1))
    row(0x29)
    for _, (a, orig, _, _) in R.PATCHES.items():
        mem.wr(a, bytes.fromhex(orig))
    ctl = N.Controller(ad)
    calls = []
    def call(fn, *args):
        guard = getattr(ctl.g, "before_call", None)
        if guard is not None:
            guard()
        calls.append((fn, args))
        if fn == R.F_TAKE_ITEM:
            row(args[0])
        elif fn == R.EQUIP_NOW:
            iid = int.from_bytes(mem.rd(args[0], 2), "big")
            mem.put(R.ITEM_MGR + 0x10, ">H", iid)
            mem.put(pg + 0x4FBC, ">B", M.weapon_classes(ctl.g)[iid][0])
        return 1
    ctl.g.call = call
    mem.writes.clear()
    return SimpleNamespace(ctl=ctl, ad=ad, mem=mem, pg=pg, pl=pl, arr=arr, row=row, calls=calls)


def test_read_only_catalogue_survives_empty_inventory_and_includes_explicit_sniper_rocket(native):
    f = native
    f.mem.put(R.ITEM_MGR + 0x1C, ">I", 0)
    f.mem.writes.clear()
    f.ctl.prepare()
    rows = f.ctl.weapon_choices()
    assert {0x2E, 0x2F, 0x35, 0x37} <= {r["item"] for r in rows}
    assert 0x41 not in {r["item"] for r in rows}
    assert not any(r["in_inventory"] for r in rows)
    assert f.ctl.current_weapon() == 0x29
    assert not f.mem.writes and not f.calls


@pytest.mark.parametrize("item", [0x2E, 0x2F, 0x35])
def test_explicit_equipment_is_never_automatically_substituted(native, item):
    f = native
    expected = f.ctl.ready()
    f.mem.put(R.PEND, ">HH", 0x37, 90)
    result = f.ctl.equip_primary(item, expected=expected, allowed=lambda: True)
    assert result["verified"] is True and result["state"] == "confirmed" and result["item"] == item
    assert result["player_generation"] == expected[1]
    assert f.ctl.current_weapon() == item and f.mem.rd(R.PEND, 4) == bytes(4)
    if item in M.SNIPERS:
        cls = M.weapon_classes(f.ctl.g)[item][0]
        want = max(1., struct.unpack_from(">f", R.FIRE_RATE_ORIG, cls*20)[0]/30)
        assert struct.unpack(">5f", f.mem.rd(R.FIRE_RATE_TBL + cls*20, 20)) == pytest.approx([want]*5)


@pytest.mark.parametrize("change", ["paused", "dead", "loading", "wrong_disc", "process"])
def test_equipment_refuses_changed_context_without_writes(native, change):
    f = native
    expected = f.ctl.ready()
    if change == "paused": f.ad.paused = True
    elif change == "dead": f.mem.put(f.pg + R.G_HP, ">h", 0)
    elif change == "loading": f.mem.put(f.pg + 0x20, ">B", 2)
    elif change == "wrong_disc": f.mem.wr(0x80000000, b"GPOE8P")
    else: f.ad.proc.pid += 1
    f.mem.writes.clear()
    with pytest.raises(N.Unavailable):
        f.ctl.equip_primary(0x29, expected=expected, allowed=lambda: True)
    assert not f.mem.writes and not f.calls


def test_observed_loading_and_vi_rewind_invalidate_handover_identity(native):
    f = native
    old = f.ctl.ready()
    f.mem.put(f.pg + 0x20, ">B", 2)
    with pytest.raises(N.Unavailable): f.ctl.ready()
    f.mem.put(f.pg + 0x20, ">B", 3)
    new = f.ctl.ready()
    assert old != new
    f.mem.put(N.VI_COUNT, ">I", 10)
    assert f.ctl.ready() != new


def test_ammo_uses_verified_patch_and_keeps_operator_setting(native):
    f = native
    assert f.ctl.ammo_status() == {"available": True, "enabled": False}
    result = f.ctl.set_infinite_ammo(True, expected=f.ctl.ready(), allowed=lambda: True)
    assert result["state"] == "confirmed" and result["enabled"] is True
    assert M.operator_overrides(f.ad)["infinite_ammo"]["on"] is True
    f.mem.wr(R.PATCHES["infinite_ammo"][0], bytes(4))
    assert f.ctl.ammo_status()["available"] is False
    f.mem.writes.clear()
    with pytest.raises(RuntimeError): f.ctl.set_infinite_ammo(False)
    assert not f.mem.writes


def test_native_effects_are_bounded_and_hand_grenade_requires_proven_protection(native):
    f = native
    with pytest.raises(N.Unavailable): f.ctl.grenade_ring("hand")
    with pytest.raises(ValueError): f.ctl.grenade_ring("electric")
    assert not f.calls
    result = f.ctl.grenade_ring("flash")
    assert result["detonated"] == 6 and len(f.calls) == 6
    assert all(fn == R.FLASH_AT for fn, _ in f.calls)
    a, _, patch, _ = R.PATCHES["unlimited_health"]
    f.mem.wr(a, bytes.fromhex(patch))
    assert f.ctl.grenade_ring("hand")["detonated"] == 6


def test_uncertain_native_result_never_reports_confirmation_or_repeats(native):
    f = native
    f.ctl.g.call = Mock(side_effect=RuntimeError("completion not observed"))
    with pytest.raises(N.Uncertain): f.ctl.flash()
    with pytest.raises(N.Unavailable): f.ctl.flash()
    assert f.ctl.g.call.call_count == 1


def test_sniper_and_rocket_automatic_policy_uses_verified_magnum_and_shotguns(native, monkeypatch):
    f = native
    def run(_ad, op, **kw):
        assert op == "merc_loadout"
        return {"verified": True, "items": kw["items"]}
    monkeypatch.setattr(M, "run", run)
    for seed in range(12):
        result = M.random_loadout(f.ad, f.ctl.g, seed=seed, weapon="rocket")
        assert M._item_id(result["picked"][0]) in M.SHOTGUNS
    result = M.random_loadout(f.ad, f.ctl.g, seed=1, weapon="rifle")
    assert result["picked"] == [R.item_name(M.HANDCANNON)]


def test_normalized_snapshot_shares_ready_identity_and_preserves_loaded_current_gun(native):
    f = native
    snap = {"player": {"ptr": f.pl}, "weapon": 0x29}
    N.normalize_snapshot(f.ad, f.mem, snap)
    assert (snap["player"]["ptr"], snap["player"]["generation"]) == f.ctl.ready()
    assert snap["mercenaries_phase"] == 1
    assert snap["inventory"][0]["rounds"] == 12
    assert snap["infinite_ammo"] is False


def test_timer_uses_existing_bounded_clock_writer(native):
    f = native
    result = f.ctl.set_timer(180, expected=f.ctl.ready(), allowed=lambda: True)
    assert result["state"] == "confirmed" and result["seconds"] == 180
    for bad in (0, 3601, float("nan"), True):
        f.mem.writes.clear()
        with pytest.raises(ValueError): f.ctl.set_timer(bad)
        assert not f.mem.writes


def test_dispatcher_timeout_preserves_owned_mailbox_and_latches_unknown_outcome(native):
    f = native
    g = M.RE4(f.ad)
    g.hook = lambda: None
    with pytest.raises(RuntimeError, match="completion was not observed"):
        g.call(R.FLASH_AT, R.BLAST_POS, timeout=-1)
    assert g.state["native_call_uncertain"] is True
    assert f.mem.rd(R.QUEUE, 4) == struct.pack(">I", R.FLASH_AT)
    f.mem.writes.clear()
    with pytest.raises(RuntimeError, match="earlier RE4 native call"):
        g.call(R.FLASH_AT, R.BLAST_POS)
    assert not f.mem.writes


def test_publication_is_never_retried_after_applied_write_raises(native):
    f = native
    g = M.RE4(f.ad)
    g.hook = lambda: None
    publications = []
    def write(a, data):
        if a == R.QUEUE and data == struct.pack(">I", R.FLASH_AT):
            publications.append(bytes(data))
            f.mem.wr(a, bytes(4))  # game consumed the function before transport reported its error
            raise OSError("transport reply lost after applying publication")
        f.mem.wr(a, data)
    f.ad.write_memory = write
    with pytest.raises(OSError, match="reply lost"):
        g.call(R.FLASH_AT, R.BLAST_POS)
    assert len(publications) == 1 and g.state["native_call_uncertain"] is True


def test_publication_uses_single_debugger_write_when_mailbox_is_consumed_immediately(native):
    f = native
    g = M.RE4(f.ad)
    g.hook = lambda: None
    writes = []
    ordinary = f.ad.write_memory
    def adapter_write(a, data):
        if a == R.QUEUE:
            raise AssertionError("volatile mailbox must not use immediate same-byte readback")
        return ordinary(a, data)
    def publish(a, data):
        writes.append((a, data))
        f.mem.put(a + 44, ">I", 1)
        f.mem.wr(a, bytes(4))  # completed before the transport reply arrives
    f.ad.write_memory = adapter_write
    f.ad.debugger = lambda: SimpleNamespace(write=publish)
    assert g.call(R.FLASH_AT, R.BLAST_POS) == 1
    assert writes == [(R.QUEUE, struct.pack(">I", R.FLASH_AT))]
    assert not g.state.get("native_call_uncertain")


def test_mod_operations_share_a_transaction_lock(native, monkeypatch):
    import threading
    f = native
    entered, finish, second = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def run(ad, op, **kw):
        calls.append(op)
        if op == "first":
            entered.set()
            assert finish.wait(2)
        else:
            second.set()
        return {"verified": True}
    monkeypatch.setattr(M, "_run", run)
    t1 = threading.Thread(target=lambda: M.run(f.ad, "first"))
    t2 = threading.Thread(target=lambda: M.run(f.ad, "second"))
    t1.start()
    assert entered.wait(2)
    t2.start()
    try:
        assert not second.wait(.05)
    finally:
        finish.set()
        t1.join(2)
        t2.join(2)
    assert calls == ["first", "second"] and second.is_set()


def test_ordinary_pickup_never_passes_with_a_bonus_goal_and_blind_vault(native, monkeypatch):
    from tests.test_re4_merc_bot import world, item
    bot = B.Bot(world([]), nav=False)
    bot._round(0x400)
    bot.goal = {"item": item("time_bonus", 0, 100)}
    snap = B.snapshot(bot.m)
    bot.stats.update(ram_action="TAKE", ram_action_aev={"item_id": 0x04, "type": 3, "enabled": True})
    assert bot.prompt_ok("a", snap) is False
    monkeypatch.setattr(bot, "_tick", lambda _: {"tap": "a"})
    assert bot.tick(snap) == {"hold": set()}
    assert bot._dialog_answer(snap["player"], bot.clock()) == "b"


def test_loadout_repair_preserves_explicit_sniper_during_lease(native, monkeypatch):
    f = native
    monkeypatch.setattr(M, "RE4", lambda _: f.ctl.g)
    f.ctl.equip_primary(0x2E, expected=f.ctl.ready())
    f.calls.clear()
    lo = {"gun_id": 0x37, "gun": "Handcannon", "fire_x": 80, "fixes": 0}
    B.LoadoutCheck(f.ad, {})._check({"weapon": 0x2E,
        "primary_weapon": {"locked": True, "usable": True, "item": 0x2E}}, lo)
    assert lo["gun_id"] == 0x2E and lo["verified"] is True
    assert not f.calls


def test_loadout_repair_uses_loaded_fallback_but_not_an_empty_inventory_guess(native, monkeypatch):
    f = native
    monkeypatch.setattr(M, "RE4", lambda _: f.ctl.g)
    lo = {"gun_id": 0x37, "gun": "Handcannon", "fire_x": 80, "fixes": 0}
    check = B.LoadoutCheck(f.ad, {})
    check._check({"weapon": 0x29, "inventory": []}, lo)
    assert lo["gun_id"] == 0x29 and not f.calls
    lo.update(fixes=0, gun_id=0x29)
    check._check({"weapon": 0x29, "inventory": [{"type": 1, "item": 0x29, "rounds": 0},
                 {"type": 1, "item": 0x2C, "rounds": 12}], "infinite_ammo": False}, lo)
    assert lo["gun_id"] == 0x2C and f.ctl.current_weapon() == 0x2C


def test_autoloadout_respects_only_live_operator_equipment_lease(native, monkeypatch):
    from gbox.mercs import primary_weapon
    f = native
    primary_weapon.install(f.ad, f.ctl.equip_primary(0x2E), f.ctl.pid)
    body = Mock(return_value={"verified": True})
    monkeypatch.setattr(M, "_run", body)
    result = M.run(f.ad, "random_loadout", g=f.ctl.g)
    assert "three-minute lease" in result["skipped"] and not body.called
    f.mem.put(f.pg + 0x20, ">B", 2)
    assert M.run(f.ad, "random_loadout", g=f.ctl.g)["verified"] is True
    assert body.call_count == 1


def test_legacy_handover_keeps_combat_stopped_after_rejected_key_release(monkeypatch):
    import time
    from tests.test_re4_merc_bot import world
    game = world([((0, 0, 1000), True)])
    stats, sent, decisions = {}, [], []
    player = B.snapshot(game)["player"]
    step = [0]
    def stop():
        step[0] += 1
        return step[0] > 3
    def tick(self, snap):
        decisions.append(step[0])
        return {"hold": {"r"}}
    def send(rows):
        sent.append(rows)
        if any(row["down"] for row in rows):
            stats["native_weapon_pending"] = {"until": time.monotonic() + 60,
                "player": player["ptr"], "generation": player.get("generation")}
            return {"sent": len(rows)}
        return {"sent": 0}
    monkeypatch.setattr(B.Bot, "tick", tick)
    B.play(None, send, stop, sleep=lambda _: None, m=game, stats=stats, clock=lambda: 0.0)
    assert decisions == [1]
    assert len(sent) >= 3 and all(not r["down"] for rows in sent[1:] for r in rows)
    assert not stats["native_weapon_pending"].get("released")
    assert stats["input_release_pending"] is True
