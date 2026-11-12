"""Rewrite the add-game panel: self-contained launch, a search bar, and a real list.

The operator's report: *"When I click this, nothing pops up. I need a list of recent games that have been launched. and a search bar with dynamic search at the
top so i can find the title and system i want to launch."*

**Why nothing popped up.** `openAdd` began with

```js
if (!valid() || typeof io.launch !== 'function') return;
```

and `io.launch` only exists once the host's `index.html` has been reloaded - the tile renders from `pip-stream-picker.js` alone, so a cached page shows the tile
with no launch behind it, and the guard silently returned. **The panel must not depend on the host for this.**

**What replaces it:**

* **launch directly** - `io.api('/api/jobs', {tool:'@launch', input:{game, node}})` from inside the component, falling back to `io.launch` if the host supplies
  one;
* **a search input at the top**, with `input` handling that filters **as you type** by title and platform;
* **two groups**: the operator's recent launches first (their own sessions, `agent_owned === false`, Merc titles dropped), then the rest of the catalog so any
  title can be found;
* each row shows **title and system** (the catalog's `platform`).

The list is fetched once when the panel opens, and filtering is local, so typing is immediate.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

start = text.find("    async function openAdd(event) {")
if start < 0:
    raise SystemExit("openAdd not found")
end = text.find("\n    function onAddAway", start)
if end < 0:
    raise SystemExit("onAddAway not found")

old_len = end - start
print("replacing the openAdd body:", old_len, "characters")

body = r'''    async function openAdd(event) {
      const button = event.target.closest?.('[data-stream-add]');
      if (!button || !valid()) return;
      event.preventDefault(); event.stopPropagation();
      dismissAdd(); dismissMenu();
      const rect = button.getBoundingClientRect();
      addMenu = document.createElement('div');
      addMenu.className = 'pip-stream-menu pip-stream-add';
      addMenu.setAttribute('role', 'dialog');
      addMenu.style.cssText = 'position:fixed;z-index:95;width:min(360px,86vw);padding:8px;' +
        'background:#1b1f2a;border:1px solid #3a4152;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.55);' +
        'left:' + Math.round(Math.min(rect.left, window.innerWidth - 372)) + 'px;top:' + Math.round(rect.bottom + 6) + 'px;';
      addMenu.innerHTML = '<div style="padding:2px 2px 6px;font-size:11px;color:#9aa3b4">Start a game</div>' +
        '<input data-add-search type="search" placeholder="Search title or system…" autocomplete="off" ' +
        'style="width:100%;box-sizing:border-box;padding:6px 8px;margin-bottom:6px;background:#0d1117;color:#e6edf3;' +
        'border:1px solid #30363d;border-radius:5px;font:inherit">' +
        '<div data-add-list style="max-height:50vh;overflow:auto"></div>';
      document.body.appendChild(addMenu);

      let recent = [], catalog = [];
      try {
        const [sessionAnswer, catalogAnswer] = await Promise.all([
          io.api ? io.api('/api/sessions') : null,
          io.api ? io.api('/api/catalog') : null,
        ]);
        const sessions = Array.isArray(sessionAnswer) ? sessionAnswer : (sessionAnswer?.items || []);
        catalog = (Array.isArray(catalogAnswer) ? catalogAnswer
          : (catalogAnswer?.items || catalogAnswer?.games || [])).filter(game => game && (game.game_id || game.id));
        const byId = new Map(catalog.map(game => [String(game.game_id || game.id), game]));
        const seen = new Set();
        for (const row of (sessions || []).filter(item => item && item.agent_owned === false && item.game_id)
          .sort((a, b) => Number(b.started || 0) - Number(a.started || 0))) {
          const id = String(row.game_id);
          if (seen.has(id)) continue;
          seen.add(id);
          const entry = byId.get(id);
          if (entry && !/mercenar/i.test(String(entry.title || entry.alt_title || ''))) recent.push(entry);
        }
      } catch { recent = []; }

      const all = [];
      const push = (game, tag) => {
        if (all.some(item => item.id === String(game.game_id || game.id))) return;
        all.push({ id: String(game.game_id || game.id), game, tag });
      };
      for (const game of recent) push(game, 'recent');
      for (const game of catalog) {
        if (/mercenar/i.test(String(game.title || game.alt_title || ''))) continue;
        push(game, 'catalog');
      }

      const list = addMenu.querySelector('[data-add-list]');
      const rowHTML = (item, index) => {
        const game = item.game;
        const label = String(game.title || game.alt_title || game.game_id);
        const system = String(game.platform || game.collections?.[0] || '');
        return '<button type="button" role="option" data-add-index="' + index + '" ' +
          'data-needle="' + esc((label + ' ' + system).toLowerCase()) + '" ' +
          'style="display:block;width:100%;text-align:left;padding:7px 8px;background:transparent;border:0;border-radius:5px;' +
          'color:#e6edf3;font:inherit;cursor:pointer">' + esc(label) +
          '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(system) +
          (item.tag === 'recent' ? ' · recent' : '') + '</span></button>';
      };
      const draw = query => {
        const needle = String(query || '').trim().toLowerCase();
        const shown = needle ? all.filter(item => item.needleCache === undefined) : all;
        list.innerHTML = all.map((item, index) => ({ item, index }))
          .filter(({ item }) => {
            if (!needle) return true;
            const game = item.game;
            const text = (String(game.title || game.alt_title || game.game_id) + ' ' +
              String(game.platform || game.collections?.[0] || '')).toLowerCase();
            return text.includes(needle);
          })
          .slice(0, 60)
          .map(({ item, index }) => rowHTML(item, index)).join('') ||
          '<div style="padding:8px;font-size:12px;color:#9aa3b4">No games match</div>';
        list.querySelectorAll('[data-add-index]').forEach(buttonEl => {
          buttonEl.addEventListener('click', () => start(all[Number(buttonEl.dataset.addIndex)]?.game));
        });
      };
      const start = async game => {
        if (!game) return;
        dismissAdd();
        const label = String(game.title || game.game_id);
        if (valid()) message('Starting ' + label + '…');
        try {
          const body = { tool: '@launch', input: { game, node: io.node ? io.node() : undefined } };
          if (typeof io.launch === 'function') { await io.launch(game); }
          else if (io.api) {
            const answer = await io.api('/api/jobs', body);
            if (answer && answer.ok === false) throw new Error(answer.error || 'refused');
          } else throw new Error('no way to launch from here');
        } catch (error) { if (valid()) message('Could not start it: ' + String(error?.message || error)); }
      };
      draw('');
      const search = addMenu.querySelector('[data-add-search]');
      search.addEventListener('input', () => draw(search.value));
      setTimeout(() => search.focus(), 30);
    }
'''

text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("openAdd rewritten: self-contained launch, search bar, two groups")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:400])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
for label, needle in (
    ("search input", "data-add-search"),
    ("dynamic filter", "search.addEventListener('input'"),
    ("does not require io.launch", "typeof io.launch === 'function'"),
    ("falls back to io.api", "io.api('/api/jobs'"),
    ("recent first", "if (recent.length"),
    ("Merc dropped", "mercenar"),
    ("tile still there", 'pip-stream-add-tile" data-stream-add'),
):
    print(f"{label}: {needle in source}")
