# Full recovery: emulator restart, worker rebind, boot automation and the live mod channel

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, pid 58572, Forest 1, `supported: true`

## Why the game froze - the real cause

The bot's "frozen character" was **never the character**. The emulator was wedged:

* the player struct's bytes did not change over 2 s (zero bytes differ) - emulation was not advancing;
* a savestate load stuck at **"Decompressing State..."** (magenta screen) for 80+ s;
* `pause`/`resume` reported PLAYING while nothing advanced.

Recovery required the process restart the operator authorised.

## The two service channels - and which one works

There are **two** APIs on this machine, and after a restart only one reaches the game:

| channel | port | behaviour |
|---|---|---|
| desktop service | **18765** | owns the emulator; `read_memory` returns real data (`47504f453850` = `GPOE8P`), `pso_controls` work |
| worker mirror | 8765 | serves jobs, but session actions time out with **504 "Session did not acknowledge"** |

**Everything now goes through 18765** (`session.py` was repointed). The 504s that blocked every mod earlier were simply the wrong
channel.

## The worker refusal and how to clear it

```
RuntimeError: Worker activation held: a delivered native launch still has an owned PID record; no emulator was stopped
```

The worker reads `D:\gBox\runtime\gbox-running.json`; it held three stale session records. The clean sequence that works:

1. stop every emulator, 2. stop the worker processes, 3. **delete `gbox-running.json`**, 4. start the worker
(`python -m gbox --config ... serve --worker` from the gBox venv - the entry point is `gbox.__main__`, there is no `gbox.cli`),
5. `launch_game` with **`debug: true`** and the full catalog entry (not a game id) so the debugger memory port opens.

## Menus: STICK moves multiple rows, D-PAD moves exactly one

This was the menu bug all round: the analog stick repeats, so one 0.05 s tap jumps 2-3 rows (0 -> 2 -> 3 -> 0, never reaching the
target), while **`ddown`/`dup` step exactly one row**. `menu_select.py` drives menus closed-loop: it samples each row's orange selection
bar from the screenshot, finds the highlighted row, and taps the D-pad toward the target until it matches - then presses A.

Measured on the title menu: `scores=[0, 81, 0, 0]` means OFFLINE GAME is selected.

## Boot automation (launch -> playable)

`boot_full.py` + `menu_select.py` do the whole path: title -> START -> closed-loop select OFFLINE GAME -> A (SINGLE MODE) -> A
(character BQF) -> A (Confirm) -> A (EPISODE 1) -> area load -> A through the intro dialogue (the operator confirmed: press A for each
dialogue). `capabilities` returning **`supported: true`** is the objective proof the game reached offline free-play.

## The build applied on the fresh character

* **TP max 999**: `stat name=mst value=999` raises TP max (measured `tp 29 / tp_max 999`); the bar then regenerates into it. The MST
  route works because direct TP writes need the job channel, which reports `SessionGone` for this session.
* **crit + always_hit + equip_any**: all `true`.
* **the same weapon five times**: four extra copies of `000100 Saber` given, then `multi_equip` on each - result: **5 Sabers equipped
  simultaneously** (4x "Weapon effects stacked") alongside Frame and Mag, 7 equipped items total.

## Still open

* `hp` via `stat` is rejected (422) and direct HP writes need the job channel, so the 8/54 -> 54/54 heal measured earlier is not
  reachable on this session yet;
* techniques remain unmapped (the learned-tech table has not been located), so "all spells" and rapid-fire casting are still pending;
* the character is in Forest 1 at `(-145,151)` with `up` blocked by terrain - navigation onward is the next gameplay step.
