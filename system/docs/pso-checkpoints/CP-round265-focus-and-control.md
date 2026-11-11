# Round 264-265: the bot no longer fights the operator's control or their focus

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, floor 11 (Dragon arena reloaded).

## Three separate causes, each fixed and each measured

**1. Focus theft.** `game_input.send` called `raise_window()` on **every key**, and that does `SetForegroundWindow` + `SetFocus`. So each injected key
pulled the foreground away from whatever the operator was doing - including typing. Verified cause, verified fix:

```
before: send up held 1.0 s -> moved 2.95 units, focus taken
after:  send returned False, moved 0.0 units, game_has_focus() still False
```

`send` now **sends only when the game already has focus**, and never raises or focuses. Keys cannot leak into another application, because
`polite=True` was measured not to reach Dolphin at all (0.0 units), while system-wide input only lands when the game is in front - so focus is
**gated on**, not grabbed.

**2. Fighting the operator's control.** `pso_operator2.IDLE_SECONDS` was **3.0**, so the bot resumed three seconds after the operator stopped
touching the pad - which reads exactly as "still fighting my control". It is now **30.0**, and `pso_input.allowed()` also requires the game to have
focus, so while the operator uses the PC the bot is genuinely idle rather than looping.

**3. A hard switch.** `D:\gBox\pso-ds\PAUSED` - while that file exists, `operator_active()` reports true and nothing is ever sent. It is a
guarantee that does not depend on timing windows.

## The boss is back in

`boss_warp` takes **`target`**, not `boss` (the first attempt 422'd for that reason):

```
boss_warp target=dragon -> {"verified": true, "requested": true,
                            "message": "Travelling to Dragon / Sil Dragon; the game is loading the destination."}
floor: 11        player (89, 0.1, 323)      HP 62/62
```

The arena is loaded; the Dragon spawns when the character walks into it, which the bot does as soon as the game holds focus.

## How the bot behaves now

| operator action | bot response |
|---|---|
| clicks into the game | resumes playing |
| clicks away, or types in another window | stops immediately, sends nothing, touches no focus |
| touches the pad | waits **30 s** of hands-off before moving |
| creates the PAUSED file | never sends anything at all |

## What this cost and what it buys

The earlier input work had solved delivery by taking the foreground - which made the game controllable but the desktop hostile. Gating on focus
instead means the same delivery works whenever the operator is actually playing, and the operator keeps their machine for everything else. That is
the difference between a bot that can send keys and a bot that can share a PC.
