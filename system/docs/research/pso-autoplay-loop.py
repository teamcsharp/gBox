"""autoplay-loop - hand the pad back and forth with the operator, with the two live guards applied throughout.

Operator's standing requests (2026-11-13):
  * "have the bot take over whenever I stop playing the game for three seconds" -- operator input (pad/keyboard/app pad)
    is watched; after 3 s of silence the operator-playing flag is withdrawn and the bounded autonomous player runs,
    exploring and fighting.
  * "I'm attempting to play the game a little bit to help you educate the bot" -- while the operator owns the pad a
    demonstration recorder runs, so their play is captured as a segmented skill trace; when they stop the recorder is
    closed cleanly (skills.json updated) before the bot takes over.
  * status ailments are cleared at TObjPlayer+0x254 and any nearby door's stage-flag gates are set (pso-operator-guard
    functions, loaded here so both guards run in this one supervisor).

It never fights the operator: the moment operator input is seen the flag is touched, the bounded player's own
OperatorGuard preempts it, and this loop waits for it to exit.

    python pso-autoplay-loop.py --once
    python pso-autoplay-loop.py
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
import uuid
from ctypes import wintypes

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
OPERATOR_FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
STOP_DEMO = OUT / "stop-demo"
RECORDER = pathlib.Path(r"C:\_tools\gBox\system\docs\research\pso-demo-recorder.py")
BOUNDED = pathlib.Path(r"C:\_tools\gBox\system\docs\research\pso-bounded.py")
GUARD = pathlib.Path(r"C:\_tools\gBox\system\docs\research\pso-operator-guard.py")
LIVE_MAP = pathlib.Path(r"C:\_tools\gBox\system\docs\research\pso-live-map.py")
PYTHON = sys.executable
OPERATOR_IDLE_S = 3.0
BOT_SECONDS = 60.0
# Weapon family -> attack reach in game units. The combo decision fires when the distance to the enemy is inside this
# range; too far and every swing whiffs, too close and the character circles (measured: Saber + attack_range 20 whiffed
# at 14-18 units). Names are the catalog's family_key suffixes; unknown kinds fall back to a short melee reach.
REACH_BY_FAMILY = {
    "saber": 13.0, "sword": 16.0, "partisan": 18.0, "dagger": 10.0, "twin_sword": 16.0, "double_saber": 16.0,
    "katana": 16.0, "claw": 10.0, "knuckle": 10.0, "slicer": 20.0, "handgun": 55.0, "rifle": 80.0,
    "mechgun": 35.0, "shot": 45.0, "launcher": 85.0, "card": 35.0, "wand": 12.0, "rod": 16.0, "cane": 12.0,
}
DEFAULT_REACH = 12.0
KEY_KEYS = (0x58, 0x5A, 0x53, 0x41, 0x45, 0x0D, 0x26, 0x28, 0x25, 0x27, 0x4B, 0x49, 0x4A, 0x4C,
            0x51, 0x57, 0x54, 0x47, 0x46, 0x48)


def load_guard():
    spec = importlib.util.spec_from_file_location("pso_operator_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "autoplay-loop.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


class XInputState(ctypes.Structure):
    _fields_ = [("packet", wintypes.DWORD), ("buttons", wintypes.WORD), ("lt", wintypes.BYTE),
                ("rt", wintypes.BYTE), ("lx", wintypes.SHORT), ("ly", wintypes.SHORT),
                ("rx", wintypes.SHORT), ("ry", wintypes.SHORT)]


class OperatorInput:
    """Operator activity from the physical pads, the keyboard, and the app's own session-pad view.

    Slot 0 is gBox's virtual pad - that is the BOT - so it is excluded. The operator's pads have been slots 1-3 on
    this node; the app pad channel covers a player who uses the gBox window instead.
    """

    def __init__(self, sid_provider) -> None:
        self.sid_provider = sid_provider
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.xinput = None
        for name in ("xinput1_4.dll", "xinput9_1_0.dll"):
            try:
                self.xinput = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        self.signature = None
        self.last_pad = None

    def poll(self) -> bool:
        active = False
        if self.xinput is not None:
            for slot in range(1, 4):
                state = XInputState()
                if self.xinput.XInputGetState(slot, ctypes.byref(state)) != 0:
                    continue
                signature = (state.packet, state.buttons, state.lt >> 4, state.rt >> 4,
                             state.lx // 512, state.ly // 512, state.rx // 512, state.ry // 512)
                if self.signature is not None and signature != self.signature:
                    active = True
                self.signature = signature
                break
        pressed = []
        for key in KEY_KEYS:
            if self.user32.GetAsyncKeyState(key) & 0x8000:
                pressed.append(key)
        if self.last_pad is not None and pressed != self.last_pad:
            active = True
        self.last_pad = pressed
        sid = self.sid_provider()
        if sid:
            try:
                request = urllib.request.Request(
                    BASE + f"/api/sessions/{sid}/pad",
                    headers={"authorization": "Bearer " + _token(), "x-gbox-actor": "agent"})
                view = json.loads(urllib.request.urlopen(request, timeout=5).read() or b"null")
                # The session-pad view also carries the BOT's own input (the worker reports what it sent), so only a
                # player/ui source is the operator. Agent-held keys must never hand the pad to the operator.
                sources = set((view.get("sources") or {}).values()) if isinstance(view, dict) else set()
                if sources & {"player", "ui"} and (view.get("held") or view.get("stick") or view.get("rstick")):
                    active = True
            except Exception:                                       # noqa: BLE001
                pass
        return active


def _token() -> str:
    return pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()


class Supervisor:
    def __init__(self) -> None:
        self.guard = load_guard()
        self.session = None
        self.sid = None
        self.catalog = None
        self.last_operator = 0.0
        self.recorder = None
        self.bot = None
        self.sid_provider = self.current_sid
        self.inputs = OperatorInput(self.sid_provider)

    def current_sid(self) -> str | None:
        try:
            return self.session.sid if self.session else None
        except Exception:                                           # noqa: BLE001
            return None

    def attach(self) -> bool:
        try:
            self.session = self.guard.Session()
            return True
        except Exception:                                           # noqa: BLE001
            self.session = None
            return False

    def give_pad_to_operator(self) -> None:
        if self.guard is None:
            return
        try:
            self.session = self.guard.Session()
            state = self.session.rpc("state") or {}
            player = state.get("player") or {}
            if player.get("ptr"):
                self.guard.clear_status(self.session, int(player["ptr"], 16))
                self.guard.unlock_nearby(self.session, state, player, 42.0)
        except Exception:                                           # noqa: BLE001
            pass

    def ensure_recorder(self) -> None:
        if self.recorder is not None and self.recorder.poll() is None:
            return
        if STOP_DEMO.exists():
            STOP_DEMO.unlink()
        env = dict(os.environ, GBOX_API=BASE)
        self.recorder = subprocess.Popen([PYTHON, str(RECORDER), "--seconds", "0", "--stop-file", str(STOP_DEMO)],
                                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("operator is playing - demonstration recorder started")

    def stop_recorder(self) -> None:
        if self.recorder is None:
            return
        STOP_DEMO.write_text("stop", encoding="utf-8")
        try:
            self.recorder.wait(timeout=25)
            log("demonstration recorder closed and its skill trace stored")
        except subprocess.TimeoutExpired:
            self.recorder.terminate()
            log("demonstration recorder did not close; terminated")
        self.recorder = None
        if STOP_DEMO.exists():
            STOP_DEMO.unlink()

    def live_map(self) -> tuple:
        """Dump the current floor's collision grid and return (path, key) for the bounded player's --map.

        This is the RAM side of the map bridge: pso-live-map.py re-parses the game's loaded collision allocation, so
        the router sees the exact floor the character is on (any area, any randomized layout) without a disc match.
        """
        try:
            result = subprocess.run([PYTHON, str(LIVE_MAP), "--json"], capture_output=True, text=True, timeout=45,
                                    env=dict(os.environ, GBOX_API=BASE))
            if result.returncode != 0:
                log(f"live map dump failed: {(result.stderr or result.stdout).strip()[-300:]}")
                return None, None
            summary = json.loads(result.stdout.strip().splitlines()[-1])
            log(f"live map: floor {summary['floor']} {summary['triangles']} triangles -> {summary['cells']} cells "
                f"({summary['key']})")
            return summary["map"], summary["key"]
        except Exception as error:                                   # noqa: BLE001
            log(f"live map dump error: {type(error).__name__}: {error}")
            return None, None

    def weapon_reach(self):
        """The equipped weapon's attack reach for the bot's combo decision, from the disc catalog's family name."""
        try:
            if self.session is None:
                return None
            if self.catalog is None:
                request = urllib.request.Request(
                    BASE + "/api/pso/items?version=gc",
                    headers={"authorization": "Bearer " + _token(), "x-gbox-actor": "agent"})
                rows = json.loads(urllib.request.urlopen(request, timeout=120).read() or b"[]")
                self.catalog = {row.get("code"): row for row in rows if isinstance(row, dict)}
            command = {"command_id": str(uuid.uuid4()), "expires": time.time() + 12, "input": {"op": "list"}}
            result = self.session.rpc("pso_controls", **command) or {}
            inventory = result.get("inventory") or []
            weapon = next((row for row in inventory
                           if row.get("equipped") and str(row.get("code", "")).startswith("00")), None)
            if not weapon:
                return None
            family = str((self.catalog.get(weapon.get("code")) or {}).get("family_key") or "")
            reach = next((value for key, value in REACH_BY_FAMILY.items() if key in family), DEFAULT_REACH)
            log(f"equipped weapon {weapon.get('name') or weapon.get('code')} ({family or 'unknown family'}) "
                f"-> attack range {reach:.0f}")
            return reach
        except Exception as error:                                   # noqa: BLE001
            log(f"weapon reach lookup failed: {type(error).__name__}: {error}")
            return None

    def run_bot(self) -> None:
        env = dict(os.environ, GBOX_API=BASE)
        log_path = OUT / "autoplay-bot.log"
        command = [PYTHON, str(BOUNDED), "play", "--seconds", str(BOT_SECONDS), "--motion", "hill"]
        map_path, map_key = self.live_map()
        if map_path:
            command += ["--map", map_path, "--map-name", map_key]
        reach = self.weapon_reach()
        if reach:
            command += ["--attack-range", f"{reach:.1f}"]
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== bot chunk {time.strftime('%H:%M:%S')} ===\n")
            self.bot = subprocess.Popen(command, env=env, stdout=handle, stderr=subprocess.STDOUT)
        log(f"operator idle {OPERATOR_IDLE_S:.0f}s - bot took the pad (bounded play {BOT_SECONDS:.0f}s"
            f"{', routed over the live collision grid' if map_path else ', no live map'})")
        started = time.monotonic()
        while True:
            if self.bot.poll() is not None:
                log(f"bot chunk finished rc={self.bot.returncode}")
                self.bot = None
                return
            if self.inputs.poll():
                self.last_operator = time.monotonic()
                OPERATOR_FLAG.write_text(json.dumps({"by": "autoplay-loop", "at": time.time()}), encoding="utf-8")
                log("operator input detected - bot stands down")
                deadline = time.monotonic() + 6.0
                while self.bot.poll() is None and time.monotonic() < deadline:
                    OPERATOR_FLAG.touch()
                    time.sleep(0.2)
                if self.bot.poll() is None:
                    self.bot.terminate()
                    log("bounded player did not yield in 6s; terminated")
                self.bot = None
                return
            self.give_pad_to_operator()
            time.sleep(0.25)

    def tick(self) -> None:
        if self.session is None and not self.attach():
            log("no live PSO session")
            return
        try:
            state = self.session.rpc("state") or {}
            player = state.get("player") or {}
            if player.get("ptr"):
                self.guard.clear_status(self.session, int(player["ptr"], 16))
                self.guard.unlock_nearby(self.session, state, player, 42.0)
        except Exception:                                           # noqa: BLE001
            self.session = None
            return
        activity = self.inputs.poll()
        now = time.monotonic()
        if activity:
            if now - self.last_operator > OPERATOR_IDLE_S:
                log("operator took the pad")
            self.last_operator = now
        operator_owns = now - self.last_operator < OPERATOR_IDLE_S
        if operator_owns:
            OPERATOR_FLAG.write_text(json.dumps({"by": "autoplay-loop", "at": time.time()}), encoding="utf-8")
            self.ensure_recorder()
            if self.bot is not None and self.bot.poll() is None:
                log("operator owns the pad - stopping the bot chunk")
                self.bot.terminate()
            self.bot = None
        else:
            if OPERATOR_FLAG.exists():
                OPERATOR_FLAG.unlink()
            self.stop_recorder()
            if self.bot is None:
                self.run_bot()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="operator/bot pad handover with live status + door guards")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--period", type=float, default=0.4)
    args = parser.parse_args(argv)
    supervisor = Supervisor()
    log(f"supervisor starting (operator idle threshold {OPERATOR_IDLE_S:.0f}s, bot chunks {BOT_SECONDS:.0f}s)")
    while True:
        try:
            supervisor.tick()
        except Exception as error:                                  # noqa: BLE001
            log(f"tick failed: {type(error).__name__}: {error}")
            supervisor.session = None
        if args.once:
            return 0
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())




