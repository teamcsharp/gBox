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
