# Mercenaries round reports and Spark2 review

Completed Notebook rows produce durable reports at `GET /api/mercs/round-reports`
and `GET /api/mercs/round-reports/{report_id}`. Reports retain the exact title,
round ID, recorded geometry/mode/character, terminal outcome, route/stall/time-bonus,
damage, mine-retreat and aiming measurements. They link the measured Reviewer
round, map/JSON artifacts, and available incident receipts containing RAM/hook or
supported save-state evidence. No RAM/save blobs enter the analysis prompt.

Only explicit solo-bot rounds with exact source-session and autoplay-start job
provenance are admitted. Federated imports require the already accepted evidence
manifest and expose when the remote job receipt is unavailable centrally. Human
demonstrations, interrupted runs and unknown ownership do not create bot tasks.
Old traces without explicit control provenance remain visible as evidence gaps.

`rank_not_verified` is an investigation category. A terminal score estimate or an
in-round rank is never promoted to an observed native result. A verified S under
assistance does not establish unmodified mastery. RE6 has no working native
Mercenaries driver here; this infrastructure does not make RE6 playable.

The scanner runs off the input thread every fifteen seconds. First activation
seeds at most one terminal round per title from the preceding hour; every later
Notebook row is visited by row ID, including late offline imports with older
source timestamps. Round identity deduplicates intake. Pending Atlas evidence
retries with bounded backoff; reports and deterministic Inbox requests commit in
one transaction, so a lost acknowledgment cannot create duplicate requests.

Hermes's existing queue owns capacity, active claims, cooldowns and execution
retries. The configured Spark2 node is `sparkDeux`, provider `gbox-sparkDeux`,
model `nvidia/Qwen3.8-27B-NVFP4`. Required-node requests wait instead of using a
different node or cloud lane. Strict node endpoints reuse the ordinary pool's
limiter. Queue acceptance, actual cron job ACK, execution outcome and accepted
structured analysis are separate states. Global auxiliary inference remains
independent of the primary route; the report never claims that its entire agent
execution was confined to Spark2 without corresponding evidence.

Analysis is bounded text-only advisory work. Image tools, production changes,
arbitrary routes/coordinates and automatic source/RAM patches are prohibited.
Structured proposals remain `analysis_only` and `evaluation_pending`.

The existing validated RE5 learner still consumes measured reviews through exact
geometry/mode recall and bounded checkpoint patience (12 or 16 seconds), with
measured route costs. Its actual source review IDs are persisted. A later round
can therefore report that this existing policy consumed a particular review,
along with observed metric changes. This is distinct from applying model
proposals. One follow-up does not prove causal improvement or guarantee S rank.

Normal damage, modifiers, controller assignment, rotation, streams and the game
process are unchanged by report intake or analysis.
