# RE4 Switch (010099A00BC1E000): integration plan

What "fully integrated" means for this title, decomposed so the work is trackable. Measured base:
`docs/research/re4-switch-round-gate.md` (round entry) and `docs/research/re4-switch-ram.md` (RAM map
so far: round clock found and verified, player position confirmed).

## Where it stands

| piece | state |
|---|---|
| round entry (3 × A after the stage loads) | measured, in `re4_switch.INTRO_PRESSES` |
| round clock (f32 seconds) | found, verified against the HUD |
| player position (x, y, z) | found, confirmed spawn-fixed; host address in the RAM note |
| player facing, health | not measured |
| Ganado list (live enemies) | not measured |
| score / kills | not measured |
| `re4_switch.snapshot()/screen()` | skeleton (returns an empty world) |
| ASLR signature for the structs | not built |
| main NSO dump / Ghidra hooks | not started |
| MercMode rotation | blocked: `re_switch.preferred_spec` returns `playable: False` |

## Stage 1 — finish the map (the bot's senses)

1. **Facing**: `a`/`d` turn in place (RE4 is tank-controlled). Sample before/after a turn, find the
   float that moved by the turned angle in a 0..2π or ±π range. Gives steering.
2. **Health**: a small int near the player struct (the GC driver's `pG+0x4FB0` is s16). Verify by taking
   damage and reading it down, and by the death screen.
3. **Ganados**: the enemy list is a container, not a single struct. Two usable routes: (a) the player
   struct's nearby pointers, (b) a scan for a repeated per-enemy layout (position triple + health) that
   appears N times and disappears as they die. The GC `re4_threats.py` documents the shape to expect.
4. **Score / kills** near the clock struct (the clock is already one field of that family).

## Stage 2 — driver (the bot's hands)

`gbox/mercs/titles/re4_switch.py`: implement `snapshot()` (player, enemies, timer, kills), `screen()`
(loading / playing / dead / results), and the round-entry burst. Reinstate `playable: True` and set
`preferred_editions = {re4: switch}` for this host. Validate with `gbox.mercs` round reports, then let
MercMode rotate it. This is the point where the game is *played*.

## Stage 3 — mods layer (the Ghidra hooks and agent tools)

Model on `re5_switch_mods` / `re6_switch_mods` (same emulator, same read/write path) and on the GC
`re_mods` op vocabulary, so the app's existing RE mod panels work unchanged:

| capability | needs |
|---|---|
| flashbang / grenade deploy | the throwable slot + the action trigger on the live player struct; a spawn-and-throw op with rollback bytes |
| skin / costume swap | the costume field the selects write, plus the model/material pointer that reloads it |
| character ↔ zombie replacement | the player and enemy model pointers (same table the Ganados come from) |
| live character replacement | rewrite the live player struct's model/behaviour pointer and force a reload, with the original bytes kept for rollback |

Each op is a measured write with a rollback, an audit row, and a receipt — the same standard as every
other gBox mod.

## Stage 4 — "decrypted": NSO, functions, Ghidra

Citron can dump the title's `main` NSO (`dump_nso`, as RE6's map used). From it: the main NSO sha256 and a
64-byte read-only signature (the ASLR anchor both the RAM reads and the hooks need), the function
addresses behind the mods above, and the message/string tables for names. That is the "decryption" step —
it makes the offsets reproducible instead of re-scanned every boot.

## Reality check
Stages 1–2 are the ones that make it *playable*; stage 3 needs the same structs plus model pointers, and
stage 4 makes both stable across builds. Each measurement needs a live round (2 minutes) and a boot
(~40 s), so the loop is minutes per fact, not seconds. This is a multi-session program, not one pass —
the map is the long pole, and it is already two fields in.

### Measurement trap (learned the hard way, 2026-11-05)

Turns sampled by the first facing pass came back flat and were nearly read as "no heading in the struct".
A screenshot showed why: **Leon was already at "You Are Dead"**, so nothing could rotate. A round's first
Ganados arrive in about 15–20 s and the player is defenceless while a scan runs — any turn/aim measurement
must finish inside roughly the first 12 s of the round: find the player (≈9 s for the big heap), then
turn/dump immediately, and take a screenshot in the same run to prove the sample was taken while alive.

## Fleet note (2026-11-05): lilspark2

`lilspark2` is a second GB10 (`10.89.1.20`, 20 cores, 121 GiB) running **vLLM in Docker**
(`vllm-qwen38`, `nvidia/Qwen3.8-27B-NVFP4`, OpenAI API on `:8101`, 65k context, ~114 GiB of unified
memory held by the model). It has **no gBox checkout, no node config, and is not a registered worker** —
the fleet is i9-NUC, JAYBUILTFINALE, lilspark.

gBox's local inference route is a *different* box: `[hermes.local]` → `sparkDeux` at
`http://10.89.1.225:8101/v1` (same model, `api_format = "openai"`, `shared_with_games = false`), with
Hermes in `local_only`. Its proxy reported **0 calls since start**, so no gBox work is reaching either
machine today. Named endpoints live in `gbox-data/hermes-dispatch/local-nodes.json`; adding lilspark2 is
a node entry (additive, reversible), but pointing the route at it instead of sparkDeux is an operator
decision, not a maintenance one.

