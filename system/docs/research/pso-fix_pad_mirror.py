"""Stop the operator's-pad mirror from watching gBox's own virtual pad.

The chain, read out of the source and matching every measurement:

* `padstate.watch_xinput` mirrors "the operator's pad" and calls `pad_lease(sid, keys)` whenever it sees a press or a moved stick;
* it picks the slot with `operator_slot`, which **falls back to slot 0** (`return _LAST_SLOT if _LAST_SLOT is not None else 0`) and, once `_LAST_SLOT` is set,
  returns it for as long as that slot answers - and a virtual pad **always** answers;
* `pad_bind` puts the session's virtual pad on slot 0 (`Device = XInput/0/Gamepad`, `Always Connected = True`);

so the mirror watches **gBox's own pad**. When the bot presses through `/api/sessions/{sid}/input` -> `_pump` -> `pad_sender.send` -> `ad.send_input` -> `vpad.apply`, slot 0
changes, `watch_xinput` reads that as the operator grabbing the pad, `pad_lease` claims the takeover lease, and `pad_takeover.inputs` then **drops the bot's own events**:

```python
if lz.active(now):
    return [e for e in events if not bot_event(e)]     # the bot's presses, discarded
```

That is exactly the measured asymmetry - `/input` never moves the character, while `session_op send_input` (which bypasses `pad_takeover` entirely) moves it 82.5 units - and
it is why the app's own autoplay cannot drive the game.

The fix: record the session's virtual-pad slot, never let `operator_slot` pick it, and do not mirror at all when the only pad answering is our own. Nothing else changes; when a
real controller is present it is still detected and still mirrored.

Written with Python so the file is UTF-8 (a PowerShell redirect once filled this tree with null bytes).
"""
import pathlib
import py_compile

padstate = pathlib.Path(r"C:\_tools\gBox\system\gbox\padstate.py")
tools = pathlib.Path(r"C:\_tools\gBox\system\gbox\tools.py")

for path in (padstate, tools):
    py_compile.compile(str(path), doraise=True)
print("both files compile BEFORE")

# ---- padstate: a per-session record of the virtual pad's slot ---------------------------------------------------
text = padstate.read_text(encoding="utf-8")
if "VPAD_SLOT" in text:
    print("padstate already patched")
else:
    anchor = "def operator_slot(get_state, st, *, samples: int = 12, gap: float = 0.05, read=None) -> int:"
    if text.count(anchor) != 1:
        raise SystemExit("operator_slot anchor not unique")
    text = text.replace(
        anchor,
        "# The slot this session's own virtual pad occupies. It must never be mistaken for the operator's pad: the\n"
        "# mirror would read gBox's own presses as the operator grabbing the pad, claim the takeover lease, and then\n"
        "# pad_takeover drops the bot's events - the bot taking the pad from itself.\n"
        "VPAD_SLOT: dict = {}\n\n\n"
        "def operator_slot(get_state, st, *, samples: int = 12, gap: float = 0.05, read=None,\n"
        "                  exclude: int | None = None) -> int:",
        1)

    # the remembered slot must not be the excluded one
    old_remembered = "    if _LAST_SLOT is not None and read(get_state, _LAST_SLOT, st) is not None:\n        return _LAST_SLOT"
    new_remembered = ("    if (_LAST_SLOT is not None and _LAST_SLOT != exclude\n"
                      "            and read(get_state, _LAST_SLOT, st) is not None):\n"
                      "        return _LAST_SLOT")
    if text.count(old_remembered) != 1:
        raise SystemExit("remembered-slot anchor not unique")
    text = text.replace(old_remembered, new_remembered, 1)

    # and the scan must skip it
    old_scan = """    for _ in range(max(1, samples)):
        for s in range(4):
            if read(get_state, s, st) is None:
                continue"""
    new_scan = """    for _ in range(max(1, samples)):
        for s in range(4):
            if s == exclude:
                continue
            if read(get_state, s, st) is None:
                continue"""
    if text.count(old_scan) != 1:
        raise SystemExit("scan anchor not unique")
    text = text.replace(old_scan, new_scan, 1)

    padstate.write_text(text, encoding="utf-8")
    py_compile.compile(str(padstate), doraise=True)
    print("padstate.py patched and compiles")

# ---- watch_xinput: pass the exclusion, and refuse to mirror our own pad ------------------------------------------
text = padstate.read_text(encoding="utf-8")
old_slot = "    slot = operator_slot(get_state, st)          # the operator's pad: not always XInput slot 0"
new_slot = ("    exclude = VPAD_SLOT.get(sid)                 # gBox's own pad is not the operator's\n"
            "    slot = operator_slot(get_state, st, exclude=exclude)   # the operator's pad: not always XInput slot 0\n"
            "    if exclude is not None and slot == exclude:\n"
            "        print(f\"padstate: the only pad on XInput slot {slot} is this session's virtual pad - not mirroring it\", flush=True)\n"
            "        return")
if text.count(old_slot) == 1:
    text = text.replace(old_slot, new_slot, 1)
    padstate.write_text(text, encoding="utf-8")
    py_compile.compile(str(padstate), doraise=True)
    print("watch_xinput patched and compiles")
else:
    print("watch_xinput anchor count:", text.count(old_slot))

# ---- tools.py: record the slot before the mirror starts ---------------------------------------------------------
text = tools.read_text(encoding="utf-8")
old_relay = "        padstate.RELAY[sid] = getattr(ad, \"vpad\", None) is not None"
new_relay = ("        padstate.RELAY[sid] = getattr(ad, \"vpad\", None) is not None\n"
             "        # the mirror must never watch the session's own virtual pad: its presses are not the operator's\n"
             "        padstate.VPAD_SLOT[sid] = getattr(getattr(ad, \"vpad\", None), \"slot\", None)")
if text.count(old_relay) == 1:
    text = text.replace(old_relay, new_relay, 1)
    tools.write_text(text, encoding="utf-8")
    py_compile.compile(str(tools), doraise=True)
    print("tools.py patched and compiles")
else:
    print("RELAY anchor count:", text.count(old_relay))
