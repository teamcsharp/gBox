# Round 298: why the game "ignores" you after using the toolbar - and switches now get faced

## The input bug, found by elimination

After a fresh check the setup looked perfect and the character still would not move:

```
gBox window: 1519,735  1030x579   (PiP active)
foreground: 'gBox'
focused: True   allowed: True
held "up" for 0.6 s -> moved 0.0 units
session live: floor 1, player pointer 0x80da62a0, 91 entities
```

So the OS focus was right, the session was live, the sends were accepted - and the game did nothing. The missing piece is **DOM focus**: clicking a
toolbar button (or typing in a dialog) moves the page's focus onto that element, and key events then go to the button instead of to the game surface.
`#gpu-game` only receives keys while it holds focus, and **the app already has the helper for it**: `window.GBoxGPUVideo.focus()`.

**That is what "it's ignoring me" was.** Not the emulator, not the session, not the window - the keyboard had been handed to a button.

The fix: a `gboxRefocusGame()` helper, called at the end of every mod click and when a dialog closes, so the keyboard returns to the game automatically.
**It needs a page load (F5)** - until then, a single click on the game view restores input by hand.

## Switches, as the operator described them

*"if I was able to use my controller ... I would basically rotate the character slightly until the reticle appears on the switch and then have them press
the switch."*

In PSO the character **faces the direction it moves**, so a short step toward the switch **is** the rotation - the reticle appears once the facing is
right, and then A interacts. Pressing A while facing elsewhere does nothing, which is exactly what the record showed: five presses from 12.3 units,
state 224 unchanged.

The switch routine is now a loop of small steps plus a press:

```
while not open and attempts < 8:
    if distance > 2.5: step toward it for 0.12 s   (turns the character, closes the gap)
    press A for 0.3 s
    read the door state
```

with the distance and the state logged every iteration, so the record shows whether the character closed, whether the facing took, and whether the door
opened.

## Also this round

* switches are **hunted across the room** (up to 120 units) rather than only noticed within 16;
* they are **pressed first in every cycle**, before fighting and before travelling;
* **`walk_through` is off** again, so the bot cannot slide through a door without learning to open it.

## State

| item | state |
|---|---|
| DOM-focus bug | **found and fixed in code**; needs F5 |
| switch facing | step-then-press, 8 attempts, logged |
| switch priority | first action in every cycle |
| game | live in Forest 1, HP 40/40 |
| workaround now | click the game view once to restore input |
