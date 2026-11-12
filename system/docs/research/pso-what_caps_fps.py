"""What is actually capping the frame rate at 201 fps?

10x for PSO needs 302 fps and the cave reaches 201. Before blaming the CPU, measure whether it is saturated: `PercentProcessorTime` per process and the total, sampled while
fast-forward is running. If one core is pegged, the ceiling is single-thread throughput and nothing else can be done. If there is headroom, something is throttling the
emulator (audio sync and vsync are the usual suspects) and that is a real lever.

Also report Dolphin's own relevant settings, so the measurement can be interpreted: CPU core (JIT vs interpreter), audio backend, DSP thread, vsync.
"""
import json
import subprocess
import time

from pso_pad import Pad, call

COUNTER = 0x805D53A4
INI = r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\Dolphin.ini"
GFX = r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GFX.ini"


def counter(pad):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": COUNTER, "length": 4}}, "POST")
    try:
        return int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                              # noqa: BLE001
        return None


def settings() -> dict:
    out = {}
    for path, keys in ((INI, ("CPUCore", "AudioBackend", "DSPThread", "SyncGPU", "SkipIdle", "MMU", "FastDiscSpeed")),
                       (GFX, ("VSync", "EFBAccessEnable", "Backend", "InternalResolution"))):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for line in text.splitlines():
            name = line.split("=")[0].strip()
            if name in keys:
                out[name] = line.split("=", 1)[1].strip()
    return out


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    print("dolphin settings:", json.dumps(settings()))

    first = counter(pad)
    samples = []
    for _ in range(6):
        time.sleep(2)
        row = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
             "Where-Object { $_.Name -match 'Dolphin' } | "
             "Select-Object -ExpandProperty PercentProcessorTime"],
            capture_output=True, text=True, timeout=60).stdout.strip()
        total = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor | "
             "Where-Object { $_.Name -eq '_Total' }).PercentProcessorTime"],
            capture_output=True, text=True, timeout=60).stdout.strip()
        samples.append((row, total))
    second = counter(pad)

    fps = round((second - first) / 12.0, 1) if first is not None and second is not None else None
    print("frames/s:", fps, "| ratio:", round(fps / 30.2, 2) if fps else None, "| 10x needs 302")
    print("dolphin PercentProcessorTime samples:", [s[0] for s in samples])
    print("total CPU samples:", [s[1] for s in samples])
    print()
    print("one core pegged (~100 of 1600) means single-thread bound;",
          "low Dolphin use with low total means something else throttles")
