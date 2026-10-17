# Unlock-on-load research

`python -m gbox.unlock_research` is a bounded, non-inference Hermes cron scan.
It covers the complete durable favorite snapshot and games played since activation,
including running non-favorites. One child inbox request per exact catalog title
tracks REA/Ghidra analysis, the full unlock inventory, implementation and runtime
acceptance. DOA3 and Resident Evil titles are enumerated first. A control-plane
timeout after request creation is reconciled by context; uncertain writes are
never blindly repeated. The scanner pauses when Hermes task mode is paused.

Activation state is `gbox-data/hermes-dispatch/unlock-research.json`: `enabled`,
`enabled_at`, `parent_request_id`, per-game request links and `last_scan`. The named
Hermes cron job runs every two minutes. It creates at most 40 missing tasks per
pass and never launches a game or changes saves. Hermes's existing queue supplies
capacity, task workspaces, retries and checkpoints. New favorites need no manual
rescan. Original games and personal saves stay available during research.

`gbox.game_unlocks.pre_launch` is the fast entry point for reviewed game-specific
implementations. `profile_for` records the supported revision, scope, exclusions
and evidence; unknown titles report `research_pending` in the session's
`detail.unlocks`. A native writer must verify the source revision and back up or
isolate saves before changes. Runtime-only routines must additionally guard the
loaded executable and mode. No decompiler runs on the Play path.

The existing pinned Resident Evil 6 Xbox 360 save routine is connected. Other
Resident Evil releases and DOA3 are research tasks until their own routines have
been implemented and tested. This does not claim every title is already unlocked.
Profiles must enumerate absent content and unknowns; boot screenshots, installed
tools, model replacement or a merged PR alone do not prove unlocks work.

Spark's standalone gBox Ghidra bridge has its PyGhidra environment installed.
REA 6's bundled Ghidra provider rejects Linux ARM; route those binary sessions to
an available x64 worker and check `rea_binary_session` before opening binaries.
The standing inbox parent records the worker probes and analysis artifacts.
The two-Spark local task pool assigns small inventories to lilspark when it has
headroom and larger implementation milestones to sparkDeux. Both hosts retain
checkpoints on the prime Spark. Local-only mode keeps newly available cloud
credit out of the inbox route. See `hermes-local-fallback.md` for machine
switches, capacity, budget limits and explicit model-management controls.
