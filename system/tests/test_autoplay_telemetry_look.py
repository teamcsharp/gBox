"""The worker's autoplay telemetry carries stats["look"] (gbox.mercs.bot_look: the Mercenaries bot's last shots and
decisions; operator 2026-10-26: "when i say 'look at the bot' i want you able to see the last things and results of the
last bullets being fired by the bot") beside the scalar stats, bounded so it never costs the whole packet."""
from types import SimpleNamespace

from gbox import tools

LOOK = {"shots": [{"t": 3.0, "weapon": "Handgun (0x23)", "gate": "on him",
                   "target": {"id": "1", "kind": "ganado", "dist_m": 2.0, "bearing_deg": 4.0},
                   "aim_err_deg": 0.5, "dot_on": "wall", "outcome": "miss:wall", "hp_delta": None}],
        "decisions": [{"t": 3.0, "phase": "fight", "decision": "fire", "reason": "on slot 1 d 2000 yaw +0.5 FIRE"}],
        "idle_among_foes_s": 0.0, "walls_shot": 1}


def test_the_worker_telemetry_carries_stats_look_and_only_within_its_bound(monkeypatch):
    threads, packets = [], []

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
            threads.append(self)

        def start(self):
            pass

    monkeypatch.setattr(tools.threading, "Thread", Thread)
    monkeypatch.setattr(tools.time, "sleep", lambda _: None)
    monkeypatch.setattr(tools, "_ap_headers", lambda ctx: {})
    monkeypatch.setattr(tools.httpx, "post", lambda *a, **kw: packets.append(kw["json"]))
    live = {"phase": "fight", "look": LOOK, "round_audit": {"verdict": "OK"}}
    tools._telemetry({"sid": "s1", "live": live}, SimpleNamespace(server="http://test", job_id="j"))
    threads[0].target()                                                   # the run is over: its last packet
    assert packets[-1]["stats"] == {"phase": "fight", "look": LOOK}      # other dict stats stay out, as before
    big = dict(LOOK, decisions=[{"t": 1.0, "phase": "x", "decision": "y", "reason": "z" * 50_000}])
    assert "look" not in tools._telemetry_blocks({"look": big})          # over the bound: left out, the packet still goes
    assert tools._telemetry_blocks({"look": {"bad": float("nan")}}) == {}   # not finite JSON: left out
    assert tools._telemetry_blocks({"look": "text"}) == {}               # only a JSON object
