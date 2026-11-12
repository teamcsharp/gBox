"""Fix the click that nulls its own menu: the outside-click listener fires on the same press.

The log, once per click:

```
Uncaught (in promise) TypeError: Cannot read properties of null (reading 'querySelector')
  (pip-stream-picker.js:245)
```

Line 245 is `addMenu.querySelector('[data-add-previous]')`, so `addMenu` was null by the time `openAdd` reached it. The cause is my own dismissal listener:

```js
function onAddAway(event) { if (!addMenu || !addMenu.contains(event.target)) dismissAdd(); }
document.addEventListener('pointerdown', onAddAway, true);
```

A press on the `+` tile fires **pointerdown before click**. If a menu is already open - and after the first attempt it always is - `onAddAway` sees a target outside
it, calls `dismissAdd()`, and nulls the reference that the click handler is about to use. The second `openAdd` then runs against `null`.

Two fixes, both narrow:

1. **`onAddAway` ignores presses on the tile itself** - that press is the one meant to open the menu, not dismiss it;
2. **`openAdd` re-checks `addMenu` after every `await`** before touching it, so an concurrent dismissal cannot cause a TypeError.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")
changes = 0

# 1. onAddAway must not treat a press on the tile as "away"
old_away = "    function onAddAway(event) { if (!addMenu || !addMenu.contains(event.target)) dismissAdd(); }"
new_away = ("    function onAddAway(event) {\n"
            "      if (event.target.closest?.('[data-stream-add]')) return;   // that press is opening it, not dismissing it\n"
            "      if (!addMenu || !addMenu.contains(event.target)) dismissAdd();\n"
            "    }")
if text.count(old_away) == 1:
    text = text.replace(old_away, new_away, 1)
    changes += 1
    print("onAddAway ignores the tile")
else:
    print("onAddAway anchor count", text.count(old_away))

# 2. null guards after the awaits
guards = [
    ("      if (!addMenu) return;\n      const previousRow", "      const previousRow"),
    ("      const list = addMenu.querySelector('[data-add-list]');", "      if (!addMenu) return;\n      const list = addMenu.querySelector('[data-add-list]');"),
    ("      const search = addMenu.querySelector('[data-add-search]');", "      if (!addMenu) return;\n      const search = addMenu.querySelector('[data-add-search]');"),
]
for old, new in guards:
    if old == "      if (!addMenu) return;\n      const previousRow":
        # already guarded before the header block? ensure one exists right before it
        if "      if (!addMenu) return;\n      const previousRow" not in text and "      const previousRow" in text:
            text = text.replace("      const previousRow", "      if (!addMenu) return;\n      const previousRow", 1)
            changes += 1
            print("guard before the header")
        continue
    if text.count(old) == 1 and new in text:
        continue
    if text.count(old) == 1:
        text = text.replace(old, new, 1)
        changes += 1
        print("guard added:", old.strip()[:60])

path.write_text(text, encoding="utf-8")
print("changes:", changes)

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("tile press ignored by dismissal:", "that press is opening it" in source)
print("null guard before the list:", "if (!addMenu) return;\n      const list" in source)
print("null guard before the search:", "if (!addMenu) return;\n      const search" in source)
