"""Fix the PSO toolbar painter: hoist it and detect PSO from the session title.

Two defects in the first pass:
  * `paintPso` was declared as a block-scoped `const` inside the toolbar-construction branch, so the later update handler could not see it and
    `typeof paintPso` would have thrown a ReferenceError rather than returning "undefined";
  * it read `COMPACT.gameId`, which does not exist - the controller's state is `{on, aspect, returnMode, sid}` and the game's identity lives in
    `compactTitle` (set from `sessionTitle(session)`).

It is now a hoisted function that tests the title for "Phantasy Star" (or the PSO title string), so it works whether the game arrives by id or by name.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

old = """      const paintPso = gameId => {
        const pso = String(gameId || '') === PSO_GAME;
        const group = controls.querySelector('[data-pso-actions]');"""
new = """      window.gboxPaintPso = () => {
        const title = String(compactTitle || '');
        const pso = /phantasy\\s*star|episode\\s*i\\s*&\\s*ii/i.test(title);
        const group = controls.querySelector('[data-pso-actions]');"""
if text.count(old) != 1:
    raise SystemExit(f"painter block count {text.count(old)}")
text = text.replace(old, new, 1)

old_call = """      paintPso(COMPACT && COMPACT.gameId);
      controls.dataset.psoPaint = 'ready';"""
new_call = """      window.gboxPaintPso();
      controls.dataset.psoPaint = 'ready';"""
if text.count(old_call) == 1:
    text = text.replace(old_call, new_call, 1)

old_update = "    if (controls && controls.dataset.psoPaint === 'ready' && typeof paintPso === 'function') paintPso(COMPACT && COMPACT.gameId);"
new_update = "    if (controls && controls.dataset.psoPaint === 'ready' && typeof window.gboxPaintPso === 'function') window.gboxPaintPso();"
if text.count(old_update) == 1:
    text = text.replace(old_update, new_update, 1)

# also repaint when the title is written, which is where a new game's identity arrives
old_title = "if (controls) { controls.querySelector('.compact-title').textContent = compactTitle;"
new_title = "if (controls) { controls.querySelector('.compact-title').textContent = compactTitle; if (typeof window.gboxPaintPso === 'function') window.gboxPaintPso();"
if text.count(old_title) == 1:
    text = text.replace(old_title, new_title, 1)

path.write_text(text, encoding="utf-8")
print("paintPso hoisted to window.gboxPaintPso and driven by the session title")
