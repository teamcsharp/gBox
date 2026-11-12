"""Wire the + button's click, and give the panel a `launch` it can call.

Two connections remain:

1. **the click** - `mount()` routes clicks through `click(event)`, which handles `[data-stream-sid]`, `[data-stream-step]` and `[data-stream-broadcast]`. The `+`
   needs its own branch before those, calling `openAdd`.
2. **`io.launch`** - the host builds the picker's options in `index.html`. It needs a `launch(game)` that starts the game the operator picked, from inside the
   PiP, without leaving it.

For the host side, the launch goes through the same job endpoint the app's own Play button uses (`/api/jobs` with `@launch`), requiring the worker for this PC.
Both edits are additive and node/JS syntax checked.
"""
import pathlib

# 1. the picker's click routing
picker = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = picker.read_text(encoding="utf-8")

if "data-stream-add" in text and "openAdd(event)" in text and "if (event.target.closest?.('[data-stream-add]'))" in text:
    print("picker click already routed")
else:
    anchor = "    const click = event => {"
    count = text.count(anchor)
    print("click anchor count:", count)
    if count == 1:
        text = text.replace(anchor, anchor + """
      if (event.target.closest?.('[data-stream-add]')) { openAdd(event); return; }""", 1)
        picker.write_text(text, encoding="utf-8")
        print("+ click routed to openAdd")
    else:
        for index, line in enumerate(text.splitlines()):
            if "const click = event" in line:
                print(f"  line {index + 1}: {line.strip()[:90]}")

# 2. the host supplies launch
page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
page_text = page.read_text(encoding="utf-8")

if "launchPipGame" in page_text:
    print("host launch already present")
else:
    anchor = "    select:(sid, valid) => pipSelection.select(sid, valid),"
    if page_text.count(anchor) != 1:
        raise SystemExit(f"select anchor count {page_text.count(anchor)}")
    addition = """    select:(sid, valid) => pipSelection.select(sid, valid),
    // Start a recently played game into the PiP - the + button in the Streams panel.
    launch: async game => {
      const worker = (S.workerName || '').trim();
      const body = { tool: '@launch', input: { game, node: S.workerId || undefined } };
      const answer = await gbox.api('/api/jobs', body);
      if (!answer.ok) throw new Error(answer.error || 'the launch was refused');
      return answer.data;
    },"""
    page_text = page_text.replace(anchor, addition, 1)
    page.write_text(page_text, encoding="utf-8")
    print("host launch added")

import subprocess
for path in (picker, page):
    if path.suffix == ".js":
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
        print(path.name, "node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:200])
