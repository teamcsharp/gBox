"""Make the PiP's context menu visible over the game.

The report: "The right click menu needs to show on top of the gameplay. Currently it's being put behind it for some reason."

The cause is structural rather than a CSS mistake. `pipMenu` appends a normal DOM div (`#pipmenu`, z-index 70), but the game in compact mode is drawn by
`#gpu-game` - a GPU surface (`web/viz/gpu-game-surface.js`) that composites **above** the page. No z-index can put a DOM element over a surface that is
not in the DOM's stacking context, which is exactly why the menu appeared to slide behind the picture.

The workable fix is to take the surface down while a menu is up and restore it when the menu closes: a context menu is transient, and the operator needs
to read it more than they need the picture for those seconds.

A single helper does the work so every PiP menu can use it, and `pipMenu`/`closePipMenu` are wired to it. The previous display value is remembered per
element, so nothing is forced to `block` that was not.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

helper = """// The PiP's game is a GPU surface above the page, so a DOM menu cannot be drawn over it no matter its z-index. Take the surface down while a menu is
// open and restore it after: a context menu is transient, and reading it matters more than the picture for those seconds.
window.gboxPipCover = (on) => {
  for (const selector of ['#gpu-game', '#compact-stream']) {
    const surface = document.querySelector(selector);
    if (!surface) continue;
    if (on) {
      if (surface.dataset.pipCover === undefined) surface.dataset.pipCover = surface.style.display || '';
      surface.style.visibility = 'hidden';
    } else if (surface.dataset.pipCover !== undefined) {
      surface.style.visibility = '';
      delete surface.dataset.pipCover;
    }
  }
};
function pipMenu(x, y) {"""

if "window.gboxPipCover" not in text:
    if text.count("function pipMenu(x, y) {") != 1:
        raise SystemExit("pipMenu anchor count wrong")
    text = text.replace("function pipMenu(x, y) {", helper, 1)
    print("helper added")

# raise the cover as soon as the menu opens
old_open = """  m.modifiers?.stop(); m.modifiers = null;
  m.streamPicker?.stop(); m.streamPicker = null;
  const opening = m.opening = {origin:S?.apiUrl};"""
new_open = """  window.gboxPipCover?.(true);
  m.modifiers?.stop(); m.modifiers = null;
  m.streamPicker?.stop(); m.streamPicker = null;
  const opening = m.opening = {origin:S?.apiUrl};"""
if text.count(old_open) == 1:
    text = text.replace(old_open, new_open, 1)
    print("cover raised when the menu opens")

# and drop it when the menu closes
index = text.find("function closePipMenu")
if index < 0:
    raise SystemExit("closePipMenu not found")
brace = text.find("{", index)
insert = "\n  window.gboxPipCover?.(false);"
if text[brace + 1:brace + 40].find("gboxPipCover") < 0:
    text = text[:brace + 1] + insert + text[brace + 1:]
    print("cover dropped when the menu closes")

path.write_text(text, encoding="utf-8")
print("done")
