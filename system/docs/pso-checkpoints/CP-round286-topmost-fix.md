# Round 286: removing the TOPMOST nudge that let gBox dominate the desktop

## The operator's report

*"G Box was forcing itself on top of the application and wasn't able to click on any other applications underneath. So it took control and was
overbearing on the computer."*

That is a real defect and part of it was mine.

## What my code did

`game_input.raise_window` used the classic trick for pushing a window forward:

```python
user32.SetWindowPos(hwnd, -1, ...)   # HWND_TOPMOST   - pins the window above everything
user32.SetWindowPos(hwnd, -2, ...)   # HWND_NOTOPMOST - meant to undo it
```

The pair only works if **both** calls land. If the second is lost, delayed, or the window manager is busy, the window **stays always-on-top** - above
every application, above the taskbar, above its flyouts. That is exactly the state the operator described: no way to click through, and the volume
control unreachable.

**It is removed.** `raise_window` now uses only calls that do not pin anything:

```python
ShowWindow(SW_RESTORE); BringWindowToTop; SetForegroundWindow; SetFocus
```

and a new `clear_topmost()` can release an already-pinned window, checking the extended style before and after rather than assuming.

## What is not mine

The gBox **application** re-asserts `topmost = True` on its own window: `clear_topmost` returns **False** on it because the style is back immediately
after the call. That is the app's own PiP/overlay behaviour, and it has to be turned off in the app - no external process can hold it down.

What did improve: after the app restarted, its window recovered to **1436,662 - 2552,1357**, which **no longer covers the taskbar** (bottom edge 1357
against a 1440-tall screen). So the volume control should be reachable now even while the window stays on top.

## State

| item | state |
|---|---|
| `raise_window` TOPMOST nudge | **removed** |
| `clear_topmost()` | added, verified against the style bits |
| app's own topmost | re-asserted by the app; must be turned off there |
| game | **not running** - no Dolphin process |
| gBox API | back on 18765 and 8765 |
| minimap server | running |

## What to do next

1. **Launch the game from the app** - this is the restart that applies `BackgroundInput`, so the bot can then play while the computer is in use;
2. **turn off the app's always-on-top / PiP overlay** in its own settings, since only the app can stop re-applying it.

With those two, the domination goes away and the bot plays in the background. Everything else is ready and self-tested: 8 of 9 checks pass, the ninth
being the minimap probe that needs a running session to read.
