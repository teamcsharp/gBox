# Goal round 7: correction - SIDevice0=6 is a STANDARD CONTROLLER, and the pad slot fix is the real one

## I was wrong in round 6

I claimed `-C Dolphin.Core.SIDevice0=6` meant a GameCube **keyboard** and called it the root cause. That was wrong. The plane's own adapters say
otherwise, in code:

```
adapters.py:2785:   "Dolphin.Core.SIDevice0": "6",   # 6 = standard controller
adapters.py:3167:   "Dolphin.Core.SIDevice0": "6",
pso_coop_setup.py:195:  want = {f"SIDevice{i}": str(SI_STANDARD_CONTROLLER) for i in range(count)}
```

**6 is a standard controller.** Port 1 was always a controller port, which is consistent with the operator's controller working all along - and
inconsistent with the keyboard explanation I gave. The correction matters because the wrong explanation would have sent the operator to change a launch
setting that was already right.

## What is then actually true

The emulator's port 1 was bound to **XInput slot 1**:

```
[GCPad1]
Device = XInput/1/Gamepad
```

and slot 1 is **one of the operator's two controllers** (`XInputGetState` shows slots 0 and 1 connected even before the bot creates anything). The bot's
virtual pad lands on **slot 2**, because 0 and 1 are taken.

**So port 1 was reading the operator's controller and never the bot's.** That is a real, sufficient explanation for "the bot cannot move the character"
that does not contradict any measurement: the game is healthy, the operator's controller works through slot 1, and the bot's pad exists on slot 2 where
nothing looks.

## The fix, already in place

`GCPad1` now reads **`XInput/2/Gamepad`**, with a backup (`GCPadNew.ini.bak-before-slot2-193728`). Dolphin reads this at startup, so **the next launch
gives controller port 1 to the bot's virtual pad** - and then `play_pad.py` drives the game with no keyboard, no focus and no window.

## The trade, stated plainly

With port 1 on slot 2, the **operator's controller on slot 1 no longer drives player 1**. That is the cost of the bot owning the pad, and the backup
restores the previous binding in one copy. If both are wanted at once, the operator's controller belongs on port 2 (`GCPad2`), which currently reads
`DInput/0/Keyboard Mouse`.

## One risk to check on the next launch

The app writes Dolphin's configuration at launch (`adapters.py` sets the option block, and `pso_coop_setup` rewrites pad INI files for co-op). If a
launch rewrites `GCPadNew.ini`, my `XInput/2` binding would be replaced by the template's `XInput/1`. **The next launch's command line and the file
afterwards will show whether it survived** - and that is the first thing to verify when a game is started.

## State

| item | state |
|---|---|
| round-6 root cause | **wrong** - corrected here |
| `SIDevice0=6` | **standard controller** (already correct) |
| `GCPad1` | **XInput/2/Gamepad** (the bot's pad), backed up |
| bot's pad | visible on XInput slot 2, verified with `XInputGetState` |
| operator's controller | slot 1 - no longer drives port 1 while the bot holds slot 2 |
| next launch | first verification of whether the binding survives |
