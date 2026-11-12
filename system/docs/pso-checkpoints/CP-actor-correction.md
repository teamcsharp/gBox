# Correction: agent input is dropped by design, so the pad fix was never the answer

## What the reload showed

The app was reloaded and `_setup_vpad` did run - `GCPadNew.ini` now carries **`Options/Always Connected = True`** on `[GCPad1]`, and `Device` stayed `XInput/0/Gamepad`
because the virtual pad took **slot 0** this time (the replacement is a no-op when the slot is 0, which is correct).

Then PSO was launched and **fourteen rounds of START and A at the title did nothing**: floor stayed 0, the player pointer stayed null.

## Why - and it is not the pad

`PUT /api/sessions/{sid}/input` stamps each event with the authenticated actor, and the comment in `server.py` states the rule:

> *"the worker gives the pad to the operator only, never to an agent or a bridge pressing buttons in the same session"*

**Agent-posted input is deliberately dropped.** So the virtual pad fixes *focus* - and that was a real fix, because the keyboard path took the window focus and blinded
the RPC for 25 s - but it cannot make an agent able to drive a session. **My earlier conclusion that the pad fix would let the bot act was wrong.**

## What does work, and it was already proven

**The app's own autoplay injects presses inside the worker** (`AUTOPLAY.get(sid)`), which is why the character moved **258 units** in round 5 while the operator's
session had the bot in charge. On an agent-owned session the `autoplay` tool also starts successfully - job `8ac2ded896db4233` returned `succeeded` - but it did not
boot the game from the title, so it appears to handle in-game play rather than title screens.

On the **operator's** session an agent cannot start it:

```
POST /api/sessions/<sid>/autoplay {"op":"start"}  ->  409 Conflict
```

which is the check that says *"That game is the operator's session; automated tasks can't start or stop its autobot."*

## The state right now

```
0b1c2656706343d6-79276d0fa07c45cc  running  agent: False  started 08:42:16   <- yours
floor: 0   player: None
```

**You are at the title screen** - floor 0, no character in the field.

## What actually makes the bot play

1. **Get into the field** - a character standing in an area, not the title.
2. **Press F3.** That is the app's autoplay, and it is the only path that both injects input internally and is allowed on your session. F3 is now a take-over, not a
   toggle, so pressing it cannot stop a running bot.

That configuration is the one that produced **258 units of movement** in round 5.

## The honest summary of this reload

The reload confirmed the pad configuration is now correct, and it also exposed that **the pad was never what stopped the bot from acting on your session** - the actor
restriction was. **I was wrong about that**, and the previous round's "relaunch will unblock input" claim was too optimistic in one specific way: it would have fixed a
session *the bot owns*, but an agent never gets the pad in a session the operator is watching.
