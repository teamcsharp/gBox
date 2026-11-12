"""Add a "+" to the Streams panel that launches a recently played game into the PiP.

The operator's request: *"the right click option of PiP Mode allow me to start games through an addition indicator on this ... it'll offer me a drop down list of
my recently played games, allowing me to start and initialize games from PiP Mode. Basically the application is loading in pip mode before I'm able to even
start the game."*

The Streams panel is `pip-stream-picker.js`: `html()` draws the heading, the carousel of running cards and a status line, and `mount(root, io)` wires it up.
There is no way to start anything from it - every card is a **running** game.

**The addition**: a `+` button beside the carousel. Clicking it lists the most recently played games (from `GET /api/catalog`, sorted by `last_played`), and
choosing one calls `io.launch(game)` - which the host supplies. The panel stays a picker; the host decides how a launch is performed.

Three pieces:
  1. the `+` button in `html()`;
  2. the recent list and its dropdown in `mount()`, with Escape and outside-click dismissal reusing the existing menu helpers;
  3. a `launch` capability on the host side.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

# 1. the + button in the heading
old_heading = """    return '<div class="pip-stream-heading"><strong>Streams</strong><span>View another instance</span>' +
      (broadcast ? '<button type="button" data-stream-broadcast="auto" title="Let the broadcast follow the active game again">Broadcast: Auto</button>' : '') + '</div>' +"""
new_heading = """    return '<div class="pip-stream-heading"><strong>Streams</strong><span>View another instance</span>' +
      '<button type="button" data-stream-add title="Start a recent game into the PiP">+</button>' +
      (broadcast ? '<button type="button" data-stream-broadcast="auto" title="Let the broadcast follow the active game again">Broadcast: Auto</button>' : '') + '</div>' +"""

if "data-stream-add" in text:
    print("+ button already present")
else:
    if text.count(old_heading) != 1:
        raise SystemExit(f"heading anchor count {text.count(old_heading)}")
    text = text.replace(old_heading, new_heading, 1)
    print("+ button added to the heading")

# 2. the dropdown, inside mount(), using the existing valid()/menu helpers
anchor = "    let menuEl = null;"
addition = '''    let menuEl = null;
    // Recently played games, for the + button: launch one into the PiP without leaving it.
    let addMenu = null;
    function dismissAdd() { if (addMenu) { addMenu.remove(); addMenu = null; } }
    async function openAdd(event) {
      if (!valid() || typeof io.launch !== 'function') return;
      const button = event.target.closest?.('[data-stream-add]');
      if (!button) return;
      event.preventDefault(); event.stopPropagation();
      dismissAdd(); dismissMenu();
      const rect = button.getBoundingClientRect();
      addMenu = document.createElement('div');
      addMenu.className = 'pip-stream-menu pip-stream-add';
      addMenu.setAttribute('role', 'menu');
      addMenu.style.cssText = 'position:fixed;z-index:95;min-width:230px;max-width:340px;padding:5px;' +
        'background:#1b1f2a;border:1px solid #3a4152;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.55);' +
        'left:' + Math.round(rect.left) + 'px;top:' + Math.round(rect.bottom + 6) + 'px;max-height:60vh;overflow:auto;';
      addMenu.innerHTML = '<div style="padding:6px 8px;font-size:11px;color:#9aa3b4">Recently played</div>' +
        '<div style="padding:6px 8px;font-size:12px;color:#9aa3b4">Loading…</div>';
      document.body.appendChild(addMenu);
      let games = [];
      try {
        const answer = await io.api ? await io.api('/api/catalog') : null;
        const rows = Array.isArray(answer) ? answer : (answer?.items || answer?.games || answer?.entries || []);
        games = (rows || []).filter(row => row && (row.game_id || row.id))
          .sort((a, b) => Number(b.last_played || 0) - Number(a.last_played || 0))
          .slice(0, 12);
      } catch { games = []; }
      if (!addMenu) return;
      addMenu.innerHTML = '<div style="padding:6px 8px;font-size:11px;color:#9aa3b4">Recently played</div>' +
        (games.length ? games.map((game, index) =>
          '<button type="button" role="menuitem" data-add-game="' + index + '" style="display:block;width:100%;text-align:left;padding:6px 8px;' +
          'background:transparent;border:0;border-radius:5px;color:#e6edf3;font:inherit;cursor:pointer">' +
          esc(game.title || game.alt_title || game.game_id) +
          '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(game.platform || '') +
          (game.last_played ? ' · played' : '') + '</span></button>').join('')
          : '<div style="padding:6px 8px;font-size:12px;color:#9aa3b4">No games in the catalog</div>');
      addMenu.querySelectorAll('[data-add-game]').forEach(buttonEl => {
        buttonEl.addEventListener('click', async () => {
          const game = games[Number(buttonEl.dataset.addGame)];
          dismissAdd();
          if (!game) return;
          try { await io.launch(game); if (valid()) message('Starting ' + (game.title || game.game_id) + '…'); }
          catch (error) { if (valid()) message('Could not start it: ' + String(error?.message || error)); }
        });
      });
    }
    function onAddAway(event) { if (!addMenu || !addMenu.contains(event.target)) dismissAdd(); }
    document.addEventListener('pointerdown', onAddAway, true);'''

if "openAdd" in text:
    print("dropdown already present")
else:
    if text.count(anchor) != 1:
        raise SystemExit(f"menuEl anchor count {text.count(anchor)}")
    text = text.replace(anchor, addition, 1)
    print("recent-games dropdown added")

path.write_text(text, encoding="utf-8")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])
