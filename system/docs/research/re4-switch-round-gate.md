# RE4 Switch (010099A00BC1E000): entering a Mercenaries round

Measured 2026-11-04 20:48–21:20 CST on **lilspark** (NVIDIA GB10, aarch64) with **Citron NEO nightly
d3df71e55** (`citron_nightly-d3df71e55-linux-aarch64-use-nopgo.AppImage`), the build
`gbox.local-lilspark.toml` names. Production Citron home, production settings: Vulkan (`backend=0`),
`use_multi_core=true`, `cpu_backend=1` (NCE), async shaders + async presentation on via the per-title
file. No emulator setting was changed to make this work.

## The round entry

**THE MERCENARIES loads its stage with the round-intro tips on screen and holds the whole round behind
them.** Until they are paged, the round looks frozen — and it is, by design of that screen:

| symptom while the intro is up | after paging the intro |
|---|---|
| banner *"Eliminate as many Ganados as you can before your evac chopper arrives!"* stays indefinitely | banners advance through their tips (*"Successive kills will result in earning you more points!"*) |
| no HUD timer, no score, no enemy spawns | timer counts down from `02'00"00`, score `0`, Ganados walk in |
| left stick does nothing (10 s hold: no displacement) | locomotion works |
| ZL does not raise the weapon | aim works (laser sight, ammo counter) |

**A** (the pad's A) is the only button that advances them. Measured with the HUD's top-left box as the
oracle (`maxima` 0.29 with no timer, 0.84 once it draws):

- 0 presses, 2 minutes idle: still the first banner, no timer.
- 1 press: no timer.
- 3 presses: timer live, round running, spawns and movement confirmed.
- 6 and 10 presses: same (further presses are harmless).

So `INTRO_PRESSES = 3`, `INTRO_GAP_S = 0.9` in `gbox.mercs.titles.re4_switch` (`round_entry_events()`),
mirroring how the GameCube bot walks menus in `gbox.re4_menus`: press, never wait for the clock.

Verified live after entry: timer `01'41"60` and `01'36"44` on successive frames, a Ganado entering at the
left fence, Leon displacing under the stick, the laser sight out under ZL, and `You Are Dead` with
`Continue Yes/No` when he was left standing among the spawns. The renderer, spawn director, AI, damage
and the round clock are all healthy on this build — only the intro gating made it look otherwise.

## Why "renders but the gameplay loop is frozen" is not a build or settings question

Five configurations, each from the title screen to the round with the same key sequence, all produce the
identical frozen intro (frame RMSE vs the first round frame ~0.010, no timer, no movement):

| Variable | Values | Result |
|---|---|---|
| `Core.use_multi_core` | `true` (production), `false` (Eden's setting for RE5/RE6) | identical |
| `Cpu.cpu_backend` | `1` NCE, `0` Dynarmic | identical |
| `Renderer` async shaders + async presentation | on (per-title), off (globals) | identical |
| LayeredFS `load/010099A00BC1E000/romfs` → the NAS's extracted 13 GB base romfs | present | identical |
| shader / pipeline caches | purged | identical |

The install is **update-only** — Citron logs `base control_nca=true`, `version=0`,
`active_update_found=false`, i.e. the `UPDATE 1.0.2` NSP is being run as the base game — but the data is
complete (the title, movies, menus and the whole village render), so this is not a missing-content fault.
Citron reads 10.7 GB of the 12.97 GB NSP before the round, then stops reading once the stage is up.

## Correction to the first pass of this investigation

An earlier version of this document concluded that the guest stalls between `PopLaunchParameter` and the
first `Service.SET` / `Service.HID` calls. **That was wrong.** The evidence was a `citron_log.txt` that
stopped at ~4 s — but that was the *private lab home*, which hangs deterministically at ~4 s in this build
(see below). In the production home the log continues normally (`Service.NS` at 26 s during the round),
the guest is healthy, and the round is simply waiting for input.

`InitializeApplicationInfoBase: ApplicationInfo init required` is also not a fault: it appears at the same
point in working runs.

## Caveats for future lab work on this box

- **Use the production Citron home** (`gbox-data/runtime-linux-aarch64/citron-linux`), backing up
  `config/citron/qt-config.ini` (`*.gboxlab-backup`) and restoring it after. A private home (own `XDG_*`,
  `nand`/`keys`/`sdmc` symlinked into the production ones) hangs deterministically at ~4 s at
  `PopLaunchParameter`, with no window and no guest progress, while the production home boots in ~24 s.
- **Only one Citron at a time.** Two instances sharing one nand kill each other at ~4 s.
- The title screen's mean brightness (~0.10) equals the round's, so a brightness test cannot identify it;
  matching against a stored reference frame (`compare -metric RMSE` < 0.02) can.
- Launch/menu recipe used: `c`, `Down`×4, `c`, `Down`×2, `c`, `c`, `c`, `c` (title → MAIN MENU → EXTRAS →
  THE MERCENARIES → GAME START → Leon → Village → round), then `c` three times for the intro.
