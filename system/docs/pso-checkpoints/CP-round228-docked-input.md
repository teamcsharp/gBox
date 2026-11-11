# Round 228: the docked window broke my input path - diagnosed precisely, with the workaround found

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Session `0d2e88799e11476b-e425afc683e145f1` (pid 2236), game docked in the gBox app at the title screen

## The game is docked now - the operator's request is satisfied

Captures switched from "Dolphin ... 1280x960" to **"gBox app -> 1030x579"**, which is the docked layout. So the emulator is inside the app,
as the operator wanted.

## But docking is exactly what broke my input, and it took three measurements to see why

1. **The emulator has no top-level window.** `(Get-Process -Id 2236).MainWindowTitle` is **empty** - it is a child window of the app, so a
   pid-based window lookup finds nothing.
2. **`app_window()` does find the app** (hwnd 1316766, visible), and `raise_window()` returns True.
3. **But the foreground is stolen:** immediately after raising, `GetForegroundWindow()` is *"Windows Shell Experience Host"* (pid 9640), so
   `_win_input_in_front` is False, `win_send_keys(polite=False)` raises "gBox or the emulator must be active", and `send()` silently returns
   False after three attempts. That is why 26 A-presses left the game sitting on PRESS START.

**The workaround exists**: `win_send_keys(..., polite=True)` posts the messages straight to the window and returns `{'sent': 2}` - it does
not need the foreground. Verified that it sends; verifying that the game reacts needs a visible capture, and the app window capture came
back at 1,814 bytes (blank), because the app is not visible behind the shell overlay while I work.

## What that means for the boot

The offline flow is not broken - the verified notes describe it (OFFLINE GAME -> single -> character -> confirm -> episode -> area -> intro
dialogs). What broke was delivery. With `polite=True` the keys do go in, so the boot becomes viable again, but it must be driven when the
app window is actually on screen so each step can be seen.

## What is ready and proven

* **memory writes work** on this session (no-op write: `verified: true, via: process memory, rollback_hex 00000000`);
* `session.py` falls back from the stale desktop port to the worker port automatically;
* `apply_master.py` stages HP freeze, 5x legendary multi-equip, Ultimate, and the technique array, each with a re-read as evidence;
* the technique table candidate is located at +0x2E7 (24 zero bytes with a single `01`) plus the `30/10/20/15/15` group at +0x2F3.

## The honest ask

The fastest unblock is the operator loading their character (START -> OFFLINE GAME -> character). That takes seconds on their own screen,
and then every staged change above can be applied and verified immediately. If they would rather I drive it, the app window needs to be
visible (not behind other windows) so the polite path can be checked step by step.

## Files

* `list_windows.py` - enumerates top-level windows with pids and classes
* `diagnose_focus.py` - shows raised=True but in_front=False with the shell host in the foreground
* `try_polite.py` - proves `polite=True` sends (`{'sent': 2}`)
* `offline_flow.py`, `boot_docked.py`, `advance_intro.py` - the deliberate boot attempts and where they stopped
