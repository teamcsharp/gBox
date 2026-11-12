"""The panel was rendered and invisible: it sits behind the GPU game surface.

The log is unambiguous - every click produced:

```
pip add: click true
pip add: panel appended
pip add: sessions 61 catalog 100 recent 0
pip add: drew 100 of 100
```

**The panel was built, filled with a hundred rows, and appended to the body.** The operator could not see it because in compact mode the game is drawn by
`#gpu-game`, a **GPU surface that composites above the page** - a DOM element cannot out-stack it with any z-index. That is the same fact the PiP context menu
hit in round 293, and the same fix applies: **take the surface down while a menu is open**, then restore it.

So `openAdd` calls `window.gboxPipCover(true)` right after appending, and `dismissAdd` calls `window.gboxPipCover(false)` - the helper built for exactly this.

**Second bug in the same read**: `recent 0`. The catalog answered 100 entries and the sessions 61, yet no recent game matched. The filter requires
`item.agent_owned === false`; if the field arrives as the string `"false"` or as `false` on a different key, that strict comparison drops every row. The filter
now accepts a boolean or its string form, so the operator's own sessions are actually recognised.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")
changes = 0

# 1. raise the cover when the panel opens
old_open = "      document.body.appendChild(addMenu);\n      console.log('pip add: panel appended');"
new_open = ("      document.body.appendChild(addMenu);\n"
            "      // The game is a GPU surface above the page: take it down while this panel is up.\n"
            "      try { window.gboxPipCover?.(true); } catch {}\n"
            "      console.log('pip add: panel appended');")
if text.count(old_open) == 1:
    text = text.replace(old_open, new_open, 1)
    changes += 1
    print("cover raised on open")

# 2. drop the cover when it closes
old_dismiss = "    function dismissAdd() { if (addMenu) { addMenu.remove(); addMenu = null; } }"
new_dismiss = ("    function dismissAdd() {\n"
               "      if (addMenu) {\n"
               "        addMenu.remove(); addMenu = null;\n"
               "        try { window.gboxPipCover?.(false); } catch {}\n"
               "      }\n"
               "    }")
if text.count(old_dismiss) == 1:
    text = text.replace(old_dismiss, new_dismiss, 1)
    changes += 1
    print("cover dropped on close")

# 3. the recent filter must accept the string form
old_filter = "          for (const row of (sessions || []).filter(item => item && item.agent_owned === false && item.game_id)"
new_filter = ("          const isMine = item => item && (item.agent_owned === false || item.agent_owned === 'false' ||\n"
              "            item.agent_owned === 0 || item.agent_owned === '0');\n"
              "          for (const row of (sessions || []).filter(item => isMine(item) && item.game_id)")
if text.count(old_filter) == 1:
    text = text.replace(old_filter, new_filter, 1)
    changes += 1
    print("recent filter accepts the string form")

# 4. log why recent is empty, once
old_log = "        console.log('pip add: sessions', (sessions || []).length, 'catalog', catalog.length, 'recent', recent.length);"
new_log = ("        console.log('pip add: sessions', (sessions || []).length, 'catalog', catalog.length, 'recent', recent.length,\n"
           "          'owned', (sessions || []).filter(item => item && (item.agent_owned === false || item.agent_owned === 'false')).length);")
if text.count(old_log) == 1:
    text = text.replace(old_log, new_log, 1)
    changes += 1
    print("logs how many sessions are the operator's")

path.write_text(text, encoding="utf-8")
print("changes:", changes)

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("raises the cover:", "gboxPipCover?.(true)" in source)
print("drops the cover:", "gboxPipCover?.(false)" in source)
print("accepts string agent_owned:", "item.agent_owned === 'false'" in source)
