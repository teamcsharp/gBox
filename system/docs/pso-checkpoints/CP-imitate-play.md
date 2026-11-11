# Learning from your play, and replaying it

Session identity: DeepSeek    Branch: ds-pso-imitate-play-20261110    Commits: this branch
Goal: 2

## What the operator asked for

> "make sure the bot is learning from me playing and is able to play imitating and learning from my play. I want the controller to
> work so i dont have to play on keyboard."

## The two halves that already existed

* **`imitate.py`** - the plane's learner: *"Autoplay that learns from the operator's own play (gameplay memory). While the operator
  plays, padstate.watch_xinput reports their controller at 30 Hz and gameplay memory keeps each report as a 'pad'…"*.
  `imitate.learn(timeline)` returns the operator's **style**: distinct bursts (with one recorded timing each), how often each occurs,
  what follows what, the idle gaps, and the menu keys they use.
* **`autoplay`** - the mission executor: `press {key, n}`, `wait {secs}`, `navigate`, `interact`, `fight`.

What was missing was the **join**: archive -> timeline -> learned style -> a mission the bot can replay. That is this branch.

## `gbox/pso_learn_play.py`

* `timeline(events)` - the archive's `pad` events as `[(seconds, frozenset(keys))]`, with the same 0.3 stick threshold `padstate`
  uses and the C-stick mapped to `cup/cdown/cleft/cright`;
* `learn(timeline)` - calls **`imitate.learn` unchanged**, so the style is the plane's own, not a second implementation;
* `follow_order(learned)` - a deterministic walk through the learned `follows` graph (most likely successor first), so a mission
  replays the bursts in the order the operator actually chains them;
* `mission(learned, ...)` - the burst sequence as mission steps, using the recorded sub-burst delays and the **median idle gap**
  between bursts, with `provenance` naming the run, the burst count, the gap and the menu keys;
* `from_events(...)` / `save(...)` - the whole pipeline and where it writes (`profiles/missions/`).

## Proven

`tests/test_pso_learn_play.py` - **6 passed**: the archive's real event shape converts; a session becomes a mission with recorded
timing; every produced step is in the autoplay vocabulary; a run with no pad events is refused rather than invented; the learned style
is byte-identical to `imitate.learn`'s own output; and the mission round-trips through `save`.

`system/tools/pso_learn_from_play.py` runs the whole thing against the live archive:

```
run 604edd54c7b94c87-51b2eaa27e234155: events {'mod_action': 1, 'pad': 2}
3 archived events, 2 pad events
learned 0 bursts, menu keys ['start'], 0 mission steps
```

**So the pipeline is complete and works on real data - but there is nothing to imitate yet.** The archive holds **two pad events with
no buttons** for this game, because the operator's controller has not been able to play (see below). The moment a real play session is
recorded, the same command produces a real mission.

## The controller: the actual blocker, precisely

```
XInput slots: ['empty', 'connected', 'empty', 'empty']     # the operator's pad is in slot 1
Dolphin GCPad1: Device = XInput/0/Gamepad                   # the game reads slot 0, which is empty
```

Dolphin polls `XInput/0/Gamepad` live, so the fix is not a config edit or a restart: **unplug the controller and plug it back in** -
slot 0 is free, so Windows assigns it there and the game sees it immediately. (Earlier the four *ghost* ViGEm pads held every slot;
they are down to an inactive stub now, and that is what kept the controller out.)

If a replug still lands it in slot 1, the alternative is to bind `GCPad1` to `XInput/1/Gamepad` and relaunch, which this lane can do -
but a replug is one action and needs no restart.

## The menu learner, for completeness

Separate branch `ds-pso-menu-learn-20261110`: a transition graph over screens with learned per-edge delays, macro replay (one
capture per route instead of one per press) and a shrink loop that makes each successful run faster - 7 tests. Live screen
identification must use `pso_menu_observer`'s semantic menus, because the attract loop's animation defeats a pixel hash.
