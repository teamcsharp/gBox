"""Phase -> signal logic for the ComfyUI coordinator (gbox/comfy_coordinator.py).

The real SIGSTOP/SIGCONT are replaced by a recorder so the logic is tested on any OS without touching a process.
The queue read is injected too (busy unless a test says otherwise), except where a tiny local HTTP server stands in.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from gbox.comfy_coordinator import (ComfyCoordinator, game_active, is_loopback, queue_state, STOP, CONT,
                                    SLOW_READS)


class Queue:
    """An injected /queue read: .state is what the next read answers."""
    def __init__(self, state="busy", running=1, pending=0):
        self.state, self.running, self.pending, self.reads = state, running, pending, 0

    def __call__(self):
        self.reads += 1
        return {"state": self.state, "running": self.running, "pending": self.pending}


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


def make(enabled=True, pid=123, alive=(123,), url="http://127.0.0.1:8188", queue=None, stopped=None, **kw):
    killer = Killer(alive=alive)
    coord = ComfyCoordinator(url, enabled, log=lambda *a, **k: None, find=lambda: pid, kill=killer,
                             queue=queue or Queue(), stopped=stopped or (lambda pid: True), **kw)
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
                             find=lambda: next(pids), kill=killer, queue=Queue(), stopped=lambda pid: True)
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
    coord = ComfyCoordinator("http://127.0.0.1:8188", True, log=lambda *a, **k: None, find=lambda: 123, kill=Boom(),
                             queue=Queue())
    coord.sync(True)                                  # must not raise, must not claim it paused
    assert coord.paused is False


# --- freeze only during renders (operator 2026-11-10 via Pine Box) ----------
def test_an_idle_comfyui_stays_awake_through_play():
    q = Queue("idle", 0, 0)
    coord, killer = make(queue=q)
    for _ in range(5):
        coord.sync(True, {"title": "Resident Evil 6", "phase": "playing"})
    assert killer.sigs() == [] and coord.paused is False
    assert q.reads == 5 and "idle" in coord.note


def test_a_render_asked_for_mid_round_pauses_on_the_next_read_and_resumes_at_the_gap():
    q = Queue("idle", 0, 0)
    coord, killer = make(queue=q)
    coord.sync(True, {"title": "Resident Evil 6", "phase": "playing"})
    assert killer.sigs() == []
    q.state, q.running, q.pending = "busy", 1, 2                      # Pine asks for an image
    coord.sync(True)
    assert killer.sigs() == [STOP] and coord.paused
    st = coord.status()
    assert st["since"] and "1 running, 2 pending" in st["why"] and "Resident Evil 6 (playing)" in st["why"]
    assert st["game"] == {"title": "Resident Evil 6", "phase": "playing"}
    coord.sync(True)                                                  # held until the gap: a stopped server is not read
    assert q.reads == 2 and killer.sigs() == [STOP]
    coord.sync(False, {"title": "Resident Evil 6", "phase": "parked"})
    assert killer.sigs() == [STOP, CONT] and coord.paused is False and coord.status()["why"] == ""


def test_nothing_listening_is_never_signalled():
    coord, killer = make(queue=Queue("down", None, None))
    coord.sync(True)
    assert killer.sigs() == [] and "nothing to pause" in coord.note


def test_a_slow_queue_pauses_only_after_reads_in_a_row():
    q = Queue("slow", None, None)
    coord, killer = make(queue=q)
    for _ in range(SLOW_READS - 1):
        coord.sync(True)
    assert killer.sigs() == []                                         # one slow answer on a busy CPU is not a render
    coord.sync(True)
    assert killer.sigs() == [STOP] and "assumed rendering" in coord.why
    q2 = Queue("slow", None, None)
    coord2, killer2 = make(queue=q2)
    coord2.sync(True)
    q2.state = "idle"
    coord2.sync(True)
    q2.state = "slow"
    coord2.sync(True)
    assert killer2.sigs() == []                                        # the streak starts again after an answer


def test_resumed_outside_gbox_is_re_checked_from_its_queue():
    q = Queue("busy")
    state = {"stopped": True}
    coord, killer = make(queue=q, stopped=lambda pid: state["stopped"])
    coord.sync(True)
    assert killer.sigs() == [STOP]
    state["stopped"] = False                                          # someone SIGCONTed it (Pine, 14:24)
    q.state, q.running = "idle", 0
    coord.sync(True)
    assert coord.paused is False and coord.outside_resumes == 1 and killer.sigs() == [STOP]   # idle: left awake
    coord.sync(False)
    assert killer.sigs() == [STOP]                                     # nothing of ours to resume at the gap


def test_resumed_outside_gbox_with_work_is_paused_again():
    state = {"stopped": True}
    coord, killer = make(queue=Queue("busy"), stopped=lambda pid: state["stopped"])
    coord.sync(True)
    state["stopped"] = False
    coord.sync(True)
    assert killer.sigs() == [STOP, STOP] and coord.paused and coord.outside_resumes == 1


def test_the_state_file_tells_pine_why_and_since(tmp_path):
    path = tmp_path / "comfy-coordinator.json"
    clock = iter(range(1000, 2000, 5))
    coord, _killer = make(state_path=path, clock=lambda: next(clock))
    coord.sync(True, {"title": "Resident Evil 4", "phase": "playing", "warming": False})
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["paused"] is True and body["pid"] == 123 and body["since"] and body["stops"] == 1
    assert "Resident Evil 4 (playing)" in body["why"] and body["game"]["title"] == "Resident Evil 4"
    assert body["updated_at"] and body["queue"]["state"] == "busy"
    coord.sync(False)
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["paused"] is False and body["conts"] == 1 and body["since"] is None


def test_with_a_watcher_the_tick_never_reads_the_queue_itself():
    q = Queue("idle", 0, 0)
    coord, killer = make(queue=q)
    try:
        coord.start(interval=0.05)
        coord.sync(True, {"title": "Resident Evil 5", "phase": "playing"})   # the tick: no HTTP on its thread
        q.state, q.running = "busy", 1
        deadline = time.time() + 3
        while not coord.paused and time.time() < deadline:
            time.sleep(0.02)
        assert coord.paused and killer.sigs() == [STOP]                  # the watcher saw the render
    finally:
        coord.release()
    assert killer.sigs() == [STOP, CONT] and coord.paused is False


def test_the_watcher_is_idle_in_the_gaps():
    q = Queue("busy")
    coord, killer = make(queue=q)
    coord.sync(False)
    coord.watch_once()
    assert q.reads == 0 and killer.sigs() == []


# --- the real /queue read against a stand-in server ----------------------
def _server(body: dict, delay: float = 0.0):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):                             # noqa: N802
            time.sleep(delay)
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_queue_state_reads_comfyui_queue():
    srv, url = _server({"queue_running": [[1, "abc"]], "queue_pending": [[2, "d"], [3, "e"]]})
    try:
        assert queue_state(url) == {"state": "busy", "running": 1, "pending": 2}
    finally:
        srv.shutdown()
    srv, url = _server({"queue_running": [], "queue_pending": []})
    try:
        assert queue_state(url) == {"state": "idle", "running": 0, "pending": 0}
    finally:
        srv.shutdown()


def test_queue_state_down_and_slow():
    srv, url = _server({})
    srv.shutdown()
    srv.server_close()
    # nothing listening (Windows retries a refused loopback connect for ~2 s; Linux refuses at once)
    assert queue_state(url, timeout=5.0)["state"] == "down"
    srv, url = _server({"queue_running": []}, delay=1.0)
    try:
        assert queue_state(url, timeout=0.2)["state"] == "slow"
    finally:
        srv.shutdown()
