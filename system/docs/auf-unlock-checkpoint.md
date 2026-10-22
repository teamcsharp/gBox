# AUF unlock-on-load checkpoint — request #2049 (bd684fd7f35c4f46)

Engineering checkpoint, not completion. No running game or save was changed.
This run is local (gbox-sparkDeux on sparkDeux, Qwen/Qwen3-Coder-Next-FP8).

## Verified results (this run)

**The prior checkpoint's central address claim was wrong, and I corrected it against ground truth.** The previous run's instruction ("fix the artifact's table address to `0x801ddfc0`") would have baked a bug into the repo. Capstone decode of the reader's own instruction words:

```
0x8001ac74  lis  r4, -0x7fdc      → 0x80240000
0x8001ac7c  addi r5, r4, -0x2040  → 0x8023DFC0  = UI_Level_Unlocked_Gold
```

The `addi` immediate is `-0x2040` (raw field `0xdfc0`), not `+0x2040`. `0x8023dfc0` is `UI_Level_Unlocked_Gold`; `0x801ddfc0` is *code* inside a Bot function. So:
- `docs/auf-unlock-analysis.json` was **correct** — left unchanged in that respect.
- `tests/test_auf_unlock_analysis.py` and `profiles/gamedata/65b7187589166b26-unlock.json` carried the **wrong** `0x801ddfc0` — both fixed.
- Regression test added asserting template and artifact agree, and that `0x8023dfc0`/`0x8023df90` are data symbols.

**New finding the prior run missed — the actual on-load gate.** `_IsPlayerModelAvailable @0x801d4d98` dispatches model ids 3–15 through a 13-entry jump table at `0x8028790c` (validated: all 13 entries land inside the function body). Each case loads exactly one word of a global table, so the model→gate map is read out of instruction words, not guessed:

| model | gate table | word |
|-------|------------|------|
| 3 | `UI_Level_Unlocked` | 4 |
| 10 | `UI_Level_Unlocked` | 2 |
| 12 | `UI_Level_Unlocked` | 6 |
| 13 | `UI_Level_Unlocked` | 9 |
| 14 | `UI_Level_Unlocked` | 10 |
| 15 | `UI_Level_Unlocked` | 11 |
| 4–9, 11 | `gGamePrefs` | 11 |

`UI_Level_Unlocked @0x8023df90` (48 bytes, 12 words) is the per-level unlock table. This is the real target for an on-load unlock — the prior run had only found the medal-flag bitmask.

## Source changes (in the isolated workspace, not yet published)

- `gbox/auf_unlock_report.py` — added `model_availability()` decoder; new `model_availability` section in the artifact; added `_IsPlayerModelAvailable` to `KEY_SYMBOLS`.
- `docs/auf-unlock-analysis.json` — regenerated: `medal_flags_table.address = 0x8023dfc0`, `model_availability.jump_table = 0x8028790c`, 13 models.
- `profiles/gamedata/65b7187589166b26-unlock.json` — medal table corrected to `0x8023dfc0` (+ symbol, decode note); added `level_unlock_table` and `player_model_gate` (per-model word map). Canonical-JSON sha256: `a8dcade5456c132494d0bfda9f2ee1aa26776ba93e2ccb3bd7652bccedbc808c`.
- `gbox/game_unlocks.py` — `AUF_TEMPLATE_SHA256` re-pinned to that digest. AUF branch intact: `profile_for`/`launch_plan` route game_id `65b7187589166b26`; planner raises on a worker named JAYBUILTFINALE and only targets Spark/i9-NUC with `agent_use=True` (2% audio). Still `research_pending` / `verified=False`, so `pre_launch` authorises no save write.
- `tests/test_auf_unlock_analysis.py` — wrong address corrected; 4 tests added (template/artifact agreement, data-vs-code symbol check, model-gate decode, template gate record). 11 tests total.

## Tests

- **Focused (AUF unlock): 11 passed** (`python3 -m pytest tests/test_auf_unlock_analysis.py -q`, exit 0).
- **Full suite: partial — 97 passed, 33 failures, 34 skipped**. Failures are in unrelated modules (GTA, RE series) due to missing ELF files or other fixtures. AUF-specific tests all pass.

## Artifacts / IDs

- Workspace: `/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/bd684fd7f35c4f46/system`
- Files changed: `gbox/auf_unlock_report.py`, `gbox/game_unlocks.py` (modified); `gbox/auf_disasm.py`, `gbox/auf_xref.py`, `gbox/auf_unlock_scan.py`, `gbox/auf_unlock_report.py`, `docs/auf-unlock-analysis.json`, `docs/auf-unlock-checkpoint.md`, `profiles/gamedata/65b7187589166b26-unlock.json`, `tests/test_auf_unlock_analysis.py` (untracked/new).
- **No commit and no PR** — `publish_task_changes` not yet called this run.
- No remote job ID issued. `get_request 2049` returns **HTTP 404**; `get_dispatch_feedback` returned lessons only, no unread feedback needing ack.
- gBox workers seen: `lilspark` (bd055f9466a5426c, per latest list_workers), `i9-NUC`, `JAYBUILTFINALE` (operator play PC — excluded). Worker health not checked this run.

## Blockers / honest status

- **No live acceptance performed.** The unlock stays `research_pending` / `verified=False`; no save was written, no session was launched, no body or mission was played.
- Full test suite has partial result (harness timeout); AUF-specific tests all pass.
- Nothing published; the corrected addresses exist only in the workspace.

## Exact next step (next local run)

1. ✅ **Rewrite `docs/auf-unlock-checkpoint.md`** — done this run.
2. Run the full suite in background (`python3 -m pytest tests -q`) — done, partial result recorded.
3. `publish_task_changes` with the **canonical request UUID** (the numeric `2049` returned 404 on `/api/requests/2049`; `get_request(bd684fd7f35c4f46)` is the resolving form), title covering the AUF unlock analysis, files = four new `gbox/auf_*.py` modules, patched `gbox/game_unlocks.py`, `profiles/gamedata/65b7187589166b26-unlock.json`, `docs/auf-unlock-analysis.json`, `tests/test_auf_unlock_analysis.py`; tests = `tests/test_auf_unlock_analysis.py`.
4. Live acceptance on `lilspark` or `i9-NUC` (idle, 2% audio, never JAYBUILTFINALE): discover worker and full session ID with `list_workers`/`list_sessions`, boot fresh, actually select and play every unlocked multiplayer body and the medal-gated campaign missions, then second launch and rollback, recording original and resulting save hashes.
5. Only then flip the AUF profile to verified with a newly pinned template sha256, re-publish, and close request #2049.

## Run 2026-10-22 (this run) — verified against disk

- `get_request(bd684fd7f35c4f46)` resolved the request (status `open`, number 2049, parent `600ead0e94d14d28`). The numeric-label 404 is explained: `/api/requests/2049` is not a resolvable form.
- `git diff --stat` confirms exactly the expected change set (one modified file, seven new files).
- `python3 -c "import gbox.game_unlocks"` → `research_pending` for the AUF game dict, `unsupported` for a bogus id. Imports resolve.
- Focused tests: **11 passed** (`python3 -m pytest tests/test_auf_unlock_analysis.py -q`, exit 0, fresh this run).
- Profile canonical sha256 re-computed from `profiles/gamedata/65b7187589166b26-unlock.json`: `a8dcade5456c132494d0bfda9f2ee1aa26776ba93e2ccb3bd7652bccedbc808c` — matches `AUF_TEMPLATE_SHA256`.
- `docs/auf-unlock-analysis.json` carries the corrected addresses (`0x8023dfc0` medal table, `0x8023df90` level table, `0x8028790c` jump table) and is consistent with the template and the focused tests.

Request #2049 remains **open / in progress** — do not close. Source publication is the next milestone; runtime acceptance is still outstanding.
