"""Examine 3D capture sessions (#971 stages 2-3).

The operator's RetroArch session often can't be captured where it runs. RenderDoc can't be put inside an OpenGL
(`gl`) session: injection stops the core from opening its game window (PSO Ver.2 on Flycast). The capability matrix
(gbox/scene_support.py) then rates the session `relaunch_under_capture` and names a capturable driver. This module
does that relaunch without touching the operator's game:

1. Keep the moment. Save a state from the operator's session into the agent-owned slot CAPTURE_SLOT, then put the
   operator's slot counter back. If the save fails, the capture session boots fresh, and the result says so.
2. Start a separate, agent-owned RetroArch under RenderDoc (`frame_rip.launch`) with the same core and content.
   It has its own config dir under runtime/capture_sessions and never reads or writes the operator's retroarch.cfg.
   Its video_driver is the one the matrix names:
   - `vulkan`: RenderDoc's Vulkan layer is added for this process only (VK_LAYER_PATH / VK_INSTANCE_LAYERS),
     with no injection.
   - `glcore`: core-profile GL, which RenderDoc supports. The compatibility `gl` context is the one it refuses.
3. Load the saved moment, capture `frames` frames, rebuild the scene (scene_capture.extract), then stop the
   capture session.

The operator's game keeps running the whole time. The result's `capture_session` names the driver and whether
the moment was restored (`moment`: "save_state" or "fresh_boot").
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
LOAD_SETTLE = 1.5                        # seconds between LOAD_STATE and the capture
# Flat state folder and slot 0 in the capture session, so the staged <content>.state is the one LOAD_STATE reads.
STATE_CFG = {"sort_savestates_enable": "false", "sort_savestates_by_content_enable": "false",
             "savestates_in_content_dir": "false", "state_slot": "0", "savestate_auto_load": "false"}


def plan(ad, host_os: str | None = "windows") -> dict | None:
    """The capture-session plan for a live adapter, or None when the matrix doesn't call for one (or the session
    lacks what a relaunch needs: a RetroArch adapter with a known core and content)."""
    row = session_support(ad, host_os)
    if row["status"] != RELAUNCH or row.get("driver") not in CAPTURE_DRIVERS:
        return None
    if (getattr(ad, "name", "") or "").lower() != "retroarch":
        return None
    content, core = getattr(ad, "content_path", None), getattr(ad, "core_path", None)
    if not content or not core:
        return None
    exe = getattr(ad, "retroarch_exe", None)
    if exe and not Path(str(exe).replace("\\", "/")).name.lower().startswith("retroarch"):
        exe = None                                       # a wrapper (renderdoccmd, cmd): use the provisioned build
    return {"driver": row["driver"], "content": str(content), "core_path": str(core), "core": core_name(core),
            "retroarch": str(exe) if exe else None, "reason": row["reason"],
            "extra_cfg": {"video_driver": row["driver"], **STATE_CFG}}


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


def _stop(proc) -> None:
    """Stop the capture session (renderdoccmd and the RetroArch it started)."""
    try:
        from .scene_capture import _kill_children
        _kill_children(proc.pid, "retroarch.exe")
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.kill()
        proc.wait(10)
    except Exception:  # noqa: BLE001
        pass


def run(ad, out_dir: Path, frames: int = 2, fovy: float = 0, aspect: float = 0, progress=None, *,
        runtime: Path | None = None, launch=None, capture=None, extract_fn=None, ra_command=None, stop=None,
        sleep=time.sleep, clock=time.monotonic) -> dict:
    """Capture the operator's session through a separate capture session (see the module docstring)."""
    from .registry import Unsupported
    say = progress or (lambda p, m: None)
    p = plan(ad)
    if p is None:
        raise Unsupported(session_support(ad, "windows")["reason"])
    if launch is None or capture is None or ra_command is None:
        from . import frame_rip
        launch, capture = launch or frame_rip.launch, capture or frame_rip.capture
        ra_command = ra_command or frame_rip.ra_command
    if extract_fn is None:
        from .scene_capture import extract as extract_fn
    if runtime is None:
        from .scene_capture import _cfg
        runtime = _cfg().runtime
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(runtime) / "capture_sessions" / f"{int(time.time() * 1000)}"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    say(5, "Saving this moment for a separate capture session (your game keeps running)")
    moment = keep_moment(ad, work, p["content"])
    cmd_port, pad_port = _free_udp_port(), _free_udp_port()
    say(15, f"Starting a capture session under {p['driver']} (RenderDoc)")
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
