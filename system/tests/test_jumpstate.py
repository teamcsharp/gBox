"""Boot jump states (gbox.jumpstate): saved after a good stretch of autoplay, loaded at the next start, dropped when
they land on a menu; the operator's save slot is always put back.

Standalone Dolphin (Windows and the Spark's flatpak) boots straight into the jump state (--save_state) when a demo
launch asks for it, and saves one through its own demo slot (10): the operator's slot 1 is never written. Nothing here
starts an emulator."""
import os
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters
from gbox import jumpstate as J


class FakeRA:
    def __init__(self, tmp: Path):
        self.config = SimpleNamespace(runtime=tmp / "runtime")
        self.states = tmp / "states"
        self.states.mkdir()
        self.slot, self.game, self.loaded = 2, b"title", None

    def _slot(self, slot=None):
        if slot is not None:
            self.slot = int(slot)
        return self.slot

    def save_state(self, slot=None):
        self._slot(slot)
        f = self.states / f"game.state{self.slot}"
        f.write_bytes(self.game)
        return {"path": str(f), "slot": self.slot}

    def load_state(self, slot=None):
        self._slot(slot)
        self.loaded = (self.states / f"game.state{self.slot}").read_bytes()


def run(ad, g, steps, stats, stuck, on_step=lambda t: None):
    now = [0.0]

    def stopped():
        on_step(now[0])
        return now[0] >= steps
    J.watch(ad, g, stuck, stats, stopped, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))


def test_saves_after_good_play_and_keeps_the_operators_slot(tmp_path):
    ad = FakeRA(tmp_path)
    g = {"game_id": "g1", "mod": "cast/hd"}
    stats, stuck = {}, SimpleNamespace(changed=0.0)

    def step(t):
        stuck.changed = t                                   # the screen keeps moving
        ad.game = b"gameplay"
    run(ad, g, 60, stats, stuck, step)
    p = J.path_for(ad, g)
    assert stats["jump"] == "saved" and p.read_bytes() == b"gameplay" and p.name == "g1-cast_hd.state"
    assert ad.slot == 2                                     # operator's slot back


def test_no_save_while_autoplay_still_presses_through_menus(tmp_path):
    ad = FakeRA(tmp_path)
    stats, stuck = {}, SimpleNamespace(changed=0.0)

    def step(t):
        stuck.changed = t
        stats["menu_at"] = t                                # still pressing Start on menus
    run(ad, {"game_id": "g1"}, 120, stats, stuck, step)
    assert "jump" not in stats and not J.path_for(ad, {"game_id": "g1"}).exists()


def test_loads_the_jump_state_at_start(tmp_path):
    ad = FakeRA(tmp_path)
    g = {"game_id": "g1"}
    p = J.path_for(ad, g)
    p.parent.mkdir(parents=True)
    p.write_bytes(b"gameplay")
    stats = {}
    run(ad, g, 60, stats, SimpleNamespace(changed=0.0))
    assert ad.loaded == b"gameplay" and stats["jump"] == "loaded, playing" and ad.slot == 2


def test_a_jump_state_that_lands_on_a_menu_is_dropped(tmp_path):
    ad = FakeRA(tmp_path)
    g = {"game_id": "g1"}
    p = J.path_for(ad, g)
    p.parent.mkdir(parents=True)
    p.write_bytes(b"attract demo")
    stats = {}

    def step(t):
        if t == 10:
            stats["menu_at"] = t                            # autoplay had to press Start after the load
    run(ad, g, 20, stats, SimpleNamespace(changed=0.0), step)
    assert stats["jump"].startswith("dropped") and not p.exists()


def test_only_retroarch_style_adapters():
    assert not J.supported(SimpleNamespace(save_state=1, load_state=1, config=1))   # Dolphin: no slots of its own


# --- standalone Dolphin: boots straight into the jump state, saves one through its own demo slot (10) ---

class FakeDolphin:
    """Dolphin as gbox.jumpstate sees it (the real adapters are exercised further down)."""
    def __init__(self, tmp: Path):
        self.config = SimpleNamespace(runtime=tmp / "runtime")
        self.jump_from, self.ff_on, self.saves, self.game = None, False, 0, b"title"

    def jump_boot(self, src):
        self.jump_from = Path(src)

    def jump_save(self, dest):
        self.saves += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.game)
        return len(self.game)


def stored(ad, g, data=b"gameplay"):
    p = J.path_for(ad, g)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_strategy_per_emulator(tmp_path):
    cfg = SimpleNamespace(runtime=tmp_path)
    assert J.strategy(FakeRA(tmp_path)) == "slot"                      # RetroArch: as before
    assert J.strategy(FakeDolphin(tmp_path)) == "boot"
    assert J.strategy(SimpleNamespace(save_state=1, load_state=1, config=1, jump_save=1, jump_boot=1)) is None
    assert J.strategy(adapters.DolphinAdapter(cfg, "gamecube")) == "boot"
    assert J.strategy(adapters.DolphinWinAdapter(cfg, "gamecube")) == "boot"
    assert J.strategy(adapters.RetroArchAdapter(adapters.EmulatorConfig(core="x"), config=cfg, platform="snes")) == "entryslot"
    assert J.strategy(adapters.MgbaAdapter(cfg, "gba")) is None             # everything else: no jump states


def test_only_a_jump_launch_with_a_state_of_the_same_game_and_build_boots_into_it(tmp_path):
    ad, g = FakeDolphin(tmp_path), {"game_id": "sc2", "mod": "sc2_sonic_cast"}
    assert J.arm_boot(ad, g) == {"booted": False, "why": "no jump state for this game and build on this PC yet"}
    stored(ad, {"game_id": "sc2", "mod": ""})                           # the stock game's moment is not this build's
    stored(ad, {"game_id": "sc2", "mod": "sc2 sonic cast"}, b"")         # nor an empty file
    assert J.path_for(ad, {"game_id": "sc2", "mod": "sc2 sonic cast"}) != J.path_for(ad, {"game_id": "sc2", "mod": ""})
    assert not J.arm_boot(ad, {"game_id": "sc2", "mod": "sc2 sonic cast"})["booted"]
    assert not J.arm_boot(ad, g)["booted"] and ad.jump_from is None and not J.booted(ad, g)
    p = stored(ad, g)
    assert J.arm_boot(ad, g) == {"booted": True, "file": "sc2-sc2_sonic_cast.state"}
    assert ad.jump_from == p and J.booted(ad, g) and not J.booted(ad, {"game_id": "sc2", "mod": ""})
    ra = FakeRA(tmp_path)                                               # RetroArch: loads it when autoplay starts
    stored(ra, {"game_id": "g1"})
    assert J.arm_boot(ra, {"game_id": "g1"})["booted"] is False and not J.booted(ra)


def test_dolphin_booted_into_its_jump_state_keeps_it_while_it_plays(tmp_path):
    ad, g = FakeDolphin(tmp_path), {"game_id": "g1", "mod": "cast"}
    p = stored(ad, g)
    J.arm_boot(ad, g)
    stats, stuck = {}, SimpleNamespace(changed=0.0)
    run(ad, g, 120, stats, stuck, lambda t: setattr(stuck, "changed", t))
    assert stats["jump"] == "loaded, playing" and p.read_bytes() == b"gameplay" and ad.saves == 0


def test_dolphin_jump_state_that_lands_on_a_menu_is_dropped_then_good_play_saves_a_new_one(tmp_path):
    ad, g = FakeDolphin(tmp_path), {"game_id": "g1"}
    p = stored(ad, g, b"attract demo")
    J.arm_boot(ad, g)
    stats, stuck, seen = {}, SimpleNamespace(changed=0.0), []

    def step(t):
        stuck.changed = t
        if t == 10:
            stats["menu_at"] = t                                     # autoplay had to press Start: a title, not play
        if t == 11:
            seen.append((stats["jump"], p.exists()))
            ad.game = b"gameplay"
    run(ad, g, 60, stats, stuck, step)
    assert seen == [("dropped: landed on a menu", False)]
    assert stats["jump"] == "saved" and p.read_bytes() == b"gameplay" and ad.saves == 1


def test_dolphin_never_loads_a_jump_state_into_a_running_game(tmp_path):
    ad, g = FakeDolphin(tmp_path), {"game_id": "g1"}
    p = stored(ad, g)                                                # a launch that did not ask for the jump
    stats, stuck = {}, SimpleNamespace(changed=0.0)
    run(ad, g, 120, stats, stuck, lambda t: setattr(stuck, "changed", t))
    assert stats["jump"] == "kept: this launch did not boot into it"
    assert p.read_bytes() == b"gameplay" and ad.saves == 0 and ad.jump_from is None


def test_dolphin_saves_after_good_play_but_never_while_fast_forwarding(tmp_path):
    ad, g = FakeDolphin(tmp_path), {"game_id": "g1"}
    stats, stuck = {}, SimpleNamespace(changed=0.0)
    ad.ff_on, ad.game = True, b"gameplay"

    def step(t):
        stuck.changed = t
        if t == 70:
            assert "jump" not in stats and ad.saves == 0             # the speed-limit key is held: no hotkey now
            ad.ff_on = False
    run(ad, g, 80, stats, stuck, step)
    assert stats["jump"] == "saved" and J.path_for(ad, g).read_bytes() == b"gameplay" and ad.saves == 1


# --- the real Dolphin adapters ---

class DolphinHotkeys:
    """Dolphin's side of gBox's Windows hotkeys: every Hotkeys.ini chord evaluated after each key gBox injects (the
    worst case, as if Dolphin polled between any two keys); a save hotkey writes <game id>.sNN like Dolphin does."""
    NAMES = {"Control_R": "RCONTROL", "Control_L": "LCONTROL", "Shift_R": "RSHIFT"}

    def __init__(self, ini: str, states: Path, game_id="GGSEA4"):
        self.chords = {}
        for line in ini.splitlines()[2:]:
            name, expr = line.split(" = ", 1)
            need, never = set(), set()
            for term in expr.split(" & "):
                (never if term.startswith("!") else need).add(term.strip("!`").split(":", 1)[1])
            self.chords[name] = (need, never)
        self.held, self.on, self.fired, self.states, self.game_id = set(), set(), [], states, game_id

    def __call__(self, pid, events, **kw):
        for e in events:
            (self.held.add if e["down"] else self.held.discard)(self.NAMES.get(e["key"], e["key"]))
            on = {n for n, (need, never) in self.chords.items() if need <= self.held and not never & self.held}
            for n in sorted(on - self.on):
                self.fired.append(n)
                slot = re.fullmatch(r"Save State/Save State Slot (\d+)", n)
                if slot:
                    (self.states / f"{self.game_id}.s{int(slot[1]):02d}").write_bytes(b"STATE" * 200 + n.encode())
            self.on = on
        return {"sent": len(events)}


@pytest.fixture
def win_dolphin(tmp_path, monkeypatch):
    from gbox.config import Config
    exe = tmp_path / "Dolphin-x64" / "gBox Dolphin.exe"
    states = exe.parent / "User" / "StateSaves"
    states.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(adapters.DolphinWinAdapter, "_lanes", {})
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    monkeypatch.setattr(ad, "_exe", lambda: exe, raising=False)
    monkeypatch.setattr(ad, "_gecko_setup", lambda user, rom: None, raising=False)
    monkeypatch.setattr(adapters, "_audio_selection", lambda *a, **k: {})
    ad._argv("GGSEA4 Twin Snakes.iso")                                   # writes Hotkeys.ini for its lane
    ad.proc = SimpleNamespace(pid=4242, poll=lambda: None)
    sim = DolphinHotkeys((exe.parent / "User" / "Config" / "Hotkeys.ini").read_text(), states)
    monkeypatch.setattr(adapters, "win_send_keys", sim)
    return ad, states, sim


def test_windows_dolphin_jump_save_fires_only_the_demo_slot_and_never_writes_slot_1(win_dolphin, tmp_path):
    ad, states, sim = win_dolphin
    mine = states / "GGSEA4.s01"
    mine.write_bytes(b"the operator's own save")
    os.utime(mine, (1000, 1000))
    dest = tmp_path / "runtime" / "jumpstates" / "g1-stock.state"
    assert ad.jump_save(dest) == dest.stat().st_size
    assert sim.fired == ["Save State/Save State Slot 10"]
    assert dest.read_bytes().endswith(b"Save State Slot 10")
    assert mine.read_bytes() == b"the operator's own save" and mine.stat().st_mtime == 1000
    assert not list(states.glob("*.s10")) and not list(states.glob("*.s08"))   # the demo slot's file: copied, removed
    ad.ff_on = True                                                      # the lane key is held: any chord could match
    with pytest.raises(RuntimeError, match="fast-forward"):
        ad.jump_save(dest)
    assert sim.fired == ["Save State/Save State Slot 10"]


def test_windows_dolphin_every_gbox_hotkey_fires_only_itself(win_dolphin):
    ad, _, sim = win_dolphin
    assert "Load State/Load State Slot 10" not in ad.HOTKEYS             # jump states load at boot, never by a key
    for name in ad.HOTKEYS:
        sim.fired.clear()
        ad._hotkey(name)
        assert sim.fired == [name]


def test_linux_dolphin_jump_save_uses_its_own_key_and_slot(tmp_path, monkeypatch):
    from gbox.config import Config
    ad = adapters.DolphinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    monkeypatch.setattr(ad, "_gecko_setup", lambda user, rom: None, raising=False)
    ad._argv("GGSEA4 Twin Snakes.iso")
    ini = (ad.config.runtime / "dolphin-user" / "Config" / "Hotkeys.ini").read_text()
    assert "Save State/Save State Slot 10 = `Shift_L` & `F10`\n" in ini and "Slot 10 = !" not in ini
    states = ad.state_dir()
    states.mkdir(parents=True, exist_ok=True)
    mine = states / "GGSEA4.s01"
    mine.write_bytes(b"the operator's own save")
    pressed = []

    def xdo(*args):                                                   # Dolphin writes the slot it was asked for
        pressed.append(args)
        if args[:4] == ("keydown", "Shift_L", "keydown", "F10"):
            (states / "GGSEA4.s10").write_bytes(b"S" * 4096)
    monkeypatch.setattr(ad, "_xdo", xdo, raising=False)
    dest = ad.config.runtime / "jumpstates" / "g1-stock.state"
    assert ad.jump_save(dest) == 4096 and dest.read_bytes() == b"S" * 4096
    assert pressed == [("keydown", "Shift_L", "keydown", "F10", "sleep", "0.1", "keyup", "F10", "keyup", "Shift_L")]
    assert mine.read_bytes() == b"the operator's own save" and not (states / "GGSEA4.s10").exists()


@pytest.mark.parametrize("cls", [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_dolphin_boots_with_save_state_only_when_a_jump_launch_found_this_builds_state(tmp_path, monkeypatch, cls):
    from tests.test_dolphin_sc2_compatibility import disc, prepare
    ad, _, _ = prepare(tmp_path, monkeypatch, cls)
    rom = disc(tmp_path / "sc2_sonic_cast.iso", b"GRSE69")
    g = {"game_id": "sc2", "mod": "sc2_sonic_cast"}
    stored(ad, {"game_id": "sc2", "mod": ""})                          # only the stock game has one
    assert not J.arm_boot(ad, g)["booted"]
    plain = ad._argv(rom)
    assert "-s" not in plain and not any("UsePanicHandlers" in a for a in plain)
    p = stored(ad, g)
    assert "-s" not in ad._argv(rom)                                    # the operator's launch: never asks, never jumps
    assert J.arm_boot(ad, g)["booted"]
    argv = ad._argv(rom)
    assert argv[-4:] == ["-s", str(p), "-e", rom]                        # Dolphin's --save_state, loaded at boot
    assert "Dolphin.Interface.UsePanicHandlers=False" in argv          # a damaged file never stops a demo on a dialog
    if cls is adapters.DolphinAdapter:                                  # the flatpak may read the jump state
        assert f"--filesystem={p.parent}:ro" in argv[:argv.index(cls.flatpak)]


# --- the launch and autoplay wiring (gbox.tools, gbox.server) ---

class LaunchDolphin(adapters.Adapter):
    """A Dolphin-like adapter for tools._launch_game: records what its --save_state would have been."""
    name = "dolphin-test"
    supported = {"launch_game", "stop_game"}

    def __init__(self, config, fail=False):
        self.config, self.fail, self.booted_from, self.jump_from = config, fail, "not launched", None

    def jump_boot(self, src):
        self.jump_from = Path(src)

    def jump_save(self, dest):
        raise AssertionError("nothing is saved at launch")

    def launch_game(self, rom):
        self.booted_from = self.jump_from
        if self.fail:
            raise RuntimeError("Dolphin exited 3")
        return {"pid": None}

    def stop_game(self):
        return {}


def launch(tmp_path, monkeypatch, jump, fail=False):
    from gbox import tools
    from gbox.config import Config, Library
    from gbox.models import CatalogEntry
    from gbox.registry import Ctx
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    share = tmp_path / "share"
    share.mkdir(exist_ok=True)
    (share / "sc2.iso").write_bytes(b"GRSE69" + bytes(64))
    cfg.libraries.append(Library(id="lib", kind="files", paths={"windows": str(share), "linux": str(share)}))
    ad = LaunchDolphin(cfg, fail)
    monkeypatch.setattr(adapters, "for_game", lambda *a, **k: ad)
    monkeypatch.setattr(tools, "SESSIONS", {})
    monkeypatch.setattr(tools, "track_emulator", lambda *a, **k: None)
    game = CatalogEntry(game_id="sc2", title="SC2", platform="gamecube", source_paths=["sc2.iso"], library="lib",
                        rel_path="sc2.iso", hashes={}, size=70, format="iso", runtimes={}, profile_id="sc2")
    try:
        return ad, tools._launch_game(tools.LaunchIn(game=game, jump=jump), Ctx(cfg, job_id="j1", worker="w1"))
    finally:
        tools.SESSIONS.clear()                                          # the session's watchers end with it


def test_a_launch_boots_into_the_jump_state_only_when_it_asks_for_one(tmp_path, monkeypatch):
    ad, out = launch(tmp_path, monkeypatch, jump=True)                   # nothing saved yet: boots the usual way
    assert ad.booted_from is None and out["detail"]["jump"]["booted"] is False
    p = stored(ad, {"game_id": "sc2", "mod": ""})
    ad, out = launch(tmp_path, monkeypatch, jump=False)                  # a plain Play, with a jump state there
    assert ad.booted_from is None and "jump" not in out["detail"]
    ad, out = launch(tmp_path, monkeypatch, jump=True)                   # the screensaver / autoplay on launch
    assert ad.booted_from == p and out["detail"]["jump"] == {"booted": True, "file": "sc2-stock.state"}


def test_a_launch_that_fails_after_booting_into_a_jump_state_drops_it(tmp_path, monkeypatch):
    ad, _ = launch(tmp_path, monkeypatch, jump=False)
    p = stored(ad, {"game_id": "sc2", "mod": ""})
    with pytest.raises(RuntimeError, match="exited"):
        launch(tmp_path, monkeypatch, jump=True, fail=True)
    assert not p.exists()                                                # the next demo boots the usual way


def test_auto_autoplay_after_a_jump_boot_plays_your_style_instead_of_replaying_from_boot(tmp_path, monkeypatch):
    from gbox import autoplay as apmod, tools
    ad, g = FakeDolphin(tmp_path), {"game_id": "g1", "mod": "", "title": "T", "platform": "gamecube"}
    stored(ad, g)
    monkeypatch.setattr(apmod, "Driver", lambda *a, **k: SimpleNamespace(stopped=False, trace=[]))
    started = time.time()
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: SimpleNamespace(
        json=lambda: [{"session_id": "s1", "game_id": "g1", "started": started}]))
    monkeypatch.setitem(tools.SESSIONS, "s1", (ad, g))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    monkeypatch.setattr(tools, "_playbook", lambda ad, g: None)
    monkeypatch.setattr(tools, "_missions", lambda game_id=None: [])
    modes = []
    monkeypatch.setattr(tools, "_start_imitation", lambda inp, *a: modes.append(inp.mode) or {"started": inp.mode})
    ctx = SimpleNamespace(server="http://x", headers={"authorization": "Bearer t"}, config=SimpleNamespace(runtime=tmp_path))

    def start():
        return tools.autoplay(tools.AutoplayIn(session_id="s1", op="start", mode="auto"), ctx)["result"]
    assert start()["started"] == "replay"                                # booted the usual way: your run from boot
    J.arm_boot(ad, g)
    assert start()["started"] == "learned" and modes == ["replay", "learned"]   # in gameplay already: your style


def test_after_a_replay_only_emulators_that_boot_into_jump_states_watch_for_one(tmp_path, monkeypatch):
    from gbox import tools
    started, went = [], threading.Event()
    monkeypatch.setattr(J, "watch", lambda ad, *a: started.append(ad) or went.set())
    run_ = {"sid": "s1", "thread": SimpleNamespace(is_alive=lambda: True)}
    d = SimpleNamespace(stopped=False)
    ra, dol = FakeRA(tmp_path), FakeDolphin(tmp_path)
    tools._jump_watch(run_, d, ra, {"game_id": "g1"}, None, {}, after_replay=True)
    tools._jump_watch(run_, d, dol, {"game_id": "g1"}, None, {}, after_replay=True)
    assert went.wait(5)
    tools._jump_watch(run_, d, ra, {"game_id": "g1"}, None, {})          # learned autoplay: RetroArch as before
    for _ in range(500):
        if len(started) == 2:
            break
        time.sleep(0.01)
    assert started == [dol, ra]


def test_autoplay_on_launch_asks_for_the_jump_and_a_plain_play_never_does(tmp_path):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    app.state.store.upsert_catalog([{"game_id": "sc2", "title": "SC2", "platform": "gamecube", "source_paths": ["sc2.iso"],
                                     "format": "iso", "profile_id": "sc2"}])
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        auto = client.post("/api/games/sc2/launch?node=linux&autoplay=true").json()
        plain = client.post("/api/games/sc2/launch?node=linux").json()
        debug = client.post("/api/games/sc2/launch?node=linux&autoplay=true&debug=true").json()
    assert auto["input"]["jump"] is True                                 # the job's input, filled in with LaunchIn
    assert plain["input"].get("jump") is False and debug["input"].get("jump") is False


def test_a_demo_launch_keeps_no_checkpoint_ring_and_is_marked_a_demo(tmp_path, monkeypatch):
    from gbox import rewind
    seen = []
    monkeypatch.setattr(rewind, "start", lambda sid, ad, config, game, enabled, alive=None: seen.append(enabled) or
                        {"mode": "off" if enabled is False else "checkpoint"})
    ad, out = launch(tmp_path, monkeypatch, jump=True)                   # the screensaver / autoplay on launch
    assert seen == [False] and getattr(ad, "demo", False) is True       # "a maximum of two save states"
    seen.clear()
    ad, out = launch(tmp_path, monkeypatch, jump=False)                  # the operator's own Play
    assert seen == [None] and not getattr(ad, "demo", False)             # gbox.toml decides, as before


@pytest.mark.parametrize("cls", [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_a_demo_dolphin_never_stops_on_a_dialog_and_shows_no_messages(tmp_path, monkeypatch, cls):
    from tests.test_dolphin_sc2_compatibility import disc, prepare
    ad, _, _ = prepare(tmp_path, monkeypatch, cls)
    rom = disc(tmp_path / "sc2.iso", b"GRSE69")
    plain = ad._argv(rom)
    assert not any("UsePanicHandlers" in a or "OnScreenDisplayMessages" in a for a in plain)   # the operator's Play
    ad.demo = True                                                       # a demo, no jump state yet
    argv = ad._argv(rom)
    assert "Dolphin.Interface.UsePanicHandlers=False" in argv            # a game crash doesn't freeze it on a dialog
    assert "Dolphin.Interface.OnScreenDisplayMessages=False" in argv     # no "Saved State to ..s08" on screen


# ---- RetroArch entry-slot jump (gbox/jumpstate.strategy() == "entryslot") ----

def real_ra(tmp_path: Path):
    """A real RetroArchAdapter whose launch paths are never taken: only the entry-slot path helpers are exercised."""
    cfg = SimpleNamespace(executable="retroarch", core="core.so", args=[])
    ad = adapters.RetroArchAdapter(cfg, config=SimpleNamespace(runtime=tmp_path))
    ad.states_override = tmp_path / "states"
    return ad


class FakeEntryAdapter:
    """The RetroArch entry-slot contract: a _jump_entryslot marker, jump_boot (records jump_from) and a real
    RetroArchAdapter's _entry_path/_jump_args (borrowed here by delegation, not by launch)."""

    config = None

    def __init__(self, tmp: Path):
        self.config = SimpleNamespace(runtime=tmp)
        self.states = tmp / "states"

    def _jump_entryslot(self, src):
        self.entry = src

    def jump_boot(self, src):
        self.jump_from = src

    def jump_save(self, dest):
        return 0


class BootAdapter:
    """An adapter whose type offers jump_boot/jump_save but no _jump_entryslot marker (Dolphin's 'boot' strategy)."""

    config = SimpleNamespace(runtime=Path())

    def jump_boot(self, src):
        pass

    def jump_save(self, dest):
        return 0


def test_retroarch_uses_the_entryslot_strategy_not_a_boot_or_slot(tmp_path):
    ad = real_ra(tmp_path)
    assert J.strategy(ad) == "entryslot"
    # an adapter whose type has jump_boot/jump_save but no _jump_entryslot marker is still "boot" (Dolphin)
    assert J.strategy(BootAdapter()) == "boot"


def test_retroarch_entry_path_is_content_dot_state1_dot_entry(tmp_path):
    ad = real_ra(tmp_path)
    assert ad._content_base("/games/sc2/star.iso") == "star"
    # the resolved ROM (archive-extracted content) is the basename without its last extension; entry adds ".entry"
    assert ad._entry_path("/games/sc2/star.iso") == (tmp_path / "states" / "star.state1.entry")


def test_jump_args_stages_the_entry_state_and_requests_entryslot_1(tmp_path):
    ad = real_ra(tmp_path)
    src = tmp_path / "jumpstates" / "sc2.state"
    src.parent.mkdir(); src.write_bytes(b"SAVESTATE")
    rom = "/games/sc2.iso"
    assert ad._jump_args(rom) == []                                     # no jump asked for: plain Play stays plain
    assert not ad._entry_path(rom).exists()
    ad.jump_boot(src)                                                   # a jump-requested launch (autoplay, never a Play)
    assert ad._jump_args(rom) == ["-e", "1"]                            # RetroArch boots into the entry slot
    dst = ad._entry_path(rom)
    assert dst.read_bytes() == b"SAVESTATE"                             # the jump state landed at <content>.state1.entry
    assert dst.name == "sc2.state1.entry"
    # the operator's plain slot file for this content is untouched: the .entry is a distinct path
    assert not (tmp_path / "states" / "sc2.state1").exists()


def test_jump_state_is_saved_through_the_reserved_slot_and_never_switches(tmp_path):
    ad = real_ra(tmp_path)
    captured = {}

    def save_state(slot=None):
        captured["slot"] = slot
        f = tmp_path / "states" / f"sc2.state{slot}"
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"PLAYFIELD")
        return {"path": str(f), "slot": slot}

    ad.save_state = save_state
    dest = tmp_path / "jumpstates" / "sc2.state"
    assert ad.jump_save(dest) == 9                                      # 9 bytes: PLAYFIELD
    assert dest.read_bytes() == b"PLAYFIELD"
    assert captured == {"slot": 9}                                      # reserved demo slot, the operator's slot untouched


