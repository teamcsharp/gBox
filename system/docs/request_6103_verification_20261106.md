# Request #6103 — verification checkpoint (cron run, 2026-11-06)

Verdict: implementation ALREADY MERGED ON MAIN — this run performs the
requested current-main verification, does not duplicate the implementation.

## Verified against canonical main (checkout gBox-src, HEAD 9aff4ff0)

1. Commit: `2ad2eb69` "Execute native RE6 flash interventions with durable
   per-click receipts" — `git merge-base --is-ancestor 2ad2eb69 HEAD` => YES.
2. Dispatcher case: `system/gbox/mercs/titles/re6_switch_mods.py:1250-1253`
   (op `run()`):
   ```
   if op in ("flash_now", "instant_flashbang"):
       # Do not hold the continuous-mod lock while waiting for a game frame.
       from .re6_switch_native import flash_now
       return flash_now(ad)
   ```
   Alias `instant_flashbang` accepted; dispatch happens BEFORE the
   continuous-mod `_LOCK`, so the op holds no persistent lock/cooldown.
3. Detonation at player position: `system/gbox/mercs/titles/re6_switch_native.py`
   - `def flash_now(ad)` (line 415): docstring "One call = one native effect.
     Callers own durable request deduplication." — one click = one effect,
     repeatable on every click; no cooldown or state lock in the op.
   - `Controller.flash()` (line 358) re-establishes the current player fresh
     on every call (lines 361-368) and detonates via the pinned native hook
     `(0x18F29C0, "detonate", 232, sha c7d90bc2...fb941)` (line 24).
4. Tests: `python -m pytest system/tests/test_re6_switch.py -k flash -q`
   => **9 passed, 224 deselected in 0.96s** (on main).
5. Production receipts (on disk, this request's agent scratch):
   - production-flash-burst-1793334017586478292.json (session 5484c0108b3e411c-e964cdf6845f48b4)
   - production-flash-burst-1793334856314086402.json (session 30af953d95d24274-6070fe126cad45d2)
   - production-flash-burst-1793338628335373721.json (session ffd7ab211ea44d02-efe5df8e708942aa)
   - production-flash-burst-1793367003163283517.json (session 75b4653ca8e04817-6e30a14170254500)
   Each: **20 ids, 20 unique** — every click produced a distinct native
   receipt (repeatable on every click, no dedupe suppression in production).

## Workspace reconciliation
Task worktree branch `hermes/request-6103-1793299244306367126` (baseline
38477e9c, pre-merge): its uncommitted 4-line diff in re6_switch_mods.py and
untracked re6_switch_native.py are BYTE-IDENTICAL to the now-merged main
versions (verified with diff -q). The prior patch is preserved uncommitted;
no re-implementation was performed or needed.

## Still open (kept in_progress, not closed on partial evidence)
Flash resource loading for characters WITHOUT inventory resource
attestation: the native controller surfaces `Unavailable` for those
characters instead of faking success. Full acceptance for that edge is
pending; everything in this ticket's title (op flash_now, player-position
detonation, repeatable per click) is merged, tested, and production-receipted.

## Next acceptance step
Live check of flash resource loading for a character with no inventory
resource attestation (session on i9-NUC or an idle Spark, 2% audio), then
close #6103.
