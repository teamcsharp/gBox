"""Minimal, safe: order by last_played, and ask the server as well as filtering locally.

Two changes only, neither touching the existing structure:

1. **after `all` is built**, sort it by `last_played` descending - most recently opened first, which is what the operator asked for; the operator's own sessions
   stay first, then everything else by recency;
2. **on input**, in addition to drawing the local matches, ask `/api/catalog/best?q=` for ranked matches and draw those when they arrive - so a title outside the
   catalog page is still findable.

The local draw stays exactly as it is, so nothing that works today stops working. The server answer simply replaces the list when it arrives.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")
changes = 0

# 1. order by last_played after the list is assembled
anchor = "      const list = addMenu.querySelector('[data-add-list]');"
ordered = (
    "      // Most recently opened first: the operator's own sessions, then everything else by last_played.\n"
    "      all.sort((a, b) => {\n"
    "        if ((a.tag === 'recent') !== (b.tag === 'recent')) return a.tag === 'recent' ? -1 : 1;\n"
    "        return Number(b.game.last_played || 0) - Number(a.game.last_played || 0);\n"
    "      });\n"
    "      const list = addMenu.querySelector('[data-add-list]');"
)
if text.count(anchor) == 1 and "Most recently opened first" not in text:
    text = text.replace(anchor, ordered, 1)
    changes += 1
    print("list ordered by last_played")

# 2. ask the server on input
old_input = "      if (search) { search.addEventListener('input', () => draw(search.value)); setTimeout(() => search.focus(), 30); }"
new_input = """      if (search) {
        let timer = null;
        search.addEventListener('input', () => {
          const value = search.value;
          draw(value);                                  // local matches, immediately
          const needle = String(value || '').trim();
          clearTimeout(timer);
          if (needle.length < 2) return;
          timer = setTimeout(async () => {
            try {
              const answer = await call('/api/catalog/best?q=' + encodeURIComponent(needle) + '&limit=30');
              const rows = Array.isArray(answer) ? answer : (answer && (answer.items || answer.games)) || [];
              const found = (rows || []).filter(game => game && (game.game_id || game.id));
              console.log('pip add: server search', JSON.stringify(needle), '->', found.length);
              if (addMenu && found.length) {
                addMenu.querySelector('[data-add-list]').innerHTML = found.map((game, index) => {
                  const label = String(game.title || game.alt_title || game.game_id);
                  const system = String(game.platform || (game.collections && game.collections[0]) || '');
                  return '<button type="button" data-add-found="' + index + '" style="display:block;width:100%;text-align:left;' +
                    'padding:7px 8px;background:transparent;border:0;border-radius:5px;color:#e6edf3;font:inherit;cursor:pointer">' +
                    esc(label) + '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(system) + '</span></button>';
                }).join('');
                addMenu.querySelectorAll('[data-add-found]').forEach(buttonEl => {
                  buttonEl.addEventListener('click', () => start(found[Number(buttonEl.dataset.addFound)]));
                });
              }
            } catch (error) { console.log('pip add: server search failed', String(error && error.message || error)); }
          }, 180);
        });
        setTimeout(() => search.focus(), 30);
      }"""
if text.count(old_input) == 1:
    text = text.replace(old_input, new_input, 1)
    changes += 1
    print("server search added to the input handler")
else:
    print("input anchor count", text.count(old_input))

path.write_text(text, encoding="utf-8")
print("changes:", changes)

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:400])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("ordered by recency:", "Most recently opened first" in source)
print("server search:", "/api/catalog/best?q=" in source)
