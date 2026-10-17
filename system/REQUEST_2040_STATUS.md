# Request #2040: Unlock all content in RE4 GC (game 78ab9efa2e310db4)

## Status: IN PROGRESS

## What we know:
- Game: Resident Evil 4 (GameCube), catalog ID 78ab9efa2e310db4
- Items inventory exists: profiles/gamedata/78ab9efa2e310db4-items.json (80+ items)
- No unlock profile exists yet for this game
- No custom build unlock profile posted yet
- REA analysis pending on sparkDeux

## What needs to be done:
1. Complete REA/Ghidra analysis of RE4 GC executable to find:
   - Character unlock logic (hidden characters, selection menu)
   - Difficulty/level unlock flags
   - Mode unlock flags
   - Item spawn/give routines
   - Save file format and progress flags

2. Implement unlock writer in gbox/re4_gc_unlock.py or similar

3. Post profile via:
   POST /api/custom-build-unlocks/78ab9efa2e310db4/profile
   with executable_sha256, inventory_complete, implementation, ghidra_artifacts, runtime_artifacts

4. For each build:
   GET /api/custom-build-unlocks/78ab9efa2e310db4/BUILD/manifest
   POST /api/custom-build-unlocks/78ab9efa2e310db4/BUILD/verify

## Workspace:
- Task workspace: /home/ehm_eckx/gbox-hermes-tasks/3abd0b9b41e6429a
- Workdir: /home/ehm_eckx/gbox-hermes-tasks/3abd0b9b41e6429a/system
- Branch: hermes/request-2040-1792260538216941221
- Baseline: 323429b71255fd098bc1204d725d0a4e393dd3f2

## Next steps:
- Check REA job status on sparkDeux
- Begin Ghidra analysis of RE4 GC executable
- Document findings in workspace
