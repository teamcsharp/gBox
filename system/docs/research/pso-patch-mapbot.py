"""Patch map_bot.send to use game_input.send (raise the window, verify focus, send) instead of a bare win_send_keys."""
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\map_bot.py")
text = PATH.read_text(encoding="utf-8")

OLD = '''def send(events):
    if not pso_operator.guard():
        return {}
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = gbox_hwnd()
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.04)
    pso_operator.note_bot_input()
    try:
        return win_send_keys(PID, events)
    except Exception:                                            # noqa: BLE001
        return {}'''

NEW = '''def send(events):
    if not pso_operator.guard():
        return {}
    import game_input
    pso_operator.note_bot_input()
    game_input.PID = None                                        # resolve the live pid
    return events if game_input.send(events) else {}'''

assert text.count(OLD) == 1, text.count(OLD)
PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
print("map_bot.send -> game_input.send")
