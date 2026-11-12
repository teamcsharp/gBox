"""Add the carousel tile with a distinct class, now that the collision is known.

`pip-stream-add` is already the dropdown's class, which is why the earlier check said "already present". The tile gets `pip-stream-add-tile` and carries
`data-stream-add`, which is what the click routing looks for.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

if "pip-stream-add-tile" in text:
    print("tile already present")
else:
    old = """        '<p class="pip-stream-empty">No active streams. Waiting for a game to be ready.</p>') + '</div>' +"""
    new = ("""        '<p class="pip-stream-empty">No active streams. Waiting for a game to be ready.</p>') + """
           """'<button type="button" class="pip-stream-card pip-stream-add-tile" data-stream-add title="Start a recent game into the PiP" aria-label="Add a game">' + """
           """'<span class="pip-stream-picture" style="display:flex;align-items:center;justify-content:center;font-size:34px;font-weight:300;line-height:1">+</span>' + """
           """'<strong>Add game</strong><span>Recent launches</span></button>' + '</div>' +""")
    if text.count(old) != 1:
        raise SystemExit(f"anchor count {text.count(old)}")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("add tile inserted at the end of the carousel")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("tile present:", 'class="pip-stream-card pip-stream-add-tile" data-stream-add' in source)
print("heading + gone:", "data-stream-add title=\"Start a recent game into the PiP\">+<" not in source)
print("opens the dropdown:", "async function openAdd" in source)
print("previous first:", "data-add-previous" in source)
print("operator only:", "agent_owned === false" in source)
print("drops Merc:", "mercenar" in source)
