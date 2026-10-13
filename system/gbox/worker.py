"""Execution worker: same code on Linux and Windows. Registers capabilities, claims jobs, posts results+artifacts."""
import base64
import platform
import threading
import time

import httpx

from . import deps
from . import tools as _builtin  # noqa: F401  (registers tools)
from .config import Config
from .models import WorkerInfo
from .registry import HOST_OS, REGISTRY, Ctx, execute
from .worker_results import ResultOutbox

MAX_PARALLEL = 4          # long jobs (library scans) must not block short ones (stop_game) on the same node
REDESCRIBE_S = 60         # re-check tool availability (e.g. after provisioning installed ghidra)
HEARTBEAT_S = 10          # liveness must not depend on a free execution slot


def user_idle_seconds() -> float | None:
    """Windows console-session inactivity, including input outside gBox. None means unknown."""
    if platform.system().lower() != "windows":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        ctypes.windll.kernel32.GetTickCount.restype = wintypes.DWORD
        return round(((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000, 1)
    except (AttributeError, OSError):
        return None


def describe(config: Config, name: str, wid: str | None = None) -> WorkerInfo:
    if _builtin.LOAD_ERRORS:
        _builtin._load_tool_modules(tuple(_builtin.LOAD_ERRORS))
    ok, bad = [], {}
    for t in tuple(REGISTRY.values()):
        try:
            reason = t.unavailable_reason(config)
        except Exception as exc:
            reason = f'availability check failed: {type(exc).__name__}: {exc}'
        (bad.__setitem__(t.name, reason) if reason else ok.append(t.name))
    bad.update({f"module {n}": why for n, why in _builtin.LOAD_ERRORS.items()})
    features = ['independent_heartbeat', 'durable_result_delivery'] + (["idle_telemetry", "desktop_stream", "two_percent_audio"] if HOST_OS == "windows" else [])
    info = WorkerInfo(name=name, os=HOST_OS, tools=ok, unavailable=bad, idle_seconds=user_idle_seconds(), features=features)
    if wid:
        info.id = wid
    return info


def _run_job(job: dict, config: Config, wid: str, server: str, h: dict, client: httpx.Client,
             active: set, active_agent: set, quiet_sessions: set, outbox: ResultOutbox):
    ctx = Ctx(config, job_id=job["id"], worker=wid)
    ctx.parent_request_id = job.get("parent_request_id")
    ctx.agent_use = bool(job.get("agent_use"))
    ctx.server, ctx.headers = server, h
    res = {"job_id": job["id"], "ok": True}
    if job.get("agent_use") and HOST_OS == "windows":
        from .audio_volume import keep_pc_at_two_percent
        if not deps.install_for("pycaw"):
            res.update(ok=False, error="Cannot keep this PC at 2% volume: pycaw is unavailable")
        else:
            try:
                keep_pc_at_two_percent()
            except Exception as exc:
                res.update(ok=False, error=f"Cannot keep this PC at 2% volume: {exc}")
    if not res["ok"]:
        res["artifacts"], res["log"] = [], ctx.log
        _deliver_finished(outbox, client, wid, res, active, active_agent)
        return
    for attempt in (0, 1):
        try:
            res["output"] = execute(job["tool"], job["input"], ctx)
            res["ok"] = True
            res.pop("error", None)
            break
        except Exception as e:
            res.update(ok=False, error=f"{type(e).__name__}: {e}")
            # a package this node doesn't have yet (Pillow, OpenCV...): install it into this environment and run the job again
            mod = deps.missing_module(e)
            if attempt or not mod:
                break
            ctx.progress(1, f"Installing the Python package for '{mod}' on this machine (one time)")
            if not deps.install_for(mod):
                res["error"] += f" (gBox tried to install the package for '{mod}' here and couldn't)"
                break
            ctx.artifacts.clear()                          # the retry starts clean (its log keeps the install line)
            ctx._pct = 0.0
    # ponytail: artifacts inline as base64; switch to streamed upload when artifacts exceed ~100MB
    res["artifacts"] = [{"name": n, "media_type": mt, "provenance": p, "b64": base64.b64encode(d).decode()}
                        for n, d, mt, p in ctx.artifacts]
    res["log"] = ctx.log
    if job.get("agent_use") and res["ok"] and job["tool"] == "launch_game" and (res.get("output") or {}).get("session_id"):
        quiet_sessions.add(res["output"]["session_id"])
    _deliver_finished(outbox, client, wid, res, active, active_agent)


def _release_settled(outbox, active, active_agent, job_ids):
    """Free the parallel-job slot of every finished job the control plane answered for.

    A result the Spark refused (4xx, e.g. an older server that already recorded
    the job and answers a redelivery with 409) is kept in the outbox and never
    resent, but its tool is no longer running. Holding its slot would saturate the
    worker after MAX_PARALLEL refusals, so it stops claiming and every new launch
    on that PC stays queued forever (#1295).
    """
    for jid in tuple(job_ids):
        try:
            settled = outbox.settled(jid)
        except (OSError, ValueError, RuntimeError):
            continue                                  # unreadable record: stay busy, never rerun
        if settled:
            if jid in active:
                print(f"result for job {jid} was answered by the control plane; its job slot is free", flush=True)
            active.discard(jid)
            active_agent.discard(jid)


def _deliver_finished(outbox, client, wid, result, active, active_agent):
    try:
        outbox.save(wid, result)  # artifact bytes are fsynced before the first request
        outbox.deliver(client, result['job_id'])
    except (OSError, ValueError, RuntimeError) as exc:
        # Keep the job busy on persistence failures. Never rerun its tool.
        print(f"result delivery held for {result['job_id']}: {type(exc).__name__}", flush=True)
        return
    _release_settled(outbox, active, active_agent, [result['job_id']])


def _deliver_ready(outbox, client, active, active_agent):
    """One delivery pass: resend due results, then free slots of settled ones."""
    try:
        outbox.send_ready(client)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"durable result delivery held: {type(exc).__name__}", flush=True)
    _release_settled(outbox, active, active_agent, active)


def _result_delivery_loop(stop, outbox, active, active_agent, server, headers):
    with httpx.Client(base_url=server, headers=headers, timeout=20) as client:
        while not stop.wait(2):
            _deliver_ready(outbox, client, active, active_agent)


def _quiet_volume_loop(stop: threading.Event, active_agent: set, quiet_sessions: set):
    if HOST_OS != "windows":
        return
    from .audio_volume import keep_pc_at_two_percent
    from .tools import SESSIONS

    while not stop.is_set():
        time.sleep(2)
        if stop.is_set():
            break
        quiet_sessions.intersection_update(SESSIONS)
        if active_agent or quiet_sessions:
            try:
                keep_pc_at_two_percent()
            except Exception as exc:
                print(f"agent 2% volume enforcement: {exc}", flush=True)


def _heartbeat_loop(stop, current_info, active, server, headers):
    """Keep saturated workers visible without claiming another job."""
    with httpx.Client(base_url=server, headers=headers, timeout=10) as client:
        while not stop.wait(HEARTBEAT_S):
            try:
                info = current_info().model_copy(update={'idle_seconds': user_idle_seconds(),
                                                        'active_jobs': len(active)})
                client.post('/api/workers/register', json=info.model_dump()).raise_for_status()
            except (httpx.HTTPError, OSError):
                # Re-registration is safe to retry. A job itself is never rerun.
                continue


def _desktop_stream(stop: threading.Event, wid: str, server: str, h: dict, config: Config):
    """Send the Windows desktop only while a gBox remote-PC picture-in-picture viewer is open."""
    if HOST_OS != "windows":
        return
    from .adapters import MjpegStream
    from .remote_desktop import gbox_window_rect

    stream = None
    seen = 0
    rect, rect_at = None, 0.0
    with httpx.Client(base_url=server, headers=h, timeout=15) as client:
        while not stop.is_set():
            try:
                watch = client.get(f"/api/workers/{wid}/desktop/watch").json().get("watch", False)
                if watch and stream is None:
                    stream = MjpegStream(None, fps=8, max_width=3200, draw_mouse=True)
                    seen = 0
                if not watch and stream is not None:
                    stream.close()
                    stream = None
                if stream is not None:
                    if stream.proc is not None and stream.proc.poll() is not None:   # None: its supervisor is restarting it
                        stream.close()
                        stream = None
                    elif stream.wait(seen, 1) and stream.latest:
                        seen = stream.seq
                        if time.monotonic() - rect_at >= 1:
                            rect, rect_at = gbox_window_rect(), time.monotonic()
                        frame_headers = {"content-type": "image/jpeg"}
                        if rect:
                            frame_headers["x-gbox-app-rect"] = ",".join(f"{v:.6f}" for v in rect)
                        client.post(f"/api/workers/{wid}/desktop/frame", content=stream.latest,
                                    headers=frame_headers, timeout=10).raise_for_status()
                else:
                    time.sleep(2)
            except (httpx.HTTPError, OSError, ValueError, AttributeError):
                if stream is not None:
                    stream.close()
                    stream = None
                time.sleep(3)
    if stream is not None:
        stream.close()


def run(server: str, token: str, config: Config, name: str | None = None,
        stop: threading.Event | None = None, poll_s: float = 1.0, *, reconcile_results: bool = False):
    stop = stop or threading.Event()
    h = {"authorization": f"Bearer {token}"}
    name = name or platform.node()
    outbox = ResultOutbox(config.runtime, server, name)
    # Drain the previous worker's exact finished results BEFORE registering a new
    # identity; registration would otherwise retire its unfinished jobs.
    with httpx.Client(base_url=server, headers=h, timeout=20) as delivery_client:
        if reconcile_results:
            outbox.reconcile_ready(delivery_client)
        else:
            outbox.send_ready(delivery_client, force=True)
    held = outbox.held()
    if held:
        def why(e):
            return f" ({' '.join(str(v) for v in (e.get('kind'), e.get('status')) if v)})" if e else ''
        detail = '; '.join(f"job {r['job_id']} {r['status']} after {r['attempts']} attempt(s){why(r['last_error'])}"
                           for r in held)
        raise RuntimeError('Worker activation held: finished results still await verified delivery: '
                           f'{detail}. Check that {server} is reachable and runs the same gBox version, '
                           'then reconnect this worker.')
    if outbox.protected_sessions(_builtin._running_file(config)):
        raise RuntimeError('Worker activation held: a delivered native launch still has an owned PID record; no emulator was stopped')
    info = describe(config, name)
    def _push():                                    # mods built on this machine join the central collection on the Spark
        try:
            from . import filemods
            sent = filemods.push_missing(config, server, h)
            if sent:
                print(f"uploaded {len(sent)} mod(s) to the central collection: {sent}", flush=True)
        except Exception as e:
            print(f"mod upload skipped: {e}", flush=True)
    threading.Thread(target=_push, daemon=True).start()
    from . import audio_cpp                         # local speech service when audiocpp_server is on this machine (#816)
    threading.Thread(target=audio_cpp.autostart, args=(config,), name="audio_cpp-autostart", daemon=True).start()
    # Live owned PIDs were checked above. Startup never kills a surviving game,
    # including a launch whose completion delivery was lost by an older worker.
    active: set[str] = set()
    active_agent: set[str] = set()
    quiet_sessions: set[str] = set()
    def current_info():
        return info.model_copy(update={'pending_results': outbox.pending_count()})
    threading.Thread(target=_quiet_volume_loop, args=(stop, active_agent, quiet_sessions), daemon=True).start()
    with httpx.Client(base_url=server, headers=h | {"x-gbox-actor": f"worker:{name}"}, timeout=30) as c:
        while not stop.is_set():                    # the control plane may be restarting: keep trying
            try:
                c.post("/api/workers/register", json=info.model_dump(), timeout=60).raise_for_status()
                break
            except httpx.HTTPError:
                stop.wait(poll_s * 3)
        threading.Thread(target=_desktop_stream, args=(stop, info.id, server, h, config), daemon=True).start()
        threading.Thread(target=_heartbeat_loop, args=(stop, current_info, active, server, h), daemon=True).start()
        threading.Thread(target=_result_delivery_loop, args=(stop, outbox, active, active_agent, server, h), daemon=True).start()
        described = time.time()
        while not stop.is_set():
            if time.time() - described > REDESCRIBE_S:
                try:
                    info = describe(config, name, info.id)
                    c.post("/api/workers/register", json=current_info().model_copy(update={'active_jobs': len(active)}).model_dump(), timeout=60).raise_for_status()
                    described = time.time()
                except (httpx.HTTPError, OSError) as exc:
                    print(f"worker registration retry: {exc}", flush=True)
                    stop.wait(poll_s * 5)
                    continue
            if len(active) >= MAX_PARALLEL:
                stop.wait(poll_s)
                continue
            try:
                r = c.post(f"/api/workers/{info.id}/claim", json={"idle_seconds": user_idle_seconds(),
                                                                     "active_jobs": len(active)})
            except httpx.TransportError:
                stop.wait(poll_s * 5)
                continue
            if r.status_code == 404:                               # server restarted with fresh state
                try:
                    c.post("/api/workers/register", json=current_info().model_copy(update={'active_jobs': len(active)}).model_dump(), timeout=60).raise_for_status()
                except httpx.HTTPError:
                    stop.wait(poll_s * 5)
                continue
            if r.status_code == 204:
                stop.wait(poll_s)
                continue
            try:
                r.raise_for_status()
            except httpx.HTTPError:
                stop.wait(poll_s * 5)
                continue
            job = r.json()
            active.add(job["id"])
            if job.get("agent_use"):
                active_agent.add(job["id"])
            threading.Thread(target=_run_job, args=(job, config, info.id, server, h, c, active, active_agent, quiet_sessions, outbox), daemon=True).start()
