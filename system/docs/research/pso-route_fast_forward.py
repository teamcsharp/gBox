"""Route the fast-forward control: the RPC can turn it off but nothing can turn it on.

`tools.session_rpc` exposes:

```python
if op == "normal_speed":
    return rewind.set_fast_forward(sid, ad, on=False, recover=True)
```

and `info` reports `fast_forward: rewind.fast_forward_status(...)`. There is **no "on"**. The capability itself is complete - `DolphinWinAdapter.fast_forward(on)` holds the
"Disable Emulation Speed Limit" lane key with `hidden_ok=True`, which the adapter's own comment says needs **no native-window focus** - so the only gap is routing.

This adds one op beside `normal_speed`, delegating to the same function, with `on` defaulting to true:

```python
if op == "fast_forward":
    return rewind.set_fast_forward(sid, ad, on=bool(args.get("on", True)))
```

It is placed after `normal_speed` so the existing behaviour is untouched, and it goes through `rewind.set_fast_forward` exactly as the off-switch does - the same
recovery and tracking, not a second implementation.
"""
import pathlib
import py_compile

path = pathlib.Path(r"C:\_tools\gBox\system\gbox\tools.py")
text = path.read_text(encoding="utf-8")

if 'if op == "fast_forward":' in text:
    print("already routed")
else:
    anchor = """    if op == "normal_speed":
        return rewind.set_fast_forward(sid, ad, on=False, recover=True)"""
    addition = anchor + """
    if op == "fast_forward":                           # the speed-run control: hold the no-speed-limit hotkey
        return rewind.set_fast_forward(sid, ad, on=bool(args.get("on", True)))"""
    count = text.count(anchor)
    print("anchor count:", count)
    if count != 1:
        raise SystemExit("normal_speed anchor not unique")
    text = text.replace(anchor, addition, 1)
    path.write_text(text, encoding="utf-8")
    print("fast_forward op added")

py_compile.compile(str(path), doraise=True)
print("tools.py compiles")

lines = pathlib.Path(r"C:\_tools\gBox\system\gbox\tools.py").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if 'op == "fast_forward"' in line or 'op == "normal_speed"' in line:
        print(f"{index + 1}: {line.strip()[:110]}")
