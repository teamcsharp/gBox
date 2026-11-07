# Request 4838 — rampage mode fires "so insane" — checkpoint

Operator (chat, request 4838 / 4773cdf3cde44c47): "i would expect rampage mode to be them
firing in front of them clearing out the immediate 5 meter circle. They are shooting so insane
i cant even describe it".

## State at this run (local spark, branch hermes/request-4838-1794038105876990908)

- Worktree clean at origin/main (ef0eebcf). No prior commits or PR for request 4838:
  `git log origin/main..HEAD` empty; open-PR scan of head refs found no 4838/4773 branch.
- Prior dispatch attempts for this cron job (job 11a8292d692b, 20x over ~30 min before this
  run) produced no saved patch and no request message — all failed pre-work; no job state to
  resume, so this run starts fresh from main.

## Bounded checks run this session (actual results)

- `pytest tests/test_re5_switch_rampage.py -q` → 12 passed in 0.23s
- `pytest tests/test_re5_switch_crowd.py -q` → 49 passed in 0.19s

Baseline is green; the complaint is runtime behavior, so the next evidence is live per-round
rampage counters, not more unit tests.

## Code anchors (where the erratic firing would live)

- `gbox/mercs/titles/re5_switch.py` — the 5 m rampage: `self._ramp`, `_rampage()`,
  `_rampage_gun()`; counters `RAMPAGE_COUNTERS` = rampage_s, rampage_shots, rampage_kills,
  idle_in_5m_s, unaims_in_5m, behind_turns, offscreen_aim_s, whips, rampage_swaps,
  crowd_fire_s, shotgun_swaps; "front-facing and calm" design intent at ~line 559.
- `gbox/mercs/titles/re5_switch_mods.py` — `rampage_loadout` (shotgun/magnum D-pad block),
  op `rampage_loadout` at line ~1247.
- Suspects for "insane" fire: swap spam (rampage_swaps / shotgun_swaps per second),
  behind_turns (whipping to rear targets), offscreen_aim_s, crowd_fire overlap.

## Next acceptance step (resume point)

1. On i9-NUC with an idle MercMode RE5 session: run one rotation round with rampage on and
   read per-round counters (rampage_swaps, behind_turns, whips, offscreen_aim_s,
   crowd_fire_s) — that names which fault the operator saw.
2. Implement the bounded fix (front-facing stable aim, cap swap cadence during rampage) in
   re5_switch.py, prove it with a focused test in tests/test_re5_switch_rampage.py.
3. Live acceptance: one round where the bot fires forward and the 5 m circle clears with
   sane swap counts; then publish + inspection_builds op=plan if a build revision is needed.

Keep request in_progress until step 3 shows a live round.
