"""Boot jump states (gbox.jumpstate): saved after a good stretch of autoplay, loaded at the next start, dropped when
they land on a menu; the operator's save slot is always put back."""
from pathlib import Path
from types import SimpleNamespace

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
