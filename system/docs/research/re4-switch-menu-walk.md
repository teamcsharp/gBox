# RE4 Switch: the automatic walk from the title to a live round

Measured 2026-11-06 on lilspark (GB10, Citron NEO d3df71e55, NCE, production Citron home). Session
`d4890e46daa040ae-70d381d6fa944691`, launched with `node: lilspark` and logged as an agent session.

**Result: 5 boots out of 5 reached a live round on their own**, about 54 s from an in-session reset, with no story load
and `savegame00.sav` byte-identical before and after (`13908f63...`).

| run | to round | presses | clock moved | module base |
|---|---|---|---|---|
| 1 | 57.2 s | 17 | yes | `0x3ca7c04000` |
| 2 | 54.5 s | 16 | yes | `0x3ca7c04000` |
| 3 | 53.6 s | 16 | yes | `0x3ca7c04000` |
| 4 | 54.2 s | 16 | yes | `0x3ca7c04000` |
| 5 | 53.2 s | 16 | yes | `0x3ca7c04000` |

Each run's two frames, taken 3.2 s apart, were read by eye: the HUD clock went from `01'59"` to `01'56"`. Run 1's extra press
was a D-pad press that had not shown when the retry came. The cursor was read again, so nothing overshot.

## What this does and does not prove

- Proven: the real `mercs_bot.Boot` and `Navigator` with the real `re4_switch.screen / step / pressed / wandered`, using the
  same frame grab (`adapters.grab_png`) and the same input (xdotool keys from `SWITCH_KEYS`) the worker's adapter uses.
- Not proven: the walk inside a worker autoplay job. That path stays closed until `mercs.ready` is true (`mercs_bot.title_engine`).
- Not proven: other characters or stages. The selects were matched with Leon and Village highlighted, which is what a fresh
  boot shows. Moving the highlight takes the frame out of its reference, so the walk would wait, not press.
- All five boots were in-session resets. A reset stops Citron's process tree and starts the same NSP on the same display.

## Why the frame, and how it reads

The title task's menu state has no RAM anchor, so `re4_switch_screens.py` reads the capture frame. Over 114 labelled frames
of one boot walk, classification was right on every menu row, and fades stayed unnamed.

| screen | how it is named | measured |
|---|---|---|
| title, THE MERCENARIES, Select Stage | 64x36 thumbnail RMSE to a stored reference, limit 3 | own screen 0.2-1.7, others at least 14 |
| Select Player | the same, limit 12 | the highlighted portrait pulses, reaching 8.9; others at least 35 |
| main menu, EXTRAS | fixed logo pixels (mask from a full pan of the background), limit 11.5 | menus up to 10, title 14.4, others 41+ |
| the cursor's row | median height of the red text in the menu box | unique across both menus, tolerance 5 px |
| in a round | clock digits plus the line under them | line 0.58-0.62, digits 0.067-0.078 (Leon, Village) |
| story: save list, BUY, attache case | RMSE to frames from the 11-06 wander, limit 12 | ends the run through `wandered` |

The dark scene after the stage's loading screen is the round's intro. Its banners type out letter by letter over a moving
camera, so no picture names them. `Reader` names it only after this walk has picked a stage and seen the black, and presses
A until the HUD shows, at most 12 times.

## Three rules that keep a confirm off the wrong row

1. **No press on a screen no frame has named.** The driver has no `BOOT_KEY`, because `Boot` presses it on "unknown".
2. **A confirm only on the row the walk has read as its target.** The cursor opens on LOAD, and a confirm there loads a story
   save. Row order: main menu EXTRAS = 5, EXTRAS THE MERCENARIES = 2.
3. **One confirm per screen per gap** (`CONFIRM_GAP_S`). A second A while a screen fades lands on the next screen's default row.

## What caused the 11-06 "confused" wander

Presses sent as two `session_op` jobs (one down, one up) hold the button for about 2.5 s because of job-queue latency, and
nothing checked the screen between them. That walked title -> LOAD -> a save -> the merchant -> the attache case. A quick tap
moves exactly one row: `session_op send_input` with down and up in one `events` list, or the worker's direct `send`.

## Known gaps for the next steps

- **"You Are Dead" reads as `loading`**, and so does the "Do you really want to quit?" prompt after `Continue > No`. Both are
  dark, and neither is safe to treat as a load once a round has run. The results screen has not been captured yet.
- `Driver.screen()` still returns `own_screen(snap)`, which is RAM only, so it says `loading` during a round. The engine reads
  that method, not the menus' `screen()`.
- The HUD limits were measured on one character and stage. Re-measure before the walk picks others.

## Files on the Spark

`~/gBox_alt/scratch/agent/`: `re4sw_walk.py` (this acceptance: `re4sw_walk.py 5 reset` against the session in
`re4sw/sid.txt`), `re4sw_collect.py` (frame collection), `re4sw_build.py` (rebuilds `re4_switch_screens.json`),
`re4sw/ds/` (the 114 labelled frames, including the death and quit screens).

Save backups: `~/gBox_alt/switch-saves/010099A00BC1E000-20261106-090017-before-menu-walk.sav` and
`RE4-SAVEDATA000-before-menu-walk-20261106-090017.tar.gz`.
