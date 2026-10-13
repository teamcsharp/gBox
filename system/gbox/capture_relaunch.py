"""Examine 3D capture sessions (#971 stages 2-4).

The operator's session often can't be captured where it runs. RenderDoc can't be put inside an OpenGL
(`gl`) RetroArch session: injection stops the core from opening its game window (PSO Ver.2 on Flycast).
Standalone Vulkan emulators (Yuzu, RPCS3) are never launched with RenderDoc inside them either. The
capability matrix (gbox/scene_support.py) rates these sessions `relaunch_under_capture` and names a
capturable driver. This module does that relaunch without touching the operator's game:

1. Keep the moment where possible. For RetroArch, save a state from the operator's session into the
   agent-owned slot CAPTURE_SLOT, then put the operator's slot counter back. Standalone emulators that
   don't expose save states (Yuzu today) boot the capture session fresh and label the result accordingly.
2. Start a separate, agent-owned emulator under RenderDoc:
   - RetroArch (`frame_rip.launch`) with its own config dir under runtime/capture_sessions.
     Its video_driver is the one the matrix names:
     - `vulkan`: RenderDoc's Vulkan layer is added for this process only (VK_LAYER_PATH / VK_INSTANCE_LAYERS).
     - `glcore`: core-profile GL, which RenderDoc supports. The compatibility `gl` context is the one it refuses.
   - Yuzu (`frame_rip.launch_yuzu`) with its own `--user-path` and the Vulkan renderer forced.
3. Load the saved moment (RetroArch only), capture `frames` frames, rebuild the scene (scene_capture.extract),
   then stop the capture session.

The operator's game keeps running the whole time. The result's `capture_session` names the driver and
whether the moment was restored (`moment`: "save_state" or "fresh_boot").
"""
from __future__ import annotations

import shutil
import socket
import time
from pathlib import Path

from .scene_support import core_name, session_support

RELAUNCH = "relaunch_under_capture"
CAPTURE_SLOT = 70                        # agent-owned state slot (same convention as char_coverage.preserve_moment)
CAPTURE_DRIVERS = ("vulkan", "glcore")   # drivers a separate capture session can run under
BOOT_TIMEOUT = 90.0                      # seconds for the capture session's RetroArch to answer GET_STATUS
YUZU_BOOT_TIMEOUT = 120.0                # seconds for Yuzu to open a game window
LOAD_SETTLE = 1.5                        # seconds between LOAD_STATE and the capture
# Flat state folder and slot 0 in the capture session, so the staged <content>.state is the one LOAD_STATE reads.
STATE_CFG = {"sort_savestates_enable": "false", "sort_savestates_by_content_enable": "false",
             "savestates_in_content_dir": "false", "state_slot": "0", "savestate_auto_load": "false"}


def _retroarch_plan(ad, row) -> dict | None:
    content, core = getattr(ad, "content_path", None), getattr(ad, "core_path", None)
    if not content or not core:
        return None
    exe = getattr(ad, "retroarch_exe", None)
    if exe and not Path(str(exe).replace("\\", "/")).name.lower().startswith("retroarch"):
        exe = None                                       # a wrapper (renderdoccmd, cmd): use the provisioned build
    return {"type": "retroarch", "driver": row["driver"], "content": str(content), "core_path": str(core),
            "core": core_name(core), "retroarch": str(exe) if exe else None, "reason": row["reason"],
            "extra_cfg": {"video_driver": row["driver"], **STATE_CFG}}


def _yuzu_plan(ad, row) -> dict | None:
    content = getattr(ad, "content_path", None)
    exe = getattr(ad, "yuzu_exe", None)
    if not content or not exe:
        return None
    return {"type": "yuzu", "driver": row["driver"], "content": str(content), "yuzu_exe": str(exe),
            "reason": row["reason"]}


def plan(ad, host_os: str | None = "windows") -> dict | None:
    """The capture-session plan for a live adapter, or None when the matrix doesn't call for one (or the session
    lacks what a relaunch needs: content path and, for RetroArch, a core; for Yuzu, the executable)."""
    row = session_support(ad, host_os)
    if row["status"] != RELAUNCH or row.get("driver") not in CAPTURE_DRIVERS:
        return None
    name = (getattr(ad, "name", "") or "").lower()
    if name == "retroarch":
        return _retroarch_plan(ad, row)
    if name == "yuzu":
        return _yuzu_plan(ad, row)
    return None


def keep_moment(ad, work: Path, content: str) -> dict:
    """Save the operator's moment into CAPTURE_SLOT and stage it as the capture session's slot-0 state.
    Puts the operator's slot counter back. Never raises; a fresh boot is the fallback."""
    if not callable(getattr(ad, "save_state", None)):
        return {"moment": "fresh_boot", "note": "this emulator has no save state"}
    prev = getattr(ad, "slot", None)
    try:
        saved = ad.save_state(CAPTURE_SLOT)
    except Exception as e:  # noqa: BLE001 - the operator's game must not be disturbed by a failed save
        return {"moment": "fresh_boot", "note": f"save state failed: {e}"}
    finally:
        if prev is not None and callable(getattr(ad, "_slot", None)):
            try:
                ad._slot(prev)
            except Exception:  # noqa: BLE001
                pass
    try:
        src = Path(saved["path"])
        dst = Path(work) / "states" / (Path(content).stem + ".state")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    except Exception as e:  # noqa: BLE001
        return {"moment": "fresh_boot", "note": f"could not stage the saved state: {e}"}
    return {"moment": "save_state", "state": str(dst), "operator_slot": CAPTURE_SLOT, "bytes": dst.stat().st_size}


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(proc, ra_command, port: int, timeout: float = BOOT_TIMEOUT, sleep=time.sleep,
               clock=time.monotonic) -> str:
    """Wait until the capture session's RetroArch answers GET_STATUS with a running content."""
    deadline = clock() + timeout
    while clock() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the capture session exited during start-up (code {proc.poll()})")
        try:
            st = ra_command("GET_STATUS", port, reply=True)
        except OSError:
            st = None
        if st and ("PLAYING" in st or "PAUSED" in st):
            return st
        sleep(1.0)
    raise RuntimeError(f"the capture session did not start within {timeout:.0f} s")


def _wait_yuzu_window(proc, timeout: float = YUZU_BOOT_TIMEOUT, sleep=time.sleep, clock=time.monotonic) -> None:
    """Wait until the Yuzu capture session opens a game window."""
    from .adapters import _pid_window
    deadline = clock() + timeout
    while clock() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the Yuzu capture session exited during start-up (code {proc.poll()})")
        if _pid_window(proc.pid):
            return
        sleep(1.0)
    raise RuntimeError(f"Yuzu did not open a game window within {timeout:.0f} s")


def _stop(proc, exe_name: str = "retroarch.exe") -> None:
    """Stop the capture session and any helper process it spawned."""
    try:
        from .scene_capture import _kill_children
        _kill_children(proc.pid, exe_name)
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.kill()
        proc.wait(10)
    except Exception:  # noqa: BLE001
        pass


def _run_retroarch(ad, p, out_dir, frames, fovy, aspect, progress, runtime, launch, capture, extract_fn,
                   ra_command, stop, sleep, clock):
    say = progress or (lambda p_, m: None)
    work = Path(runtime) / "capture_sessions" / f"{int(time.time() * 1000)}"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    say(5, "Saving this moment for a separate capture session (your game keeps running)")
    moment = keep_moment(ad, work, p["content"])
    cmd_port, pad_port = _free_udp_port(), _free_udp_port()
    say(15, f"Starting a RetroArch capture session under {p['driver']} (RenderDoc)")
    proc = launch(p["content"], work, core=p["core"], retroarch=p["retroarch"], cmd_port=cmd_port,
                  pad_port=pad_port, extra_cfg=p["extra_cfg"], core_path=p["core_path"])
    try:
        wait_ready(proc, ra_command, cmd_port, BOOT_TIMEOUT, sleep, clock)
        if moment["moment"] == "save_state":
            say(25, "Loading your moment into the capture session")
            ra_command("LOAD_STATE", cmd_port)
            sleep(LOAD_SETTLE)
        say(30, "Capturing the frame in the capture session (RenderDoc)")
        rdcs = capture(pid=0, frames=frames, cap_dir=work / "cap", wait=60)
        t1 = time.time()
        say(40, f"Rebuilding the 3D scene from {len(rdcs)} captured frame(s)")
        summary = extract_fn(rdcs, out_dir, fovy, aspect)
    finally:
        (stop or _stop)(proc)
    summary["capture_session"] = {"driver": p["driver"], "moment": moment["moment"], "note": moment.get("note"),
                                  "work": str(work), "operator_paused": False}
    summary["timings"] = {"capture_s": round(t1 - t0, 2), "extract_s": round(time.time() - t1, 2)}
    summary["frame_png"] = False
    return summary


def _run_yuzu(ad, p, out_dir, frames, fovy, aspect, progress, runtime, launch_yuzu, capture, extract_fn,
              wait_window, stop, sleep, clock):
    say = progress or (lambda p_, m: None)
    work = Path(runtime) / "capture_sessions" / f"{int(time.time() * 1000)}"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    say(5, "Starting a Yuzu capture session under Vulkan (RenderDoc); your game keeps running")
    user_dir = work / "user"
    proc = launch_yuzu(p["content"], p["yuzu_exe"], user_dir, cap_dir=work / "cap")
    try:
        (wait_window or _wait_yuzu_window)(proc, YUZU_BOOT_TIMEOUT, sleep, clock)
        say(30, "Capturing the frame in the Yuzu capture session (RenderDoc)")
        rdcs = capture(pid=0, frames=frames, cap_dir=work / "cap", wait=60)
        t1 = time.time()
        say(40, f"Rebuilding the 3D scene from {len(rdcs)} captured frame(s)")
        summary = extract_fn(rdcs, out_dir, fovy, aspect)
    finally:
        (stop or _stop)(proc, "yuzu.exe")
    summary["capture_session"] = {"driver": p["driver"], "moment": "fresh_boot",
                                  "note": "Yuzu capture sessions boot fresh (save-state moment preservation not yet implemented)",
                                  "work": str(work), "operator_paused": False}
    summary["timings"] = {"capture_s": round(t1 - t0, 2), "extract_s": round(time.time() - t1, 2)}
    summary["frame_png"] = False
    return summary


def run(ad, out_dir: Path, frames: int = 2, fovy: float = 0, aspect: float = 0, progress=None, *,
        runtime: Path | None = None, launch=None, launch_yuzu=None, capture=None, extract_fn=None, ra_command=None,
        wait_window=None, stop=None, sleep=time.sleep, clock=time.monotonic) -> dict:
    """Capture the operator's session through a separate capture session (see the module docstring)."""
    from .registry import Unsupported
    p = plan(ad)
    if p is None:
        raise Unsupported(session_support(ad, "windows")["reason"])
    if runtime is None:
        from .scene_capture import _cfg
        runtime = _cfg().runtime
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if p["type"] == "retroarch":
        if launch is None or capture is None or ra_command is None:
            from . import frame_rip
            launch = launch or frame_rip.launch
            capture = capture or frame_rip.capture
            ra_command = ra_command or frame_rip.ra_command
        if extract_fn is None:
            from .scene_capture import extract as extract_fn
        return _run_retroarch(ad, p, out_dir, frames, fovy, aspect, progress, runtime, launch, capture,
                              extract_fn, ra_command, stop, sleep, clock)
    if p["type"] == "yuzu":
        if launch_yuzu is None:
            from . import frame_rip
            launch_yuzu = frame_rip.launch_yuzu
        if capture is None:
            from . import frame_rip
            capture = frame_rip.capture
        if extract_fn is None:
            from .scene_capture import extract as extract_fn
        return _run_yuzu(ad, p, out_dir, frames, fovy, aspect, progress, runtime, launch_yuzu, capture,
                         extract_fn, wait_window, stop, sleep, clock)
    raise Unsupported(f"unknown capture session type: {p['type']}")
