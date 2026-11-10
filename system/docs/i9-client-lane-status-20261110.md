# i9 client lane - consolidated status, 2026-11-10

What the i9 NUC (this PC) does for gBox today, what was verified live, and what remains open. Every claim below has a
build, a job, or a frame behind it in this repo's session log
(`ds-i9-client-lane-and-hot-swap-requests-20261109.md`) and `docs/mcp.md`.

## 1. The client is linked and dispatchable

* `i9-NUC` runs the gBox worker (`gbox worker --server http://10.89.1.246:8765 --name i9-NUC`) and takes jobs from the
  Spark's control plane. It was restarted once this session after a stuck build job (the real command line and the
  `PYTHONPATH=system` / gbox-venv requirements are recorded in the log).
* Every tool in the registry is an MCP tool automatically (`job_<name>`), verified against the live registry (279
  tools); `job_switch_decrypt` is the decrypting entry point.

## 2. Decrypting: complete, measured, dispatchable

| piece | state |
|---|---|
| `gbox/switch_nca.py` | NCA header, title key from the ticket, CTR sections |
| `gbox/switch_romfs.py` | RomFS header + tables, 60,645-file walk on the 18.8 GB RE6 base |
| `gbox/switch_bktr.py` | BKTR relocation/subsection tables |
| `gbox/switch_patch.py` | patched-file reconstruction |
| `gbox/switch_arc.py` | ARC header/entry parse + donor comparison |
| `gbox/switch_extract.py` | CLI: `info`, `exefs`, `romfs-list`, `romfs-get`, `bktr` |
| `gbox/switch_decrypt.py` (tool) | all of the above as a registry job, incl. `arc-list`/`arc-compare` |
| `gbox/switch_romfs_materialize.py` | pulls exactly the arcs a swap needs (`--include uPlTex`: 56 arcs / 313.7 MB) |
| `gbox/switch_romfs_extract.py` | pool extraction (measured: sequential 0.10 s / 8 threads 0.30 s on 24.5 MB) |

The decrypting is **I/O- and open-bound at ~245 MB/s with AES-NI**; GPU offload or more threads do not help this
workload. Scaling is across containers/workers, i.e. dispatch.

## 3. RE6 live swaps (the main lane)

* A Mercenaries round runs on the i9 with the update's ExeFS on the base NSP (RESULTS screens captured repeatedly).
* Swap builds verified live: single head, 7 heads (Helena's donor excluded - it breaks the load), 18 hands (clean
  renders), 9 bodies (mesh renders broken), the 34-arc clean roster, and whole-model character swaps
  (Leon-as-Chris).
* **Hot reload acceptance passed**: one session, `uPl00LeonUsa.arc` overwritten in place at the results boundary
  (donor 1,455,481 -> game 1,626,591 -> donor), two rounds live, no restart, different file lengths.
* The MercMode sidebar drives it: `default_mods[title]` seeds `random_swap_build`/`cast_swap_build` (`base_build=`), so
  a sidebar reskin is launch-ready.
* Enemy/cast swap builds (`cast_swap_build`): six enemy arcs wearing cast models + the player in majini clothes. The
  models swap and the round runs, but the **swapped enemies render untextured**; appending the cast maps or replacing
  the enemy's texture slots both failed, so the remaining explanation is the engine's per-unit material texture binding.

## 4. RE4 lane

* `Resident Evil 4 [switch]` launches from its update NSP and reaches the title and main menu (60 FPS).
* `recovery-re4-sonic-on-leon-v1` applies (`bio4/em/pl08.udas` + a texture pack): NEW GAME starts and the intro cutscene
  sequence plays at 10-18 FPS.
* The **in-game village frame was not captured**: the intro runs far slower than real time and no key tried (A, m,
  minus, plus, A+B) skips it. Next routes: unlock Mercenaries and read the character-select 3D preview, or load a
  village save state.

## 5. Bot and events

* `autoplay` starts a learned-policy bot run on RE6 on the i9 ("146 moves learned from 16 recorded sessions").
* In-game event ops (`game_intervention`: flash, grenade ring, infinite ammo, magnum quick4) ride **autoplay runs only**
  - a plain launch has no intervention channel by design.
* On this Windows/Yuzu node the native effects report **"native flash currently requires Linux Switch NCE"**: the
  grenade ring and native flash are Linux-lane features. An i9 version would need a GDB-stub RAM spawn for RE6.

## 6. Open items, in priority order

1. **Enemy textures**: find how RE6's MRL materials bind their maps (per-unit id) so swapped enemies stop rendering
   white. The arcs, the maps and the loading path are all proven; only the binding is unknown.
2. **RE4 in-game frame**: Mercenaries preview or a save state (mechanical).
3. **RE6 grenade ring**: native mapping does not exist; a RAM-spawn implementation on the i9 is a separate RE effort.
4. **Build retention**: builds are pruned aggressively; the durable source is the Spark's artifact store by sha256
   (restore verified: 45/45 roster donors).
