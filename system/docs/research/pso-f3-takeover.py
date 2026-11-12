"""F3 must take over, not toggle.

The operator's request: *"when i press F3 in pso have the bot take over immediately."*

F3 is wired to `op: 'toggle'` in both places that can fire it:

* `index.html` -> `f3Autobot()` -> `GBoxPiPMedia.autobot(api, sid, {op: 'toggle', source: 'F3'})`
* `pip-media.js` -> `toggleAutobot()` -> `op: 'toggle'`

The server resolves `toggle` as *"if running then stop, else start"*. So **pressing F3 while the bot is already playing stops it** - the character halts, and
the screen shows exactly the "it just stands there" the operator keeps reporting. The menu item is even labelled "Take control (autoplay) F3", which is a
take-over, not a toggle.

Both call sites now send `op: 'start'`. The server answers `already_running` when it is already in charge, so a second press is harmless and never hands control
back - F3 always means "the bot drives now". Stopping stays available from the menu and the API.

The session lookup before the call is also shortened, so the request goes out on the first frame the shown game is known instead of waiting up to 2.5 s.
"""
import pathlib

changes = 0

page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = page.read_text(encoding="utf-8")

old_call = "await GBoxPipMedia.autobot(compactApi, sid, { op: 'toggle', source: 'F3' })"
new_call = "await GBoxPipMedia.autobot(compactApi, sid, { op: 'start', source: 'F3' })"
if old_call in text:
    text = text.replace(old_call, new_call, 1)
    changes += 1
    print("index.html: F3 now sends op start")

old_wait = "const sid = await shownSessionSoon({ fallback: true }, 2500);"
new_wait = "const sid = await shownSessionSoon({ fallback: true }, 1200);"
if old_wait in text:
    text = text.replace(old_wait, new_wait, 1)
    changes += 1
    print("index.html: shown-session lookup shortened to 1.2 s")

page.write_text(text, encoding="utf-8")

media = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-media.js")
mtext = media.read_text(encoding="utf-8")
old_media = "out=await autobot(api,sid,{op:'toggle',source:'F3'},"
new_media = "out=await autobot(api,sid,{op:'start',source:'F3'},"
if old_media in mtext:
    mtext = mtext.replace(old_media, new_media, 1)
    media.write_text(mtext, encoding="utf-8")
    changes += 1
    print("pip-media.js: F3 now sends op start")

print("changes:", changes)

import subprocess
for path in (media,):
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
    print(path.name, "node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:200])

page_text = page.read_text(encoding="utf-8")
print("index sends start:", "{ op: 'start', source: 'F3' }" in page_text)
print("no F3 toggle left in index:", "{ op: 'toggle', source: 'F3' }" not in page_text)
print("media sends start:", "{op:'start',source:'F3'}" in mtext.read_text(encoding="utf-8"))
