"""Render the Streams panel instantly; fill it when the data arrives.

Line 185 of `pip-stream-picker.js`:

```js
root.innerHTML = '<p class="pip-stream-empty" role="status">Loading streams…</p>';
```

The panel therefore shows **only** that sentence until `refresh()` finishes - and `refresh()` awaits `io.read()` (the sessions) and then starts a preview request
for every stream. **Ten seconds of nothing is that wait, rendered in full.**

The fix is to draw the real panel **immediately** with no entries, which already renders the heading, the carousel with the `+` tile, and the "No active streams"
line - then let `refresh()` replace it when the data arrives. The recent strip and the add panel already fetch in parallel and are unaffected.

Nothing about the data path changes; only what is on screen while it runs.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

old = """    root.innerHTML = '<p class="pip-stream-empty" role="status">Loading streams…</p>';"""
new = """    // Draw the panel at once so the menu is usable immediately; refresh() fills the carousel when the data lands.
    root.innerHTML = html([], io.current ? io.current() : '', io.title, !!io.broadcast);"""

count = text.count(old)
print("anchor count:", count)
if count == 1:
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("the panel renders immediately")
else:
    print("anchor missing")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("no loading placeholder:", "Loading streams…" not in source)
print("renders html at once:", "root.innerHTML = html([]," in source)
print("refresh still fills:", "root.innerHTML = html(entries" in source)
