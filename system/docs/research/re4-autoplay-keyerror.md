# Why the game sits, and the `KeyError: 'load_state'` (2026-11-07)

## The game was waiting for one button

The frame the operator sent is the round **briefing**: Leon standing at the village edge with
*"Successive kills will result in earning you more points!"* on screen and no clock running. RE4 does not start the
round until **A** is pressed on that screen - the driver's own note says exactly that ("three A presses after the stage
draws"), and three A presses started a live round in the capture that follows.

![the briefing, waiting for A](evidence/re4-briefing-waits-for-a.jpg)

Nothing was pressing A because the autoplay that got started was **"vision autoplay (any game)"** - the fallback for a
title with no playbook. It needs a vision model and a per-title route; RE4 Switch has a verified round entry but no
registered playbook, so the fallback had nothing to press with.

With the documented round entry applied:

![the same mod, in a live round](evidence/re4-mod-in-play-em16morph.jpg)

`01'12"73` on the clock and the `re4-em16morph` enemies around Leon - the bone-morphed `em16` meshes from earlier rounds,
now in a running round rather than a still.

## The red error was a real bug, and it is fixed

```
KeyError: 'load_state'
```

The failed job was `session_op {op: "load_state", args: {slot: 0}}` on the **Switch** session. Eden has no save states and
says so (`checkpoint_state, checkpoint_reason = False, "Eden (yuzu) has no save states"`), and its `supported` set
correctly leaves `load_state` out. But `session_op` validated the op against the **global** `adapters.OPS` list, not
against the adapter's own capability set, then called the inherited `load_state`, which indexes a hotkey table that has no
`load_state` entry - a `KeyError` out of a method that should never have been reached.

The dispatcher now refuses an op the adapter does not support, and says why:

```python
supported = getattr(ad, "supported", None)
if supported is not None and inp.op not in supported and inp.op != "stop_game":
    reason = getattr(ad, "checkpoint_reason", "") if inp.op in ("save_state", "load_state") else ""
    raise Unsupported(f"{inp.op} is not available on this emulator ({getattr(ad, 'name', '?')})"
                      + (f": {reason}" if reason else ""))
```

So the same request now answers `load_state is not available on this emulator (eden): Eden (yuzu) has no save states`
instead of dying, and the caller can skip. After deploying, an autoplay job on RE4 returned 200 with **no failed jobs**.
Pinned by `tests/test_session_op_capabilities.py` (the guard must run before the adapter call and must name the reason).

## What is still true

* RE4 Switch still has no playbook, so `autoplay` on it falls to vision, which needs a vision model that answers.
* Its round entry (three A presses) works and is verified; that is what a playbook would use.
* The merc-mode edition rule keeps the GameCube build out of the rotation, so this edition is the one to finish.
