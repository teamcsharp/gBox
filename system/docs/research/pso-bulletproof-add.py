"""Make the add panel bulletproof and observable: no gate can return silently, and the log says so.

The log after the operator's restart is decisive: **no exception from pip-stream-picker since 11:34** - the errors there predate the fix - and nothing since. So
the click reaches the handler and `openAdd` returns **without doing anything and without throwing**. The only paths that do that are:

```js
const button = event.target.closest?.('[data-stream-add]');
if (!button || !valid()) return;
```

`valid()` is the host's `() => m.opening === opening && S?.apiUrl === opening.origin` - a staleness check for the *session* the menu was opened for. It is the right
check for switching streams and the **wrong** one for launching a game, which does not care which session the menu belongs to.

So this version:

1. **drops the `valid()` gate entirely** - launching a game is not conditional on the menu's session being current;
2. **logs the click** to the console (which lands in `app-console.log`), so the next attempt is verifiable;
3. **uses `globalThis.gbox.api` directly** and falls back to the documented endpoints, so it does not depend on options the host may not pass;
4. **renders even before the fetch resolves**, so a slow or failed read still shows a searchable panel instead of nothing.
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

body = r'''    async function openAdd(event) {
      // No gate may return quietly: launching a game does not depend on which session this menu belongs to.
      const button = event.target.closest?.('[data-stream-add]');
      console.log('pip add: click', !!button);
      if (!button) return;
      event.preventDefault(); event.stopPropagation();
      dismissAdd(); dismissMenu();
      const rect = button.getBoundingClientRect();
      addMenu = document.createElement('div');
      addMenu.className = 'pip-stream-menu pip-stream-add';
      addMenu.setAttribute('role', 'dialog');
      addMenu.style.cssText = 'position:fixed;z-index:9999;width:min(360px,86vw);padding:8px;' +
        'background:#1b1f2a;border:1px solid #3a4152;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.55);' +
        'left:' + Math.round(Math.max(8, Math.min(rect.left, window.innerWidth - 372))) + 'px;' +
        'top:' + Math.round(Math.min(rect.bottom + 6, window.innerHeight - 120)) + 'px;';
      addMenu.innerHTML = '<div style="padding:2px 2px 6px;font-size:11px;color:#9aa3b4">Start a game</div>' +
        '<input data-add-search type="search" placeholder="Search title or system…" autocomplete="off" ' +
        'style="width:100%;box-sizing:border-box;padding:6px 8px;margin-bottom:6px;background:#0d1117;color:#e6edf3;' +
        'border:1px solid #30363d;border-radius:5px;font:inherit">' +
        '<div data-add-list style="max-height:50vh;overflow:auto">' +
        '<div style="padding:8px;font-size:12px;color:#9aa3b4">Loading your games…</div></div>';
      document.body.appendChild(addMenu);
      console.log('pip add: panel appended');

      const call = async (path, init) => {
        if (typeof io.api === 'function') return io.api(path, init);
        const helper = globalThis.gbox && globalThis.gbox.api;
        if (!helper) throw new Error('no api helper');
        const answer = await helper(path, init);
        if (answer && answer.ok === false) throw new Error(answer.error || 'request failed');
        return answer && typeof answer === 'object' && 'data' in answer ? answer.data : answer;
      };

      let recent = [], catalog = [];
      try {
        const [sessionAnswer, catalogAnswer] = await Promise.all([
          call('/api/sessions').catch(() => null),
          call('/api/catalog').catch(() => null),
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
        console.log('pip add: sessions', (sessions || []).length, 'catalog', catalog.length, 'recent', recent.length);
      } catch (error) {
        console.log('pip add: read failed', String(error && error.message || error));
      }
      if (!addMenu) { console.log('pip add: panel went away during the read'); return; }

      const all = [];
      const push = (game, tag) => {
        const id = String(game.game_id || game.id);
        if (all.some(item => item.id === id)) return;
        all.push({ id, game, tag });
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
        const system = String(game.platform || (game.collections && game.collections[0]) || '');
        return '<button type="button" role="option" data-add-index="' + index + '" ' +
          'style="display:block;width:100%;text-align:left;padding:7px 8px;background:transparent;border:0;border-radius:5px;' +
          'color:#e6edf3;font:inherit;cursor:pointer">' + esc(label) +
          '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(system) +
          (item.tag === 'recent' ? ' · recent' : '') + '</span></button>';
      };
      const draw = query => {
        const needle = String(query || '').trim().toLowerCase();
        const matches = all.filter(item => {
          if (!needle) return true;
          const game = item.game;
          const text = (String(game.title || game.alt_title || game.game_id) + ' ' +
            String(game.platform || (game.collections && game.collections[0]) || '')).toLowerCase();
          return text.includes(needle);
        });
        list.innerHTML = matches.length
          ? matches.slice(0, 60).map((item) => rowHTML(item, all.indexOf(item))).join('')
          : '<div style="padding:8px;font-size:12px;color:#9aa3b4">' +
            (all.length ? 'No games match' : 'No games available') + '</div>';
        list.querySelectorAll('[data-add-index]').forEach(buttonEl => {
          buttonEl.addEventListener('click', () => start(all[Number(buttonEl.dataset.addIndex)]?.game));
        });
        console.log('pip add: drew', matches.length, 'of', all.length);
      };
      const start = async game => {
        if (!game) return;
        const label = String(game.title || game.game_id);
        dismissAdd();
        if (valid()) message('Starting ' + label + '…');
        try {
          if (typeof io.launch === 'function') { await io.launch(game); }
          else { await call('/api/jobs', { tool: '@launch', input: { game } }); }
        } catch (error) {
          console.log('pip add: launch failed', String(error && error.message || error));
          if (valid()) message('Could not start it: ' + String(error?.message || error));
        }
      };
      draw('');
      const search = addMenu.querySelector('[data-add-search]');
      if (search) { search.addEventListener('input', () => draw(search.value)); setTimeout(() => search.focus(), 30); }
    }
'''

text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("openAdd rewritten: no valid() gate, console trace, self-contained api")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:400])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("no valid() gate in the entry:", "if (!button || !valid()) return;" not in source)
print("logs the click:", "pip add: click" in source)
print("self-contained api:", "globalThis.gbox && globalThis.gbox.api" in source)
print("renders before fetch:", "Loading your games" in source)
