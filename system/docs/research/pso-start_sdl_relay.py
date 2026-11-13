"""Start the SDL watcher next to the XInput one, so a HID controller is mirrored too.

`watch_xinput` is started here and gives up when no XInput pad answers - which is exactly the case on this PC, where the operator's Xbox 360 pad enumerates as HID. Starting
`watch_sdl` on the same line means whichever API the controller actually uses, the operator's presses reach the session and the bot yields to them.
"""
import pathlib
import py_compile

TOOLS = pathlib.Path(r"C:\_tools\gBox\system\gbox\tools.py")
text = TOOLS.read_text(encoding="utf-8")
py_compile.compile(str(TOOLS), doraise=True)
print("tools.py compiles BEFORE")

old = "        threading.Thread(target=padstate.watch_xinput, args=(server, headers, sid, lambda: sid in SESSIONS), daemon=True).start()"
new = ("        threading.Thread(target=padstate.watch_xinput, args=(server, headers, sid, lambda: sid in SESSIONS), daemon=True).start()\n"
       "        # A controller that enumerates as HID/DirectInput never answers XInputGetState (measured: the operator's\n"
       "        # Xbox 360 pad is SDL-visible but absent from every XInput slot), so mirror it through SDL as well.\n"
       "        threading.Thread(target=padstate.watch_sdl, args=(server, headers, sid, lambda: sid in SESSIONS), daemon=True).start()")

count = text.count(old)
print("watch_xinput start anchor count:", count)
if count != 1:
    raise SystemExit("anchor not unique - refusing to guess")

text = text.replace(old, new, 1)
TOOLS.write_text(text, encoding="utf-8")
py_compile.compile(str(TOOLS), doraise=True)
print("tools.py compiles AFTER - watch_sdl is started with watch_xinput")
