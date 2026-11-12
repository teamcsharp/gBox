"""Turn off text selection everywhere except where text is actually typed.

The operator's screenshot shows the Streams panel with its text highlighted blue - a drag that was meant to click text selected it instead. That is the whole
complaint: selecting text in an application whose text is not content is noise, and it interferes with clicking and dragging.

The app already disables selection in three places for specific reasons (`#chathead` on drag, `body.chatresizing *`, `#remote-pip img`), which shows the intent
was there but never general.

So the **global reset** carries it:

```css
* { box-sizing:border-box; -webkit-user-select:none; user-select:none; }
```

and the few places where selection is legitimate opt back in:

```css
input, textarea, select, [contenteditable=""], [contenteditable="true"], .selectable {
  -webkit-user-select:text; user-select:text;
}
```

The search box in the new panel, the chat composer, and any future text field keep working normally; everything else stops highlighting on drag.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

old = "  * { box-sizing:border-box; }"
new = """  * { box-sizing:border-box; -webkit-user-select:none; user-select:none; }
  /* text is legitimate only where it is typed */
  input, textarea, select, [contenteditable=""], [contenteditable="true"], .selectable,
  input *, textarea * { -webkit-user-select:text; user-select:text; }"""

count = text.count(old)
print("anchor count:", count)
if count == 1:
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("selection disabled globally, re-enabled for inputs")
else:
    for index, line in enumerate(text.splitlines()):
        if "box-sizing:border-box" in line:
            print(f"  line {index + 1}: {line.strip()[:110]}")

lines = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if "-webkit-user-select:none" in line or "user-select:text" in line:
        print(f"{index + 1}: {line.strip()[:130]}")
