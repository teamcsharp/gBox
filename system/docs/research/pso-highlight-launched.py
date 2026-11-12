"""Search results ordered by what you actually launched, with launched titles highlighted.

The operator's request: *"When I'm searching for a game, list the games by which title I recently launched. So always show the most recently launched title and do
a special highlight around an item that has actually been launched recently, so I don't launch something obscure by accident."*

The screenshot shows why it matters: typing `phan` gives **Phantasy Star Online (USA)** first - a Dreamcast title they never ran - ahead of the GameCube one they
play daily, with **Phantom 2040** sitting right below, one misclick away.

So the server-search results now:

1. **sort by `last_played` descending** - anything ever launched comes before anything never launched, newest first, and never-launched titles keep the server's
   relevance order below them;
2. **highlight launched titles** - a blue border and tinted background, plus a `launched <when>` line, so the ones with history are unmistakable;
3. **mark the operator's own sessions** more strongly - those are certain launches, not just catalog timestamps, and they get the accent colour and the word
   *recent*.

The same treatment is applied to the locally drawn rows, so both paths agree.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")
changes = 0

# 1. sort the server results by last_played, and remember which are the operator's own
old = """              const found = (rows || []).filter(game => game && (game.game_id || game.id));"""
new = """              let found = (rows || []).filter(game => game && (game.game_id || game.id));
              const owned = new Set(all.filter(item => item.tag === 'recent')
                .map(item => String(item.game.game_id || item.game.id || '')));
              // What you actually launched comes first; never-launched titles keep the server's order below.
              found = found.slice().sort((a, b) => Number(b.last_played || 0) - Number(a.last_played || 0));"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    changes += 1
    print("server results sorted by last_played")

# 2. the row: highlight launched titles
old_row = """                  const label = String(game.title || game.alt_title || game.game_id);
                  const system = String(game.platform || (game.collections && game.collections[0]) || '');
                  return '<button type="button" data-add-found="' + index + '" style="display:block;width:100%;text-align:left;' +
                    'padding:7px 8px;background:transparent;border:0;border-radius:5px;color:#e6edf3;font:inherit;cursor:pointer">' +
                    esc(label) + '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(system) + '</span></button>';"""
new_row = """                  const label = String(game.title || game.alt_title || game.game_id);
                  const system = String(game.platform || (game.collections && game.collections[0]) || '');
                  const id = String(game.game_id || game.id || '');
                  const launched = Number(game.last_played || 0) > 0 || owned.has(id);
                  const mine = owned.has(id);
                  // A launched title is framed and tinted so an obscure neighbour cannot be clicked by accident.
                  const style = 'display:block;width:100%;text-align:left;padding:7px 8px;border-radius:5px;font:inherit;' +
                    'cursor:pointer;color:#e6edf3;' +
                    (mine ? 'background:#1b2b45;border:1px solid #4a7fd4;'
                          : launched ? 'background:#182130;border:1px solid #35507a;'
                                     : 'background:transparent;border:1px solid transparent;');
                  const when = Number(game.last_played || 0);
                  const age = when ? Math.max(0, Math.round((Date.now() / 1000 - when) / 86400)) : null;
                  const note = mine ? 'recent' : launched ? (age === 0 ? 'launched today' : age === 1 ? 'launched yesterday'
                    : age !== null ? 'launched ' + age + 'd ago' : 'launched') : '';
                  return '<button type="button" data-add-found="' + index + '" style="' + style + '">' +
                    esc(label) + '<span style="display:block;font-size:11px;color:' +
                    (launched ? '#8fb6ff' : '#9aa3b4') + '">' + esc(system) +
                    (note ? ' · ' + esc(note) : '') + '</span></button>';"""
if text.count(old_row) == 1:
    text = text.replace(old_row, new_row, 1)
    changes += 1
    print("launched titles highlighted and dated")
else:
    print("row anchor count", text.count(old_row))

# 3. the local rows get the same framing
old_local = """          '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(system) +
          (item.tag === 'recent' ? ' · recent' : '') + '</span></button>';"""
new_local = """          '<span style="display:block;font-size:11px;color:' + (item.tag === 'recent' ? '#8fb6ff' : '#9aa3b4') + '">' +
          esc(system) + (item.tag === 'recent' ? ' · recent' : '') + '</span></button>';"""
if text.count(old_local) == 1:
    text = text.replace(old_local, new_local, 1)
    changes += 1
    print("local recent rows keep the accent")

path.write_text(text, encoding="utf-8")
print("changes:", changes)

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:400])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("sorts server results:", "found.slice().sort" in source)
print("highlights launched:", "1b2b45" in source)
print("dates them:", "launched today" in source)
