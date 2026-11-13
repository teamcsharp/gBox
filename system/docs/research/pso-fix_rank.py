"""Only rank interactables that are actually reachable.

The bug the operator watched in real time:

```
interact.sort()  ->  [(0, 698.6, 'TObjWarpBossMulti'),   # a warp, ranked first regardless of distance
                      (1, 124.5, 'TLazerFenceSw'),       # the switch, ignored
                      ...]
interact[0] = the warp at 698.6
idist <= 400 ?  False  ->  neither branch runs  ->  the loop does NOTHING
```

Ranking put `Warp` ahead of everything, so a level exit **698 units away** became the chosen target, failed the range
gate, and the iteration fell through - while a fence switch **124 units away** stood untouched. That is precisely
"walks right up to switches and you're not flipping them".

Fix: filter to what is reachable **before** ranking. A warp only outranks a switch when both are within 400 units.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = (
    '            idist = math.hypot(float(candidate.get("x") or 0) - x, float(candidate.get("z") or 0) - z)\n'
    '            interact.append((rank, idist, candidate))'
)
NEW = (
    '            idist = math.hypot(float(candidate.get("x") or 0) - x, float(candidate.get("z") or 0) - z)\n'
    '            # ONLY RANK WHAT IS REACHABLE. Ranking a warp first regardless of distance made a warp 698 units away\n'
    '            # the chosen target, which then failed the range gate so the loop did NOTHING - while a switch 124\n'
    '            # units away stood untouched. That is the "walks right up to switches and does not flip them" fault.\n'
    '            if idist <= 400.0:\n'
    '                interact.append((rank, idist, candidate))'
)
count = text.count(OLD)
print("anchor count:", count)
if count != 1:
    raise SystemExit("interaction append not unique")
text = text.replace(OLD, NEW, 1)
ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - only reachable interactables are ranked now")
