# Character replacement scope

A character replacement targets every appearance by default: gameplay, in-engine cutscenes, costumes/detail
variants, and prerecorded cinematics. A gameplay screenshot does not verify cinematic coverage. If the original
character still appears anywhere, keep the investigation open with the scene and asset identified.

The registered characters tool returns replacement_scope for use/live_use/match/cast_swap results that name a mod.
New build records retain this requirement. Reused markers are not relabelled as having new coverage. Complete
remains false until coverage is established; gameplay_verified and verified_in_game are not full-scope receipts.

Twin Snakes now includes in-engine demo/intro/ending stages carrying the selected model or its low-detail twin.
The source model's texture set is read from a stage that actually holds that model. Existing sector-size checks,
shrinking retries and source-disc preservation still apply. New _cs1 names avoid legacy gameplay-only cache hits.
Its prerecorded movies remain unchanged and are explicitly recorded as such.

Ocarina of Time cast builds budget cutscene layers by default. strict_cutscenes=false is an explicit diagnostic
opt-out, retained in rebuild recipes; it is not a complete replacement. Cast builds use separate _cs1/_cs0 names
rather than overwrite legacy output. Memory budgeting does not itself prove visual cutscene correctness.

FF7's current writer covers FIELD/CLOUD.BCX and ENEMY6/CLOUD.LZS; prerecorded movies and portraits still use
original assets. Other titles may share gameplay models with cinematics or load separate assets. Inventory and
verify each title; neither a generic model swap nor Ghidra analysis automatically changes rendered video.

Validation in this change uses synthetic binary fixtures, model/texture decode, stage byte comparisons, cache
separation, metadata and recipe tests. No new emulator gameplay or cinematic visual verification is claimed.
