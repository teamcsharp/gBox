"""Wire the relaunch prompt: load it, let it through compact mode, and remember every launch."""
import pathlib

page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = page.read_text(encoding="utf-8")
changes = 0

# 1. load the script after the picker
old = '<script src="pip-stream-picker.js"></script>'
new = '<script src="pip-stream-picker.js"></script>\n<script src="relaunch-prompt.js"></script>'
if 'relaunch-prompt.js' not in text:
    if text.count(old) == 1:
        text = text.replace(old, new, 1)
        changes += 1
        print("script loaded")
    else:
        print("script anchor count", text.count(old))

# 2. allow the card through the compact rule
if ":not(.pip-relaunch-prompt)" not in text:
    anchor = ":not(.pip-stream-menu)"
    if text.count(anchor) == 1:
        text = text.replace(anchor, ":not(.pip-stream-menu):not(.pip-relaunch-prompt)", 1)
        changes += 1
        print("card allowed in compact mode")
    else:
        print("allow anchor count", text.count(anchor))

# 3. remember on the host's launch
old_launch = "    launch: async game => {"
new_launch = "    launch: async game => {\n      try { globalThis.gboxRememberGame?.(game); } catch {}"
if "gboxRememberGame?.(game)" not in text:
    if text.count(old_launch) == 1:
        text = text.replace(old_launch, new_launch, 1)
        changes += 1
        print("host launch remembers the game")

page.write_text(text, encoding="utf-8")
print("index changes:", changes)

# 4. the picker remembers too (it launches without the host)
picker = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
ptext = picker.read_text(encoding="utf-8")
if "gboxRememberGame" not in ptext:
    old_mark = "        const label = String(game.title || game.game_id);\n        dismissAdd();"
    new_mark = ("        const label = String(game.title || game.game_id);\n"
                "        try { globalThis.gboxRememberGame?.(game); } catch {}\n"
                "        dismissAdd();")
    if ptext.count(old_mark) == 1:
        ptext = ptext.replace(old_mark, new_mark, 1)
        picker.write_text(ptext, encoding="utf-8")
        print("picker launch remembers the game")
    else:
        # the strip's click
        old_strip = "          if (!game) return;\n          message('Starting ' + String(game.title || game.game_id) + '…');"
        new_strip = ("          if (!game) return;\n"
                     "          try { globalThis.gboxRememberGame?.(game); } catch {}\n"
                     "          message('Starting ' + String(game.title || game.game_id) + '…');")
        if ptext.count(old_strip) == 1:
            ptext = ptext.replace(old_strip, new_strip, 1)
            picker.write_text(ptext, encoding="utf-8")
            print("strip click remembers the game")
        else:
            print("picker anchor not found:", "gboxRememberGame" in ptext)

import subprocess
for path in (page, picker):
    if path.suffix == ".js":
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
        print(path.name, "node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:200])

result = subprocess.run(["node", "--check", r"C:\_tools\gBox\system\clients\desktop\relaunch-prompt.js"],
                        capture_output=True, text=True, timeout=120)
print("relaunch-prompt.js node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = page.read_text(encoding="utf-8")
print("script loaded:", "relaunch-prompt.js" in source)
print("allowed in compact:", ":not(.pip-relaunch-prompt)" in source)
print("remembers on launch:", "gboxRememberGame?.(game)" in source)
