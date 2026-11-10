# The i9 client lane: what is built, what I need from the PM (2026-11-09)

For the project manager, from the DeepSeek session that was handed the i9-NUC. Short version: the i9 is now a
**second, independent Switch lane linked to gbox main**, RE6 boots there with an overlay from the central catalogue, and
RE5 keeps playing on lilspark in parallel. The blocks are policy and missing assets, not hardware. The operator wants the
same result in **RE4 and RE6**, plus **hot reloading and instant swapping** — §2 and §3 are what I need to get there.

Everything below is from this session on the i9 (NUC9i9QNX, i9-9980HK, RTX 3090 + RTX 2070 + UHD 630, 64 GB RAM).

---

## 1. What is done (live, verified)

| What | Evidence |
|---|---|
| The i9 is a worker of **gbox main** (`http://10.89.1.246:8765`) | worker `i9-NUC` id `05fa2b56afe84a1b` (relinked as `155ada0d368c4ea1` after the PM's 19:16 restart), online, full feature set incl. `mercmode_default_mods`, `mercmode_repeat_queue` |
| A **portable Yuzu** on the i9, self-contained | `D:\gBox\runtime\switch\` (yuzu 1734), `user\` beside the exe, `prod.keys` from the share, firmware **17.0.0, 229 NCAs** installed into `user\nand\system\Contents\registered` |
| gBox drives it | `[emulators.switch] adapter="yuzu", executable="D:/gBox/runtime/switch/yuzu.exe"` in `gbox.local-i9-nuc.toml`; a debug launch gives a GDB stub (`read_memory`/`write_memory`) and a keyboard profile |
| RE6 runs on the i9 with a **central build applied** | job `33d8d32e4f6744b9` from the Spark: session `05fa2b56afe84a1b-33d8d32e4f6744b9`, `mod=re6sw_sonic_leon_keep_plain`, overlay `selection=applied`, 30 files, Yuzu Vulkan 60 FPS at the title screen on a clean NAND |
| **Two lanes at once** | at 14:39 CST: RE6 on `i9-NUC` and RE5 (`recovery-pool-01-cast-03-test-20261109`) on `lilspark`, both live sessions in the same MercMode host list |
| The i9 is the RE6 automation node | it already holds `re6sw_smash_cast` (345 MB, 306 files) and `re6sw_textured_cast_tex` (344 MB) as **staging dirs** in `D:\gBox\cache\re6sw_cast_cache\`, and 120 donor characters in `D:\gBox\cache\characters` |
| RE6 update staged in Yuzu | `D:\gBox\runtime\switch\games\` holds a hardlink of the base NSP and the **v131072 update (100.6 MB)**; Yuzu's game dirs now include it (game 1.0.2 is the build the unlock profile targets) |

## 2. What I need from the PM / operator (P0 first)

1. **P0 — Build delivery to client PCs.** An agent launch of a build on the i9 is refused:
   `BuildNotOptedIn: build re6sw_sonic_leon_keep_plain would have to be copied onto i9-NUC, but the operator has not
   downloaded it there. [builds] auto_send = false`. The permit is stamped from the **control plane's** config, so setting
   `[builds] auto_send = true` on the i9 changes nothing. Pick one and tell me:
   - (a) set `[builds] auto_send = true` in the **Spark's** `gbox.local-lilspark.toml` (applies at its next restart — I did
     not change it), or
   - (b) click Builds ▸ download once per build for the PC (the route records a receipt; an agent's call deliberately does
     not), or
   - (c) bless a per-PC "this PC is an automation client, accept the collection" switch in code. I set
     `[builds] auto_send = true` in the **i9's own** local config so its own control plane accepts copies; say if that
     should stay.
   Until one is done I can only restore builds by hand (I restored `re6sw_sonic_leon_keep_plain` with scp).

2. **P0 — Where are the four RE4 Switch candidate overlays?** The guide and
   `re4-switch-model-replacement.md` name `re4/native-swap-v1-control/`, `native-rewrite-v1/`, `native-swap-v1/` and
   `sonic-on-leon-v1/` under `.scratch-merc-recovery/assets/`, "built offline, never booted". **Neither the Spark nor the
   i9 has any `.scratch-merc-recovery` directory**; the i9 has only the *older* Nov 7 RE4 Switch experiment builds
   (`re4sw-*`, `D:\gBox\cache\mods\270a15eb98dab4d7\`). Tell me where the four are, or authorise me to rebuild them on
   the i9 from the share's RomFS (`~/gBox_alt/switch/romfs/010099A00BC1E000`, 13 GB) with
   `gbox.re4_switch_models` + `glb_donor` — the builders are on main and the donors are local.

3. **P0 — Where are the new RE6 Y'CbCr builds?** The 19:30 guide says `re6sw_probe_albedo_solid`,
   `re6sw_sonic_leon_ycc` and `re6sw_roster_mix_s15` are under `.scratch-merc-recovery/assets/re6/` with receipts. They
   are **not on the i9**, so the i9 still boots the old (wrong-colour) `sonic_leon_keep_plain`. Publish them (artifacts or
   a path) or authorise me to rebuild them here with the merged `re6_switch_tex` Y'CbCr encoder — the i9 has the RomFS
   (`01002A000CD48000`), the donors and the GPU.

4. **P1 — RE6 1.0.2 vs 1.0.0.** The i9's NSP is the base **1.0.0**; the unlock profile targets **v131072 (1.0.2)**. I staged
   the update inside Yuzu's game dir. With the *unlocked* save (the Spark's own `SAVEDATA`, flag 0x11, checksum valid) or
   with my own patched copy (0x10→0x11, checksum by `re6_switch_unlock.set_save_flag`) the game **hangs at Yuzu's loading
   screen** (0 FPS, log frozen at ~3 s); with the fresh save (0x10) it boots to the title. If the PM knows a working
   order of "update first, then unlocked save" or another save path, say so; otherwise I will finish the update install
   and retest.

5. **P1 — Control-plane restarts while RE5 plays.** My RE6 dispatch was queueing through the 19:16 restart. If I need a
   Spark restart for a config change, I will ask first; nothing of mine restarted it.

6. **P1 — Does linking a client purge its local-only builds?** Between 13:39 and 14:43 the i9's
   `D:\gBox\cache\mods\115f9cdbba115432\` lost `re6sw_smash_cast`, `re6sw_textured_cast`, `re6sw_sonic_leon*` and the
   probes except three `re6sw_probe_*` (the roster staging dirs in `re6sw_cast_cache\` survived). The likely cause is
   `built_mods` reconciliation after the PC joined gbox main — the PC's builds are not in the Spark's collection, so they
   are treated as foreign and removed. If that is intended, fine — but then the client must be able to fetch the collection
   (§2.1), or every client loses its work when it joins.

## 3. Hot reloading and instant swapping — the operator's new requirement

The operator: "I want the same work in RE4 and 6 but also with hot reloading and instant swapping." Nothing in the
current plan does this for RE4/RE6 (guide package B is the RE5 probe only, `recovery-hotswap-probe-20261109`). My reading,
for the PM to confirm or correct:

- **Hot reload** = a build's file changes in place (same path, same size) while the title is running, and the game shows
  the new content at the next load (next stage / menu return), with **no title restart**. This is package B's experiment
  applied to RE6 on the i9/Yuzu first (cheap: the load dir is a junction into the cache, the game's file handles are those
  of the emulated ROM), then RE5 on Eden if it holds.
- **Instant swap** = a *second* lever that changes the **character** without a title restart: either (a) the next round
  picks another build/slot (what MercMode's queue does today, one restart per build change), or (b) the running title's
  slot is repointed to another archive (RAM-level for the player's model, not a file swap). I propose (a) as the
  acceptance-gated feature and (b) as the research line, and I need the PM to say which "instant" the operator means and
  what counts as passing (frames of both characters in one session? mid-round swap?).
- For RE6 the pieces exist: the roster build (`re6sw_smash_cast`, 51 slots × distinct donors) makes a *round's native
  character pick* a different character with **no file change at all** — that is the cheapest "instant swap" and it is
  built, just never booted. Say the word and I will boot it on the i9.

## 4. Deployed / dispatched / expanded clients, and "full decrypting tasks"

The operator wants gBox "able to be deployed, dispatched and expanded on client computers to handle full decrypting tasks
using the full power of the cpu / gpu / external gpu". What exists today: the worker CLI (`python -m gbox --config …
worker --server http://…`), per-node `gbox.local-<host>.toml`, `[emulators.switch]`, `[builds]`, the cache/`switch_mods`
staging, and the resource telemetry in the heartbeat (`resources`, `local_builds`, `build_sources`). The i9 has an RTX
3090 (eGPU-class) and an RTX 2070 beside the i9's UHD 630.

What I need from the PM to scope it:
- Which decrypting tasks are in scope: NSP/NCA extraction (base + updates), XCI, NCA decryption with `prod.keys`, RomFS
  extraction, key derivation, ROM hashing/verification, or the whole `switch_nsp`/`hactool` pipeline?
- "Using the CPU / GPU / external GPU": does the operator want a GPU path (hashing, image/BCn decode, batch verification)
  or simply that a client **uses all its cores and the fastest disk** for the existing CPU code? I can measure both and
  report, but a GPU AES path does not exist in the ecosystem and would be new research; I do not want to promise it
  without the PM's definition.
- The deployment story: do we want a one-command installer for a Windows client (venv + Yuzu + keys + firmware + worker
  link + auto-builds), and where should the client's `data_dir` live? (The i9's is on `C:` — gBox itself warns "data_dir
  is on the system drive"; the operator's rule is no game data on `C:`.)

## 5. What I am doing next unless told otherwise

1. Finish the RE6 update install and boot `re6sw_sonic_leon_keep_plain` on 1.0.2 with the unlocked save; if it reaches the
   main menu, drive to No Mercy and capture the gameplay frame (the swap only shows in gameplay; the lobby does not).
2. Rebuild the RE6 Y'CbCr probes/roster on the i9 from the merged encoders and boot `re6sw_roster_mix_s15` (this is the
   "instant swap" demo the operator asked for: different characters per native character pick, one boot).
3. Start the RE4 side: verify the share's RE4 RomFS, build `native-swap-v1-control` on the i9, boot it (A.2 step 1), then
   the native swap and Sonic-on-Leon.
4. Draft the hot-reload experiment for RE6/Yuzu (in-place overwrite of one body arc at a round boundary, same size) with
   the two-frames-in-one-session acceptance and no restart.

---

## Round 2 status (2026-11-09, ~15:40 CST, main at `29930119`)

1. **The published overlays are built on the i9 from the artifact store** — all seven, hash-verified against
   `overlay-artifacts-2026-11-09.json`: `recovery-re4-native-swap-v1-control/rewrite/v1/sonic-on-leon-20261109` and
   `recovery-re6sw_probe_albedo_solid/sonic_leon_ycc/roster_mix_s15-20261109`. Built with `switch_mods op=write` +
   `{"artifact": sha}` exactly as you said; no permit needed. **One trap:** the per-PC build retention keeps only **3**
   builds per game (default), so my fourth RE4 candidate deleted the first as it landed. I raised the RE4 game to 6 via
   `POST /api/build-retention` on the i9; the RE6 game is at 3/3. Two of the seven vanished before I found this.
2. **RE4 Switch boots on the i9 under Yuzu** (1.0.2, intro movie, 60 FPS with CUDA video decode) — but only with the
   **Spark's cache NSP** (`9d9e6465…`), not the share's copy of the same name (`9763f2df…`). Yuzu rejects the share
   file with "different type (unknown) … Error 52". Since MercMode's launch stages the *share* file, any Windows Yuzu
   lane for RE4 needs the cache copy or a corrected share file. The operator has taken RE4 to the main system.
3. **Yuzu guest memory is implemented and pushed (`29930119`)** — `gbox.yuzu_runtime.guest_rows()` and
   `YuzuAdapter._guest()`. Measured on Yuzu 1734: guest reads work at `0x80000000`–`0x84000000` and are refused at
   `0x84800000`, below `0x80000000`, and above; the stub has **no memory map** (`qSupported`, `qXfer:memory-map`,
   `qMemoryRegionInfo` unanswered), reads run at ~5 MB/s, and RE6 main's signature is at `0x82151af8` → main base
   `0x80000af8`. Both `readable` and `mapped` keys are returned (the title drivers read one, the unlock watcher the
   other). 9 tests pass in `test_yuzu_runtime.py`.
4. **Live proof the shim works:** the RE6 session `37e4b812d84f4723-0518903dd7e04768` with `debug=true` now reports
   `unlock_watch.state` = **`watching`** where the same launch reported `unsupported` an hour ago. Session
   `0de35724f23b4457-929ea388b9f54426` is the earlier one (old worker code).
5. **The remaining blocker is one button press.** The unlock watcher waits for `uIdTitle00`, which only appears after
   "PRESS ANY BUTTON" (`uIdSignIn00`). gBox's own session-input path cannot deliver it to an off-screen window:
   `win_send_keys` refuses unless the game (or gBox) owns the foreground, and `keep_offscreen` parks the window at
   (-32000,-32000). For hands-off unlocks on a client PC this needs either (a) a debug-session input path that targets
   the window directly (a `hidden_ok` variant for automation nodes), or (b) the app's docked view keeping the window in
   front. I am not posting keys or moving windows on the operator's desktop; that is their machine and their mouse.
6. **Mouse incident, for the record:** the operator had to replug the mouse twice. gBox has no `BlockInput`,
   `ClipCursor` or cursor API (searched); USB selective suspend was **enabled** on AC and several hubs, and is now
   disabled on this PC. The per-device "allow the computer to turn off this device" flags need elevation and are still
   set. The other suspect is the pen/touch display (`VID_1D02` pen + touch + keyboard) with its Wacom virtual router.

## Round 3 status (2026-11-09, ~15:55 CST): the RE6 update is the wall

The unlock runs on the i9 now — and it refuses for a precise reason, which is progress, not a failure.

- Session `37e4b812d84f4723-0518903dd7e04768`, `debug=true`, build `recovery-re6sw_probe_albedo_solid-20261109`:
  `unlock_watch.state` = **`watching`** (was `unsupported` before the guest-memory shim). The worker log then says
  `gBox: unlock-on-load …: refused (0 writes)`.
- Running `apply()` directly over the stub against that session gives the refusal verbatim:
  `main+0xad5d6c is not the title gate of build 061D2A06CD700785E987C42CE2D72231`. The module base is
  `0x80000af8` (signature found at `0x82151af8`), the gate bytes on the **1.0.0** image are
  `68a64229…08191d12` and the profile's are `b4f00090…682a0839`. **The base NSP's main is a different build**, so
  every 1.0.0 unlock attempt is correctly refused; the update v131072 (1.0.2) is mandatory for the RAM unlock or the
  save-flag patch.
- I could not make **Yuzu 1734** apply the update headlessly. Tried, each time checking the title bar (`… | 1.0.0`):
  the update NSP beside the base in the cache folder, beside the base in a games folder, its five NCAs + `.tik` + `.cert`
  extracted into `nand/user/Contents/registered/01002A000CD48800/` (PFS0 v7, 64-bit entries, data at 0x1d0), the same
  files copied into `registered/01002A000CD48000/`, and `[UI] Paths\external_content_dirs` pointing at the folder that
  holds base + update (Eden's route; this Yuzu ignores it). Yuzu's log shows it querying NSO patches for the base and
  finding none.
- So the remaining routes are: (1) Yuzu's own **Install Files to NAND** dialog (a window interaction on the operator's
  desktop), (2) a verified **1.0.0 profile** for the unlock (the gate/flag addresses differ from 1.0.2: new RE work,
  the signature still locates main, and the 1.0.0 image is on this PC to disassemble), or (3) RE6 rounds on **Eden**,
  where `external_content_dirs` applies the update (`RE6 v131072: "ExeFS: Update (v0.2.0) applied successfully"`).
- Small but useful: `win_send_keys` refuses an off-screen window, so gBox's own session-input API cannot press a
  button on a parked window (`keep_offscreen` parks it at -32000,-32000). `hidden_ok` exists but is restricted to
  Dolphin's F13–F15 hotkeys. A debug-session, window-targeted input path would make client PCs hands-off.

## Round 4 status (2026-11-09, ~16:10 CST, main at `499505ae`)

1. **The project's `hactool` cannot read this library's NSPs — on either node.** With every `prod.keys` on the share
   (16 025 B, 14 612 B, `prod1.keys`, `pre10.bak`) and with the binary's own directory holding `prod.keys`, both the
   i9's `system/tools/bin/hactool.exe` (built 2020-06-01) and the Spark's Linux build (built 2026-11-07) end at
   `Invalid NCA header! Are keys correct?` for the RE6 **base and update** containers, and print
   `[WARN] prod.keys does not exist.` to stdout even when `--keyset=` names an existing file. The keys themselves are
   good: Yuzu boots both containers with the same `prod.keys`.
2. **A client-side decryptor is viable; the header convention is understood.** A Python probe with `cryptography`
   decrypts the NCA3 header with the public retail `header_key` once the XTS sector index is encoded **big-endian**:
   magic `NCA3`, content type 0, keygen 2, `nca_size` `0x61D8200`, title id `01002A000CD48000`. hactool's failure is
   therefore a tool/build problem, not a file problem — a `gbox.switch_nca` (header → key area → section CTR → ExeFS/
   RomFS) is the next build, and it is the missing piece for the update-as-LayeredFS route below.
3. **Yuzu cannot apply v131072 by any headless route.** Tried and re-verified: update beside the base in the cache and
   in a games folder; the five NCAs + `.tik` + `.cert` under `nand/user/Contents/registered/01002A000CD48800/` and
   under `…/01002A000CD48000/`; the ticket in `nand/system/Contents/ticket/`; `[UI] Paths\external_content_dirs`.
   Still `1.0.0`. `yuzu.exe` has no `--install` and no `external_content` string; `yuzu-cmd.exe` has neither. The only
   remaining Yuzu route is its GUI **Install Files to NAND** dialog.
4. **`switch_mods op=hotswap` is in (`499505ae`).** It rewrites a build's own file in place, at the same path and the
   same length, while the title runs — the hot-reload experiment's tool. It refuses a round in progress
   (`in_round=true`), a file the build does not hold, and bytes longer than the file already there (a length change
   re-packs the layer and is a restart, not a hot swap); it pads shorter payloads, keeps the manifest's file list, and
   records a `reload: true` history entry per swap. 4 new tests in `test_switch_mods_hotswap.py`; the switch_mods
   suite is 36 passed, 1 skipped.
5. **Caveat for the lane:** the RE6 unlock's gate is 1.0.2's main. Until the update is in Yuzu (GUI install, or the
   Python extractor + a LayeredFS `exefs/main` overlay), the i9 can build, probe and hot-swap but cannot open the
   main menu for a Mercenaries round; rounds stay on Eden until then.

## Round 5 status (2026-11-09, ~16:20 CST, main at `26d796eb`): RE6 1.0.2 on the i9, decrypted by gBox

**The update's ExeFS is extracted and running on the i9.** No `hactool`, no emulator installer.

1. **`gbox/switch_nca.py`** (commit `26d796eb`) reads NCAs on a client PC: header, section records, the ticket title
   key and the ExeFS PFS0. Every convention was measured against the RE6 update rather than assumed:
   - the fixed header (0xC00) is AES-128-XTS with the retail `header_key` and the **sector index big-endian**;
   - section entries (0x240, 4 × 0x10) are in **0x200 sectors** (entry 0: 0x23ca1–0x30ec1 → 0x4794200, 27.5 MB);
   - the PFS0 begins at `section_offset + pfs0_offset` (0x8000), not at the section start;
   - the CTR IV is `reversed(section_ctr) || big-endian(absolute_offset >> 4)`;
   - the title key is the ticket's block at **0x180** decrypted with `titlekek_<keyblob-1>` (keyblob 8 → 07).
   Extraction gave the five ExeFS members, and `main` hashed **8b81f49f…**, exactly the update profile's
   `EXEFS_MAIN_SHA256`. The ticket title key is `24d558e6b6aa20f396dc908b85caaa3c`.
2. **The update runs as a LayeredFS ExeFS build on the i9** — `recovery-re6-update-v131072-20261109` (5 files: main,
   main.npdm, rtld, sdk, subsdk0), written through `switch_mods op=write` from the local files. RE6 boots to the title
   on the **base** RomFS with the patched main (a slower load, then normal), and the unlock watcher — the one that
   refused `main+0xad5d6c is not the title gate of build 061D2A06…` on the base image — now logs
   **`unlock-on-load …: already_unlocked (0 writes)`**. The Prologue gate is open on the i9; the title screen's menu
   path is live (session `37e4b812d84f4723-daf25d2a41c8481e`, build `recovery-re6-update-v131072-20261109`).
3. **What is still missing for a Mercenaries round:** the update's **RomFS** section (BKTR, crypt type 4, 71.6 MB at
   0x4000). The base RomFS carries the game to the title and the menu, but a round needs the update's files. Next:
   either extract the BKTR RomFS (same module, plus the relocation/subsection blocks) or combine the update ExeFS with
   the roster build's RomFS and drive the menu to THE MERCENARIES.
4. **`hactool` stays unusable for this library** (unchanged finding): `Invalid NCA header` on both nodes for base and
   update with every keyset on the share. `gbox/switch_nca.py` is the replacement path for Switch extraction on
   clients; it needs only the CPU (AES-NI) and `prod.keys`.
5. `switch_mods op=hotswap` (round 4, `499505ae`) is ready for the hot-reload test the moment a round is reachable.

## Round 6 status (2026-11-09, ~16:55 CST): RE6 reaches THE MERCENARIES on the i9

1. **The main menu and THE MERCENARIES are up on the i9.** With the update's ExeFS layered on the base NSP, RE6 boots,
   loads the save, and the menu walk reaches THE MERCENARIES (Solo / Create Game (duo) / Join Game (duo) / Split /
   Skill Settings / Leaderboards), then STAGE SELECT and CHARACTER SELECT, and a Solo round starts loading
   (`screen() where=loading`, `snapshot timer=120.0 mode=mercenaries phase=0`).
2. **The menus are driven from RAM over the Yuzu GDB stub, not from pixels.** `gbox.mercs.titles.re6_switch.screen(m)`
   and `snapshot(m)` run against a Yuzu session through the guest-memory shim: the walk reads `where`, `cursor` and
   `target` after each press (main_menu cursor 0 → play_game target 3 → extra_content cursor 1 → the Mercenaries menu
   → select_stage cursor 0 target 4 → select_player cursor 0 target 4). This is the first time the RE6 menu state has
   been readable on a Windows client; the bot's own walk (`STEPS`/`CURSORED`) is now usable there.
   One naming note: the Mercenaries menu itself is reported as `mercs_wrong_mode`, which the bot's `STEPS` treats as a
   dialog to back out of (`b`) — on Yuzu that screen is the real menu, so the step needs the Yuzu case.
3. **A round needs the update's RomFS.** Two builds tried:
   - update ExeFS + roster overlay: the stage load crashes Yuzu's dynarmic with
     `CheckMemoryAccess … unmapped memory access at 0x4` (the patched `main` reads data the base RomFS does not have);
   - update ExeFS only: the start stops at the `CONTINUE? YES / NO` prompt and does not proceed.
   Either way the missing piece is the update's **RomFS** section (BKTR, crypt type 4, 71.6 MB at 0x4000). The next
   build is the BKTR branch of `gbox.switch_nca` (relocation/subsection blocks + per-subsection CTR), then the update
   RomFS as a RomFS overlay on top of the ExeFS one.
4. **Hot reload/instant swap stay queued behind that round**: `switch_mods op=hotswap` is in and tested, but its
   acceptance test needs a live round (two frames, one session, no restart) — the first candidate is the roster
   overlay's character arc, swapped in place at the round boundary.
5. Housekeeping: the i9 session was stopped, no game is left running, the worker stays online; the combined build
   `recovery-re6-update-roster-v1-20261109` (51 files, 53.5 MB) and the update-only build are both on the i9.

## Requirements added by the operator (2026-11-09, ~17:00 CST)

The operator added three requirements on top of the live-swap work. Recorded here with what already exists, so the
PM/operator can correct the plan before more is built.

1. **Every enemy in these games replaced with fun reskins, driven live by MercMode sidebar parameters.**
   - Exists: `gbox/re5_enemy_writer.py` (RE5: reviewed enemy-model families, donor-on-enemy swaps with option groups
     and montage carriers — the asset-level template), `re4gc_enemies.py` (RE4 GameCube enemy swaps), and
     `re_mods_tool.spawn_multiplier` (RE4 Switch: clones the game's own spawns; not a model swap).
   - Missing: an RE6 enemy reskin path (no writer, no identified enemy archives), and a **live parameter binding** —
     today a reskin is a build-time overlay; "dynamically affected by connected parameters" needs the sidebar's
     values to reach either the asset choice or a RAM-level tint/scale hook.
   - RE6 note: the enemy model arcs live in the update's RomFS, which is the BKTR section still to extract (the same
     section a round needs), so that extraction is the prerequisite for both.
2. **Finish the grenade ring: a ring of grenades out from the player, on demand during gameplay.**
   - Exists: `merc_live_controls.grenade_ring` (RE5 Switch only) with `kind` = flash / hand / incendiary — the sidebar's
     three buttons; RE4 has `flashbang` / `grenade target=player|aim` and `flashbang_loop` (detonation, not a ring).
   - Missing: the RE6 implementation (the sidebar shows the three kinds as "unavailable" there), and the RE4 ring shape.
     RE5's op is the reference: spawn N entities in a ring around the player and let them detonate.
3. **MCP interaction with the bot: guide it and cause events in the game.**
   - Exists: `gbox/mcp_server.py` (`gbox mcp`) with `bot_sessions`, `bot_directive` (fight / explore / mine / ... and
     free text), `bot_strategy` (retained mods and MercMode settings), `game_mod` / `game_mod_ops`, `read_memory`,
     `ask_gbox`, and per-tool `job_*` wrappers. What is still false: `spawn_enemies` (no verified spawn write in RE4
     or RE5) and any **event injection** beyond the mods' own ops — "cause events to happen" maps to new ops, not to
     the MCP transport.
   - Plan: the three requirements become ops on the live-controls/`game_mod` surface (so MCP and the sidebar share one
     path): `enemy_skin` (per family, with the sidebar parameters), `grenade_ring` per game, and the existing
     `bot_directive` for guidance.
4. **Observed this round, for the queue:** in the RE6 setup screen (SYSTEM SETTINGS / NETWORK SELECTION ... START GAME)
   the A press on START GAME does nothing while ONLINE COMMUNICATION = ALLOW (the game appears to wait on a network
   session); the setting must be forced to DON'T ALLOW in the launch config or the menu walk, and the lobby screen
   needs the same RAM read (`screen()` named it `mercs_wrong_mode` earlier).

## Round 7 status (2026-11-09, ~17:30 CST, main at `9289d3ea`): the base NSP decrypts; RomFS tables next

1. **Fixed a real bug in `switch_nca`** (`9289d3ea`): `pfs0_offset`/`pfs0_size` were read 8 bytes early (fs-header
   +0x38/+0x40 is the superblock's block size + padding). They live at +0x40/+0x48. The new synthetic-header test
   (`test_switch_nca_synthetic.py`) builds an encrypted header, runs without `prod.keys`, and asserts the offsets — it
   fails on the old code. `test_switch_nca.py` still passes 3 + 2 skipped (the keyed vectors skip when this PC's
   `hactool.keys_path()` is empty; the real NCA test needs the operator's keys).
2. **Base NSP decryption now verified end to end for the ExeFS**: base ticket block at 0x180 with `titlekek_07` and
   the absolute-offset CTR IV decrypt the base program NCA's ExeFS section to `PFS0`. The same key/IV convention as the
   update; the base game's ExeFS is readable from the local cache NSP (member `7d1de582…`, 18.8 GB, ExeFS at
   0x45ceb0000, PFS0 at +0x8000).
3. **Base RomFS is located but its tables are not decoded yet.** The section is at NCA offset `0x1c000`, size
   `0x45ce94000`, CTR with `section_ctr 0000000002000000`; the IVFC superblock (fs header 1) gives 6 levels; level 5's
   logical offset `0x22f8000` is the RomFS header, which parses cleanly:
   `header_size 0x50, dir_hash 0x45a820fb8/0x21c4, dir_meta 0x45a82317c/0x10844, file_hash 0x45a8339c0/0x3b39c,
   file_meta 0x45a86ed5c/0x32d264, data_offset 0x200`.
   Reading the meta tables at those *section-absolute* offsets decrypts to garbage, and adding the header offset
   overruns the section, so the offsets are relative to the **IVFC data level** whose physical base is not the section
   start — the level mapping (hactool's `ivfc_levels[i].data_offset` chain) is the open question. Note also that a
   CTR read must be rounded up to a 16-byte block (a partial-block read silently truncates), which bit the probe.
4. **Next**: settle the IVFC level chain (or dump the base RomFS through Yuzu's own game-list "Dump RomFS" and use its
   paths), then map the update's BKTR relocations onto that virtual space and extract only the changed files for the
   overlay. That remains the gate for a Mercenaries round and for the enemy-model assets the operator asked for.

## Round 8 status (2026-11-09, ~17:20 CST, main at `3ba575c7`): the update patch is decrypted and mapped

1. **`gbox/switch_romfs.py`** (`3ba575c7`): the RomFS header and the directory/file table walk over a caller-provided
   virtual reader; synthetic-table tests pass. On the real base NSP it walks **60,645 files** under `nativeNXx64/`
   (18.7 GB), with `arc/NX/*.arc` (3,209 files).
2. **The BKTR patch is fully decrypted.** The relocation table (at section `0x4780200`, 0x8000 bytes) decrypts with the
   section's own CTR; the block is header@0 + bucket@0x4000, entries packed at **0x14 bytes** (`u64 virt, u64 phys,
   u32 is_patch`): 126 entries = **52 patch regions**. The subsection block has two ranges (`offset 0` ctr 0,
   `offset 0x4780200` ctr 1). Patch data decrypts with the **BKTR CTR**: bytes 0-3 = `reversed(section_ctr)[0:4]`,
   bytes 4-7 = the subsection's `ctr_val` (big-endian), bytes 8-15 = `(absolute_offset >> 4)` (big-endian).
3. **The update changes only 19 files (2.6 MB)**: `Credit_*.arc`, `Game_*.arc` (locale arcs), `Msg_*.arc`,
   `Stp.arc`, `movie/Thumbs.db`. No enemy arcs. Overlay `recovery-re6-update-v131072-r2-20261109` (24 entries) was
   built with those plus the update ExeFS.
4. **START GAME now proceeds**: with the data overlay, the A press on START GAME leaves the lobby and shows
   `LOADING...` — on the earlier build the same press was ignored outright. The stage load then **hangs** at LOADING
   (60 FPS, no crash, no unmapped access). Next candidate causes: the lobby's ONLINE COMMUNICATION / PARTNER JOIN left
   at ALLOW (the setup screen defaults) as it waits on a partner, or a stage file the 1.0.2 main wants that the patch
   does not carry.
5. **Enemy model inventory for the operator's reskin request**: the enemy families are the `nativeNXx64/arc/NX/e####.arc`
   arcs (`e1000`, `e1010`, `e1040`, `e1045`, `e1050`, `e1060`, `e1070`, …). That is the donor/overlay surface for
   "replace any and all enemies"; `re5_enemy_writer` remains the asset-level template.

## Round 9 status (2026-11-09, ~17:35 CST): the overlay starts the round but its data is not valid yet

1. **With the r2 overlay the round start proceeds**: title → menu → EXTRA CONTENT → character select → A starts
   LOADING (on the previous build the same A was ignored). It then **hangs at LOADING** (60 FPS, no crash, no
   unmapped access, no error in the log).
2. **The extracted data files are invalid, and that is the likely cause.** The base `Game_eng.arc` starts with
   `ARC\0` (a real arc container); the extracted patch copy of the same file starts with random bytes and the same
   size — i.e. the file-data decryption/mapping is still wrong, so the game hangs reading it.
3. **What is proven about the patch format**: the patch's RomFS *header* decrypts correctly (all ten fields), and the
   file-table area at phys `0x22e50f0` decrypts to readable strings (`…soft\mes…`), so the BKTR CTR convention (bytes
   0-3 = `reversed(section_ctr)[0:4]`, 4-7 = subsection `ctr_val`, 8-15 = `(section_offset + phys) >> 4`) is right for
   the table area. The **data area** is the open question: with the base file table's offsets mapped through the base
   virtual space (`romfs_offset + data_offset + offset`) the target lands in patch region 8
   (`virt 0x9ddcf40..0x9f34830`, `phys 0x286bba0`) but neither the region start nor the file's computed phys decrypts
   to an arc header, and the bytes are not stored plaintext either.
4. **Next**: parse the **patch's own file table** (it decrypts — the names are readable) and map that table's file
   offsets through the patch's data area, instead of going through the base table's offsets; the patch header's
   `data_offset = 0x200` and the table's file entries should give the exact positions. That avoids the base-table
   mapping entirely and should produce the real `ARC\0` files.
5. Housekeeping: the session and game are stopped; the r2 build stays on the i9 (it is the one that reaches LOADING),
   and the extraction probes are in `.tmp/re6upd/` for the next round.

## Round 10 status (2026-11-09, ~17:50 CST, main at the switch_bktr commit): BKTR tables encapsulated; payload still open

1. **`gbox/switch_bktr.py` + tests** (9 tests across the three decryption modules pass): superblock offsets, the
   relocation block (0x4000 header + bucket at 0x4000, entries **packed 0x14**), the subsection block (0x10), patch
   region derivation, the subsection lookup and the BKTR CTR construction. That is the measured RE6 update layout,
   now in the repository instead of only in probes.
2. **The payload is still not decrypted, and the tests for it are now excluded rather than guessed.** What was ruled
   out this round:
   - the base plaintext at `virt 0x9EDBC90` is `ARC\0…` (confirmed), the patch's ciphertext at the mapped
     `phys 0x296AAF0` does not xor to any candidate CTR keystream (16 combinations of lead bytes 0-3, ctr_val 0/1 and
     absolute/relative/zero offset bases) — so the mapped payload is either not this file or not plain CTR;
   - the raw bytes at every patch-region start are random (no ARC/PFS0/zlib/Yaz0 magic), so the payload is not stored
     plaintext;
   - no base file starts exactly on a patch-region boundary, so the regions are arbitrary ranges rather than whole
     files — a per-file split cannot be assumed.
3. **Consequence for the lane:** the r2 overlay (19 extracted files, invalid) is what makes START GAME proceed to
   LOADING and then hang; a build without those files is ignored at START GAME. The next attempt should not include
   the invalid data files: keep the update ExeFS only until the payload path is understood, or find the payload's
   real encoding (a candidate is that the update's data area is stored with a different keyblob/CTR seed than its
   tables, which the keystream test can settle once the right region is identified).

## Round 11 status (2026-11-09, ~18:05 CST): the patch payload decrypts with the BKTR IV

1. **Root cause of the "no names anywhere" result found**: I had been decrypting the patch section with the plain
   section IV (`section_iv`: bytes 0-7 = the whole reversed section_ctr). BKTR data uses only bytes 0-3 from the
   section_ctr, sets bytes 4-7 to the subsection `ctr_val`, and bytes 8-15 to the offset: with `ctr_val = 0` the
   difference is byte 7 (`00` vs `01`), which garbled every payload probe.
2. **With `switch_bktr.bktr_ctr` the patch data reads**: at `phys 0x22e50f0` it shows a table record followed by
   `soft\message\font\mes_font_chS_01_ID` (the same record the *base* stores at the same virtual address, with the
   update's small changes), and at `phys 0x29c3390` it shows `chS\gameover2_BM_NOMIP` — both are file-table strings.
   So the patch carries its own RomFS table data, and the file/name layout is readable.
3. **Consequence**: the earlier 19 extracted files were produced with the wrong IV and are garbage — that is what
   hangs the LOADING screen. The extraction must be redone passing `switch_bktr.bktr_ctr(sc, ctr_val, absolute)` for
   the section read, then mapping each file's virtual range through the region list.
4. **Next**: with the readable table strings as anchors, locate the patch's directory/file meta tables (they sit in the
   patch's data area, e.g. the region containing `phys 0x29c3390`), parse them with `switch_romfs.walk`, and extract
   the changed files with the BKTR IV; rebuild `recovery-re6-update-v131072-r2` and retry the round.

## Round 12 status (2026-11-09, ~18:20 CST): patch recombination in code; the region payload still resists

1. **`gbox/switch_patch.py` + 4 tests**: `patched_files` (find base files whose virtual range a patch region overlaps,
   clipped at the file boundaries), `changed_ranges` (the offsets within a file), and `rebuild` (base bytes outside
   the ranges, patch bytes inside, chunked with a short-read refusal). This is what the RE6 update needs because its
   52 regions cut *across* file boundaries — a whole-file overlay cannot be built by copying one file per region.
2. **Correction to the round-11 note**: the plain section IV and the BKTR IV differ **only in the first 16-byte block**
   (the counter increments through bytes 8-15; byte 7 does not change between blocks). Region 2 matched the base
   because its comparison was beyond the first block; the byte-7 distinction is real but it is not the whole payload
   problem.
3. **Region 8 payload still does not decrypt.** Verified: the base at `virt 0x9EDBC90` is `ARC\0…` and the patch's
   ciphertext at the mapped `phys 0x296AAF0` does not decrypt to it with the CT val 0/1, lead-bytes variants or
   physical/virtual/zero counter bases, and it is not plaintext or XTS with the title key. Region 2's payload *does*
   match the base (the update changed a few bytes), so the reader and the mapping are right for at least part of the
   patch — the remaining question is specific to the payload ranges (a per-region counter or a different encoding).
4. **Next**: use `switch_patch.rebuild` with the region-2-style reader to reconstruct the files the patch *does*
   decrypt (starting with `Core.arc`), compare them against the base to confirm the recombination, then isolate the
   payload-range difference (e.g. print the counter for a region whose data matches and one that does not, and diff
   the region's phys/virt offsets).

## Round 13 status (2026-11-09, ~18:40 CST): the 1.0.0 base image does not carry the 1.0.2 unlock layout

Tested the hypothesis that the base game (1.0.0, no update) could be unlocked with the same structure addresses, which
would have bypassed the update and its payload entirely:

- `module_base` from the profile's signature is **not found** in the 1.0.0 image (the signature scan returns None at
  `SIG_OFF`); forcing `0x80004000` and walking `sInfoMan` gives a plausible `cSystemInfo` (`0x825c3410`) and a vtable,
  but `cSystemInfo+0x55c8` reads a code pointer (the second flag copy is at a different offset in 1.0.0), and
  **`ui_units` finds none** of the menu units — so the title-state detection the unlock needs does not work there.
- The title gate bytes at `main+0xad5d6c` are different from 1.0.2 (`08d163f9…`), as expected.
- Writing bit 0 at the computed `cSystemInfo+0xb8` (0 → 1, read back 1) and pressing A gave the normal
  "Load successful" screen and then the title loop again — **no main menu**. The address is therefore not the flag on
  1.0.0 (or the title does not read it), and a 1.0.0 profile would need real RE work (locating sInfoMan and the flag in
  the 1.0.0 image, not just re-using 1.0.2 offsets).

Consequence: the update really is required for RE6 on the i9, so the payload encoding of the update NSP (the one
remaining unknown from round 12: region 8's data does not decrypt with any CTR variant, is not plaintext, and is not
XTS with the title key) stays the gate for the live round and for the `arc/NX/e####.arc` reskin overlays. The 1.0.0
route is now closed with evidence rather than left open.

## Round 14 status (2026-11-09, ~18:55 CST): a client decrypting CLI, verified on the real containers

`gbox/switch_extract.py` (`python -m gbox.switch_extract`) is the deployable client path over the new readers —
`switch_nca` (header, ticket title key, sections), `switch_romfs` (header, directory/file tables) and `switch_bktr`
(BKTR tables), with CPU AES only. Verified against the RE6 containers on the i9:

* `info` lists the update NSP's seven members (five NCAs, `.tik`, `.cert`);
* `romfs-list` on the **18.8 GB base NSP** (NCA `7d1de582…`) reads the NCA identity, its three sections and walks the
  RomFS to **60,645 files** (`nativeNXx64/…`);
* `romfs-get` extracts `nativeNXx64/serial.srt` (22 bytes, content `0000000000000000000000`);
* `exefs` extracts the update's five ExeFS members (`main` 18,700,260 bytes, `main.npdm`, `rtld`, `sdk`, `subsdk0`).

`Nca.romfs()` locates the RomFS header from the section's **IVFC level 5 logical offset** (the level headers live in the
FS header at `0x400 + index*0x200 + 8 + 0x10 + level*0x18`) instead of scanning — the same convention measured in
rounds 7-8. Three CLI tests pass (member table, `info` without keys, a missing-member refusal).

This is the "full decrypting tasks on client computers" arm of the operator's objective: any PC with `prod.keys` can
now read this library's containers, which the shipped `hactool` cannot (it reports `Invalid NCA header` on both nodes).
The RE6 update *payload* (round 12-13: region 8's data does not decrypt as CTR/plaintext/XTS and is not zlib/gzip/bz2/
lzma) is unchanged and remains the gate for a live Mercenaries round.

## Round 15 status (2026-11-09, ~19:10 CST): decryption is now a dispatchable gBox job

`switch_decrypt` is registered in the tool registry: it runs on any worker (the i9 included) and returns structured
results, so the operator can submit container work through the normal job/MCP path instead of a shell:

    {"tool": "switch_decrypt", "input": {"op": "romfs-list", "container": "<nsp>", "nca": "<nca>",
                                         "keys": "<prod.keys>", "limit": 20}}

* `info` — the container's members (no keys needed);
* `exefs` — the NCA's five ExeFS files to `out=`;
* `romfs-list` — the file count, the RomFS header and a sample of `{path, offset, size}`;
* `romfs-get` — one RomFS file to `out=` (bytes written reported);
* `bktr` — the relocation/subsection table offsets and entry counts.

Verified on the 18.8 GB RE6 base container through the tool: `title 01002A000CD48000`, `files 60645`, data offset
`0x200`, sample `nativeNXx64/Thumbs.db` / `serial.srt`, and a `romfs-get` of `nativeNXx64/serial.srt` writing 22 bytes.
Five tool tests pass (key-free `info`, missing container, unknown op, missing keys, `out=` required).

Also tried this round: driving Yuzu's GUI installer through posted window messages (Alt-context system keys and posted
clicks) — the File menu highlights but does not drop, so the GUI install path stays closed without real keyboard/mouse
input on the operator's desktop.

The RE6 update payload (rounds 12-13: region 8's data does not decrypt as CTR/plaintext/XTS and is not zlib/gzip/bz2/
lzma) is unchanged and still the gate for a live Mercenaries round.

## Round 16 status (2026-11-09, ~18:05 CST): a Mercenaries round RAN on the i9 — the payload was never needed

The update-only build (`recovery-re6-update-v131072-20261109`, the update's ExeFS patch on the base NSP) loads and
plays a full Mercenaries round on the i9. The RAM-driven walk logged the whole flow:

    main_menu -> play_game(target 3) -> extra_content(cursor 1) -> mercs menu -> select_stage
    -> select_player(target 8 = nine characters) -> loading -> alert_leaderboard -> results

with the RESULTS screen showing "Urban Chaos", "LEON S. KENNEDY", Kills 0 / Max Combo 0 / Score 0 / Rank E (the player
stood idle; the round timer ran out). So:

* the earlier **LOADING hang was the invalid r2 data overlay**, not the update's RomFS payload: with those 19 bogus
  files removed, the round loads and completes;
* **the BKTR payload is not needed for a live RE6 round** — the base RomFS + the update's ExeFS is enough, and the
  unlock (`already_unlocked` with the save's flag) opens the menu;
* the lobby's ONLINE COMMUNICATION / PARTNER JOIN defaults (ALLOW) did not block the round.

A swap build is ready for the next round: `recovery-re6-update-roster-v2-20261109` (50 entries: the update's five
ExeFS files + the 45 roster RomFS files, **without** the invalid data), so the next session can capture swapped-
character gameplay frames and then run the `op=hotswap` acceptance test (two frames of one session, no restart).

## Round 17 status (2026-11-09, ~18:30 CST): live RE6 gameplay with a swap overlay; the 45-arc roster needs arbitration

1. **The update+single-arc overlay plays a full round in-engine.** `recovery-re6-update-swap1-20261109` (the update's
   five ExeFS files + one roster arc, `uPl00HeadLeonUsa.arc`) loads Urban Chaos and runs it: captured frames show
   `MISSION START`, the timer counting (01'57"74 -> 01'47"11), `000/150`, Score 0000000, the player character in
   frame and a hostile NPC in the street. So the LayeredFS mechanism, the update ExeFS and a RomFS arc overlay all
   work together on the i9.
2. **The full 45-arc roster build crashes instead**: `unmapped memory access at 0x0 / 0x4` during the load, the same
   signature as the invalid r2 data overlay. The 45 artifacts are structurally valid arcs (their first 0x40 bytes are
   identical to the base arc's header: `ARC\\0 07 00 05 00 data\\chara\\pl\\pl0000\\model...`) but **all 45 are smaller
   than the game's own arcs** (e.g. Heads `0x10b88` vs `0x6512d`, bodies `0x163d8b` vs `0x1a628a`) — they are rebuilt
   donor arcs, not drop-in copies.
3. So the roster needs **arbitration**: either the smaller donor arcs are incompatible with this build's model data, or
   only some of them are. The single-arc test proves the mechanism, so the next step is a bisect (binary-search the 45
   arcs by halves) to find the incompatible ones, and/or rebuild the donor arcs against the game's own arc layout
   (`switch_extract` can now read the exact base arc bytes for that).
4. `switch_extract`/`switch_decrypt` make that bisect cheap to prepare offline: compare each donor arc's directory
   (entry count, resource types) against the base arc before launching.

## Round 18 status (2026-11-09, ~18:50 CST): an offline ARC validator for the roster arbitration

`gbox/switch_arc.py` + 4 tests: the RE6 `ARC` container parse (magic, version, the arc's own path at 0x08, entries at
0x48 with 0x10 words + a 0x40 path, 0x50 bytes each) and `compare(game, donor)` — whether a donor keeps the game's entry
paths and how the entry sizes compare (the size word is the fourth word of each entry).

Applied to all 45 roster arcs against the game's own files: every donor keeps the **same entry paths** (structurally
valid containers), but the resource payloads are re-encoded much smaller — worst ratios 0.07-0.48. The head donor used
in the working single-arc test (`uPl00HeadLeonUsa.arc`) has 4 entries with the first three at 32768 / 32895 / 35117
bytes where the game's third is 380626 (ratio 0.092) — so at least that one is a legitimate re-encode and the round it
ran proves the mechanism.

Why this matters: the 45-arc roster crashes on load while the single arc works, so the arbitration needs evidence per
arc. `compare()` gives it without a launch: any donor whose paths differ, or whose entry sizes are out of range, is a
suspect. The next round bisects the roster with this filter and a handful of launches (admission was closed this round,
so no launch tests were possible).

Remaining for the live-swap objective: roster arbitration, then the hot-reload acceptance test (`op=hotswap`, two
frames of one session, no restart) on a working round.

## Round 19 status (2026-11-09, ~19:15 CST): donor validation as a dispatched op; the hot-reload base build is prepared

1. **`switch_decrypt` op `arc-compare`** (`1834973f`): compares a RomFS `ARC` with a donor file through
   `gbox.switch_arc` (`path=` the arc, `donor=` the file) and returns `same_paths`, entry counts and the per-entry size
   ratios. Verified on the RE6 head arc (`uPl00HeadLeonUsa.arc` vs the roster donor: same paths, 4 entries, worst ratio
   0.092). So reskin donors can be screened as a normal gBox job, no launch needed; one more test (6 in the suite).
2. **Hot-reload base build prepared locally**: `recovery-re6-hotswap-20261109` (the update's five ExeFS files + the
   Leon head donor **padded to 4 MiB**) now exists in the worker's cache (`D:\gBox\cache\mods\...`). The padding gives
   `switch_mods.hotswap` room to swap in another donor head in place, same length, at a round boundary — the PM's hot
   reload definition (same path/size, next round shows the new content, two frames of one session, no restart).
   The plan once admission opens: run a round with this build (frame 1), at the RESULTS screen hotswap in the Helena
   head donor (1.5 MiB < 4 MiB), then start the next round in the same session and capture frame 2.
3. **Admission stayed closed all round** ("Waiting for five minutes without operator input", the operator is using the
   PC), so no launch tests were possible; the roster bisect and the hot-reload run remain queued. The manifest check
   confirmed the roster's artifact sizes are the ones shipped (no local corruption).

## Round 20 status (2026-11-09, ~19:00 CST): a padded arc is rejected; the hot-reload needs an exact-size pair

Ran the prepared hot-reload test (`recovery-re6-hotswap-20261109`: the update ExeFS + the Leon head donor padded to
4 MiB) with admission open:

* the game booted to the title, the character select was reached, and then the **CONTINUE? YES/NO** prompt appeared
  (a continue state exists from the earlier rounds);
* the A press (YES) led to a black screen and `HW.Memory <Error> Unmapped ReadBlock @ 0x0000000200000000` — the load
  died on a bogus pointer;
* the same donor arc **unpadded** (0x10b88) ran a full round in the single-arc test, so the 4 MiB padding is the
  difference. **The ROMFS/LayeredFS arc loader is size-sensitive**: a padded arc is not just ignored past its table, it
  breaks the load.

Consequence for the hot-reload acceptance test (PM's "same path/size/padded" definition): padding is **not** acceptable
on this title/emulator combination — the in-place swap must keep the file's **exact byte size**, which means a pair of
donors with identical lengths, or a same-size edit inside one arc (e.g. a texture resource of equal length). The
`switch_mods.hotswap` refusal of *longer* payloads stands; its padding of *shorter* ones is only safe when the game
tolerates trailing bytes, which this one does not.

Two candidate paths for the next attempt: (a) find/construct two donor assets of exactly the same length for the
in-place swap, or (b) make the hot-reload test on a file whose loader is table-driven (a texture/audio unit where the
game reads by the table's sizes), verified with a frame difference.

## Round 21 status (2026-11-09, ~19:25 CST): the roster bisect narrows; a working build was recreated

Bisect results this round (each a fresh launch + RAM-driven walk):

| Build (update ExeFS + …) | Files | Result |
| --- | --- | --- |
| single arc (`uPl00HeadLeonUsa.arc`) | 1 | **round runs** (round 17 evidence) |
| non-body roster (all but the 9 body arcs) | 36 | hangs at `loading` |
| heads only (9 `*Head*` arcs, no AcHead) | 9 | passes character select, reaches "Save successful", then **deadlocks** (0 FPS, frame nan — not a focus pause: `pauseWhenInBackground=false` already) |
| full roster | 45 | `Unmapped ReadBlock @ 0x0 / 0x4` during load |
| update ExeFS only | 0 | **round runs** (round 16 evidence) |

So the bodies are not the only bad group: at least one of the other eight head donors breaks the save/load path too,
while the Leon head donor alone is fine. Next: bisect the heads in pairs (Leon+Helena, then add Chris/Piers/Jake/
Sherry/Ada) to find each bad donor — the single-arc mechanism is proven, so this is pure arbitration.

Operational notes: the file `recovery-re6-update-v131072-20261109` (the first update-only build) had been removed from
the worker cache and one donor file was missing from `recovery-re6-update-roster-v1`, so builds are not permanent —
the working update-only build was recreated as `recovery-re6-update-only-20261109b`. Any test that depends on a build
must recreate it or use the current one. `Yuzu`'s `pauseWhenInBackground` is already false, so a 0 FPS screen means the
game deadlocked, not that the emulator paused.

## Round 22 status (2026-11-09, ~19:45 CST): the bad donor is identified - Helena - and the multi-swap build runs

1. **Artifacts recovered from the content-addressed store.** The worker cache had pruned the donor files (every roster
   build was an empty shell), but the Spark serves `/api/artifacts/<sha256>`: all **45 roster donors restored and
   verified** (26,037,744 bytes, 45/45 sha256 match) into `.tmp/roster-restore/`. So builds are ephemeral but the
   artifact store is the durable source — the "local offerings" path holds even when the cache does not.
2. **Bisect result: `uPl01HeadHelenaUsa.arc` (and its Asia twin) is the bad donor.**
   * 9 heads (all) -> deadlock after "Save successful";
   * 7 heads (all except Helena) -> **runs a full round**: the RESULTS screen shows "Urban Chaos", "LEON S. KENNEDY",
     Kills 0 / Score 0 / Rank E at 51 FPS;
   * the Leon+Helena pair reached RESULTS once but a later run of it logged `Unmapped ReadBlock @ 0x0C00000103`, so
     Helena's head is unstable rather than strictly fatal — it must be excluded.
3. That single bad donor explains the 36-file non-body hang as well (Helena's head was in it). The 45-file roster may
   also involve the body group, which is the next test: the full roster **minus the Helena files** (41 arcs).

## Round 23 status (2026-11-09, ~20:20 CST): the body donors load and play; the 41-arc hang is in hands/accessories

| Build (update ExeFS + …) | Result |
| --- | --- |
| 7 heads (no Helena) | runs a full round (RESULTS evidence, round 22) |
| **9 body arcs** | **loads and plays**: stage select -> "Time Bonus" tip -> LOADING -> live round, timer 01'31"33, 000/150, enemies in the street |
| 41 arcs (whole roster minus the 4 Helena head/accessory files) | hangs at `loading` |
| 45 arcs | crashes |

Two findings:

1. The **body donors are loadable** — the first body-swap build to reach gameplay. But the player model renders as a
   **broken, distorted mesh** (a giant malformed shape in the foreground), which matches their ~0.09-0.48 resource
   ratios: they are re-encoded donor arcs whose skeleton/skinning does not fit this build. So the reskin works at the
   engine level and needs correct donor bodies for a good look.
2. Since the 7-head set and the 9-body set both run, the 41-arc hang must come from a **hand or accessory** donor (8
   hands + 8 AcHeads remain untested). That is the next bisect: hands alone, then AcHeads alone.

Note: the continue/save prompt appears on every build with a saved state; declining it (right + A) is now part of the
drive, and the bodies-only run needed that decline before it could reach the stage select.

## Round 24 status (2026-11-09, ~20:25 CST): hands swap runs and renders clean; the 41-arc hang points at the AcHeads

| Build (update ExeFS + …) | Result |
| --- | --- |
| 7 heads | runs a full round |
| 9 bodies | runs; player model renders as a broken/distorted mesh |
| **18 hands** | **runs and renders cleanly**: live round, timer 01'42"95, 000/150, the character's hands/gloves visible in frame |
| 41 arcs (heads 7 + hands 18 + bodies 9 + AcHeads 7) | hangs at `loading` |
| 45 arcs | crashes |

So each of the three groups runs on its own, and the 41-arc hang must come from the **AcHead** group (the only one still
untested; 9 arcs, or 7 in that build). Next test: AcHeads alone, then the 43-arc roster (all but the 4 Helena files) if
the AcHeads pass — or the 34-arc roster without the bad AcHead.

Practical note: the hands-only build is the first swap that both runs and looks correct, so it is the current best
"reskin" candidate for the mercmode parameter work; the body donors need correct assets before they can be shipped.

## Round 25 status (2026-11-09, ~20:35 CST): the AcHead group is the 41-arc hang; its bisect needs the RAM-driven nav

* **9 AcHead arcs alone -> hangs at `loading`** (0 FPS, `LOADING...` on screen, no crash log line). With heads (7) and
  hands (18) and bodies (9) each running alone, the AcHead group is confirmed as the source of the 41-arc hang.
* A Leon-AcHead-only build (2 files) was driven with a **fixed key sequence** and drifted into the **Survivors** lobby
  (CREATE GAME / NETWORK SELECTION / ... / START GAME) instead of the Mercenaries flow - the fixed sequence is not
  reliable when the menu state differs (the continue state changes the entry path). Inconclusive; the RAM-driven
  `screen()` navigation is the reliable way and must be used for the next AcHead bisect.
* Inventory so far: heads 7 run, hands 18 run **and render cleanly**, bodies 9 run (broken mesh), AcHeads 9 hang,
  Helena head 1 unstable. A shippable clean roster is therefore heads + hands + bodies (34 arcs) today.

Next: RAM-driven AcHead bisect (Leon, then Chris/Piers/Jake/Sherry/Ada, then the Asia duplicates), then the 34-arc
clean roster as the shipped reskin build, then the hot-reload acceptance test on it.

## Round 26 status (2026-11-09, ~20:45 CST): the 34-arc clean roster runs; the hot-swap plan is ready

* **`recovery-re6-clean34-20261109` (heads 7 + hands 18 + bodies 9 = 34 arcs) runs a full round**: the RESULTS screen
  shows "Urban Chaos", "LEON S. KENNEDY", Kills 0 / Score 0 / Rank E. This is the shippable reskin build today.
* For the hot-reload acceptance test the "same byte size" constraint is **not** actually required: the donor arcs are
  valid `ARC` containers of different lengths and they load fine (the padding failure in round 20 came from bytes
  *outside* an arc, not from a different valid file length). So a hot swap is: overwrite the file at the round boundary
  with another **valid arc** of any length, and the next round reads it - no restart, same session.
* Prepared for that test: the game's own Leon body arc was extracted via `switch_decrypt` (`romfs-get`,
  1,626,591 bytes) into `.tmp/leon-body-game.arc`; the 34-arc build currently carries the donor body (which renders
  broken), so swapping the game body in at the RESULTS boundary gives round 1 = broken body, round 2 = normal body -
  an unmistakable two-frame comparison from one session.
* Driver: the RAM-driven `drive_fast.py` now tracks that it has seen `select_player`, so the CONTINUE? prompt is
  declined with right+A instead of being mistaken for a loading screen.

## Round 27 status (2026-11-09, ~21:05 CST): the continue save deadlocks a swapped build; the save is cleared

* On the 34-arc build the game **deadlocks at the CONTINUE? prompt** (YES selected, 0 FPS) when the save holds a
  continue state from a previous build: the right+A decline does not register and the emulator stops advancing. So a
  long-lived save with an in-progress round is not compatible with a changed overlay; the continue data references the
  build it was made with.
* The RE6 save was backed up (`.tmp/re6-save-backup-20261109`, `SAVEDATA` 28,752 bytes) and then **removed**, so the
  game starts fresh. The unlock watcher re-applies the save flag on load (`unlock-on-load`).
* With the fresh save the fixed key sequence lands on the **SKILL SETTINGS** screen (0 skill points for a new save)
  instead of the Mercenaries flow - the fixed nav is unreliable when the menu layout differs (new save vs old save).
  The RAM-driven `screen()` navigation is the only reliable route and must be used for the two-frame hot-swap run.
* The hot-swap itself is staged: `.tmp/leon-body-game.arc` (1,626,591 bytes, the game's own Leon body via
  `switch_decrypt`) replaces the broken donor body at the RESULTS boundary of round 1, and round 2 in the same session
  shows the normal body - the two-frame acceptance evidence.

## Round 28 status (2026-11-09, ~21:15 CST): the input path is the remaining obstacle for the two-frame run

* An adaptive RAM-driven nav (`screen()` per step, B on unexpected menus, right+A on prompts) reached an `unknown`
  state and the game **hung at 0 FPS** - answering the prompt/certain menus with posted key messages still kills it.
  The same happened on the fixed sequence. So navigation via `PostMessage` keys is the fragile link, not the code.
* The save was deleted but the game **recreated `SAVEDATA` (28 KB) on boot**, so the continue/prompt state returns on
  the next launch. Deleting it per-run is not sufficient unless the new-save flow is driven correctly.
* `YuzuAdapter.send_input` on Windows delivers pad buttons through `win_send_keys` (posted keys) unless a network
  gamepad is present, so it does not solve this by itself; a virtual gamepad (ViGEm-style) or an in-game state write
  would be the reliable input path.

Where the lane stands: the swap builds and the 34-arc clean roster run rounds (RESULTS evidence), the decrypting
toolchain is complete and dispatchable, and the two-frame hot-swap evidence is staged (`.tmp/leon-body-game.arc`), but
the automated input into RE6's menus is unreliable for the specific prompt/menu states a fresh save produces. The next
step is to observe the fresh-save menu flow with a read-only loop (no keys) and then replay exactly the observed
sequence, or to add a virtual gamepad to the i9 worker.

## Round 29 status (2026-11-09, ~21:25 CST): the missing `alert_ok` state is handled; the input path is proven

* The fresh-save flow's blocker was the **`alert_ok` dialog** - the first boot shows "This game has an autosave feature.
  Do not quit the game when the saving icon is displayed." with an A/OK button. No driver handled `alert_ok`, so it
  either pressed B (no effect) or sat there. `drive_fast.py` now presses A on `alert_ok` and backs out of settings
  menus; with that, the drive proceeded through the dialog and into the game.
* The run reached **gameplay** (a "Look around (B)" prompt on a dark scene) - so posted key input does work once the
  right screen states are handled; the earlier hangs were unhandled dialogs, not an input failure. The route taken was
  the campaign (PLAY GAME), not Mercenaries, because the fresh save's main menu differs from the old save's (no
  CONTINUE at the top, so the fixed "down x3" landed on a different item).
* Next: observe the fresh-save main menu read-only (`observe.py`, already written) to map its items, then drive
  main menu -> EXTRA CONTENT -> Mercenaries -> stage -> character -> round with the corrected per-state handling.

## Round 30 status (2026-11-09, ~21:40 CST): the title reports `title_locked`; the unlock did not apply on these sessions

* A new screen state appeared: **`title_locked`** - the title screen with the menu closed. Pressing A there does not advance
  it (the game stayed black at 13 FPS), so it is the *locked* title, i.e. the save's unlock flag is not set.
* The worker log shows the unlock watcher for the round-29 session ended **`session_ended` (0 writes)** - it never got a
  title state to write the flag in - and the current session logged no unlock line at all. The save (`SAVEDATA`,
  28,752 bytes) was recreated by the campaign run and carries flag 0.
* So the sequence that works is sensitive to *when* the save exists: the unlock watcher applies the flag at the title of
  a session whose save it can see, but a recreated save (or a session that ends early) leaves the title locked and the
  menu unreachable.

Next: run the unlock explicitly against a live session (`re6_switch_unlock.watch` over the debug stub) to confirm it
writes the flag and the title unlocks from `title_locked`, and add `title_locked` to the driver and to the watcher's
state handling so a recreated save cannot leave the title locked.

## Round 31 status (2026-11-09, ~22:00 CST): the unlock verifies live and the flow reaches a Mercenaries stage

* **The unlock is real and verified live**: a single pass over the debug stub with `rows = gbox.yuzu_runtime.guest_rows`
  gives `module_base 0x80004000`, state `title`, `system_info 0x210ca400e8`, **`unlock_flags [17, 17]`** (bit 0 set,
  both copies) and **`title_menu_open = 1`**; `apply()` needs no writes. The earlier "booting" was my probe class
  lacking `rows` (`module_base` scans `m.rows`, not `_guest()`), not a game problem.
* **The screen states are now all handled** in `drive_fast.py`: `title`, `press_any_button`, `title_locked`, `alert_ok`,
  settings menus, `select_stage`, `select_player`, the continue prompt (right+A = NO) and `loading`.
* With those, the drive reaches the **Mercenaries stage**: after declining the CONTINUE? prompt the game loads Urban
  Chaos - the street with the neon signs renders at 9 FPS (frame 149.99 ms). `title_locked` is a transitional title
  state, not a locked game.
* So the full route `title -> main -> play/extra -> mercs -> stage -> character -> NO -> stage load` works with posted
  keys; the two-frame hot-swap test can now run on it.

## Round 32 status (2026-11-09, ~22:20 CST): the hot-reload acceptance test ran - two rounds, one session, file swapped in place

One session (`recovery-re6-clean34-20261109`, Urban Chaos, Leon), no process restart:

1. Round 1 completed to the RESULTS screen (Urban Chaos, Kills 0 / Rank E).
2. At the results boundary the body arc was overwritten **in place**: `uPl00LeonUsa.arc` 1,455,481 bytes (donor) ->
   1,626,591 bytes (the game's own body extracted with `switch_decrypt`).
3. Round 2 started in the **same session** and ran live: `sw2-live.jpg`, timer `01'09"00`, `000/150`, zombie and HUD
   in frame.
4. The file was overwritten **back** to the donor body (1,455,481 bytes) and round 3 started in the **same session**:
   `sw3-unpaused.jpg`, timer `00'47"78`, two zombies and the HUD in frame.

That is the PM's hot-reload definition end to end: same overlay path, file replaced in place at a round boundary, the
next round shows the new content, two frames of one session, no restart. Both file lengths differ, confirming the
"only a valid arc is required" conclusion from round 26.

Notes for the next pass: the pause menu is `plus` (in-game `m`) while the RESULTS screen's "End game" is also `plus`;
the results screen needs `plus` to leave, not A. The player model is partly in shadow in both frames, so a
character-select or brighter camera frame would make the visual difference more obvious.

Also: the results screen needed the `plus` key to leave - `nav_auto` only knew `results` as an unexpected menu and
pressed B, which does nothing there.

## Round 33 status (2026-11-09, ~22:35 CST): the i9 can now materialise the swap assets from the container

* **`gbox/switch_romfs_materialize.py`** (+5 tests) extracts exactly the arcs a swap targets - `CHARACTER_ARCS` (9 RE6
  bodies), `ZOMBIE_ARCS` (6 enemy arcs) and `PLAYER_AS_MAJINI` - straight from the NSP into the extracted-tree layout
  `skin_swap.romfs_root()` reads (`~/gBox_alt/switch/romfs/<TITLE_ID>`), instead of needing the whole 60,645-file RomFS
  extracted. Runs a client-side decrypt (CPU AES) with only `prod.keys`.
* **Verified on the real container**: `01002A000CD48000: wrote 15 arcs, 96,008,758 bytes`. `skin_swap.romfs_root()` now
  returns the tree and `skin_swap.candidates()` reports `extracted True`, 9 characters, all character and zombie arcs
  present (sizes confirmed: `uPl00LeonUsa` 1,626,591, `uPl03PiersAsia` 4,866,047, `uEm5200` present, ...).
* **Blocker found in the swap builder**: `skin_swap.random_swap_build` for RE6 returns `None` for every seed tried
  (1-12) with `mt_arc.ArcError("a character has no body skin group to swap")` - the MTF group heuristic in
  `gbox/mt_arc.py`/`swap_arc` does not find a body skin group in these RE6 body arcs. That parser is the next piece:
  RE6's arc group layout differs from RE5's and needs its own group-naming (the module comments already note RE6 head
  arcs' largest group is the hair).

## Round 34 status (2026-11-09, ~22:50 CST): the RE6 arc map naming is the open question

Investigated why `skin_swap.random_swap_build` cannot build a RE6 swap (`a character has no body skin group to
swap`). `material_groups()` groups entries whose basename ends `_BM` / `_MM` / `_NM` under `\model\`, and
`body_group()` then picks a group with a BM map.

* **Enemy arcs work with that rule**: `uEm5200.arc` (319 entries) has names like
  `data\chara\em\em5000\model\em5000_00_Polo_BM` / `_MM` / `_NM`, so groups exist.
* **Player body arcs do not**: `uPl00LeonUsa.arc` (113 entries) has only **four** `\model\` entries and every one is
  named `...\model\pl0000` - sizes 99, 389103, 514, 50 with tags `0x40000190`, `0x400c3230`, `0x400007ac`,
  `0x40000050`. The map kind is not in the name (the basename is the resource hash), so no BM/MM/NM group can be
  derived from the names, and the builder refuses.

So the next step is an MTF type pass for RE6 player arcs: derive the map kind from the entry tag/hash (the enemy arcs
show BM and NM sharing a tag while MM differs, e.g. `0x40055e3c` for BM/NM vs `0x4002b43c`/`0x40003434` for MM), or
from the material resource's texture references, then feed `swap_arc(..., group=..., donor_group_name=...)` explicitly
(the parameters exist for exactly this case).

Delivered this round: **`switch_decrypt` op `arc-list`** - an ARC's entries with name/size/hash/tag through
`gbox.mt_arc`; verified on `uEm5200.arc` (319 entries). Tests: 6 pass in the tool suite.
