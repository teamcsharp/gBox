# Playing PSO through gBox: controller, mods, multiple titles

Session identity: DeepSeek    Branch: ds-pso-gbox-play-20261110    Commits: this branch
Goal: 2

## The operator's request

> "can we play and handle pso through gbox so i am able to play it through gbox and use the mods associated with the game and
> inherent control schemes there? gbox is supposed to be able to play multiple titles at once and be able to switch between them"

This is a product question, not a research one, and the answer turned out to be **"yes - once gBox's running process is the
current code"**.

## The controller: gBox already has the fix, the process predates it

`gbox/pad_bind.py` chooses which XInput slot Dolphin's `GCPad1` should name. Its own header describes this machine:

> "On this PC slot 0 is a **phantom virtual pad that reports exactly zero forever** while the operator's real controller is on
> another slot, so the fallback binds the game to a dead device: the game ignores every gBox press *and* the operator's own
> controller."

and `adapters.DolphinWinAdapter._argv` calls it when no virtual pad was created:

```python
# The base INI names XInput/0. A leftover virtual pad can hold slot 0 reporting all zeros forever, and then
# the game -- and the operator's own controller -- see nothing (i9-NUC 2026-11-10: slot 0 phantom, the real
# pad on slot 1, every press dropped). Bind a pad that actually reports instead.
vpad_ini = pad_bind.bind_note(vpad_ini, pad_bind.choose_slot(pad_bind.probe_pads()))
```

**Measured on the live machine**, with the operator's controller plugged in:

```
xinput slots: 0 empty, 1 connected (lx -866, ly -959, rx -433, ry -774), 2 empty, 3 empty
pad_bind.alive_slots -> [1]
pad_bind.choose_slot  -> 1
bind_note(...)        -> "# gBox: Player 1 bound to XInput slot 1 (the pad that reports input; slot 0 was idle/dead)"
                          "[GCPad1]" / "Device = XInput/1/Gamepad"
```

`tests/test_pad_bind.py` + `tests/test_padstate_operator_slot.py` - **10 passed**.

**Why it does not happen today:** the running gBox server was started at **02:20**, and `pad_bind.py` was written at **06:40 the same
day**. A restart of gBox is all that stands between the operator and a controller that works *through gBox*, with gBox's own binding
logic - no virtual-pad hacks, no window tricks.

## Mods

`launch_game` already takes `mod` and `mod_title`, and this lane built a real one this evening:
`D:\\gBox\\cache\\mods\\436e0bb84d5337d1\\ds_cp14_room_added\\` (235 records in `g_set_object.gsl`, build verified). After the restart,
one launch plays the **modded** PSO through gBox:

```
POST /api/games/436e0bb84d5337d1/launch?node=i9-NUC   {"mod": "ds_cp14_room_added"}
```

## Multiple titles at once, and switching

The machine already ran **two PSO sessions simultaneously** tonight (two Dolphin processes, `session.detail.pid` distinguishing them),
so concurrent titles are supported; the plane's session list is the switchboard, and each session carries its own `pid` and
`local_window`. The practical rule this lane learned the hard way: **always address the session's own pid** - two windows with the
same title made hotkeys and captures hit the wrong game until the pid was pinned.

## What is needed, in one line

**Restart gBox** (the operator's standing rule is that this lane does not restart it) - then playing PSO through gBox works with the
operator's controller, with the mod, and with a second title alongside it.

## Round 146: why the controller is not Player 1 in gBox - and the two ways to make it so

The dry run of gBox's own launch decision, on the live machine, is unambiguous:

```
pad_bind.probe_pads()  -> {1: (0, -74, -348, 278, -1046, 0, 0)}      # the operator's controller, drifting
pad_bind.choose_slot() -> 1
bind_note(bind_device(PAD_INI_WIN, 1), 1) ->
    "# gBox: Player 1 bound to XInput slot 1 (the pad that reports input; slot 0 was idle/dead)"
    "Device = XInput/1/Gamepad"
```

If gBox's launch reaches that branch, **the operator's controller is Player 1**. But for PSO it does not, and this is deliberate:

```python
def _want_vpad(self) -> bool:
    """Drive Player 1 through a ViGEm virtual XInput pad instead of the keyboard? Windows only, opt-in: on for PSO
    (gecko id GPO*, which loses the attract loop on the i9 because keyboard input needs focus)..."""
    if not (str(getattr(self, "gecko_id", "") or "").startswith("GPO") or flag in (...)):
        return False
```

`GPO*` is PSO, so **every PSO launch puts Player 1 on gBox's virtual pad** - the operator's controller is *not* P1, whatever slot
it is in. That is what made this evening look like a broken controller: gBox was working as designed, and the design has PSO's P1
owned by the bot so that presses are focus-free.

**Two ways to give Player 1 to the operator:**

1. **`GBOX_DOLPHIN_VPAD=off` in gBox's environment**, then relaunch. `_want_vpad` returns False, no virtual pad is created, the
   fallback runs, and `pad_bind` binds `XInput/1/Gamepad` (proven above). This needs a **gBox restart** to take the variable - and
   the startup of the plane is the operator's call, not this lane's.
2. **The takeover lease** (`pad_takeover.py`): *"Pick up the controller, take over from the bot for a moment, put it down: the bot
   plays on"* - the operator's input overrides the bot's for a moment **and is recorded as operator segments**, which is also the
   material `imitate.learn` wants. It needs a live autoplay run (the lease lives in `tools.AUTOPLAY`), so it is the route to use
   *while* the bot plays, not for a plain operator session.

**So the answer to the operator's question is yes, with one setting.** PSO through gBox: controller -> route 1; mods -> `mod=` on the
launch; multiple titles -> already true (two PSO sessions ran side by side tonight, each with its own `session.detail.pid`).
