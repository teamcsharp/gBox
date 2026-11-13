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

## Object-controlled windows and ladders

The separate `cOmWindowEvent_dive`, `cOmLadderEvent_climb`, and `cOmLadderEventV_climb` objects are now admitted through their own proved layout. They are not aliases for `cPlAction_pl_act_fence` or `cPlAction_pl_act_ladder_v_climb`. Targeted native exports are in `/home/ehm_eckx/gBox_alt/analysis/merc-full/re5-traversal-research-20261113` on Spark. Addresses in this section are Ghidra addresses, still main RVA plus `0x100000`.

| Exact event | Registration / allocator | Final event vtable / DTI | Entry / update / exit |
| --- | --- | --- | --- |
| `cOmWindowEvent_dive` | `0x00182D90` / `0x00886980` | `0x01D222E0` / `0x01E700A0` | `0x00886A70` / `0x00886E70` / `0x00886DF0` |
| `cOmLadderEvent_climb` | `0x00176110` / `0x007DFAA0` | `0x01CDF3C0` / `0x01E64C00` | `0x007DFB90` / `0x007DFF10` / `0x007DFE10` |
| `cOmLadderEventV_climb` | `0x00176110` / `0x007DEA00` | `0x01CDF350` / `0x01E64C38` | `0x007DEB10` / `0x007DEF40` / `0x007DEDC0` |

Each event is `0xB0` bytes. Its inherited actor owner is `+0x10`; its scene-object owner is `+0x18`. **Event `+0x30` is not a player pointer.** The reader pins both the exact final vtable and exact native DTI, verifies actor owner equals the selected live player, and requires the scene object to inherit the matching native class: `uOmWindow` DTI `0x01E6FF18`, `uOmLadder` DTI `0x01E64928`, or `uOmLadderV` DTI `0x01E64960`. The parent walk is bounded and rejects cycles. Scene vtable, unit generation at `+0x1A00`, live unit phase (`+0x10 & 7` in 1/2), and inheritance chain are captured and rechecked. Both player and scene lifetime must remain stable for the native sample. Unknown scene/event types remain unavailable.

The dispatcher establishes actual ownership rather than inferring it from animation:

1. LadderV action-button callback `0x007E1550` calls the actor's virtual `+0x280` with the `cOmLadderEventV_climb` DTI and its ladder object.
2. The player implementation `0x008A1F40` creates that event through the DTI allocator, invokes event virtual `+0x30`, then player virtual `+0x278`. Event initializer `0x009241A0` stores the scene owner at `+0x18` and resets status `+0x2C`.
3. Player `+0x278`, `0x008A1EA0`, writes event `+0x10 = player`, queues it at player `+0x1B70`, selects event action ID `0x80000000`, and marks a pending transition.
4. Native action processing `0x00891220` transfers that pending object into player `+0x1B60`, invokes its entry (`+0x38`) and update (`+0x40`). On transition it invokes the old object's exit (`+0x48`) and releases it. Thus these wrappers really occupy the current player-action slot.

Object event status is a 32-bit value at `+0x2C`; only 0/1/2 are observed as admissible. Shared update `0x00924240` marks an invalid scene owner as status 4. The player/enemy variation selector is `+0x34`: the reader admits only player selectors (window 0/1, ladders 0/1/2), not the enemy selector 3.

Completion has different semantics from `cPlAction`:

- Window update `0x00886E70` uses a 32-bit phase at `+0x38`. Phase 0 aligns the player, then plays object motion `0xF01` or `0xF03` and enters phase 1. Phase 1 requests player action 0 through virtual `+0x270` after the animation-end bit (`player +0x8FA & 4`).
- Standard object-ladder update `0x007DFF10` uses byte phase `+0x28`. It aligns and plays `0xF00`, loops `0xF01`, plays the appropriate `0xF02`/`0xF03` exit, and only requests action 0 in phase 3 after the same animation-end bit.
- Variable object-ladder update `0x007DEF40` uses byte phase `+0x28`. Phase 1 advances climb segments and height from the ladder's native transform/height; phase 2 waits for the exit animation-end bit, then passes through phase 3 to request action 0 and records phase 10. A missing ladder can also force phase 3, which is why the live scene-owner checks are mandatory.

Player virtual `+0x270` is `0x008A1D50`, which delegates normal action selection to `0x00890FE0`. No cPl traversal action is inserted between an object event and the normal action. The observer therefore requires an observed terminal phase/animation-end witness for these cOm events, followed by a different owned grounded cPl action, at least 60cm displacement and the usual stable landing. A missed terminal sample refuses the mine rather than converting an interrupted object event into a completed traversal. The old cPl completion flag is not used as proof for cOm events.

`traversal_observation` now publishes `active`, round/player owner, observation `at`, native `sampled_at`, current action pointer/vtable, exact name, layout and scene identity. This supports preserving an already active native traversal; it does not authorize activating a prompt or traversing an unknown link. Invalid/menu/dead/operator observations clear the active fact. There is no proved generation counter on the action object itself; consumers must not invent one or reuse an old action pointer after the freshness/lifetime checks fail.

The three native RTTI getter instruction sequences have been read directly from the pinned ELF and frozen in tests (main RVAs `0x786A60`, `0x6DFB80`, `0x6DEB00`). This establishes the reader's instruction decoding against actual code. A complete live cOm entry-to-grounded-exit trace and its resulting mine placement remain to be observed; neither the static exports nor the frozen fixtures claim live effectiveness.

## Validation

`tests/test_re5_traversal.py` covers exact native RTTI decoding (direct and GOT getter forms and three real ELF getter byte sequences), both cPl owner pointers, cOm actor/scene ownership, scene inheritance and generation, exact event vtable/DTI, co-op slot ownership, lifetime/action/vtable/phase/status races, read timing, five cPl traversal families and the three object events, stable landing and latest anchor, no airborne event, interrupted/cancelled traversal, missing completion evidence, duplicate prevention, stale active facts and event lifetime/freshness.
