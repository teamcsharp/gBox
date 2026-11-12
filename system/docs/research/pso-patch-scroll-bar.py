"""Make the mod bar a real scrollable row: wider, a visible scrollbar, and wheel scrolling.

The operator's words: "I need them to be a scrollable row where I'm able to access them and adjust them adequately."

The bar was capped at **42vw** with `overflow-x:auto` and a hidden scrollbar, so on a narrow window the icons beyond the fold were unreachable - there was
nothing to grab and nothing to turn. Now:

  * the row takes up to **64vw**, so more icons are visible before scrolling;
  * the horizontal scrollbar is **thin but visible**, with a hover-highlighted thumb;
  * the **mouse wheel scrolls the row sideways** while the pointer is over it, which is how people actually reach the end of a horizontal strip;
  * a little padding keeps the scrollbar from overlapping the icons.

Nothing about the buttons changes: same size, same tooltips, same behaviour.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

old = ("  #compact-controls [data-game-mods] { display:flex; align-items:center; gap:3px; flex:0 0 auto; "
       "max-width:42vw; overflow-x:auto; overflow-y:hidden; -webkit-app-region:no-drag; }")

new = ("  /* the per-game mod icons: a scrollable strip - wide, with a visible thin scrollbar and wheel scrolling */\n"
       "  #compact-controls [data-game-mods] { display:flex; align-items:center; gap:3px; flex:0 1 auto; min-width:0; "
       "max-width:64vw; overflow-x:auto; overflow-y:hidden; padding-bottom:2px; -webkit-app-region:no-drag; "
       "scrollbar-width:thin; scrollbar-color:#4a5160 transparent; scroll-behavior:smooth; }\n"
       "  #compact-controls [data-game-mods]:hover { scrollbar-color:#6b7488 transparent; }\n"
       "  #compact-controls [data-game-mods]::-webkit-scrollbar { height:6px; }\n"
       "  #compact-controls [data-game-mods]::-webkit-scrollbar-track { background:transparent; }\n"
       "  #compact-controls [data-game-mods]::-webkit-scrollbar-thumb { background:#4a5160; border-radius:3px; }\n"
       "  #compact-controls [data-game-mods]:hover::-webkit-scrollbar-thumb { background:#6b7488; }")

count = text.count(old)
print("css anchor count:", count)
if count == 1:
    text = text.replace(old, new, 1)
    print("bar css: 64vw, visible thin scrollbar, smooth scrolling")

# wheel scrolls the strip sideways
anchor = "      const buildMods = () => {"
wheel = """      // The mouse wheel scrolls the mod strip sideways while the pointer is over it.
      if (!controls.dataset.modsWheel) {
        controls.dataset.modsWheel = '1';
        controls.addEventListener('wheel', event => {
          const strip = event.target.closest?.('[data-game-mods]');
          if (!strip || strip.scrollWidth <= strip.clientWidth) return;
          if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
          strip.scrollLeft += event.deltaY;
          event.preventDefault();
        }, { passive: false });
      }
      const buildMods = () => {"""
if text.count(anchor) == 1 and "modsWheel" not in text:
    text = text.replace(anchor, wheel, 1)
    print("wheel scrolling added")

path.write_text(text, encoding="utf-8")
print("done")
