"""Let boxes reach the sweep: the reticle catch-all was eating them.

The box branch sweeps three swings and rotates, which is the only thing proven to break a container. It was never running, because an **earlier** branch caught boxes first:

```python
if kind == "enemy" or kind == "object" or kind == "gate":     # containers are kind "object"
    ... actionables.append(...)                               # -> inside 12 units this fires
```

So a box within 12 units hit the **reticle catch-all**, which presses `b`+`a` **once** and moves on - one swing at one heading, which is exactly the pattern measured to destroy nothing. The box branch
below it, with the sweep, was unreachable.

Fix: the catch-all **excludes containers, capsules and traps**, so those fall through to the dedicated box branch that sweeps. Everything else actionable - enemies, doors, keys, switches, barriers - keeps
the catch-all, which is right for a single press.

This is why changing the distance threshold did nothing: the sweep was never being reached at any distance.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """                if candidate_class.startswith("TItem") or candidate_class.startswith("TObjItem"):
                    continue"""
new = """                if candidate_class.startswith("TItem") or candidate_class.startswith("TObjItem"):
                    continue
                # Containers, capsules and traps are NOT for the catch-all: they belong to the box branch, which
                # SWEEPS the aim cone. A single press here was preempting that and destroying nothing.
                if ("Container" in candidate_class or "Capsule" in candidate_class
                        or "Trap" in candidate_class):
                    continue"""
count = text.count(old)
print("catch-all anchor count:", count)
if count != 1:
    raise SystemExit("catch-all filter not unique - refusing to guess")
text = text.replace(old, new, 1)
print("boxes/traps now fall through to the sweeping branch")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
