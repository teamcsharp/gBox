"""A controller relay that actually reaches the game, and makes the bot yield to it.

The measurement that started this: the Xbox 360 pad IS readable through SDL (pygame sees one joystick, 6 axes, 11 buttons) while XInput shows slots 1-3 empty, and Dolphin's GCPad is bound to
`XInput/0/Gamepad` - **gBox's virtual pad**. So the operator's presses have to be *injected* into that virtual pad, not delivered natively.

This daemon does exactly that, and it is the whole chain:

* read the pad at 30 Hz through SDL;
* on every **change** (not every frame - a held stick is not a new event), send it to the session with `session_op send_input`,
  which is the route measured to move the character (211 units through a gate, 38.3 after a pause, 44.7 just now);
* while the operator is touching the pad, write a **pause file** so the bot stands down and does not fight them for it;
* after `IDLE_RELEASE` seconds of no input, remove the pause file and the bot resumes.

The pause file is the contract between this daemon and `endless.py`: its presence means "the operator is playing".
"""
import os
import pathlib
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

import pygame                                                      # noqa: E402

from pso_pad import Pad, call                                       # noqa: E402

PAUSE_FILE = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
IDLE_RELEASE = 4.0
DEADZONE = 0.24
DEBOUNCE_FRAMES = 3          # frames a button must persist before it is believed (a failing pad chatters faster)

# SDL index -> the key names the session input understands. The A/B swap matches padstate._XI, where physical A is "b".
BUTTONS = {0: "b", 1: "a", 2: "y", 3: "x", 4: "l", 5: "r", 6: "select", 7: "start", 8: "l3", 9: "r3"}
DIRECTIONS = ("up", "down", "left", "right")


PROCESS_SUSPEND_RESUME = 0x0800


def _bot_pids():
    """PIDs of every running `endless.py` - the only processes the relay may suspend.

    `wmic` is absent on current Windows, which is why the first version of this silently found nothing and never
    suspended anything. PowerShell's CIM query is the supported equivalent and is present on every supported build.
    """
    import subprocess

    pids = []
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match 'endless' } | "
              "ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:                                          # noqa: BLE001
        return pids
    for line in (out or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def send(pad, events):
    if not events:
        return
    try:
        call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                           "input": {"session_id": pad.sid, "op": "send_input",
                                     "args": {"events": events}}}, "POST")
    except Exception as error:                                      # noqa: BLE001
        print("send failed:", type(error).__name__, flush=True)


def main():
    pad = Pad()
    print("relay session:", pad.sid, flush=True)

    # The session changes whenever the bot relaunches, and a relay bound to a dead sid silently drops every press.
    # Re-resolve it periodically and rebind so the operator's controller always reaches the LIVE game.
    def rebind(current):
        try:
            fresh = Pad()
        except RuntimeError:
            return current
        if fresh.sid != current.sid:
            print(f"relay rebinding {current.sid[:12]} -> {fresh.sid[:12]}", flush=True)
            return fresh
        return current
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        raise SystemExit("no joystick visible to SDL")
    wanted = os.environ.get("RELAY_PAD")
    pads = []
    for index in range(pygame.joystick.get_count()):
        if wanted is not None and wanted.strip().isdigit() and index != int(wanted):
            continue                                          # RELAY_PAD pins one controller
        try:
            device = pygame.joystick.Joystick(index)
            device.init()
            pads.append(device)
        except Exception:                                      # noqa: BLE001 - a dead pad must not stop the relay
            continue
    if not pads:
        raise SystemExit("no joystick visible to SDL")
    # Read EVERY pad. The operator has two connected, and watching only the first means watching a silent one.
    print("relay watching: " + ", ".join(f"[{i}] {p.get_name()}" for i, p in enumerate(pads)), flush=True)

    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0
    stable_buttons = {}
    while True:
        pygame.event.pump()
        now = set()
        lx = ly = 0.0
        raw_buttons = set()
        for device in pads:
            try:
                for index, name in BUTTONS.items():
                    if index < device.get_numbuttons() and device.get_button(index):
                        raw_buttons.add(name)
                if device.get_numaxes() > 0:
                    value = device.get_axis(0)
                    if abs(value) > abs(lx):
                        lx = value
                if device.get_numaxes() > 1:
                    value = device.get_axis(1)
                    if abs(value) > abs(ly):
                        ly = value
            except Exception:                                  # noqa: BLE001 - a pad dropping out is not fatal
                continue
        # Debounce: a button has to persist for a few frames before it is believed, which suppresses the chatter a
        # failing button produces (measured: A/B toggling every 0.1s on a 360 pad) while leaving held presses intact.
        for name in list(stable_buttons):
            if name not in raw_buttons:
                stable_buttons.pop(name, None)
        for name in raw_buttons:
            stable_buttons[name] = stable_buttons.get(name, 0) + 1
        now = {name for name, count in stable_buttons.items() if count >= DEBOUNCE_FRAMES or name in held}
        lx = 0.0 if abs(lx) < DEADZONE else lx
        ly = 0.0 if abs(ly) < DEADZONE else ly
        stick = (lx, ly)

        events = []
        if now != held:
            events += [{"key": name, "down": True} for name in now - held]
            events += [{"key": name, "down": False} for name in held - now]
            held = now
        if stick != last_stick:
            events += [{"key": name, "down": False} for name in DIRECTIONS]
            if abs(ly) > 0:
                events.append({"key": "up" if ly < 0 else "down", "down": True})
            if abs(lx) > 0:
                events.append({"key": "left" if lx < 0 else "right", "down": True})
            last_stick = stick

        if time.time() - last_rebind > 1.0:
            last_rebind = time.time()
            pad = rebind(pad)

        if events:
            # No process freezing: Pad.send() yields per press while the flag is fresh, which is finer-grained and
            # does not impair injection. Measured: suspended 2.8 units of movement vs 30-73 unsuspended.
            last_activity = time.time()
            try:
                PAUSE_FILE.write_text("operator playing", encoding="utf-8")
            except OSError:
                pass
            send(pad, events)
            print(f"  relayed {len(events)} event(s): {[e['key'] for e in events]}", flush=True)
        elif time.time() - last_activity > IDLE_RELEASE:
            if PAUSE_FILE.exists():
                try:
                    PAUSE_FILE.unlink()
                except OSError:
                    pass
                print("  operator idle - bot may resume", flush=True)

        time.sleep(1 / 30)


if __name__ == "__main__":
    main()
