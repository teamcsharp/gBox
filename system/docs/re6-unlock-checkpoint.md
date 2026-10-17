# RE6 unlock-on-load — checkpoint (request #2042)

No source changes were made in this run. This checkpoint records the current
state of the RE6 (Xbox 360) unlock-on-load work so the next local run can
resume safely.

## State

- Verified unlock profile exists and is hash-pinned:
  `profiles/gamedata/0871eee3b68cdea3-unlock.json` (SHA256
  `194cb5b71858f65feeb2b1703642ddc4ffde09b9a087119189b29b0ad7b83f11`), enforced
  by `gbox/game_unlocks.py::profile_for`.
- `gbox/re6_tool.py` provides `unlock_all` and the save-file unlock pipeline
  (`unlock_save`, `apply_unlock`, `unlock_template`, `_save_sum`) and the live
  `unlock_live` path.
- The verified template covers or32 (0xbc, 0x974, 0x978), 42 flags8 offsets,
  and 9 binary regions (0xcc..0x20e4).
- `source.iso` (8 GiB) is cached at `/home/ehm_eckx/gbox-cache/0871eee3b68cdea3/`.
  The save-file (`savedata.bin`) unlock path is ready; live in-memory unlock
  verification remains pending a live RE6 session on the designated worker.

## Blockers / next steps

1. Live acceptance requires an RE6 session on JAYBUILTFINALE (designated
   testing worker) with `agent_use` and 2% audio policy. No live session was
   started in this run (operator gameplay protection; unattended run).
2. Verify `unlock_save` produces the same byte-for-byte save as the game's own
   0x824D8800 routine by comparing `_save_sum` and region hex.
3. Once a live session is available, run `re6_tool op=unlock_all on=true`
   and confirm the game boots to the title with everything unlocked.

## Artifacts

- Template: `profiles/gamedata/0871eee3b68cdea3-unlock.json`
- Tool: `gbox/re6_tool.py`
- Planner: `gbox/game_unlocks.py`
- Cache: `/home/ehm_eckx/gbox-cache/0871eee3b68cdea3/source.iso`
