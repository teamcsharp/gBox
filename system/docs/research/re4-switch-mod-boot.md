# RE4 Switch: a modded pack boots (first in-game run)

2026-11-07. The first time a pack written by gBox's own HD writer was booted by the game.

## What was done

1. `re4gc_inventory.pack_patch` wrote one mesh slot of `bio4/em/em10.udas` from another slot's geometry (see
   `re4hd-bin.md` §11): slot #75, 241,216 B, 5,892 verts, 38 bones ← donor #119 (2,400 verts, 1,664 tris).
2. `switch_mods op=write` built the LayeredFS overlay `mods/270a15eb98dab4d7/re4-swap-test` with that pack at
   `romfs/bio4/em/em10.udas`.
3. `POST /api/games/270a15eb98dab4d7/launch?node=lilspark&mod=re4-swap-test` launched the title.
4. Frames were sampled every 20 s; the session reported `mod: re4-swap-test`.

## What was seen

| time | frame | what it is |
|---|---|---|
| +20 s … +220 s | mean 61.2 / std 48.9, 50 KB | **title screen, "PRESS A"** — the game booted with the patched pack |
| bot run, +20 s | mean 40.3 | transition |
| +40 s … +300 s | mean 48.2 / std 26.3, 27 KB, static | **LOAD / save-select screen** (slots 03–07, "Chapter · Saves · Time · Round · Mode") |

![title screen with the swapped pack](evidence/re4switch-mod-boot-title.jpg)

![the save-select screen](evidence/re4switch-mod-boot-loadscreen.jpg)

## What this does and does not prove

**Proven:** the overlay path works end to end — a 8.9 MB pack rebuilt by `pack_patch` (one 241 KB mesh slot replaced,
every other slot byte-identical) is accepted by the title, which boots and reaches its menus and its save list. The
earlier `pack_patch`/`pad_to` work is therefore not just byte-consistent on disk; the game loads it.

**Not proven:** that the **swapped geometry renders**. No enemy has been on screen, so nothing here shows the new mesh
drawing. The claim stops at "boots with a modified pack".

## What the run exposed, for the next attempt

* **The load screen is the shortcut.** The title has existing saves (slots 03–07), so the route to an enemy is *load a
  save that has gameplay*, not walk the menus from the title. Starting a new game means playing to the village.
* **The RE4 autoplay driver stalls here.** It reached the LOAD screen and then produced identical frames for 260 s —
  it has no strategy for this screen on this edition. That is a concrete gap in `gbox.mercs.titles.re4_switch`.
* **Mercenaries may need an unlock.** RE4's Mercenaries mode is not available on a fresh save, which is why an
  "Unlock everything in custom builds: Resident Evil 4" ticket exists. A load-save route avoids that question only if
  the save itself already has it.
* **One emulator slot.** This run had to pause the RE5 MercMode rotation; it was restarted afterwards
  (`phase: playing` within 60 s). Any in-game RE4 test costs the rotation one turn.

## Reproduce

```
scp .work/re4-probe/re4_swap_boot.py spark:/tmp/ && ssh spark 'sed -i "s/\r$//" /tmp/re4_swap_boot.py; python3 -u /tmp/re4_swap_boot.py'
```

(`restore_mercmode.py` in the same folder puts the rotation back.)

## Second run: attempting to load a save with the modded pack (2026-11-07)

The load screen is reachable, so the next step was to load a save and put an enemy on screen.

**What the save list showed:** the title has `Cleared Game` saves (slot 01 "008 04:18:02 � 01 � PRO", slot 02
"005 02:47:06 � 01 � ADA"), so a cleared game - and therefore Mercenaries access - is on this copy.

**Modded pack, confirmed a load:** title ? LOAD list ? "Load data? Yes / No" ? answered Yes ? **black screen**
(7,056 B frame, mean 0.8, std 9.6) held for **210 s**. The emulator stayed up; nothing rendered.

**Stock control, same intent:** the load list was reached, "Load data?" was answered the same way, and the title
**returned to the save list** (mean 40.2-40.3 for 180 s) instead of going black.

**What that does and does not establish.** The two runs are not the same experiment: the prompt appears at a
different tap depending on where the cursor sits beforehand (the modded run reached it after six taps, the stock run
needed a seventh), so "stock refused the load" and "stock never attempted it" cannot be told apart from frames alone.
The black screen is therefore **consistent with** the swapped pack breaking the level load, and equally consistent with
a load this copy refuses at a different point. **The swap is not implicated yet.**

**What would settle it,** and what this run says about the driver:

1. Read the menu state instead of tapping blind. The correct signal is the LOAD screen being *stable* and its cursor
   position - neither is currently sensed, which is exactly why `gbox.mercs.titles.re4_switch` stalls here (identical
   frames for 260 s in the round-9 bot run).
2. With that, run the pair properly: stock load ? expect gameplay; modded load ? either gameplay (swap is fine, look
   for the enemy) or black (swap implicated). Same save, same cursor, one variable.
3. Only then does "the mesh renders" become a claim worth making.

Cost of the two runs: MercMode was paused for both and restored after (`phase: playing` within 60 s).
## Third run: the walk with the story-list recovery (2026-11-07, same day)

Two changes went in and were tested in game:

1. `step()` cancels out of a story screen instead of the run ending there (`wandered()` only ends it once a 4-press
   budget is spent).
2. `Reader` treats an **unnamed frame after a story screen** as that list's "Load data? Yes / No" dialog
   (`story_prompt`), and the driver cancels it. This is the hole that let the previous run load a story save � the
   overlay is drawn over the list, matches no reference, and read as `unknown`, so a press meant for an unnamed screen
   answered Yes. That run ended in the **merchant's TUNE UP screen** (1,751,510 PTAS on it).

**In game, neither reached the Mercenaries.** The third run sat on the story LOAD list (slots 03-07, mean 48.2 / std
26.3) for 255 s with identical frames.

**So the cancel does not work, and the next step is instrumentation, not another guess:**

* `B` is evidently not this title's cancel on that screen. Trying keys blind is exactly the mistake this project has
  already paid for twice, so the next move is to read what the walk believes: log `screen()`/`step()` each tick while
  the game is on the list, and see whether the recovery is even being asked for (`story` vs `unknown`, and whether the
  menus loop's "press once, then wait for the screen to change" guard is holding the cancel back).
* It is also still unexplained **how the walk reaches LOAD at all**: `re4_switch` declares no `BOOT_KEY` (precisely so
  `mercs_bot.Boot` never blind-presses), and the menus loop only confirms when the cursor reads its target row. If a
  cursor read lags one frame behind a D-pad press, `cur == tgt` can be true on the wrong row - that is the hypothesis
  the logging should confirm or kill.

Cost: one more rotation turn (MercMode paused and restored, `phase: playing` within 60 s).