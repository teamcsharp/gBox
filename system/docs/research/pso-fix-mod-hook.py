"""Replace the last dormant reference to the old painter with the manifest builder.

An earlier patch called `window.gboxPaintPso()` when the compact title is written; that function was removed when the manifest took over, so the call
is dead. `typeof` on a missing window property is safe, but the icons should rebuild when the title changes, which is exactly where a new game's
identity arrives.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

count = 0
for old, new in (
    ("if (typeof window.gboxPaintPso === 'function') window.gboxPaintPso();",
     "if (typeof window.gboxBuildMods === 'function') window.gboxBuildMods();"),
):
    count += text.count(old)
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print(f"replaced {count} dormant painter call(s) with the manifest builder")
