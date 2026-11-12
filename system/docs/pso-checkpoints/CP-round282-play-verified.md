# Round 282: the bot plays when it has the screen - background play still needs one restart

## Measured this round

**The play loop works when the game has focus.** Handed the screen for a couple of minutes it did exactly what it was built to do:

```
18:01:40   hunting TObjEneRe2Flower hp 70 at 332 units
18:02:17   hunting TObjEneRe2Flower hp 70 at 265 units
18:03:17   hunting TObjEneShark hp 69 at 221 units
```

Three hundred units of travel toward the nearest enemy, planned with the height-aware route. Then focus left and it stopped - correct behaviour under the
no-steal contract.

**Background input is not active yet.** The emulator has been up for **180 minutes**, since long before `BackgroundInput = True` was written into its
config, and Dolphin reads that setting at startup. A direct send still had to focus the window to land (it moved the character 29 units and left
`focused: True`), which is exactly the behaviour BackgroundInput is meant to remove.

## What that means

There remain two things the bot cannot do for itself:

1. **Apply BackgroundInput** - requires Dolphin to start again, and the game must be launched **from the app**: a session I launch is `agent_owned`
   and receives no input at all, which is the problem this is trying to solve.
2. **Reset the app's window state** - the gBox window re-applies `topmost = True` immediately after any clear, and that is what blocks PiP.

Both are fixed by the same action: **restart the gBox app and launch the game from it.**

After that, `play_background.py` runs with no focus requirement, no window raising, and the bot plays while the operator uses the computer - which is
the request this round is about.

## Also re-asserted

`survival` (permanent Scape Doll), `crit` and `always_hit` are all verified on again, since the character's HP was unchanged at 31 through a fight
that may have knocked it out.

## State

| item | state |
|---|---|
| play loop | verified working when focused (hunted 332 -> 221 units) |
| background play | written, needs Dolphin restarted to take effect |
| PiP | blocked by the app's stuck topmost state |
| emulator uptime | 180 minutes - predates the config change |
| assists | survival, crit, always_hit verified on |
| remaining goal item | CP19, one continuous unattended episode |
