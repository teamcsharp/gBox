"""The E3 read-only `.bss` watch that rides the RE4 bot's snapshots (telemetry, 2026-11-10)."""
import json

from gbox.mercs.titles import re4_switch as R


class FakeMem:
    def __init__(self, pages=None, fail=()):
        self.pages = pages or {}
        self.fail = set(fail)
        self.reads = []

    def rd(self, at, n):
        self.reads.append((at, n))
        if at in self.fail:
            raise OSError("unmapped")
        return self.pages.get(at, b"\0" * n)


def test_the_watch_reads_all_five_pages_and_reports_hex():
    base = 0x100000000
    mem = FakeMem({base + off: bytes([1 + i]) * 16 for i, off in enumerate(R.BSS_WATCH_PAGES)})
    out = R.bss_watch(mem, base)
    assert set(out["pages"]) == {f"{off:#x}" for off in R.BSS_WATCH_PAGES}
    assert all(len(v) == 32 for v in out["pages"].values())
    assert len({v for v in out["pages"].values()}) == 5
    assert isinstance(out["at"], float)


def test_a_failed_page_is_none_and_the_others_still_read():
    base = 0x100000000
    mem = FakeMem({}, fail={base + R.BSS_WATCH_PAGES[1]})
    out = R.bss_watch(mem, base)
    assert out["pages"][f"{R.BSS_WATCH_PAGES[1]:#x}"] is None
    assert out["pages"][f"{R.BSS_WATCH_PAGES[0]:#x}"] == "00" * 16


def test_the_snapshot_stamps_the_watch_into_the_round_stats(monkeypatch):
    base = 0x100000000
    mem = FakeMem({base + off: b"\0" * 16 for off in R.BSS_WATCH_PAGES})
    monkeypatch.setattr(R, "snapshot", lambda m: {"module_base": base, "game": {"stage": 2}})
    monkeypatch.setattr(R.re4_nav, "attach", lambda snap: snap)
    bot = R.RE4Switch()
    bot.stats = {}
    snap = bot.snapshot(mem)
    assert snap["game"]["stage"] == 2
    assert isinstance(bot.stats["bss_watch"], str)              # the telemetry publishes only scalar stats
    watch = json.loads(bot.stats["bss_watch"])
    assert watch["stage"] == 2 and set(watch["pages"]) == {f"{off:#x}" for off in R.BSS_WATCH_PAGES}
    assert len(mem.reads) == len(R.BSS_WATCH_PAGES)


def test_the_snapshot_does_not_read_before_a_round_has_a_stats_dict(monkeypatch):
    monkeypatch.setattr(R, "snapshot", lambda m: {"module_base": 0x100000000, "game": {"stage": 1}})
    monkeypatch.setattr(R.re4_nav, "attach", lambda snap: snap)
    mem = FakeMem()
    bot = R.RE4Switch()
    bot.snapshot(mem)
    assert mem.reads == []
    assert bot.stats is None


def test_each_stage_load_is_kept_and_only_the_last_three(monkeypatch):
    base = 0x100000000
    mem = FakeMem({base + off: b"\0" * 16 for off in R.BSS_WATCH_PAGES})
    stage = {"n": 1}
    monkeypatch.setattr(R, "snapshot", lambda m: {"module_base": base, "game": {"stage": stage["n"]}})
    monkeypatch.setattr(R.re4_nav, "attach", lambda snap: snap)
    bot = R.RE4Switch()
    bot.stats = {}
    for n in (1, 1, 2, 3, 4):
        stage["n"] = n
        bot.snapshot(mem)
    assert isinstance(bot.stats["bss_watch_loads"], str)
    loads = json.loads(bot.stats["bss_watch_loads"])
    assert [row["stage"] for row in loads] == [2, 3, 4]     # the last three distinct stage loads
    assert json.loads(bot.stats["bss_watch"])["stage"] == 4


def test_a_menu_snapshot_is_not_a_stage_load(monkeypatch):
    base = 0x100000000
    mem = FakeMem({base + off: b"\0" * 16 for off in R.BSS_WATCH_PAGES})
    monkeypatch.setattr(R, "snapshot", lambda m: {"module_base": base, "game": {}})
    monkeypatch.setattr(R.re4_nav, "attach", lambda snap: snap)
    bot = R.RE4Switch()
    bot.stats = {}
    bot.snapshot(mem)
    assert json.loads(bot.stats["bss_watch"])["stage"] is None
    assert "bss_watch_loads" not in bot.stats


def test_each_round_start_on_the_same_stage_is_a_load(monkeypatch):
    """RE4 Switch plays one stage per session (the MercMode pick rides the launch), so the three-load watch must
    count round starts, not only stage-id changes, or the harness mailbox can never be proven - live 2026-11-11 a
    session played nine rounds on stage 3 and the watch held one entry. The stage is re-loaded every round; a page
    that stays zero across three round starts is the same evidence the lane's rule asks for."""
    base = 0x100000000
    pages = {base + off: (b"\0" * 16 if off == 0x1700000 else bytes([7]) * 16) for off in R.BSS_WATCH_PAGES}
    mem = FakeMem(pages)
    phase = {"v": "results"}
    monkeypatch.setattr(R, "snapshot", lambda m: {"module_base": base, "game": {"stage": 3, "phase": phase["v"]}})
    monkeypatch.setattr(R.re4_nav, "attach", lambda snap: snap)
    bot = R.RE4Switch()
    bot.stats = {}
    for flow in (("intro", "playing", "results"), ("intro", "playing", "results"), ("intro", "playing")):
        for p in flow:
            phase["v"] = p
            bot.snapshot(mem)
    loads = json.loads(bot.stats["bss_watch_loads"])
    assert [row["stage"] for row in loads] == [3, 3, 3]
    from gbox.mercs.titles import re4_switch_native as N
    assert N.choose_mailbox(loads) == 0x1700000
