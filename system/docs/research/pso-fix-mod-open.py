"""Fix the mod click handler: `root` is undefined, so no mod could open anything.

The operator's screenshot shows the toast exactly as designed - *"mod failed: root is not defined"* - which means the delegated handler caught the exception
(the error surface works) and the bug is in the one line that opens a panel:

```js
if (mod.open) { root.open(mod.open, 'gbox-mod-' + mod.id, 'width=960,height=760'); return; }
```

`root` came from a helper's closure when this line was written; in the compact bar's scope it does not exist. `window.open` is what opens a pop-up window,
and it is what the Map button needs to show the live map viewer.

Everything else in the handler is correct - the RPC mods fail only because the worker refuses input, not because of this.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

old = "            if (mod.open) { root.open(mod.open, 'gbox-mod-' + mod.id, 'width=960,height=760'); return; }"
new = ("            if (mod.open) {\n"
       "              const popup = window.open(mod.open, 'gbox-mod-' + mod.id, 'width=1000,height=760');\n"
       "              if (!popup) toast('The pop-up was blocked - allow pop-ups for gBox.');\n"
       "              return;\n"
       "            }")

count = text.count(old)
print("anchor count:", count)
if count == 1:
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("window.open replaces the undefined root.open")
else:
    for line in text.splitlines():
        if "mod.open" in line:
            print("  found:", line.strip()[:120])
