"""Live end-to-end probe of the operator's controller -> game path.

The complaint is that touching the controller does nothing. Rather than reason about it, this does the whole chain in the open for 30 seconds and prints every stage:

1. **read** the pad through SDL (pygame) - if this stays silent while the operator presses, the controller is not being read at all;
2. **show** each button and axis change as it happens;
3. **apply** the same event to the session's virtual pad through `session_op send_input`, which is the route measured to actually move the character;
4. **report** whether the character's own state changed at the end (position or heading), which is the only proof that reaches the game.

SDL button indices follow the Xbox layout: 0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 Back, 7 Start, 8 L3, 9 R3.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

import pygame                                                      # noqa: E402

from pso_pad import Pad, call                                      # noqa: E402

SECONDS = 30
NAMES = {0: "a", 1: "b", 2: "x", 3: "y", 4: "l", 5: "r", 6: "select", 7: "start", 8: "l3", 9: "r3"}


def pad_state():
    state = call("/api/sessions/%s/rpc" % Pad().sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    return state.get("player") or {}


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    before = pad_state()
    print("player before:", (before.get("x"), before.get("z")), "heading", before.get("heading_deg"))

    pygame.init()
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    print("SDL joysticks:", count)
    if count == 0:
        raise SystemExit("no joystick visible to SDL")
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"watching '{joy.get_name()}' - {joy.get_numaxes()} axes, {joy.get_numbuttons()} buttons")
    print(">>> PRESS AND HOLD SOMETHING ON THE CONTROLLER NOW <<<\n")

    held, last_stick = set(), (0.0, 0.0)
    deadline = time.time() + SECONDS
    events_sent = 0
    while time.time() < deadline:
        pygame.event.pump()
        now = {NAMES[i] for i in NAMES if i < joy.get_numbuttons() and joy.get_button(i)}
        stick = (joy.get_axis(0) if joy.get_numaxes() > 0 else 0.0,
                 joy.get_axis(1) if joy.get_numaxes() > 1 else 0.0)

        if now != held:
            pressed = now - held
            released = held - now
            print(f"  [{time.time() - (deadline - SECONDS):5.1f}s] buttons {sorted(now)} "
                  f"{'(+' + ','.join(sorted(pressed)) + ')' if pressed else ''}"
                  f"{'(-' + ','.join(sorted(released)) + ')' if released else ''}")
            held = now
        if abs(stick[0] - last_stick[0]) > 0.25 or abs(stick[1] - last_stick[1]) > 0.25:
            print(f"  [{time.time() - (deadline - SECONDS):5.1f}s] stick lx {stick[0]:+.2f} ly {stick[1]:+.2f}")
            last_stick = stick

        # push the change straight to the virtual pad, every frame a button or stick is moved
        if now or abs(stick[0]) > 0.3 or abs(stick[1]) > 0.3:
            events = [{"key": name, "down": True} for name in now]
            if abs(stick[1]) > 0.3:
                events.append({"key": "up" if stick[1] < 0 else "down", "down": True})
            if abs(stick[0]) > 0.3:
                events.append({"key": "left" if stick[0] < 0 else "right", "down": True})
            if events:
                events_sent += 1
                try:
                    call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                                       "input": {"session_id": pad.sid, "op": "send_input",
                                                 "args": {"events": events}}}, "POST")
                except Exception as error:                          # noqa: BLE001
                    print("  send failed:", type(error).__name__)
        else:
            # nothing held: make sure nothing stays pressed
            try:
                call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                                   "input": {"session_id": pad.sid, "op": "send_input",
                                             "args": {"events": [{"key": k, "down": False}
                                                                 for k in ("up", "down", "left", "right")]}}}, "POST")
            except Exception:                                       # noqa: BLE001
                pass
        time.sleep(1 / 30)

    after = pad_state()
    print("\nplayer after:", (after.get("x"), after.get("z")), "heading", after.get("heading_deg"))
    moved = abs(float(after.get("x") or 0) - float(before.get("x") or 0)) + \
        abs(float(after.get("z") or 0) - float(before.get("z") or 0))
    print("events pushed:", events_sent)
    print("VERDICT:", "controller reached the game" if moved > 2.0 else
          "no movement - presses were read but did not reach the game" if events_sent else
          "the controller produced no input at all")
