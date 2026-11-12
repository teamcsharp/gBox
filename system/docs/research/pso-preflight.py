"""Pre-flight: check everything a PSO launch needs, before the launch, so a failure has a name.

The freezes of the last several attempts were diagnosed after the fact. This checks the prerequisites up front and prints each one, so the next launch is
either cleared or has a specific missing piece named:

  * **the ISO cache** - the launch passes `-e <cache>...gcz`; if the cached image is missing the emulator has nothing to start;
  * **the memory card** - the launch passes `-C Dolphin.Core.MemcardAPath=...A.USA.raw`; a missing card is a silent save failure;
  * **the save states** - after round 19 these should be absent (the stale ones were moved aside), and a stale one is what froze the transfer;
  * **the worker** - the job is dispatched to a worker, so one must be online;
  * **the config the launch depends on** - `BackgroundInput = True` and a `GCPad1` line;
  * **the API** - health.

Read-only: nothing is created, moved or started.
"""
import json
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

GAME_ID = "436e0bb84d5337d1"
CACHE_DIR = pathlib.Path(r"D:\gBox\cache") / GAME_ID
STATE_DIR = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\pso-buddies\i9-NUC") / GAME_ID / "User\StateSaves"
CONFIG = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\Dolphin.ini")
PAD = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini")

problems = []


def report(label, ok, detail=""):
    print(("  OK   " if ok else "  MISS ") + label + (" - " + detail if detail else ""))
    if not ok:
        problems.append(label)


print("API")
try:
    health = S._call("/api/health")
    report("health", bool(health.get("ok")), str(health)[:60])
except Exception as exc:                                          # noqa: BLE001
    report("health", False, str(exc)[:80])

print("workers")
try:
    rows = S._call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    online = [row for row in rows if row.get("online")]
    report("a worker is online", bool(online), f"{len(online)} of {len(rows)}")
except Exception as exc:                                          # noqa: BLE001
    report("workers", False, str(exc)[:80])

print("game image")
images = sorted(CACHE_DIR.glob("*.gcz")) + sorted(CACHE_DIR.glob("*.iso")) if CACHE_DIR.exists() else []
report("cached image", bool(images), images[0].name if images else f"nothing in {CACHE_DIR}")

print("memory card")
cards = list(pathlib.Path(r"C:\_tools\gBox\system\gbox-data\memory-cards\sessions").glob(f"*/dolphin/A.USA.raw")) \
    if pathlib.Path(r"C:\_tools\gBox\system\gbox-data\memory-cards\sessions").exists() else []
report("a memory card exists for some session", bool(cards), f"{len(cards)} cards")

print("save states (should be clear)")
states = list(STATE_DIR.glob("*")) if STATE_DIR.exists() else []
live_states = [path for path in states if ".stale-" not in path.name]
report("no live save state to restore", not live_states,
       "none" if not live_states else ", ".join(path.name for path in live_states))

print("dolphin config")
if CONFIG.exists():
    text = CONFIG.read_text(encoding="utf-8", errors="replace")
    report("BackgroundInput = True", "BackgroundInput = True" in text)
else:
    report("Dolphin.ini", False, str(CONFIG))
if PAD.exists():
    pad_text = PAD.read_text(encoding="utf-8", errors="replace")
    device = next((line.strip() for line in pad_text.splitlines() if line.startswith("Device =")), "")
    report("GCPad1 has a device line", bool(device), device)
else:
    report("GCPadNew.ini", False, str(PAD))

print()
if problems:
    print(f"{len(problems)} problem(s): {problems}")
    raise SystemExit(1)
print("pre-flight clear - a launch has everything it needs")
