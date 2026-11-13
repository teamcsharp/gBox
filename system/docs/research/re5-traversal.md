# RE5 traversal completion observations

The observer in `gbox/mercs/titles/re5_traversal.py` publishes one `traversal_mine_event` after a verified native traversal action exits to an owned grounded player action and the landing height remains stable. It does not issue pad input, change the weapon, write game memory, or place a mine. The existing native mine controller consumes the event, deduplicates its ID, and owns placement/escape admission.

## Native evidence

Analyzed main ELF SHA-256: `674c88288eda98b8974e4185853d0b7c2f3fe6b623c823124326d14834856f5c`. The existing full Ghidra export is `/home/ehm_eckx/gBox_alt/analysis/merc-full/re5-674c8828-20261113`; input is `/home/ehm_eckx/gBox_alt/scratch/agent/switch/re5/ghidra/re5main.elf`. Addresses below are Ghidra addresses with image base `0x100000`.

Player action registration at `0x00191080` establishes the exact `cPlAction_pl_act_*` names. The reader follows the player's current action at `+0x1B60`, decodes its native MtDTI getter, and admits complete exact names. Both the inherited actor owner at action `+0x10` and the player owner at `+0x30` must equal the current player. Action phase is `+0x28`.

| Action | Native update | Completion evidence |
| --- | --- | --- |
| `jump_down` | `0x00A666F0` | World collision query `0x00268FF0` in phase 1; collision hit height written to player `+0x64` at `0x00A66914..60`; landing motion `0x14E` then phase 2; animation-end bits at `+0x8FA & 5` precede completion at `0x00A66814..1C`. |
| `ladder_v_climb` | `0x00A421F0` | Animation-end bits at player `+0x8FA & 5` precede completion and phase increment. |
| `climb_cliff` | `0x00A4D190` | Starts climb motion `0x174`; waits for animation-end bits before completion. |
| `fence` | `0x00A65540` | Native collision/position update then motion `0x146`; animation-end bits precede completion at `0x00A65724..2C`. |

These updates set player `+0x3F0C |= 0x10000000`. The generic exit routine at `0x00A42290` can also set that bit, so the bit alone is **not** landing proof. The observer records whether it saw the bit but requires an actual transition to a known grounded native action plus at least 0.2 seconds of stable height (15cm tolerance). It requires at least 60cm traversal displacement. It does not add a separate native collision-floor query.

Covered names also include registered `jump_broad_3m`, `jump_broad_4m`, `coop_jump_broad_6m_jump`, `coop_jump_up_4m_jump`, `coop_climb_cliff`, and `coop_climb_cliff_rescue`. No motion-number heuristic admits a traversal. Grounded actions are exact registered idle/walk/run/turn/weapon action names, not arbitrary names with a matching prefix.

Read-only live ownership confirmation on 2026-11-13: session `af3d25f1f3b34383-4ad5db7f15004e64`, round `d0e033594fe84395adbc7ca1330194f3`, HP 804. Player `0x5D474680A0`, generation 1, action `0x5D475A0640`, native name `cPlAction_pl_act_turn_180`. Both action `+0x10` and `+0x30` read `0x5D474680A0`. This confirms the live normal-action ownership layout; it does not demonstrate a completed live traversal or successful mine deployment.

## Event contract and bounds

`traversal_mine_event` persists for five seconds so the native mine controller's ordinary request interval can elapse. Fields include monotonic `id`, `kind: "traversal"`, `owner: [round_evidence_id, player_ptr, player_generation]`, `at`, landing `pos`, traversal kind/name, grounded completion action, and `completion_flag_seen`. Placement should use the recorded landing position as its anchor. Consumers must retain owner/ID deduplication, freshness and existing native admission checks; an event is evidence for a request, not placement confirmation.

The integrated consumer requests one mine at that recorded exit, behind hit/QTE reactions and ahead of travel-distance drops. Existing mine escape, placement spacing, controller busy state, weapon handover and the Automine toggle still apply. A new traversal or unavailable owned-action read removes an uncommitted event. The background worker retains an immutable token and caps pre-commit time to the remainder of its five-second lifetime; refreshing ordinary player telemetry cannot renew it. After a physical mine is deployed, native arming observation continues and the hazard remains tracked even if the token expires. Request and confirmed-armed counters are separate; uncertain placement is not replayed.

Each native read rechecks player slot/generation, game manager/playing phase, action pointer/vtable, and both action owners; a read taking over 150ms is rejected. Lost/unknown action reads, death, operator control, menu/closed round, changed lifetime, clock reversal, sampling gaps over one second, and traversal episodes over 60 seconds cancel the episode. A still-running traversal never emits even when its completion bit is set. Stable grounded samples remove the episode, so repeated samples do not create repeated mines.

Coverage remains deliberately limited to proved `cPlAction` ownership. Separate `cOmWindowEvent_dive`, `cOmLadderEvent_climb`, and `cOmLadderEventV_climb` wrappers exist in the native registration tables, but their event-owner/completion layouts are not established by this change. They are unavailable rather than interpreted as ordinary player actions. Full window and horizontal-ladder coverage needs those layouts and a live exit trace. Live traversal-to-mine effectiveness remains to be observed after integration.

## Validation

`tests/test_re5_traversal.py` covers exact native RTTI decoding (direct and GOT getter forms), both owner pointers, co-op slot ownership, lifetime/action/vtable/phase races, read timing, five traversal families, stable landing and latest anchor, no airborne event, interrupted/cancelled traversal, missing single-frame completion flag, duplicate prevention, and event lifetime/freshness.
