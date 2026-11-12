"""The panel was hidden by the compact-mode rule: `body.gbox-compact > :not(...)` sets `display:none !important`.

The rule at index.html:1312 is a long chain of `:not(...)` selectors naming every element allowed to show while the PiP is active:

```
body.gbox-compact > :not(.pso-review-window):not(.game-analysis): … :not(#pipmenu):not(.coach-menu)
  :not(.coach-sub):not(.merc-weapon-menu):not(.merc-round-menu):not(.flash-shortcut-menu) …
```

Every other direct child of `<body>` is `display:none !important`. The context menus are all listed - `#pipmenu`, `.coach-menu`,
`.merc-weapon-menu`, `.flash-shortcut-menu`, `.ring-kind-menu` - because each one had to be. **`.pip-stream-menu` is not**, and the add-game panel is
appended to `document.body` with that class.

So the panel was created, filled with a hundred rows, appended, and set to `display:none !important` by a CSS rule half a file away. That is why every log line
said the work succeeded and nothing appeared, and why raising the GPU cover changed nothing - the surface was never the obstacle.

The fix is the one every other menu got: **add `:not(.pip-stream-menu)` to the allow-list.**
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

if ":not(.pip-stream-menu)" in text:
    print("already allowed")
else:
    anchor = ":not(#pipmenu)"
    count = text.count(anchor)
    print("anchor count:", count)
    if count != 1:
        raise SystemExit("pipmenu anchor not unique")
    text = text.replace(anchor, ":not(#pipmenu):not(.pip-stream-menu)", 1)
    path.write_text(text, encoding="utf-8")
    print(".pip-stream-menu added to the compact allow-list")

lines = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if "body.gbox-compact > :not" in line:
        print(f"{index + 1}: …{line[line.find(':not(#pipmenu)'):][:120]}")
        break
