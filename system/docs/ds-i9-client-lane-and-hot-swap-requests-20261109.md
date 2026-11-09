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
