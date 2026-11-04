# RE4 Switch: RAM map + autoplay driver (title 010099A00BC1E000, The Mercenaries)

Resident Evil 4 on Nintendo Switch, title `010099A00BC1E000`, update 1.0.2. ROM on the NAS:
`/mnt/gbox/quickswap2/Emulation/_switch/Resident Evil 4/Resident Evil 4 [UPDATE 1.0.2] [010099a00bc1e000].nsp`.

Mode: **The Mercenaries** (RE4's Switch Mercenaries mode - *not* "No Mercy", which is RE5/RE6). "RE4" always means
this Switch edition, never the GameCube G4BE08 build.

**STATUS 2026-11-04: PENDING live measurement.** This document is the scan plan. The driver scaffold
(`gbox/mercs/titles/re4_switch.py`) and the map scaffold (`profiles/gamedata/010099A00BC1E000-ram.json`,
`mercs.ready: false`) are in place with every live constant set to `None`; filling them here drives the driver.

## Why this is not like RE5 / RE6 Switch

RE5 and RE6 Switch are MT Framework (singleton managers, `MtDTI` class descriptors, the `sUnit` interface-unit
line that names the menus - see `docs/research/re5-switch-ram.md`, `re6-switch-ram.md`). **RE4 Switch is a port of
the 2007 HD / PS2 / PC build and does not use any of that.** Its layout is the RE4 engine's, the same one the
GameCube driver reads (`gbox/re4_merc_bot.py`, `gbox/re4_menus.py`, `profiles/gamedata/G4BE08-ram.json`):

- a global work area **pG** (room id, Leon's health),
- a player object (position, facing, health),
- the **EmMgr** enemy table (base pointer / count / stride, then a `cEm` record per Ganado),
- a **Mercenaries game struct** (countdown clock in frames, combo, kills, score),
- the **title.cpp task** with a **TW** work area on the heap holding the menu routine state and the menu cursors.

What is shared with re5_switch / re6_switch is only the *mechanism*: ARM64, little-endian, ASLR (so everything is
`module_base + offset`, pinned by a 64-byte main signature), reads through `gbox.adapters.SwitchLinuxAdapter`
(Eden, single-core, NCE: guest address == host address) over `/proc/<pid>/mem`. The GameCube build is big-endian
PowerPC with fixed addresses; the Switch port keeps the same *structure* but the *offsets* and the *endianness*
differ and are measured fresh.

## Environment for the scan (Eden on lilspark)

- Eden only (`switch_linux_emulator="eden"`). The live-scan step requires pausing the live RE5/RE6 rotation on
  lilspark and launching an **agent-owned** RE4 Switch Eden session there (coordinator confirms the stream-pause
  window with the operator first).
- Control plane: lilspark `10.89.1.246:8765`, `Authorization: Bearer $(cat gbox-data/api_token)`,
  `x-gbox-actor: deploy` for reads, `x-gbox-actor: agent` for the agent-owned launch.
- Tools: `job_read_memory` / `job_write_memory` / `job_memory_search` for the live reads/writes (read back every
  write), `job_get_frame` / `capture_worker_screen` for gameplay-frame evidence. Static side: dump the update's
  ExeFS `main` NSO from Eden and disassemble (capstone / Ghidra) to name the managers, as was done for RE6.

## Scan order (minimize the stream-pause window - target the essentials first)

Measure only what gets RE4 to a driveable Mercenaries round first; refine later.

1. **main signature + `module_base`.** Read 64 read-only bytes of `main` at a stable offset that is unique in the
   module; set `SIG_OFF` and `SIGNATURE` in the driver (and the build id in the map title). Verify `module_base(m)`
   relocates across a reboot. (Pattern: `re5_switch.module_base`.)

2. **pG global work area (`S_PGLOBAL`, `PG_ROOM`, `PG_HP`).** Find the pointer that holds the current room id
   (`0x04RR` while in a Mercenaries stage) and Leon's health. GameCube hypotheses: `pG+0x4FA8` u16 room,
   `pG+0x4FB0` s16 health. Confirm room changes when you enter a stage; confirm health drops on a hit.

3. **Player object (`S_PLAYER`, `P_POS`, `P_ROT`, optionally `P_HP`).** Pointer to Leon's object; his position
   (3*f32, cm) and facing (f32, rad). GameCube: `player+0x94` pos, `player+0xA4` facing. Walk and turn to confirm.
   Health may live in pG (step 2) rather than the object - set `P_HP` only if it is in the object.

4. **EmMgr enemy table (`S_EMMGR`, `E_POS`, `E_HP`, `E_FLAGS`).** The anchor holds `{+0 base, +4 count, +8 stride}`
   (`<QII` on Switch). Per `cEm`: position (3*f32) and health (s16 hp, s16 max). GameCube: `enemy+0x94` pos,
   `enemy+0x320` hp. `E_FLAGS` is the alive/active test (GC uses an alive bit at +0x00 and a `+0x398 == 0xFF` dead
   marker); set it so dead/empty slots are skipped. Spawn multipliers can push the count past 128 (read budget
   `MAX_ENEMIES = 512`).

5. **Mercenaries game struct (`S_MERC`, `MERC_TIMER`, `MERC_COMBO`, `MERC_KILLS`, `MERC_SCORE`, `MERC_PHASE`).**
   Clock in frames (seconds = frames / `MERC_FPS`; Switch is 60 - confirm the decrement cadence). Combo, kills,
   score. A phase field (0 intro / 1 playing / 3 over) if the port exposes one; otherwise derive the screen from
   the clock + Leon's pointer (`own_screen` already handles both). Cross-check against the results screen (kills /
   max combo / score), as the RE5 scan did.

6. **Menus - the TW work area (`S_TITLE_TASK`, `TW_ROUTINE`, `TW_SUB`, `TW_MENU_CURSOR`, `TW_MERC_CURSOR`,
   `TW_PLAYER_CURSOR`, `TW_STAGE_CURSOR`) and `title_work()`.** This is the critical path to *reach* a round. On
   GameCube `gbox.re4_menus.tw` finds TW by locating the title task in the scheduler and reading the routine table
   saved beside TW on the task's stack. Port that walk to the Switch task layout (or find a static pointer to TW),
   then confirm the cursors:
   - `TW_ROUTINE` (GC TW+0x00): 5 = main menu, 6 = extra games (The Mercenaries), 7 = a game starting.
   - `TW_SUB` (GC TW+0x01): within routine 6, 0x08 = Select Player, 0x0C = Select Stage.
   - `TW_MENU_CURSOR` (GC TW+0x28): main-menu cursor (walk to THE MERCENARIES).
   - `TW_MERC_CURSOR` (GC TW+0x54): 0 GAME START / 1 EXIT.
   - `TW_PLAYER_CURSOR` (GC TW+0x55): 0..4 (Leon..Wesker).
   - `TW_STAGE_CURSOR` (GC TW+0x56): 0..3, a 2x2 grid (Village 0, 1 right, 2 down, 3 down-right).

7. **Controls (`CONTROLS_READY`, `AIM_BTN`, `FIRE_BTN`, `RELOAD_BTN`).** Confirm the Switch pad mapping live
   (aim held + fire + reload) before the brain fires. Until `CONTROLS_READY = True` the first-cut brain only turns
   to face the nearest Ganado, so a scan session never wastes ammo blind.

## Driver first cut (what "driveable" means here)

`gbox.mercs.titles.re4_switch` already has the full plumbing so the scan only fills constants:

- `module_base` / `snapshot` / `own_screen` / `screen` / `step` / `wandered` / `pressed` / `warm_probe` mirror
  re5_switch; `RE4Switch(Driver)` and a first-cut `Bot` (face nearest living Ganado -> aim -> fire) are in place.
- Menu walk: title -> `main_menu` (-> THE MERCENARIES) -> `mercs_title` (GAME START) -> `select_player` (target
  Leon) -> `select_stage` (target Village) -> round. `jump_at = "select_player"`.
- Deliverable for the first cut: RE4 reaches a Mercenaries round under autoplay (gameplay frame + a RAM read that
  shows the clock counting and the player/enemies populated), then flip `mercs.ready` to `true` and add `re4` to the
  rotation (`titles=["re5","re6","re4"]`, preferred_edition re4 Switch). Report to the coordinator before changing
  the rotation.
- Refinements after the first round (match re5 / re6): line-of-sight gating, no wall shots / no standing on mines
  (memory `gbox-bot-no-wall-shots-no-mine-standing`), combo routing, time-bonus hunting, mods parity with re4_gc.

## Open questions for the scan

- Does the Switch port keep a `MERC_PHASE` field, or must the screen be derived from the clock + Leon's pointer?
- Is Leon's health in the player object or in pG? (Set `P_HP` vs `PG_HP` accordingly.)
- Does `TW` relocate per boot (heap), and is the GC task/stack walk portable, or is there a static TW pointer?
- World units: GC is cm (`units_per_m = 100`); confirm on the Switch port.

## Live session 2026-11-04 (lilspark Eden) - VERIFIED findings

A live window on lilspark Eden confirmed the groundwork; the deep struct map was NOT reached this window (a ~20 min
first-run shader-cache build consumed it before the title screen). What is verified:

- **Cataloged.** RE4 Switch is in the catalog as game_id **`270a15eb98dab4d7`** (path-hash of
  `quickswap-switch:Resident Evil 4/Resident Evil 4 [UPDATE 1.0.2] [010099a00bc1e000].nsp`). It was missing because a
  whole-library scan aborted on an unrelated corrupt zip; a scoped `scan_library(libraries=["quickswap-switch"])`
  indexed it. A scanner hardening (catch `BadZipFile`/`TarError` in `catalog.scan`) is committed so this can't recur.
- **Boots and renders on Eden/NCE with the current prod.keys.** The master-key/boot risk (memory
  `gbox-switch-prodkeys-block`) is CLEARED for this title: Eden loaded `010099A00BC1E000 | resident evil 4 (64-bit) |
  1.0.2`, mapped guest memory (`address_mode` direct), and drew frames. No key error.
- **Module build ids** (Eden boot log, for NSO identification / signature anchoring):
  - `main` = **82C2A04A21D3E0B850F273D4149C9003**  (this is `BUILD_ID` in the driver)
  - `rtld` = E701850BDB94823AFB3C0F133137832BF0E8D666
  - `subsdk0` = 2E8D3A967B3539EB77F50D1647380378CD481ACF
  - `sdk` = F7C7B7A90ECDC2D41C97508CC7236B8AF973B76C
- **Memory layout:** `Core.memory_layout_mode = Memory_4Gb`; single-core (`use_multi_core=false`); NCE direct, so a
  guest address IS the host address inside the Eden arena (per-boot arena base e.g. `0xf9f599fc0000`). Reads/writes via
  `job_read_memory`/`job_write_memory`; cheat-search via `job_memory_search`.
- **Input:** Eden pad tokens (gbox.yuzu_runtime.SWITCH_KEYS) for `send_input` events `[{"key","down"}]`:
  `a b x y l r zl zr plus minus start select dup ddown dleft dright up down left right lup/ldown/lleft/lright ...`.
- **Caveat - first boot is slow:** RE4 Switch sat ~20 min on Eden's "Launching..." loader building its shader/pipeline
  cache from empty (the cache persists on disk, so subsequent boots are fast). RE5/RE6 Switch boot fine on the same
  Eden. Any future live window should reuse the warm cache (boots to title in seconds).

## Follow-up: how to finish off-stream (no live stream needed for most of it)

The remaining work is the struct map + autonomous menu-walk + combat. Two routes, both need only a SHORT non-stream
slot (the heavy writing is offline):

1. **Static (preferred for offsets + signature):** obtain `main.nso` and disassemble it (capstone/Ghidra) to find the
   manager singletons (pG / EmMgr / the Mercenaries game struct / the title task) and struct field offsets, and pick a
   stable 64-byte `.rodata` run for `SIG_OFF`/`SIGNATURE`. Get `main.nso` via Eden's own `Debugging.dump_nso=true` -
   a one-off RE4 launch dumps the decrypted NSOs within seconds of load (no need to reach the title). External
   extraction (hactool / NSP decryption) is OUT in this environment - dump_nso only.
2. **Live cheat-search (for the in-round values):** on a warm-cache RE4 boot, drive to a Mercenaries round and use
   `job_memory_search` (playbook below). Convert found absolute addresses to `module_base + offset` once the
   signature pins `module_base`.

Decision (2026-11-04): both halves are folded into ONE focused warm-cache live window (no separate stream blip);
everything above is prepared so that window is short.

The driver (`gbox/mercs/titles/re4_switch.py`) is structured so these results drop straight into the pending
constants; `mercs.ready` flips to true only after a verified round, then `re4` joins the rotation
(`titles=["re5","re6","re4"]`).

## Turnkey memory_search playbook (for the one combined live window)

Preconditions: RE4 session_id known, worker lilspark (280b43b136f54c19), RE4 driven to a Mercenaries round by pad
input (`job_session_op op=send_input args={"events":[{"key":"<k>","down":true/false}]}`; Eden keys: a b x y l r zl
zr plus minus start select dup ddown dleft dright ...). Each `job_memory_search` call: `session_id`, `op`
(start|next), `cmp` (changed|unchanged|increased|decreased|eq|ne), `type` (u32|s16|f32), optional `value`.

- **A. Eden dump_nso (boot-stable anchors):** one RE4 launch with dump_nso on; read the dumped `main` NSO; pick
  `SIG_OFF`+`SIGNATURE` from a stable `.rodata` run; disassemble to confirm the manager-singleton module offsets
  (pG / EmMgr / the Mercenaries game struct / the title task). `module_base` is then found live by that signature.
- **B. Mercenaries clock (strongest anchor - decrements every frame):** `op=start type=u32` snapshot; wait ~2-3 s;
  `op=next cmp=decreased`; repeat 3-4x. The clock is the candidate decreasing at ~30/s (GC stores frames at 30/s;
  confirm cadence - Switch may be 30 or 60) and matching the on-screen time. Also try `type=f32` in case the port
  stores seconds. Read +-0x40 around the hit for kills/combo/score neighbours (GC: combo at merc+0x28).
- **C. kills / combo / score (increase on a kill):** `op=start type=u32` with no recent kill; fire and kill a
  Ganado; `op=next cmp=increased`; repeat over 2-3 kills. Cross-check against the results screen after the round
  (kills / max combo / score), exactly as the RE5 scan did.
- **D. player position + health:** position - `op=start type=f32`, move Leon, `op=next cmp=changed`; stand still,
  `cmp=unchanged`; repeat 2-3 cycles -> the 3 contiguous position floats (GC player+0x94). Health - `op=start
  type=s16`, take a hit, `op=next cmp=decreased` (GC: pG+0x4FB0 s16; may be in pG, not the player object).
- **E. enemy table (EmMgr):** isolate via the live enemy count changing as Ganados spawn/die, or pointer-scan from a
  found enemy pos. GC shape: EmMgr {+0 base, +4 count, +8 stride}; per-enemy pos+0x94, hp+0x320/+0x322.
- **F. menu cursors (TW):** at each menu (main_menu / THE MERCENARIES / Select Player / Select Stage) press up/down
  and `op=next cmp=changed` to isolate the cursor byte. Anchor TW to a static pointer via the dumped NSO so it is
  boot-stable (GC codes: TW_ROUTINE 5/6/7, TW_SUB 0x08 player / 0x0C stage, cursors +0x28/+0x54/+0x55/+0x56).
- **G. convert to offsets:** with `module_base` pinned by the signature, each static anchor offset =
  found_absolute - module_base; heap-object fields are read through the manager pointer chains, not fixed offsets.

Value ranges to recognize candidates (from GC): Mercenaries clock <= 1200 s; combo a small int; Ganado HP ~100s-1000s,
bosses up to ~6500 (Dr. Salvador, Village); score grows by hundreds per kill; player pos floats in cm.

## BLOCKER (2026-11-04): RE4 Switch does not boot on lilspark Eden v0.2.1 (GB10) in EITHER core mode

Before any RAM mapping can happen, RE4 must reach a running state. It does not, on the current Eden:

- **Single-core** (the shipped config, `_MT_FRAMEWORK_EDEN`): the guest HANGS. It executes no code at all -
  `job_memory_search` start->next cmp=changed showed 0 of ~813,773,824 u32 values changing over 15 s (two passes),
  while Eden's "Launching..." loader animated host-side. RE5/RE6 boot fine single-core on the same Eden, so this is
  RE4-specific. (Why RE4 specifically stalls single-core is not yet known - a service/thread it waits on.)
- **Multi-core** (tried live via a temporary `_RE4_EDEN` override, use_multi_core=true): the guest now EXECUTES to
  ~3 s, then CRASHES - Eden log: `Unmapped Write32 @ 0x...F42400 / 0x...E400`, then
  `Break: ... Unknown break reason 0XE401, info1=0x...43A21558` and `Emulated program broke execution! reason=0xE401`
  with an ARM backtrace into nnSdk at PC. This is the SAME Eden v0.2.1 multi-core thread-migration bug documented for
  RE5/RE6 (a thread moves itself between cores via SetThreadCoreMask, Eden loses it -> InvalidHandle 0xE401, threads
  jump to PC~0, SIGSEGV/break 3-4 s in) - which is exactly why RE5/RE6 are forced single-core. So RE4 is caught: the
  single-core mode that fixes RE5/RE6 hangs RE4, and the multi-core mode RE4 might want hits the 0xE401 thread bug.

The temporary multi-core override was reverted on lilspark and in this branch (it is not a working fix on this Eden).

### Fallbacks to get RE4 booting (need infra / deeper debugging, not a RAM-map task)
1. **Newer Eden / yuzu-successor build** (most promising): the 0xE401 crash is an Eden v0.2.1 thread-handling bug; a
   build that handles the cross-core thread migration should let RE4 boot MULTI-core. Then re-apply `_RE4_EDEN`.
2. **Citron** (multi-core; a different fork): may or may not hit the same 0xE401. Rendering is broken on the GB10
   (memory gbox-switch-render-fix-2026-11-03), but if the GUEST executes under Citron the RAM map could still be done
   there (rendering is a separate concern from a memory scan).
3. **Debug the single-core hang**: attach the gdbstub on a single-core RE4 boot and find where the guest stalls (the
   service/thread it blocks on). If a targeted stub/fix frees it, single-core (no 0xE401) would be the cleanest path.
4. Firmware/service-stub differences for RE4 1.0.2 (less likely - its NSOs load and decrypt fine).

Until one of these makes RE4 reach a running state, the RAM map / driver cannot be measured and RE4 cannot join the
rotation. The driver scaffold, menus, fire-gates and the memory_search playbook are all ready for the moment it boots.
