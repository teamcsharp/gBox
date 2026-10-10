"""Apply gBox's volume to its Windows playback sessions, including new games.

The Electron parent sends a percentage on stdin. Only its process family and
executables in gBox's own runtime folder are touched; other desktop audio keeps
its Windows mixer setting.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import threading

import psutil


def belongs_to_gbox(process, owner_pid: int, runtime: Path) -> bool:
    """Include the desktop process tree and gBox-managed emulator binaries."""
    try:
        if process.pid == owner_pid or any(parent.pid == owner_pid for parent in process.parents()):
            return True
        exe = Path(process.exe())
        return os.path.commonpath((os.path.normcase(str(exe)), os.path.normcase(str(runtime)))) == os.path.normcase(str(runtime))
    except (OSError, ValueError, psutil.Error):
        return False


def apply_volume(level: float, owner_pid: int, runtime: Path, sessions=None) -> int:
    """Set 0..1 on matching Windows audio sessions; return the number matched."""
    if sessions is None:
        from pycaw.pycaw import AudioUtilities
        sessions = AudioUtilities.GetAllSessions()
    matched = 0
    for session in sessions:
        try:
            process = session.Process
            if process is None or not belongs_to_gbox(process, owner_pid, runtime):
                continue
            volume = session.SimpleAudioVolume
            if abs(volume.GetMasterVolume() - level) > 0.005:
                volume.SetMasterVolume(level, None)
            matched += 1
        except Exception:
            continue  # a short-lived game can exit between enumeration and update
    return matched


def playback_sessions():
    """Enumerate sessions on every active playback device, including headsets."""
    from pycaw.pycaw import AudioSession, AudioUtilities, IAudioSessionControl2
    from pycaw.constants import DEVICE_STATE, EDataFlow

    sessions = []
    for device in AudioUtilities.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value):
        try:
            enumerator = device.AudioSessionManager.GetSessionEnumerator()
            for index in range(enumerator.GetCount()):
                control = enumerator.GetSession(index)
                if control:
                    sessions.append(AudioSession(control.QueryInterface(IAudioSessionControl2)))
        except Exception:
            continue  # an output device can be unplugged during enumeration
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--volume", type=int, default=30)
    args = parser.parse_args()
    from .config import load
    runtime = load(args.config).runtime
    level = max(0, min(100, args.volume)) / 100
    stop = threading.Event()
    changed = threading.Event()

    def commands() -> None:
        nonlocal level
        for line in sys.stdin:
            try:
                level = max(0, min(100, int(line.strip()))) / 100
                print(f"gBox volume {round(level * 100)}%", file=sys.stderr, flush=True)
                changed.set()
            except ValueError:
                continue
        stop.set()

    threading.Thread(target=commands, daemon=True).start()
    while not stop.is_set():
        sessions = []
        try:
            sessions = playback_sessions()
            apply_volume(level, args.owner_pid, runtime, sessions)
        except Exception as exc:
            print(f"gBox audio volume: {exc}", file=sys.stderr, flush=True)
        if changed.wait(1):
            changed.clear()
            apply_volume(level, args.owner_pid, runtime, sessions)


if __name__ == "__main__":
    main()
