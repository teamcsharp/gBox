# Goal round 4: the app restarted clean, the supervisor is armed, and a virtual-pad path exists

## What happened this round

* The **gBox app restarted at 19:33:30** (seven new gBox processes, API answering 200 on both 18765 and 8765). That is the reset that has restored input
  every time tonight, and it also brings in every change made since it was last started: the **Ctrl+R binding** in the main process, the **real mod
  dialog**, the **game-aware toolbar** with its 21 PSO entries and Area picker, the **context menu that steps aside for the game**, and the
  **refocus-after-click** rule.
* **No game is running** - all sessions read `ended` - so the launch is the operator's next step.
* The **supervisor is running** and waiting:

```
19:33:59 === supervisor starting
19:33:59 no live session - waiting for the game to be launched
```

It polls every ten seconds; on seeing a session it **measures whether background input actually works** (one key, unfocused, and whether the character
moves), then starts `play_background` if it does and `play_when_focused` if it does not. So the launch will be picked up without another instruction
from me.

* The **minimap viewer** is up on 8802.

## A new input path, found and not yet tested

`vgamepad` is installed and **ViGEmBus is running**, and the plane itself describes the technique: `pso_coop_setup.xinput_pad` builds *"a
focus-independent XInput virtual pad"*, with keyboard alternatives stripped so extra pads never share P1's keys. If the app polls XInput for the pad it
forwards - and its pad module says it forwards *the operator's controller* - then a **virtual pad is an input path that needs no keyboard and no focus at
all**.

`vpad_test.py` is written to settle it: it creates a virtual Xbox pad and measures the character's movement for left-stick up, down, left, right and an A
press. It could not run this round because no game was live; it is the first thing to run once one is.

**If it works, it is the answer to the whole goal** - the bot would drive the game the way the operator's controller does, with no focus dependency.

## State

| item | state |
|---|---|
| app | **fresh** (19:33:30), all changes live |
| game | not running - launch pending |
| supervisor | **armed**, will auto-start the right loop |
| virtual pad test | written, **not yet run** (needs a live game) |
| minimap | up on 8802 |
| bot logic | complete: switches first (step-then-press), rooms with bounded attempts, 14 floors mapped |
