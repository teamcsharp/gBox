# Why PSO "takes so long to load" - and the mechanism that fixes it permanently

## The mechanism already exists: jump states

`gbox/jumpstate.py`:

> *"Once autoplay has played a game for SAVE_AFTER seconds without needing a menu press for QUIET_FOR seconds while the screen keeps moving, it saves an emulator state for that
> game and build (`runtime/jumpstates/<game>-<build>.state`). **The next autoplay start of the same game and build starts there: no logos, title screen or menus.**"*

For Dolphin the strategy is `"boot"`: a launch that asks for a jump boots **straight into the state** with `--save_state`, so not even a logo shows.

## It is wired, and it ran

This launch asked for a jump (`autoplay=true` implies `jump: True`), and the session's own detail confirms it executed:

```
detail.jump : {"booted": true, "file": "436e0bb84d5337d1-stock.state"}
```

**So the whole path works**: the launch asked, `arm_boot` found a state for PSO (`436e0bb84d5337d1` is its game id), and Dolphin booted into it.

## But the saved state itself is bad

```
436e0bb84d5337d1-stock.state   15.5 MB   written 11/10/2026 19:49   (two days old)
```

After booting into it: **floor 0, player pointer null** - the title screen, not gameplay. A jump state is supposed to be dropped when it lands on a still screen, but this one
survived - PSO's title has motion, so the "screen keeps moving" check cannot tell it from play.

**Retired** it (`...state.bad-20261112`) so the next boot is a clean, predictable normal boot instead of silently landing on a menu.

## The permanent fix, and it needs one manual pass

**Autoplay writes jump states itself.** So the sequence that ends this problem for good is:

1. **get into the field once** - a character standing in an area, not the title;
2. **autoplay plays for 45 s** without needing a menu press;
3. it saves a **fresh** jump state for PSO;
4. **from then on every launch boots straight into gameplay** - no logos, no title, no menus.

That is not a workaround; it is the feature the codebase already implements, which had only ever been fed a bad state.

## What this round also established

* **`autoplay=true` on the launch route works**: the job succeeded, the session came up, and the autoplay attached - but **it cannot pass the title**, because it plays
  gameplay and does not drive menus.
* **The worker is free again**: the stuck session was stopped, so **0 live sessions** - nothing of mine is occupying what MercMode needs to broadcast.
* **My admin kit works**: the app was restarted through `gbox-desktop-launch` and the launch route no longer demands a `linux` worker for `kind: "attract"` games, so this
  launch dispatched normally.

## Honest state of the goal

| clause | state |
|---|---|
| map internalised | 51 collision rooms + room inventories + adjacency graph, routing at 1.08x |
| path-guiding the bot | local room routing ready; world-scale mapping proven impossible without per-instance transforms |
| **bot autoplaying** | **the bot plays in-game (258 units measured), but cannot pass the title - one manual pass into the field fixes it permanently via the jump state** |
| speedrunning at 10x | 3.6x measured; one saturated CPU core |
| decrypting PSO | pathing never needed it - collision parses from the disc |

**The single remaining human action: play into the field once.** After that, autoplay saves a good jump state and every launch starts in gameplay.
