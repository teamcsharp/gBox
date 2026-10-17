# Request #2040 (3abd0b9b41e6429a): Unlock all RE4 GC content — status checkpoint

## Status: IN PROGRESS — no source changes this run; exact resume point recorded.

## Workspace (tracked, preserved for next run)
- Task workspace: /home/ehm_eckx/gbox-hermes-tasks/3abd0b9b41e6429a
- workdir: /home/ehm_eckx/gbox-hermes-tasks/3abd0b9b41e6429a/system
- Branch: hermes/request-2040-1792260538216941221 (pushed to origin; PR URL:
  https://github.com/teamcsharp/gBox/pull/new/hermes/request-2040-1792260538216941221)
- Baseline: 323429b71255fd098bc1204d725d0a4e393dd3f2
- Commit this run: e4ab410 (this checkpoint file)

## Tests
- tests/test_unlock_research.py + tests/test_re4gc_inventory.py: 16 passed (python3 -m pytest -x -q, 1.25s)

## Existing artifacts reused (no new Ghidra run this run)
- profiles/gamedata/78ab9efa2e310db4-items.json: full RE4 GC item inventory, 80+ ITEM_IDs
  (weapons 0x03/0x0D/0x17/0x21-0x38/0x3E/0x40/0x52-0x53/0x6D/0x94, ammo 0x00-0x04/0x07/0x18/0x1A/
  0x20/0x46/0x6A/0x72/0xA0, herbs/health 0x05-0x09/0x12-0x16/0x19/0x1C/0xA8, grenades 0x01-0x02/0x0E,
  key items 0x0C/0xAC/0xAD, cases 0x7C-0x7F, equipment 0x3F/0x42-0x45/0xAA-0xAB/0xC5/0xFE,
  Ada weapons 0x51-0x53, infrared 0x51/0x99/0xA0)
- gbox/re4gc_inventory.py, gbox/re4gc_enemies.py, gbox/re4gc_models.py — existing RE4 GC modules
- gbox/custom_build_unlocks.py — full unlock-all acceptance framework (profile/manifest/verify;
  CATEGORIES = characters, hidden_characters, levels, stages, costumes, modes, items, extras)
- Modified ISO: exports/78ab9efa2e310db4/play_as_mario/Resident Evil 4 - Play as Mario.iso
  (sha256 178011bc7578df5042eb7762e44fe144d039655941160d9dd2cbf17cef1363f9, source crc32 f5c51b40,
  8482410 changed bytes via BPS)

## Blockers for next run
1. Vanilla RE4 GC ISO ("Resident Evil 4 (USA) (Disc 1).gcz"/iso, crc32 f5c51b40) not found in
   standard ROM locations — dolphin-user/GC has no RE4 entry; only the modified export exists.
   Must locate it before Ghidra/REA analysis (profile requires vanilla executable_sha256).
2. No Ghidra/REA analysis done yet for RE4 GC executable (no REA job running; exports dir has
   only the play_as_mario export).
3. No custom_build_unlocks profile posted yet for game_id 78ab9efa2e310db4.

## Exact next steps (resume order)
1. Locate vanilla RE4 GC ISO; compute its sha256 (becomes executable_sha256 in the profile).
2. Run Ghidra (ghidra_bridge / job_ghidra_bridge) on the vanilla executable to inventory:
   - Character selection/unlock logic (Luis, Ada, Krauser hidden selection)
   - Difficulty flags (Normal/Hard/Extreme — Extreme unlock predicate)
   - Mode unlock flags, save file layout (progress/completion flags)
   Record addresses + expected original bytes as stored artifacts.
3. Implement reusable RE4 GC unlock writer step in gbox/re4gc_unlock.py, applied to every custom build.
4. POST /api/custom-build-unlocks/78ab9efa2e310db4/profile with executable_sha256,
   inventory_complete:true, implementation, ghidra_artifacts, runtime_artifacts, inventory covering all 8 categories.
5. For each build: GET manifest, POST verify with runtime evidence.
6. Publish via publish_task_changes → draft PR; live acceptance only on idle worker (never JAYBUILTFINALE).
