"""Remove the garbage line the circling patch inserted.

An editing slip left this in `endless.py`:

```
_zs = [row[2] for row in LIVENING_SAFE(_xs, _zs=None) if False] if False else [row[2] for row in LIVENESS["recent"]]
```

`LIVENING_SAFE` does not exist; it was debris from a rewrite. The intent was a plain extraction of the z values from the
same window the x values come from.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
lines = ENDLESS.read_text(encoding="utf-8").splitlines()

fixed = 0
for index, line in enumerate(lines):
    if "LIVENING_SAFE" in line:
        indent = len(line) - len(line.lstrip())
        lines[index] = " " * indent + '_zs = [row[2] for row in LIVENESS["recent"]]'
        fixed += 1
        print("fixed line", index + 1)

if not fixed:
    raise SystemExit("no bad line found")

ENDLESS.write_text("\n".join(lines) + "\n", encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")

for index, line in enumerate(lines):
    if "_zs = " in line and "LIVENESS" in line:
        print("verify:", index + 1, line.strip())
