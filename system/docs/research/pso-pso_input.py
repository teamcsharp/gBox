"""The ONLY way bot code is allowed to press a key.

Every input helper here checks the operator lock before sending anything, and declares the action window so the watcher can tell the
bot's motion from the operator's. A caller cannot accidentally bypass it: if the operator is active, `hold`/`tap` do nothing and say so.

This exists because ad-hoc helpers in individual scripts bypassed the lock and fought the operator - the exact complaint this round.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import pso_operator2 as OP                                         # noqa: E402


def allowed():
    """True while the operator is not on the pad.

    The focus test that used to be here applied to the keyboard path, whose presses only land while the game window owns the foreground. Input now goes
    through the plane's send_input, which uses the focus-independent virtual XInput pad when one exists, so focus no longer decides whether the bot can
    act - only whether the operator currently has the controls.
    """
    if OP.operator_active():
        return False
    return True


def hold(key, seconds, log=None, wait_for_operator=False, timeout=180.0):
    """Hold one key for `seconds`, only if the operator is inactive. Returns True when the key was pressed."""
    if not allowed():
        if wait_for_operator:
            started = time.time()
            while time.time() - started < timeout and not OP.wait_for_idle(5.0):
                pass
            if not allowed():
                return False
        if log is not None:
            log("  (operator has the controller: holding off)")
        return False
    OP.note_bot_input(seconds + 1.0)   # include the character's deceleration after the key is released
    G.send([{"key": key, "down": True}])
    time.sleep(seconds)
    G.send([{"key": key, "down": False}])
    time.sleep(0.05)
    return True


def hold2(keys, seconds, log=None):
    """Hold two keys at once (diagonals), under the same operator lock."""
    if not allowed():
        if log is not None:
            log("  (operator has the controller: holding off)")
        return False
    OP.note_bot_input(seconds + 1.0)   # include the character's deceleration after the key is released
    G.send([{"key": key, "down": True} for key in keys])
    time.sleep(seconds)
    G.send([{"key": key, "down": False} for key in keys])
    time.sleep(0.05)
    return True


def tap(key, gap=0.3, log=None, wait_for_operator=False):
    """Press and release one key under the same lock rules."""
    if not allowed():
        if wait_for_operator:
            OP.wait_for_idle(30.0)
            if not allowed():
                return False
        if log is not None:
            log("  (operator has the controller: holding off)")
        return False
    OP.note_bot_input(0.3)
    G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(gap)
    return True


def wait_until_ready(timeout=120.0):
    """Block until the operator has been idle for the full window. Returns True when the bot may act."""
    started = time.time()
    while time.time() - started < timeout:
        if allowed():
            return True
        OP.wait_for_idle(3.0)
    return allowed()


def self_test():
    """Prove the lock is enforced: with the operator active, nothing is sent."""
    import pathlib

    marker = pathlib.Path(r"D:\gBox\pso-ds\input-selftest.log")
    lines = []

    def fake_log(line):
        lines.append(line)

    before_active = OP.operator_active()
    if not before_active:
        # simulate an active operator by writing a fresh last_motion
        lock = pathlib.Path(r"D:\gBox\pso-ds\operator-lock.json")
        lock.write_text('{"last_motion": %f, "moved": 9.0, "operator_active": true}' % time.time(),
                        encoding="utf-8")
        simulated = True
    else:
        simulated = False
    sent = tap("a", log=fake_log)
    result = {"operator_active_before": before_active, "simulated": simulated,
              "sent_while_active": sent, "log": lines}
    if simulated:
        # clear the simulation so the real state can be read again
        lock = pathlib.Path(r"D:\gBox\pso-ds\operator-lock.json")
        lock.write_text('{"last_motion": 0.0}', encoding="utf-8")
    marker.write_text(str(result), encoding="utf-8")
    print(result)
    return 0 if sent is False else 2


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        raise SystemExit(self_test())
    print("allowed now:", allowed(), "| operator_active:", OP.operator_active())
