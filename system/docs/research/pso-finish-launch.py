"""Finish the tool rename, and build the recent list from sessions instead of hoping the catalog has them.

Two remaining faults, both in the log:

```
pip add: sessions 61 catalog 100 recent 0 owned 12
pip add: launch failed 404 {"detail":"not found"}
```

* **one `@launch` survived** in the panel's `start`, so the server still answers *tool not found*;
* **`recent 0` against `owned 12`** - twelve of the operator's sessions exist, but the loop resolves each `game_id` through the **catalog page of 100**, and
  those ids are not in that page, so every one is skipped.

The fix for the second is to **use what the session already carries** - it has `title` and `game_id` - and to resolve the full entry **on click** with
`/api/catalog/<id>`, which always works for a game the operator has run. That also means the list is complete rather than limited to whatever the catalog page
happened to hold.
"""
import pathlib

picker = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = picker.read_text(encoding="utf-8")
changes = 0

# 1. the surviving @launch
old = "const body = { tool: '@launch', input: { game, node: io.node ? io.node() : undefined } };"
new = "const body = { tool: 'launch_game', input: { game } };"
if old in text:
    text = text.replace(old, new, 1)
    changes += 1
    print("start(): @launch -> launch_game")

# 2. recent from the sessions themselves; resolve the entry on click
old_loop = """          const entry = byId.get(id);
          if (entry && !/mercenar/i.test(String(entry.title || entry.alt_title || ''))) recent.push(entry);"""
new_loop = """          const entry = byId.get(id) || { game_id: id, title: row.title || id };
          if (!/mercenar/i.test(String(entry.title || entry.alt_title || row.title || ''))) recent.push(entry);"""
if old_loop in text:
    text = text.replace(old_loop, new_loop, 1)
    changes += 1
    print("recent() builds entries from the sessions")

# 3. the strip: same, and resolve on click
old_strip = """          const entry = byId.get(id);
          if (!entry || /mercenar/i.test(String(entry.title || entry.alt_title || ''))) continue;
          seen.add(id);
          games.push(entry);"""
new_strip = """          const entry = byId.get(id) || { game_id: id, title: row.title || id };
          if (/mercenar/i.test(String(entry.title || entry.alt_title || row.title || ''))) continue;
          seen.add(id);
          games.push(entry);"""
if old_strip in text:
    text = text.replace(old_strip, new_strip, 1)
    changes += 1
    print("strip() builds entries from the sessions")

# 4. resolve a full CatalogEntry before launching, wherever a launch happens
old_start_body = """      const start = async game => {
        if (!game) return;
        const label = String(game.title || game.game_id);"""
new_start_body = """      const start = async game => {
        if (!game) return;
        // A session-derived tile carries only id and title; /api/catalog/<id> gives the entry launch_game needs.
        if (!game.launch && io.api) {
          try { const full = await io.api('/api/catalog/' + encodeURIComponent(String(game.game_id))); if (full && (full.game_id || full.id)) game = full; }
          catch { /* fall back to what we have */ }
        }
        const label = String(game.title || game.game_id);"""
if old_start_body in text:
    text = text.replace(old_start_body, new_start_body, 1)
    changes += 1
    print("start() resolves the full entry first")

picker.write_text(text, encoding="utf-8")
print("changes:", changes)

import subprocess
result = subprocess.run(["node", "--check", str(picker)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = picker.read_text(encoding="utf-8")
print("no '@launch' left:", "'@launch'" not in source)
print("recent from sessions:", "row.title || id" in source)
print("resolves on launch:", "/api/catalog/' + encodeURIComponent" in source)
