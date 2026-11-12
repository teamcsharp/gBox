"""Make the operator's pad detection work the moment a real pad enumerates, and never return the virtual one.

`operator_slot` ends with `return _LAST_SLOT if _LAST_SLOT is not None else 0`, and after my exclusion patch a slot that answers but has not moved yet would be skipped
entirely - so with the virtual pad on slot 0 the function could return **0**, which is the excluded slot, and `watch_xinput` would then refuse to mirror anything. That
would silence the operator's controller relay: their presses would never reach the game.

Two changes, both small:

* the scan accepts a slot that **answers** (XInput reports it at all), not only one that is already moving - a pad at rest is still the operator's pad, and the mirror
  simply has nothing to send until they touch it;
* the fallback never returns the excluded slot; `-1` means "no operator pad", and `watch_xinput` already treats the excluded slot as "not mirroring".

So: a real controller is picked up as soon as Windows exposes it to XInput, and the virtual pad can never be mistaken for one.
"""
import pathlib
import py_compile

path = pathlib.Path(r"C:\_tools\gBox\system\gbox\padstate.py")
text = path.read_text(encoding="utf-8")
py_compile.compile(str(path), doraise=True)
print("compiles BEFORE")

if "no operator pad" in text:
    print("already patched")
    raise SystemExit(0)

old = """    for _ in range(max(1, samples)):
        for s in range(4):
            if s == exclude:
                continue
            if read(get_state, s, st) is None:
                continue
            g = st.gamepad
            if g.buttons or abs(g.lx) > 7849 or abs(g.ly) > 7849 or abs(g.rx) > 7849 or abs(g.ry) > 7849:
                _LAST_SLOT = s
                return s
        time.sleep(gap)
    return _LAST_SLOT if _LAST_SLOT is not None else 0"""
new = """    for _ in range(max(1, samples)):
        for s in range(4):
            if s == exclude:
                continue
            if read(get_state, s, st) is None:
                continue
            g = st.gamepad
            if g.buttons or abs(g.lx) > 7849 or abs(g.ly) > 7849 or abs(g.rx) > 7849 or abs(g.ry) > 7849:
                _LAST_SLOT = s
                return s
        time.sleep(gap)
    # Nothing moved, but a slot that answers is still a pad this PC has (a controller at rest). Prefer it over the
    # fallback to 0, which is the virtual pad this fix exists to exclude - otherwise the operator's relay goes silent
    # the moment their controller is plugged in but not yet touched.
    for s in range(4):
        if s == exclude:
            continue
        if read(get_state, s, st) is not None:
            _LAST_SLOT = s
            return s
    return -1                      # no operator pad on this PC: nothing to mirror"""

count = text.count(old)
print("anchor count:", count)
if count != 1:
    raise SystemExit("operator_slot tail anchor not unique")

text = text.replace(old, new, 1)

# watch_xinput: -1 means no operator pad
old_slot = """    if exclude is not None and slot == exclude:
        print(f"padstate: the only pad on XInput slot {slot} is this session's virtual pad - not mirroring it", flush=True)
        return"""
new_slot = """    if slot < 0 or (exclude is not None and slot == exclude):
        print(f"padstate: no operator pad to mirror (virtual pad on slot {exclude}) - the bot drives alone", flush=True)
        return"""
if text.count(old_slot) == 1:
    text = text.replace(old_slot, new_slot, 1)
    print("watch_xinput guard updated")
else:
    print("watch_xinput guard count:", text.count(old_slot))

path.write_text(text, encoding="utf-8")
py_compile.compile(str(path), doraise=True)
print("compiles AFTER")
