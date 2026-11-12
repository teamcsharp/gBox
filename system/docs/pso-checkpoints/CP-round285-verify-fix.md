# Round 285: verifying the fix before asking for it

The remaining blocker is that keyboard input only lands in the focused window, and the fix is Dolphin's `BackgroundInput` - already written into both
configs but only read at startup. Before asking the operator to restart anything, the setting itself was verified against the binary that is actually
running.

## The check

```
Dolphin.exe: 22,716,416 bytes
BackgroundInput       -> FOUND (offset 20,712,696)
"Background Input"    -> FOUND (offset 16,453,264)
PadType               -> FOUND
GFXBackend            -> FOUND
```

The config key exists in this build **and** the UI label for it exists, so `[Interface] BackgroundInput = True` is a real setting here rather than a
guess from documentation. Dolphin reads it at startup; the restart the operator has been asked to do will therefore apply it.

## Also confirmed this round

* the emulator has been running **190 minutes** and the gBox app **20 hours** - which is exactly why the app's window state is wedged: a fullscreen,
  always-on-top window re-asserting itself for 20 hours, over the taskbar, which is what stops the volume control being clicked;
* the game session is unchanged (`25cacd83…`, pid 45920), so nothing has restarted yet;
* the focus remains with the browser, so the play loops stay paused - correct behaviour, not a fault.

## Why the restart is still the answer

* **BackgroundInput** - verified present, applies at startup, removes the focus requirement so the bot plays while the operator uses the computer;
* **the window state** - 20 hours of the app forcing fullscreen/topmost, re-applied within a second of every external change, so PiP and the taskbar can
  only be recovered by the app rebuilding that state;
* **and it must be launched from the app**: an agent-launched session is `agent_owned` and receives no input at all.

## State

| item | state |
|---|---|
| `BackgroundInput` | **verified present in this Dolphin build** |
| configuration | set in both the root and the live i9-NUC profile |
| takes effect | Dolphin's next start |
| play loops | stopped; nothing is sending keys |
| character | floor 3, survival verified on |
| CP17 / CP18 | pass, evidence reproducible |
| CP19 | pending the restart |
