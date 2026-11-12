"""Make Ctrl+R do what F5 does: fetch the latest client and reload without cache.

The app already has the machinery - `GAME_KEYS.F5 = "client-refresh"` sends the page a hotkey that ends in `win.webContents.reloadIgnoringCache()`, and
before that it fast-forwards this checkout (app-update.cjs). The operator asked for Ctrl+R to be the key that "fixes and reloads the latest version",
so it is routed to that same path rather than reimplementing it:

    if (input.key is 'r' with Control, no Alt) -> win.webContents.send("hotkey", "client-refresh")

That gives Ctrl+R the whole sequence - update check, then an ignoring-cache reload - instead of a bare `location.reload()` that would serve stale files
from the cache and would not pick up a new `game-mods.js`.

It is placed with the other guarded keys in the existing `before-input-event` handler, so it respects the same exclusions: windows owned by the
Mercenaries viewer or the task dashboard keep their own keys.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js")
text = path.read_text(encoding="utf-8")

old = """  else if (input.key === "F2" && (input.shift || input.control) && !input.alt) { win.webContents.send("hotkey", input.shift ? "slot+" : "slot-");"""
new = """  // Ctrl+R: the same path as F5 - update this checkout, then reload ignoring the cache - so a new game-mods.js or page is really picked up
  // (operator 2026-11-11: "make it where ctrl + R fixes and reloads the latest version of the app").
  else if (input.control && !input.alt && String(input.key).toLowerCase() === "r") {
    win.webContents.send("hotkey", "client-refresh"); ev.preventDefault(); return;
  }
  else if (input.key === "F2" && (input.shift || input.control) && !input.alt) { win.webContents.send("hotkey", input.shift ? "slot+" : "slot-");"""

if text.count(old) != 1:
    raise SystemExit(f"anchor count {text.count(old)}")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("Ctrl+R now sends client-refresh, the same path F5 uses")
