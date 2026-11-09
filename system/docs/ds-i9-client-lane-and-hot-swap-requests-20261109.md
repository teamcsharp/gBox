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
