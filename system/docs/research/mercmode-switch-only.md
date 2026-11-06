# MercMode is Switch only, and why PS3 builds appeared

2026-11-06. Operator saw PS3 builds in the MercMode rotation. This records what actually happened, and the corrections two
of my earlier claims needed.

## What was observed

Sessions by adapter: **54 Switch (`eden`)** and **5 PS3 (`rpcs3`)**. Three of the PS3 ones start at 07:41:47, 07:46:27 and
07:52:08 - between two Switch rounds - and they coincide with the agent's own boot-test launches. The other two (03:16,
03:41) are the same kind of probe.

The rotation itself launched Switch throughout. **The PS3 runs were agent launches.**

## Why an agent launch could pick PS3

An `@launch` that names only a title resolves it through the library. My launches did that, and one of them came up as
`rpcs3` running `e7ca89bbeb67360d` ("Resident Evil 5 - Gold Edition").

**Correction to an earlier version of this note:** it said `preferred_editions` was unset and that the default edition was
therefore PS3. That is wrong. MercMode's status showed RE5 pinned to the Switch No Mercy edition (`01:34`), and the pin is
only consulted by the MercMode scheduler - a **direct launch never reads it**, which is why the pin could be correct and the
launches could still resolve elsewhere. The pin is kept anyway, as a statement of intent for the scheduler.

## The real risk is the emulator choice, not the edition

`adapters.pick_switch_emulator` reads `switch_linux_emulator` from the config **before** it ever consults
`SWITCH_CITRON_TITLES`:

```python
choice = str(getattr(config, "switch_linux_emulator", "auto") or "auto").casefold()
if choice in ("eden", "citron"):
    return choice                      # a forced choice wins; the title list is not read
```

On lilspark (and in this repository) that setting is:

```
switch_linux_emulator = "eden"   # Citron NEO aborts at renderer init on the GB10 (VK_ERROR_UNKNOWN in the Vulkan WSI
                                 # path); Eden renders (RE5/RE6 verified 2026-11-03)
```

So on this host every Switch title is forced onto Eden and `SWITCH_CITRON_TITLES` has no effect. That has a consequence
worth stating plainly: **RE4 Switch needs Citron because it does not run on Eden, and Citron is currently refused on this
GPU** - so RE4 Switch cannot be played on lilspark until either Citron works on the GB10 or RE4 runs on Eden.

`SWITCH_CITRON_TITLES` is now committed as RE4-only, matching the deployment, so a deploy no longer moves RE5/RE6 to
Citron:

```python
SWITCH_CITRON_TITLES = frozenset({"010099A00BC1E000"})   # RE4 only
```

Because the config forces Eden, that list only matters on a host configured `auto`.

## Always pass the node

A launch with no `node` may run on another PC entirely: one of my test launches produced a **yuzu** session on
JAYBUILTFINALE, the operator's play PC. Test sessions belong on lilspark:

```
POST /api/jobs {"tool": "@launch", "input": {"game": <switch catalog entry>, "mod": "<build>", "node": "lilspark"}}
```

Two sessions running at once is not a slot violation either: rpcs3 ran on lilspark while yuzu ran on JAYBUILTFINALE. The
limit is one Switch emulator per PC, because its config and NAND live in one folder.

## How to launch a test build into MercMode

1. A build is a folder `mods/<game_id>/<build>/` **with `.gbox-mod.json`** (`MARKER` in `gbox/switch_mods.py`). A
   hand-copied `romfs/` tree without the marker is ignored - the session comes up with `mod: ""`.
2. `switch_mods` `op: "apply_live"` is the sanctioned test path for Switch on Linux: it writes the build and reboots the
   title in the same session. It refuses non-Switch sessions, and on yuzu it relaunches as a new session.
3. **Use a test build of your own, never the rotation's live build** (`cast-inverted`): a bad edit there breaks every later
   round.
4. Before reading any frame, confirm the session reports your build and that `detail.boot_failures` is empty.
5. Do not judge by mean/std brightness - look at the frame and prove the changed asset appears in a live round.
6. Pausing MercMode interrupts the operator's rotation: ask first, and restore the settings exactly afterwards.
