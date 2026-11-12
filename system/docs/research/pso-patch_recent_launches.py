"""List the operator's own launches, with "previous game" first, and never Merc titles.

The operator's correction: *"one of the first options it should ask me is to launch the previous game. Always offer a list of the most recently launched titles
for me to launch that I manually launch. Don't list Mercenary titles from Merc mode. List titles that I have personally launched in the application."*

What the data shows:

* **`/api/sessions` records `agent_owned`** per session - so **operator-owned** sessions are exactly "what I launched myself", and agent launches (mine) and Merc
  runs are excluded by construction;
* the operator's seven operator-owned sessions are **all PSO**, while the catalog also holds *"Resident Evil: The Mercenaries 3D"* - a Merc title they never
  launched, which is precisely what should not appear;
* the catalog is needed only to turn a `game_id` into the full entry `@launch` requires.

So `openAdd` now sources its list from **sessions**, not the catalog:

1. fetch sessions and catalog together;
2. keep **`agent_owned === false`** only;
3. **dedupe by game_id**, newest first;
4. **drop Merc titles explicitly** as well (a title match), so a Merc run never leaks in even if it were operator-owned;
5. the **first row is "Launch the previous game"** with that title;
6. the rest are the recent operator-launched titles, in order.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

old_start = "      let games = [];"
old_end = "      if (!addMenu) return;"
start = text.find(old_start)
end = text.find(old_end, start)
if start < 0 or end < 0:
    raise SystemExit("openAdd's fetch block not found")

old_block = text[start:end]
print("replacing", len(old_block), "characters of the fetch block")

new_block = '''      let games = [], previous = null;
      try {
        const [sessionAnswer, catalogAnswer] = await Promise.all([
          io.api ? io.api('/api/sessions') : null,
          io.api ? io.api('/api/catalog') : null,
        ]);
        const sessions = Array.isArray(sessionAnswer) ? sessionAnswer : (sessionAnswer?.items || []);
        const catalog = Array.isArray(catalogAnswer) ? catalogAnswer : (catalogAnswer?.items || catalogAnswer?.games || []);
        const byId = new Map((catalog || []).filter(game => game && (game.game_id || game.id))
          .map(game => [String(game.game_id || game.id), game]));
        // What the operator launched themselves: sessions they own, not agent or Merc runs.
        const mine = (sessions || []).filter(row => row && row.agent_owned === false && row.game_id)
          .sort((a, b) => Number(b.started || 0) - Number(a.started || 0));
        const seen = new Set();
        for (const row of mine) {
          const id = String(row.game_id);
          if (seen.has(id)) continue;
          seen.add(id);
          const entry = byId.get(id);
          if (!entry) continue;
          // Never a Mercenaries title, whatever launched it.
          if (/mercenar/i.test(String(entry.title || entry.alt_title || row.title || ''))) continue;
          if (!previous) previous = entry;
          games.push(entry);
          if (games.length >= 12) break;
        }
      } catch { games = []; previous = null; }
'''
text = text[:start] + new_block + text[end:]
path.write_text(text, encoding="utf-8")
print("openAdd now lists the operator's own launches")

# the menu header and rows: "Launch the previous game" first
old_header = """      addMenu.innerHTML = '<div style="padding:6px 8px;font-size:11px;color:#9aa3b4">Recently played</div>' +"""
new_header = """      const previousRow = previous
        ? '<button type="button" role="menuitem" data-add-previous="" style="display:block;width:100%;text-align:left;padding:7px 8px;' +
          'background:#22304a;border:1px solid #33456b;border-radius:5px;color:#e6edf3;font:inherit;cursor:pointer;margin-bottom:4px">' +
          'Launch the previous game<span style="display:block;font-size:11px;color:#9aa3b4">' +
          esc(previous.title || previous.game_id) + '</span></button>'
        : '';
      addMenu.innerHTML = '<div style="padding:6px 8px;font-size:11px;color:#9aa3b4">Your recent launches</div>' + previousRow +"""
if text.count(old_header) == 1 and "data-add-previous" not in text:
    text = text.replace(old_header, new_header, 1)
    print("the previous-game row is first")

# and wire the previous row
old_wire = """      addMenu.querySelectorAll('[data-add-game]').forEach(buttonEl => {"""
new_wire = """      addMenu.querySelector('[data-add-previous]')?.addEventListener('click', async () => {
        const game = previous;
        dismissAdd();
        if (!game) return;
        try { await io.launch(game); if (valid()) message('Starting ' + (game.title || game.game_id) + '…'); }
        catch (error) { if (valid()) message('Could not start it: ' + String(error?.message || error)); }
      });
      addMenu.querySelectorAll('[data-add-game]').forEach(buttonEl => {"""
if text.count(old_wire) == 1 and "data-add-previous]')?.addEventListener" not in text:
    text = text.replace(old_wire, new_wire, 1)
    print("the previous-game row is wired")

path.write_text(text, encoding="utf-8")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("filters operator sessions:", "agent_owned === false" in source)
print("drops Merc titles:", "mercenar" in source)
print("previous row:", "data-add-previous" in source)
