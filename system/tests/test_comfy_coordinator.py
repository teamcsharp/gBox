"""Phase -> signal logic for the ComfyUI coordinator (gbox/comfy_coordinator.py).

The real SIGSTOP/SIGCONT are replaced by a recorder so the logic is tested on any OS without touching a process.
"""
from gbox.comfy_coordinator import ComfyCoordinator, game_active, is_loopback, STOP, CONT


class Killer:
    """Records (pid, sig) calls; os.kill(pid, 0) liveness probes consult `alive`."""
    def __init__(self, alive=None):
        self.calls = []
        self.alive = set(alive or ())

    def __call__(self, pid, sig):
        if sig == 0:                                  # liveness probe
            if pid not in self.alive:
                raise ProcessLookupError(pid)
            return
        self.calls.append((pid, sig))

    def sigs(self):
        return [sig for _pid, sig in self.calls]


def make(enabled=True, pid=123, alive=(123,), url="http://127.0.0.1:8188"):
    killer = Killer(alive=alive)
    coord = ComfyCoordinator(url, enabled, log=lambda *a, **k: None, find=lambda: pid, kill=killer)
    return coord, killer


# --- pure helpers ---------------------------------------------------------
def test_game_active_phases():
    assert game_active({"phase": "playing"}) is True
    assert game_active({"phase": "starting"}) is True
    assert game_active({"phase": "launching"}) is True
    for gap in ("parked", "ready", "ended", "prelaunch", None, ""):
        assert game_active({"phase": gap}) is False
    assert game_active(None) is False
    assert game_active({}) is False


def test_is_loopback():
    assert is_loopback("http://127.0.0.1:8188")
    assert is_loopback("http://localhost:8188")
    assert is_loopback("http://[::1]:8188")
    assert not is_loopback("http://10.89.1.246:8188")
    assert not is_loopback("http://spark2:8188")


# --- playing -> stop ------------------------------------------------------
def test_playing_stops_once_and_is_idempotent():
    coord, killer = make()
    coord.sync(True)
    assert coord.paused is True and coord.pid == 123
    assert killer.sigs() == [STOP]
    coord.sync(True)                                  # still playing: no second stop
    assert killer.sigs() == [STOP]
    assert coord.stops == 1


# --- park / rotate -> cont ------------------------------------------------
def test_gap_resumes_once_and_is_idempotent():
    coord, killer = make()
    coord.sync(True)
    coord.sync(False)                                 # round ended / warm-park / rotation
    assert coord.paused is False and coord.pid is None
    assert killer.sigs() == [STOP, CONT]
    coord.sync(False)                                 # still a gap: no second resume
    assert killer.sigs() == [STOP, CONT]
    assert coord.conts == 1


def test_play_gap_play_cycle():
    coord, killer = make()
    coord.sync(True); coord.sync(False); coord.sync(True); coord.sync(False)
    assert killer.sigs() == [STOP, CONT, STOP, CONT]
    assert coord.stops == 2 and coord.conts == 2


# --- shutdown / release -> cont ------------------------------------------
def test_release_resumes_when_paused():
    coord, killer = make()
    coord.sync(True)
    coord.release()                                   # server shutdown
    assert coord.paused is False
    assert killer.sigs() == [STOP, CONT]


def test_release_is_noop_when_not_paused():
    coord, killer = make()
    coord.release()
    assert killer.sigs() == []


# --- disable safety -------------------------------------------------------
def test_disabled_never_stops():
    coord, killer = make(enabled=False)
    coord.sync(True)
    assert killer.sigs() == [] and coord.paused is False


def test_disabling_at_runtime_resumes_a_paused_process():
    coord, killer = make()
    coord.sync(True)
    assert coord.paused is True
    coord.enabled = False                             # operator turned it off
    coord.sync(True)                                  # must not strand it stopped
    assert coord.paused is False
    assert killer.sigs() == [STOP, CONT]


# --- fail-soft ------------------------------------------------------------
def test_no_comfy_running_is_a_noop():
    coord, killer = make(pid=None)
    coord.sync(True)
    assert coord.paused is False and killer.sigs() == []


def test_non_loopback_url_is_inert():
    coord, killer = make(url="http://10.89.1.246:8188")
    coord.sync(True)
    assert killer.sigs() == [] and coord.paused is False


def test_dead_process_is_re_paused_with_new_pid():
    # We paused pid 123; it dies; a fresh ComfyUI (pid 777) is now listening. Next active tick must re-pause 777.
    killer = Killer(alive={123})
    pids = iter([123, 777])
    coord = ComfyCoordinator("http://127.0.0.1:8188", True, log=lambda *a, **k: None,
                             find=lambda: next(pids), kill=killer)
    coord.sync(True)
    assert coord.pid == 123 and killer.sigs() == [STOP]
    killer.alive = {777}                              # 123 gone, 777 up
    coord.sync(True)
    assert coord.pid == 777
    assert killer.sigs() == [STOP, STOP]


def test_signal_failure_does_not_mark_paused():
    class Boom(Killer):
        def __call__(self, pid, sig):
            if sig == 0:
                return
            raise PermissionError("nope")
    coord = ComfyCoordinator("http://127.0.0.1:8188", True, log=lambda *a, **k: None, find=lambda: 123, kill=Boom())
    coord.sync(True)                                  # must not raise, must not claim it paused
    assert coord.paused is False
