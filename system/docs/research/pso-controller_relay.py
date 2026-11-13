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
import pathlib
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

import pygame                                                      # noqa: E402

from pso_pad import Pad, call                                       # noqa: E402

PAUSE_FILE = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
IDLE_RELEASE = 4.0
DEADZONE = 0.24

# SDL index -> the key names the session input understands. The A/B swap matches padstate._XI, where physical A is "b".
BUTTONS = {0: "b", 1: "a", 2: "y", 3: "x", 4: "l", 5: "r", 6: "select", 7: "start", 8: "l3", 9: "r3"}
DIRECTIONS = ("up", "down", "left", "right")


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
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"relay watching '{joy.get_name()}'", flush=True)

    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0
    while True:
        pygame.event.pump()
        now = {name for index, name in BUTTONS.items() if index < joy.get_numbuttons() and joy.get_button(index)}
        lx = joy.get_axis(0) if joy.get_numaxes() > 0 else 0.0
        ly = joy.get_axis(1) if joy.get_numaxes() > 1 else 0.0
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
