"""An autobot stop always completes (2026-10-27 05:56, RE4 on the Spark: the MercMode park's stop and warm pause ran
together, the bot thread blocked in os.pread of the paused Dolphin's memory, never saw its stop, and every later start,
prepare and bot reload was refused "stopping"):
  * the readers of a Dolphin's memory refuse while the session is paused (gbox.ram_dump.ShmRam, re4_merc_bot.OwnShm) and
    the adapter is marked paused before SIGSTOP; the RE4 bot's loop idles while paused and sees its stop;
  * the warm pause ends the session's autobot first (a bounded wait, then the run is reaped);
  * a run stuck stopping past REAP_AFTER_S is reaped by the next start, prepare or bot reload - its inputs dropped."""
import errno
import threading
import time
from types import SimpleNamespace

import pytest

from gbox import adapters, ram_dump, re4_merc_bot, tools


def test_shm_ram_refuses_to_read_a_paused_dolphin(monkeypatch):
    reads = []
    ram = ram_dump.ShmRam.__new__(ram_dump.ShmRam)
    ram.pid, ram.hosts, ram.fd = 1, {0x80000000: 0x7F0000000000}, -1
    ram.gate = SimpleNamespace(paused=True)
    monkeypatch.setattr(ram_dump.os, "pread", lambda *a: reads.append(a) or b"\0" * 4, raising=False)
    with pytest.raises(OSError) as e:
        ram.read(0x80000000, 4)
    assert e.value.errno == errno.EAGAIN and reads == []
    ram.gate.paused = False
    assert ram.read(0x80000000, 4) == b"\0" * 4 and len(reads) == 1


def test_the_re4_bots_own_view_refuses_while_paused():
    ad = SimpleNamespace(paused=True)
    m = re4_merc_bot.OwnShm(SimpleNamespace(read=lambda a, n: pytest.fail("read a paused Dolphin")), ad)
    with pytest.raises(OSError):
        m.rd(0x80001000, 4)
    ad.paused = False
    m.ram = SimpleNamespace(read=lambda a, n: b"\1" * n)
    assert m.rd(0x80001000, 2) == b"\1\1"


def test_the_dolphin_adapter_is_marked_paused_before_it_stops():
    seen = []
    ad = adapters.DolphinAdapter.__new__(adapters.DolphinAdapter)
    ad.dbg, ad.paused, ad.name = None, False, "dolphin"
    ad._signal_tree = lambda sig: seen.append((sig, ad.paused)) or 1
    if adapters.HOST_OS == "windows":
        pytest.skip("SIGSTOP pauses only on Linux")
    ad.pause()
    ad.resume()
    import signal
    assert seen == [(signal.SIGSTOP, True), (signal.SIGCONT, True)] and ad.paused is False


def test_the_re4_loop_idles_while_paused_without_reading_and_ends_on_its_stop(monkeypatch):
    ad = SimpleNamespace(paused=True)
    calls = {"n": 0}

    def stopped():
        calls["n"] += 1
        return calls["n"] > 6

    reads = []

    def refused(m):                                                       # what OwnShm answers while paused
        reads.append(1)
        raise OSError(errno.EAGAIN, "the emulator is paused")
    monkeypatch.setattr(re4_merc_bot, "snapshot", refused)
    sleeps = []
    stats = re4_merc_bot.play(ad, lambda rows: None, stopped, sleep=sleeps.append,
                              m=SimpleNamespace(rd=lambda a, n: refused(None)), stats={})
    assert len(reads) == 1                                                # the setup's one try; the loop reads nothing
    assert sleeps and all(s == re4_merc_bot.PAUSED_IDLE_S for s in sleeps[-3:]) and stats.get("screen") == "paused"


class Thread:
    """A bot thread that is blocked (alive) until released."""

    def __init__(self):
        self.done = threading.Event()

    def is_alive(self):
        return not self.done.is_set()

    def join(self, timeout=None):
        self.done.wait(timeout)


def stuck_run(sid, stop_age):
    th = Thread()
    run = {"sid": sid, "mission": "playbook: re4_merc_bot", "mode": "playbook", "playbook_module": "gbox.re4_merc_bot",
           "driver": SimpleNamespace(stopped=True), "thread": th, "stop_at": time.time() - stop_age, "inp": None,
           "ctx": None}
    return run, th


def test_a_start_reaps_a_run_stuck_stopping_but_not_one_that_just_stopped(monkeypatch):
    monkeypatch.setattr(tools, "_session_game_id", lambda *a: "re4")
    monkeypatch.setattr(tools, "_release_all", lambda sid: None)
    run, th = stuck_run("w-re4", 5.0)
    monkeypatch.setitem(tools.AUTOPLAY, "w-re4", run)
    with pytest.raises(ValueError, match="is stopping"):                 # 5 s: it may still end by itself
        tools.autoplay(tools.AutoplayIn(session_id="w-re4", op="start"), SimpleNamespace(job_id="j"))
    assert tools.AUTOPLAY["w-re4"] is run and not run.get("reaped")
    run["stop_at"] = time.time() - tools.REAP_AFTER_S - 1                 # 21 s: blocked
    monkeypatch.setattr(tools, "Driver", None, raising=False)
    with pytest.raises(Exception):                                        # past the reap the real start goes on (no
        tools.autoplay(tools.AutoplayIn(session_id="w-re4", op="start"), SimpleNamespace(job_id="j"))   # session here)
    assert run["reaped"].startswith("still stopping") and tools.AUTOPLAY.get("w-re4") is not run
    assert tools.REAPED[-1]["session_id"] == "w-re4"
    th.done.set()


def test_a_reaped_run_sends_nothing_and_its_end_posts_nothing(monkeypatch):
    sent = []
    ad = SimpleNamespace(send_input=lambda rows: sent.append(rows))
    d = SimpleNamespace(screensaver=None, demo=False)
    run = {"sid": "w-re4"}
    from gbox import pad_takeover
    monkeypatch.setattr(pad_takeover, "Gate", lambda sid, send: send)
    send = tools._bot_send(run, ad, d)
    send([{"key": "a", "down": True}])
    run["reaped"] = "test"
    send([{"key": "b", "down": True}])
    assert sent == [[{"key": "a", "down": True}]]


def test_a_bot_reload_reaps_a_stuck_run_instead_of_refusing_forever(monkeypatch):
    monkeypatch.setattr(tools, "_release_all", lambda sid: None)
    run, th = stuck_run("w-re4", tools.REAP_AFTER_S + 5)
    monkeypatch.setitem(tools.AUTOPLAY, "w-re4", run)
    assert tools._ReloadHost().busy() is None and run["reaped"] == "still stopping at a bot reload"
    fresh, th2 = stuck_run("w-re5", 3.0)
    fresh["playbook_module"] = "gbox.mercs_bot"
    monkeypatch.setitem(tools.AUTOPLAY, "w-re5", fresh)
    assert tools._ReloadHost().busy() == "the autobot on w-re5 is still stopping"   # it may still end by itself
    th.done.set()
    th2.done.set()


def test_the_warm_pause_ends_the_bot_first_and_reaps_one_that_will_not_end(monkeypatch):
    monkeypatch.setattr(tools, "_release_all", lambda sid: None)
    th = Thread()
    run = {"sid": "w-re4", "mission": "playbook: re4_merc_bot", "driver": SimpleNamespace(stopped=False), "thread": th}
    monkeypatch.setitem(tools.AUTOPLAY, "w-re4", run)
    threading.Timer(0.05, th.done.set).start()                            # it ends once told to stop
    assert tools._park_autobot("w-re4", wait_s=2.0) == {"autobot": "ended"} and run["driver"].stopped
    th2 = Thread()
    run2 = {"sid": "w-re4", "mission": "playbook: re4_merc_bot", "driver": SimpleNamespace(stopped=False), "thread": th2}
    monkeypatch.setitem(tools.AUTOPLAY, "w-re4", run2)
    assert tools._park_autobot("w-re4", wait_s=0.05) == {"autobot": "reaped"}
    assert run2["reaped"] == "still running at the warm pause" and tools.AUTOPLAY.get("w-re4") is None
    th2.done.set()
    order = []
    ad = SimpleNamespace(pause=lambda: order.append("pause") or {"state": "PAUSED"})
    monkeypatch.setitem(tools.SESSIONS, "w-re4", (ad, {}))
    monkeypatch.setattr(tools, "_park_autobot", lambda sid: order.append("park") or {"autobot": "none"})
    monkeypatch.setattr(tools, "_warm_priority", lambda ad, n: None)
    from gbox.mercs import warm_boot
    monkeypatch.setattr(warm_boot, "cancel", lambda ad: None)
    tools.session_op(tools.SessionIn(session_id="w-re4", op="pause", args={"warm": True}), SimpleNamespace())
    assert order == ["park", "pause"]
