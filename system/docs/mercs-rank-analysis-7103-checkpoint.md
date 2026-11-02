# Mercenaries rank_not_verified analysis checkpoint (request #7103)

## Status
- Request: `ee8ace65d73034e8` (#7103)
- Status: `in_progress` (was `open`, transitioned at ts 1793544090.409746, audit_seq 237195)
- Lane: inbox
- Read-only: true

## What was done
- Text-only analysis of round report `48b2e06f441d0d4b16a7520b2e578333b31dab4e6877f76380f3cff1f1d40e0c`
- Round: `1455ed11bd474a09ab6e2f5e4105b1f6` (terminal solo, Sheva BSAA, outcome=died, score 9820)
- Posted `gbox.mercs.analysis/1` JSON to the request at ts 1793543834.8184805
- Provenance: autoplay_job_id `8f5acd39db474f2e`, session_id `bf921a462a2f41fa-ea11072d33034612`, game_id `52d15709be0fda1a`, geometry `1411-1725-7fee6ff36812b399-0fb005b38d0c`
- Provenance verified: source=owning_local_autoplay_job, reason=matched exact worker/session start, verified=true
- Inference node: sparkDeux
- No source/config/RAM/save changes, no patch deployment, no game launch, no image/vision tools

## Key findings
- Rank: score 9820, rank.verified=false, no score-to-rank mapping exists for this title
- Aim: 13/25 shots = 52.0% accuracy, 0.66s trigger, 1.14 shots/kill
- Damage: 14 events, 15 hits, 2 heal failures (40% of 5 starts), round_dying=1
- Enemy DB: 2/23 classes seen (uEm10 75% hit, uEm12 85% hit); uEm0b (20% hit, danger 0.46) NOT in classes_seen
- 12 explicit unknowns listed (per-class aim, attacker attribution, health protection, time_bonuses_remaining, etc.)
- 3 advisory proposals: evaluate_aim, review_damage_incidents, checkpoint_patience_s=12

## What is NOT done
- No policy applied (learning.analysis_policy_applied=false, status=evaluation_pending)
- No improvement claimed
- No native character or replacement work begun

## Next steps (for a future run)
1. Determine if a score-to-rank mapping can be established for this title (010018100CD46000) to resolve rank.verified
2. Obtain per-class aim/range/danger for THIS round (not just cumulative DB) — requires a round with 2+ classes present and per-class hit/miss breakdown
3. Enable incident event recording so damage events carry timestamp, attacker class, and distance
4. Verify checkpoint patience value (12 vs 16 s) with time_bonuses_remaining data
5. Request can be closed (status=done) only after rank is verified or a score-to-rank mapping is established

## Pending jobs
- None active. Analysis is complete and posted.

## Evidence artifact
- Analysis JSON posted as message on request #7103 (ts 1793543834.8184805)
- Local copy: /home/ehm_eckx/.hermes/cache/scratch/analysis_7103.json
