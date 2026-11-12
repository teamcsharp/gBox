# Round 281: background play prepared - the config that lets Dolphin hear keys while unfocused

The operator's requirement is explicit: *"I need you able to support background play and play this game with me able to use the computer and still
chat and interact with you in the background. I don't like that the game has to pause just because I'm talking to you."*

## Why it was pausing, and the setting that fixes it

Windows delivers keystrokes to the **focused** window. Every earlier play mode therefore had to choose between holding focus (fighting the operator)
and pausing (what the operator rejected). Dolphin has a setting that removes the constraint: **`[Interface] BackgroundInput = True`** makes the
emulator read its input devices while it is **not** the foreground window, and Dolphin's keyboard device is one of those input devices.

**Two configs exist and the live one was not the obvious one.** The session runs on the `i9-NUC` worker profile, whose Dolphin reads:

```
D:\gBox\runtime\dolphin\Dolphin-x64\gbox-data\pso-buddies\i9-NUC\436e0bb84d5337d1\User\Config\Dolphin.ini
```

not the root `User\Config\Dolphin.ini` that was patched first. **Both** now carry the setting:

```
[Interface]
BackgroundInput = True
```

Dolphin reads this **at startup**, so it takes effect on the next launch - it cannot be applied to the running instance.

## `play_background.py`

The play loop for that configuration:

* **no focus gate at all** - it never checks or waits for focus and never raises a window;
* still yields whenever the operator has touched the pad within 30 s;
* **detects that it is not working**: if thirty actions in a row are refused, it says BackgroundInput has not taken effect rather than spinning;
* same behaviour as before otherwise - lock a target, short-step and swing, cast beyond 30 units, hunt the nearest enemy anywhere when nothing is
  close.

## The PiP problem

*"G Box isn't letting me put the program back into PIP mode."* The gBox window reports **`topmost=True`**, and clearing it with
`SetWindowPos(HWND_NOTOPMOST)` is **immediately reverted** - the app's own window state keeps re-applying it. That is almost certainly what blocks
the PiP transition, and it is the app's state to reset, not something an external process can override.

## The one action that fixes both

**Restart the gBox app and launch the game from it again.** That does two things at once:

1. Dolphin re-reads its config, so **BackgroundInput takes effect** - and from then on the bot plays while the operator uses the computer;
2. the app's window state is rebuilt, which is what the stuck PiP needs.

After the relaunch, `play_background.py` is the loop to run - it needs no focus and no clicking.

## State

| item | state |
|---|---|
| BackgroundInput | set in **both** Dolphin configs |
| takes effect | on the next Dolphin start |
| `play_background.py` | written, compiles, ready |
| PiP | blocked by a stuck topmost state in the app; needs the app restarted |
| current game | still running on the old config, so still focus-bound |
