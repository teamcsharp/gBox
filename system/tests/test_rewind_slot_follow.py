"""#1488: PSO (Flycast) froze; the emulation-issue recovery preserved the moment in RetroArch slot 15. The checkpoint
ring kept saving into whatever slot RetroArch was on, so its next save landed in slot 15 and it then copied slot 0's
backup over that file. The ring must follow a slot change: protect the new slot before saving and never restore
another slot's backup onto it."""
import threading
from pathlib import Path

from gbox import adapters, rewind


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, dt: float) -> float:
        self.t += dt
        return self.t


class SlotEmulator:
    """RetroArch-like: saves go to the current slot (game.state, game.state1, ...); save_state(slot) switches slot."""
    name = "fakearch"
    supported = {"save_state", "load_state"}
    checkpoint_state = "path"

    def __init__(self, states: Path, follow: bool = True):
        self.states, self.frame, self.slot, self.loads = states, 0, 0, []
        self.states.mkdir(parents=True, exist_ok=True)
        self._state_lock = threading.RLock()
        if follow:
            self.checkpoint_target = lambda: self.file(self.slot)

    def file(self, slot: int) -> Path:
        return self.states / ("game.state" + (str(slot) if slot else ""))

    def state_dir(self):
        return self.states

    def save_state(self, slot=None):
        if slot is not None:
            self.slot = int(slot)
        self.file(self.slot).write_bytes(f"frame={self.frame}".encode())
        return {"slot": self.slot, "path": str(self.file(self.slot)), "verified": True}

    def load_state(self, slot=None):
        self.frame = int(self.file(self.slot).read_bytes().split(b"=")[1])
        self.loads.append(self.frame)
        return {"slot": self.slot}


def ring_for(tmp_path, ad, clock):
    return rewind.CheckpointRing(ad, tmp_path / "ring", interval_s=1.0, depth=10, clock=clock, sleep=lambda s: None,
                                 content=tmp_path / "roms" / "game.chd")


def test_ring_follows_a_slot_switch_and_keeps_the_preserved_checkpoint(tmp_path):
    clock, ad = Clock(), SlotEmulator(tmp_path / "states")
    ad.file(0).write_bytes(b"operator slot 0")
    ring = ring_for(tmp_path, ad, clock)
    ad.frame = 4
    assert ring.maybe_take(clock.tick(1.0)) is not None
    assert ad.file(0).read_bytes() == b"operator slot 0"
    with ring.guard():                                    # the emulation-issue recovery preserves the frozen moment
        ad.frame = 7
        ad.save_state(slot=15)
    preserved = ad.file(15).read_bytes()
    ad.frame = 9
    entry = ring.maybe_take(clock.tick(1.0))
    assert Path(entry["file"]).read_bytes() == b"frame=9"
    assert ad.file(15).read_bytes() == preserved == b"frame=7"      # not slot 0's backup, not the ring's save
    assert ad.file(0).read_bytes() == b"operator slot 0"
    assert ring.step_back()["seq"] == 2 and ad.loads == [9]
    assert ad.file(15).read_bytes() == b"frame=7"
    ring.release()
    ring.close()
    assert ad.file(15).read_bytes() == b"frame=7" and ad.file(0).read_bytes() == b"operator slot 0"


def test_operator_save_to_the_old_slot_survives_the_slot_switch(tmp_path):
    clock, ad = Clock(), SlotEmulator(tmp_path / "states")
    ad.file(0).write_bytes(b"operator slot 0")
    ring = ring_for(tmp_path, ad, clock)
    ad.frame = 4
    ring.maybe_take(clock.tick(1.0))
    with ring.guard():
        ad.frame = 6
        ad.save_state(slot=0)                             # the operator saves slot 0 again...
        ad.frame = 7
        ad.save_state(slot=15)                            # ...then the freeze recovery preserves slot 15
    ad.frame = 9
    ring.maybe_take(clock.tick(1.0))
    assert ad.file(15).read_bytes() == b"frame=7"
    assert ad.file(0).read_bytes() == b"frame=6"          # the newer manual save, not the ring's stale backup
    ring.close()
    assert ad.file(0).read_bytes() == b"frame=6" and ad.file(15).read_bytes() == b"frame=7"

def test_switch_to_an_empty_slot_never_receives_another_slots_backup(tmp_path):
    clock, ad = Clock(), SlotEmulator(tmp_path / "states", follow=False)   # adapter that cannot name its next file
    ad.file(0).write_bytes(b"operator slot 0")
    ring = ring_for(tmp_path, ad, clock)
    ring.maybe_take(clock.tick(1.0))
    ad.slot = 3                                                        # slot switched by hotkey, nothing saved yet
    ad.frame = 5
    ring.maybe_take(clock.tick(1.0))
    assert ad.file(3).read_bytes() == b"frame=5"                       # the ring's own save, never b"operator slot 0"
    assert ad.file(0).read_bytes() == b"operator slot 0"


def test_retroarch_names_the_file_of_its_current_slot(tmp_path):
    ra = object.__new__(adapters.RetroArchAdapter)
    assert ra.checkpoint_target() is None                              # nothing saved yet: RetroArch's folder is unknown
    ra._last_state_path = tmp_path / "Flycast" / "Phantasy Star Online Ver. 2 (USA).state15"
    ra.slot = 0
    assert ra.checkpoint_target().name == "Phantasy Star Online Ver. 2 (USA).state"
    ra.slot = 3
    assert ra.checkpoint_target() == tmp_path / "Flycast" / "Phantasy Star Online Ver. 2 (USA).state3"
