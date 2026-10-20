# RE6 Xbox 360 unlock-on-load handoff (request #2042)

This is an engineering checkpoint, not completion of the unlock request.
No running game or save was changed during this review.

## Verified code and local inventory

- Exact catalog game: `0871eee3b68cdea3`, platform `xbox360`.
- `gbox.game_unlocks.profile_for` recognizes the existing native-save template
  using the SHA256 of **canonical JSON** (sorted keys, compact separators):
  `194cb5b71858f65feeb2b1703642ddc4ffde09b9a087119189b29b0ad7b83f11`.
  This is not the raw file hash. Raw checked-in bytes hash to
  `bae0c77ab45090900ad855db396779f78a6197e91f01a34d8f42db86434e87ce`.
- The template has three `or32` masks, 42 `flags8` offsets and **10** binary
  regions, whose starting offsets range from `0xcc` through `0x20e4`.
- `gbox.re6_tool` implements `unlock_all`, `unlock_save`, `apply_unlock`,
  `unlock_template`, `_save_sum` and `unlock_live`. Existence of these routines
  is separate from acceptance of a new boot or custom build.
- The existing profile records prior native-routine capture at `0x824d8800`.
  Its declared scope is disc-present campaign content, skills, Mercenaries
  characters/EX costumes and three disc stages, figures/emblems/titles/extras.
  It explicitly excludes No Hope, No Mercy and absent DLC/retro costumes.
- The cached `source.iso` is 8,091,336,704 bytes at
  `/home/ehm_eckx/gBox_alt/gbox-cache/0871eee3b68cdea3/source.iso`. File existence/size
  is inventory evidence, not a new complete-disc integrity check.

## Remaining acceptance

1. Use the designated JAYBUILTFINALE test worker only when available, preserving
   operator gameplay. Apply the existing `agent_use` and 2% audio policy.
2. Verify a backed-up or isolated save overlay. The save upgrader intentionally
   preserves better existing progress: it should not be required to overwrite
   those bytes merely to match a debug-routine capture. Independently check the
   checksum, intended unlock masks/categories, idempotence and preserved fields.
3. Exercise the actual unlock-on-load path on the exact game/build. Verify the
   title/menu categories and a second launch, then test rollback. A command's
   successful return is insufficient to establish that everything is unlocked.
4. Keep request #2042 open until its live/build acceptance criteria pass.

## Reusable entry points

- Template: `profiles/gamedata/0871eee3b68cdea3-unlock.json`
- Save/live tool: `gbox/re6_tool.py`
- Exact-game profile and launch planner: `gbox/game_unlocks.py`
- Contract tests: `tests/test_unlock_research.py`,
  `tests/test_favorite_capabilities.py`, `tests/test_custom_build_unlocks.py`.
