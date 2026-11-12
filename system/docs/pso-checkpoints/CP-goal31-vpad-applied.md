# Round 31: the vpad fix applied cleanly - and the layer beneath it

## Done properly this time

`_vpad_works` now trusts a pad that exists on a slot instead of requiring the emulator to react to a probe press (which cannot be counted on at the title
screen, where every launch begins). Applied with the discipline round 30 lacked:

* **timestamped backup** first: `adapters.py.bak-211734` (332 KB);
* the method located by its **exact class-level signature** and ended at the next `    def ` - 27 lines replaced, nothing else touched;
* **`py_compile` OK**, **import OK**, `DolphinWinAdapter._vpad_works` verified as the new source;
* the restore command printed and the backup still on disk.

## And it is not enough, because a layer beneath it is failing

A fresh launch after the restart still writes the keyboard INI, and input still fails:

```
RuntimeError: the game window isn't open
```

That is the **keyboard** branch failing - a headless session has no window. So `send_input` is not reaching `vpad.apply`, which means **`self.vpad` is None**:
`_setup_vpad` returned None at launch.

But every ingredient checks out **at rest**:

| check | result |
|---|---|
| `vpad_win.available()` | **True** |
| `vpad_win.VGamepad()` | **creates, detects a slot** |
| `_want_vpad` gate | PSO's `GPO*` disc id satisfies it |
| `pad_bind` | pass-through (verified source) |

So the failure is **inside `_setup_vpad` at launch time** - either `_want_vpad` returning false in that moment, `VGamepad()` throwing (the transient ViGEm
contention its own comment describes), or `_detect_slot()` returning None and the three retries giving up.

## Where I stopped, and why

I had an instrumentation patch ready to log each of those three points. **I did not run it.** I broke this file twice today with rushed edits, it is the
adapter for every emulator, and a diagnostics patch with nested f-strings and escaped quotes is exactly the kind of change that fails at import. **The state I
leave is safe and verified:**

```
adapters.py compiles ✓  imports ✓  _vpad_works is the patched source ✓
backup on disk: adapters.py.bak-211734
health: True   worker: 1   queue: 0
```

## What is established, and what is left

**Established:** the bot is complete and verified (45 checks across perception, movement, decision, batched input); the server launches PSO in 9-21 seconds
every time; the app *does* build a virtual pad and bind it when `_setup_vpad` succeeds; and the input path has three gates - `_want_vpad`, `VGamepad()`, and
`_detect_slot()` - any of which explains this failure from the outside but not which one it is.

**Left:** one log line in `_setup_vpad` naming the gate that fails. That is a five-minute change with the backup discipline now in place, and it is the last
unknown in the road to an agent-driven session.

**Meanwhile the operator's own launches remain the route that works end to end** - operator-owned sessions accept input - and their client is still stalling at
`state_transfer`, which a client reload or app restart clears.
