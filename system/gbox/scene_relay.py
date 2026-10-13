"""Examine 3D *Capture again* at the operator's exact moment, without touching their game (#971 stage 2).

RenderDoc can't get inside some sessions where they run: RetroArch's compatibility-GL window breaks under injection
(PSO Ver.2 on Flycast), and sessions started without Examine 3D have no RenderDoc at all. For those the capability
matrix (gbox/scene_support.py) sets `relay`. This module, run inside the control plane as the in-server job
"scene_relay", does:

  1. save state     state_transfer export on the operator's session (the game keeps running; nothing is paused)
  2. capture session launch_game with capture_backend on the test PC (config `examine_capture_worker`,
                    background-testing rules: ticked in the Tasks menu, no live game there, not the operator's PC);
                    when it can't be used, RetroArch runs a hidden capture session on the operator's own worker next to
                    their game (keep_session: their game is not closed; its own config dir, no audio, no pad, window
                    parked off-screen). The capture session renders with the matrix's driver (vulkan + RenderDoc's
                    Vulkan layer, or glcore with RenderDoc injected) and is labelled agent-owned.
  3. load state     state_transfer import into the capture session
  4. capture        scene_capture on the capture session -> scene.glb artifact
  5. close          the capture session is stopped whatever happened; the GLB goes back to the Examine panel

Everything that talks to the control plane is injected (run_job, workers, sessions, label, end_session), so the
flow is tested without a server or an emulator (tests/test_scene_relay.py).
"""
from __future__ import annotations

import time

TOOL = "scene_relay"
BOOT_SETTLE_S = 6.0                 # same as session_swap: let the core boot before loading the state
LOAD_SETTLE_S = 2.0                 # let the loaded moment render before the capture is armed
LOCAL_ADAPTERS = ("retroarch",)     # adapters whose capture session can run beside the operator's game on one PC
                                    # (Dolphin would share the operator's portable User folder: test PC only)


class RelayError(RuntimeError):
    """The relay could not run; the message is shown in the Examine panel. The operator's game is never affected."""


def wants_relay(sess: dict | None, inp: dict | None = None) -> bool:
    """POST /api/jobs scene_capture -> run it as a relay? (explicit `relay`, or the session's matrix row asks for it.)
    Never for a capture session itself (no relay of a relay)."""
    sess, inp = sess or {}, inp or {}
    detail = sess.get("detail") or {}
    if detail.get("capture_session"):
        return False
    row = detail.get("scene_capture") or {}
    if inp.get("relay"):
        return True
    return bool(row.get("relay")) and row.get("status") == "relaunch_under_capture"


def pick_worker(sid: str, adapter: str, workers: list[dict], live_sessions: list[dict], preferred: str = "",
                worker_of=lambda s: s.split("-")[0], skip: tuple = ()) -> dict:
    """Where the capture session runs: {"worker": <worker dict>, "keep_session": sid | "", "where": "test PC" |
    "this PC"}. Raises RelayError with the reason when neither can be used."""
    op_wid = worker_of(sid)
    ok = [w for w in workers if w.get("online") and w.get("os") == "windows"
          and {"launch_game", "scene_capture", "state_transfer"} <= set(w.get("tools") or [])
          and w.get("id") not in skip]
    busy = {worker_of(s["session_id"]) for s in live_sessions if s.get("state") == "running" and s.get("session_id")}
    why = []
    if preferred:
        test = next((w for w in ok if preferred.lower() in (str(w.get("name", "")).lower(), str(w.get("id", "")).lower())), None)
        if test is None:
            why.append(f"the test PC {preferred} is offline or can't run capture sessions")
        elif test["id"] == op_wid:
            pass                                          # the operator plays on the test PC: same-PC capture session
        elif test.get("background_testing") is False:
            why.append(f"{test['name']} is unticked for background testing (Tasks menu)")
        elif test["id"] in busy:
            why.append(f"{test['name']} already has a live game")
        else:
            return {"worker": test, "keep_session": "", "where": "test PC"}
    op = next((w for w in ok if w["id"] == op_wid), None)
    if op is not None and adapter in LOCAL_ADAPTERS:
        return {"worker": op, "keep_session": sid, "where": "this PC"}
    if op is None:
        why.append("the game's own PC can't run a capture session (offline, or RenderDoc capture unavailable)")
    else:
        why.append(f"a {adapter} capture session can't run beside your game on the same PC")
    raise RelayError("No PC can run the capture session right now: " + "; ".join(why) + ". Your game keeps running.")


def relay(sid: str, sess: dict, game: dict, *, run_job, workers, live_sessions, label=None, end_session=None,
          preferred: str = "", frames: int = 2, fovy: float = 0, aspect: float = 0, say=None, should_stop=None,
          worker_of=lambda s: s.split("-")[0], sleep=time.sleep) -> dict:
    """Run the capture relay for live session `sid` (see the module docstring); returns the scene_capture-shaped
    output {session_id, glb, summary, paused: False, resume_on_leave: False, capture_session}.
    run_job(tool, input, worker_id, wait, progress=None) -> job output (raises on failure)."""
    say = say or (lambda pct, msg: None)
    stop = should_stop or (lambda: False)
    detail = sess.get("detail") or {}
    row = detail.get("scene_capture") or {}
    adapter = sess.get("adapter") or row.get("adapter") or ""
    if sess.get("state") != "running":
        raise RelayError("This game session has ended. Open the running game in Sessions to examine it.")
    if row.get("status") == "unsupported":
        raise RelayError(row.get("reason") or "This emulator has no 3D capture path (2D frame only).")
    if row and not row.get("relay") and row.get("status") != "supported":
        raise RelayError(row.get("reason") or "This session can't be captured in a capture session.")
    driver = row.get("driver") or "auto"
    t0 = time.time()
    op_wid = worker_of(sid)

    say(3, "Saving this moment for a capture session (your game keeps running)")
    try:
        saved = run_job("state_transfer", {"session_id": sid, "op": "export"}, op_wid, 90)
        art = (saved.get("result") or {})["artifact"]
    except Exception as e:                                # noqa: BLE001
        raise RelayError(f"Your moment could not be saved ({_short(e)}), so nothing was captured. "
                         "Your game keeps running.") from e
    if stop():
        raise RelayError("cancelled before the capture session started; your game keeps running")

    tried, launched, target, last = [], None, None, None
    for _ in range(2):                                    # the test PC first; if its launch fails, this PC (RetroArch)
        target = pick_worker(sid, adapter, workers(), live_sessions(), preferred, worker_of, tuple(tried))
        w = target["worker"]
        say(12, f"Starting a capture session on {w['name']} ({target['where']}, {driver})")
        try:
            launched = run_job("launch_game", {
                "game": game, "mod": sess.get("launch_mod") or sess.get("staged_mod") or sess.get("mod") or "",
                "examine": True, "capture_backend": driver, "capture_for": sid,
                "keep_session": target["keep_session"]}, w["id"], 900,
                lambda pct, msg: say(12 + pct * 0.18, f"Capture session: {msg}"))
            break
        except Exception as e:                            # noqa: BLE001
            last = e
            tried.append(w["id"])
            if target["where"] == "this PC":
                break
    if launched is None:
        raise RelayError(f"The capture session did not start ({_short(last)}). Your game keeps running.")
    nsid, w = launched["session_id"], target["worker"]
    if label:
        try:
            label(nsid, {"label": f"Examine 3D capture of {sess.get('title') or game.get('title') or sid}",
                         "owner": "agent"})
        except Exception:                                 # noqa: BLE001
            pass
    load, cap = {}, None
    try:
        sleep(BOOT_SETTLE_S)
        say(32, "Loading your moment into the capture session")
        try:
            load = (run_job("state_transfer", {"session_id": nsid, "op": "import", "artifact": art}, w["id"], 120)
                    .get("result") or {})
        except Exception as e:                            # noqa: BLE001
            raise RelayError(f"Your moment could not be loaded into the capture session ({_short(e)}); nothing was "
                             "captured. Your game keeps running.") from e
        sleep(LOAD_SETTLE_S)
        say(40, "Capturing the frame in the capture session (RenderDoc)")
        try:
            cap = run_job("scene_capture", {"session_id": nsid, "frames": frames, "fovy": fovy, "aspect": aspect},
                          w["id"], 900, lambda pct, msg: say(40 + pct * 0.55, msg))
        except Exception as e:                            # noqa: BLE001
            raise RelayError(f"The capture session could not capture the frame ({_short(e)}). Your game keeps "
                             "running.") from e
    finally:
        say(96, "Closing the capture session")
        try:
            run_job("session_op", {"session_id": nsid, "op": "stop_game", "args": {}}, w["id"], 60)
        except Exception:                                 # noqa: BLE001
            pass
        if end_session:
            try:
                end_session(nsid)
            except Exception:                             # noqa: BLE001
                pass
    info = {"session_id": nsid, "worker": w.get("name"), "where": target["where"], "driver": driver,
            "attach": row.get("attach"), "moment": "save_state", "state_artifact": art,
            "load_requested": bool(load.get("load_requested", True)), "load_verified": load.get("load_verified"),
            "operator_paused": False, "seconds": round(time.time() - t0, 1)}
    summary = dict(cap.get("summary") or {})
    summary["capture_session"] = info
    return {"session_id": sid, "glb": cap["glb"], "summary": summary, "paused": False, "resume_on_leave": False,
            "capture_session": info}


def _short(e) -> str:
    s = str(getattr(e, "detail", None) or e)
    return s if len(s) < 300 else s[:297] + "..."
