"""Take the relaunch prompt out of the page until it is proven safe.

The operator reports the right-click menu no longer lists options and the app is unresponsive, after the relaunch prompt was added. It is the newest change and the
only one that runs on page load, so it stops being loaded now:

* the `<script src="relaunch-prompt.js">` tag is removed, so its `setTimeout(maybeAsk, 4500)` never runs;
* the file stays on disk, unchanged, so it can be re-enabled once the cause is understood;
* the `pip-relaunch-prompt` clause stays in the compact allow-list - harmless on its own.

The host's `gboxRememberGame` call stays; it is a try/catch one-liner that does nothing when the global is absent.
"""
import pathlib

page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = page.read_text(encoding="utf-8")

old = '<script src="relaunch-prompt.js"></script>\n'
if old in text:
    text = text.replace(old, "", 1)
    page.write_text(text, encoding="utf-8")
    print("relaunch-prompt.js no longer loaded")
else:
    print("script tag not found")

source = page.read_text(encoding="utf-8")
print("script tag gone:", 'src="relaunch-prompt.js"' not in source)
print("allow-list clause kept:", ":not(.pip-relaunch-prompt)" in source)
print("remember call kept:", "gboxRememberGame?.(game)" in source)

import subprocess
result = subprocess.run(["node", "--check", str(page)], capture_output=True, text=True, timeout=120)
print("index.html node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:200])
