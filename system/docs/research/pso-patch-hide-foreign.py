"""Show only what belongs to the game being played: hide the Resident Evil controls during PSO.

The operator's report: the gBox menu bar offers **Flash → Hand (unavailable), Incendiary (unavailable)** while playing Phantasy Star Online. Those are Resident
Evil 4's flashbang and grenade-ring controls, bound into the compact bar for every game, and PSO has neither - so the app advertises options that cannot work.

The gate uses the game-aware manifest already in place: `gboxGameMods.modsFor(title)` returns PSO's 21 entries when PSO is running and nothing otherwise, so
"this game has mods of its own" is exactly "this game is not RE". When it returns entries, the RE-only controls are hidden:

  * `[data-flash]` - the flashbang button, and its `.flash-shortcut-menu`;
  * `[data-ring]` / `.ring-control` - the grenade ring and its type chooser.

Nothing is removed: they are hidden with `hidden` and restored the moment the title stops being PSO, so switching games in the same window still works.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

anchor = """      const buildMods = () => {
        const host = controls.querySelector('[data-game-mods]');
        if (!host || !window.gboxGameMods) return [];
        const mods = window.gboxGameMods.modsFor(compactTitle);"""

replacement = """      // Resident Evil's flashbang and grenade ring do not exist in PSO, so they are hidden while a game with its own mods (PSO) is running.
      const hideForeignControls = (foreign) => {
        for (const selector of ['[data-flash]', '[data-ring]', '.flash-shortcut-menu', '.ring-control']) {
          controls.querySelectorAll(selector).forEach(element => { element.hidden = !!foreign; });
        }
      };
      const buildMods = () => {
        const host = controls.querySelector('[data-game-mods]');
        if (!host || !window.gboxGameMods) return [];
        const mods = window.gboxGameMods.modsFor(compactTitle);
        hideForeignControls(mods.length > 0);"""

if anchor in text:
    text = text.replace(anchor, replacement, 1)
    path.write_text(text, encoding="utf-8")
    print("buildMods now hides RE-only controls when the game has its own mods")
else:
    print("anchor not found")
