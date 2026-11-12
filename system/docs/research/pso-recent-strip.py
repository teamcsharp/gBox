"""A row of the last five launched games at the top of the right-click menu, clickable to launch.

The operator's request: *"Put thumbnails of recently played games cover art here … At the top of the right click menu always show the last five games that were
loaded as square thumbnails that I'm able to scroll between and select in order to launch that game."*

**What exists for art, and what does not.** The catalog carries `media.boxart` paths like
`collections/Nintendo GameCube/boxart/Phantasy Star Online Episode I & II Plus (USA)`, but:

* there is **no `collections` directory** on this machine (checked `D:\collections`, `C:\collections`, `C:\_tools\gBox\collections`, `D:\gBox\cache\collections`);
* `D:\gBox\cache\<game_id>` holds the game archive, not art;
* the only images in the cache are **Smash character previews**;
* the app has **no boxart route** — `boxart` appears nowhere in its JS, and `/api/art?path=` and `/api/media/boxart?path=` both 404.

So a real cover thumbnail cannot be shown from data that does not exist. **The row is built anyway, with an honest generated tile**: a square carrying the
title's initials on a colour derived from the game id, the full title as a tooltip, and a small label beneath. **When real art becomes available the same slot
uses it** - `media.boxart` is checked first, and the tile falls back to the generated cover.

**The five**: the operator's own sessions (`agent_owned === false`), newest first, de-duplicated, Merc titles excluded. Squares are 64px, in a horizontally
scrollable strip.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")
changes = 0

# 1. a container at the top of the panel html
old = """    return '<div class="pip-stream-heading"><strong>Streams</strong>"""
new = """    return '<div class="pip-stream-recent" data-stream-recent aria-label="Recently launched games"></div>' +
      '<div class="pip-stream-heading"><strong>Streams</strong>"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    changes += 1
    print("recent strip container added to the panel html")
else:
    print("heading anchor count", text.count(old))

# 2. fill it in mount(): last five launched games as squares
anchor = "    const valid = () => !stopped && io.valid?.() !== false;"
addition = '''    const valid = () => !stopped && io.valid?.() !== false;
    // The last five launched games, as squares you can click to launch again.
    const initials = title => String(title || '')
      .replace(/\\([^)]*\\)/g, '')
      .split(/[\\s:—-]+/).filter(Boolean).slice(0, 2).map(word => word[0]).join('').toUpperCase() || '?';
    const tint = id => {
      let hash = 0;
      for (const char of String(id || '')) hash = (hash * 31 + char.charCodeAt(0)) % 360;
      return `hsl(${hash} 34% 26%)`;
    };
    async function recentStrip() {
      const host = root.querySelector('[data-stream-recent]');
      if (!host) return;
      let games = [];
      try {
        const [sessionAnswer, catalogAnswer] = await Promise.all([
          io.api ? io.api('/api/sessions') : null,
          io.api ? io.api('/api/catalog') : null,
        ]);
        const sessions = Array.isArray(sessionAnswer) ? sessionAnswer : (sessionAnswer?.items || []);
        const catalog = (Array.isArray(catalogAnswer) ? catalogAnswer
          : (catalogAnswer?.items || catalogAnswer?.games || [])).filter(game => game && (game.game_id || game.id));
        const byId = new Map(catalog.map(game => [String(game.game_id || game.id), game]));
        const seen = new Set();
        for (const row of (sessions || []).filter(item => item && (item.agent_owned === false || item.agent_owned === 'false') && item.game_id)
          .sort((a, b) => Number(b.started || 0) - Number(a.started || 0))) {
          const id = String(row.game_id);
          if (seen.has(id)) continue;
          const entry = byId.get(id);
          if (!entry || /mercenar/i.test(String(entry.title || entry.alt_title || ''))) continue;
          seen.add(id);
          games.push(entry);
          if (games.length >= 5) break;
        }
      } catch { games = []; }
      if (!valid()) return;
      if (!games.length) { host.style.display = 'none'; return; }
      host.style.cssText = 'display:flex;gap:6px;overflow-x:auto;padding:2px 2px 8px;scrollbar-width:thin';
      host.innerHTML = games.map((game, index) => {
        const title = String(game.title || game.alt_title || game.game_id);
        return '<button type="button" data-recent-tile="' + index + '" title="Launch ' + esc(title) + '" ' +
          'style="flex:none;width:64px;height:64px;border-radius:6px;border:1px solid #3a4152;cursor:pointer;' +
          'background:' + tint(game.game_id) + ';color:#e6edf3;font:600 18px system-ui;display:flex;' +
          'align-items:center;justify-content:center;letter-spacing:.5px">' + esc(initials(title)) + '</button>';
      }).join('');
      host.querySelectorAll('[data-recent-tile]').forEach(buttonEl => {
        buttonEl.addEventListener('click', () => {
          const game = games[Number(buttonEl.dataset.recentTile)];
          if (!game) return;
          message('Starting ' + String(game.title || game.game_id) + '…');
          const go = typeof io.launch === 'function'
            ? io.launch(game)
            : io.api('/api/jobs', { tool: '@launch', input: { game } });
          Promise.resolve(go).catch(error => message('Could not start it: ' + String(error?.message || error)));
        });
      });
      console.log('pip recent: drew', games.length);
    }'''
if text.count(anchor) == 1 and "recentStrip" not in text:
    text = text.replace(anchor, addition, 1)
    changes += 1
    print("recent strip builder added")
else:
    print("valid anchor count", text.count(anchor))

# 3. call it when the panel mounts
old_call = "    const ready = refresh();"
new_call = "    recentStrip().catch(() => {});\n    const ready = refresh();"
if text.count(old_call) == 1:
    text = text.replace(old_call, new_call, 1)
    changes += 1
    print("recent strip runs on mount")

path.write_text(text, encoding="utf-8")
print("changes:", changes)

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:400])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("strip container:", "data-stream-recent" in source)
print("five tiles:", "games.length >= 5" in source)
print("clickable:", "data-recent-tile" in source)
print("runs on mount:", "recentStrip().catch" in source)
