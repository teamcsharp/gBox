"""Wait for the warp to finish before judging it.

The last run showed the warp working and the check giving up too early:

```
[18:15:52] in the city (31 entities) - warping to a field
[18:16:00] after the warp: 1 entities, 0 gates        <- still loading, not a failure
```

`1 entity` is a **transition**: the old area's table is torn down before the new one is built. A single check five seconds later therefore reports failure for a warp that is
in progress. This polls instead - up to 25 s, every 2 s - and only concludes failure if the count never rises.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """    time.sleep(1.5)
    tap(pad, "a")
    time.sleep(5)
    after = state(pad)
    count = len(after.get("entities") or [])
    gates = [e for e in (after.get("entities") or []) if str(e.get("kind")) == "gate"]
    log(f"after the warp: {count} entities, {len(gates)} gates")
    return count > 60"""

new = """    time.sleep(1.5)
    tap(pad, "a")

    # A warp tears the old area's entity table down before the new one is built, so a single check right after the
    # press sees "1 entity" for a warp that is working. Poll until the field exists.
    for attempt in range(13):
        time.sleep(2)
        after = state(pad)
        entities = after.get("entities") or []
        count = len(entities)
        gates = [e for e in entities if str(e.get("kind")) == "gate"]
        log(f"  warp +{(attempt + 1) * 2}s: {count} entities, {len(gates)} gates")
        if count > 60:
            return True
    return False"""

if text.count(old) != 1:
    raise SystemExit("post-warp anchor count: %d" % text.count(old))
ENDLESS.write_text(text.replace(old, new, 1), encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("endless.py compiles AFTER - the warp is now polled, not sampled once")
