# Round 210: the operator lock is fixed (action windows), and switch flipping has a tool

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1

## The control fight - root cause and fix

The operator reported the bot still taking the controller. The v1 detector compared motion against "time since the bot last CALLED
send", but a stride is a **0.7 s held key** - the game keeps moving the character long after that call, so the operator's motion during a
stride looked like the bot's own and the lock never engaged.

**v2 introduces an explicit action window**:

* `note_bot_input(seconds)` records `bot_active_until = now + seconds` - the period the bot's input is on the wire;
* motion counts as the operator's only when `now > bot_active_until + 0.20 s`;
* `guard()` refuses to send while operator motion is inside the last 3 s.

The decision is a pure function and is unit-tested - **5/5 cases pass**:

```
ok  operator moves while the bot is idle       -> operator=True
ok  bot's own stride                           -> operator=False
ok  bot's stride just ended (grace)            -> operator=False
ok  tiny jitter                                -> operator=False
ok  operator moves 1 s after the bot stopped   -> operator=True
```

`map_bot.py` now imports `pso_operator2`, declares the window on every `hold`/`tap`, and re-checks `guard()` before each press. The bot was
stopped while this was built, so the operator had the controller throughout.

## Switches: what the flips actually change

The operator flipped the room's switches by hand. Comparing the entity snapshot taken before with the state after shows what a flip does:

```
TObjLazerFenceNorm at (-547,-531)  +0x190: 0 -> 18.0
TObjLazerFenceNorm at (-420, 486)  +0xb8: 0 -> 2.7   +0x198: 0 -> 2.7
TObjLazerFenceNorm at ( 498,-261)  +0x190: 0 -> 8.0
TLazerFenceSw (the switch itself)  unchanged
```

So **flipping a fence switch moves the fence's animation floats** (+0x190 / +0x198 / +0xB8) and leaves no persistent flag on the switch -
a momentary press. That is the proof a flip can be detected by.

## The tooling delivered

* `flip_switches.py` - finds switch classes, walks to each with the empirical controller, presses A (then attacks if A changes nothing),
  and proves the flip by diffing the switch and every fence before/after. Every input goes through the v2 lock.
* `switch_state.py` / `switch_diff.py` - snapshot and before/after diff of switches, fences and key doors.
* `static_switches.py` - reads the level set file for placed switches. `map_forest01d.dat` holds class **4352 exactly twice** (the pair
  the operator means); its coordinate fields are not yet decoded, so positions from the set file are not available to the bot yet.
* `steer2.py` - steering with a distance-regression guard and stall re-planning (v1 verifiably arrived: 123 units in 5 steps).

## Honest status

* control arbitration: **fixed and tested**;
* switch flipping: tool ready, proof method measured, but the loaded room's only switch entities (`TLazerFenceSw` x4) are 450+ units away,
  so it has not yet flipped one in this room;
* the two switches the operator used are static set objects (class 4352) whose positions still need decoding from the set file.
