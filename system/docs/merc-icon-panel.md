# Mercenaries icon panel

The stream toolbar is the **icon panel**. The shared stream view and the compact
desktop view expose the same controls.

* **Recycle** requests the current stage again after this round ends, with a
  different character. A queued request becomes applied only after native game
  state confirms the new round. RE5 costumes from the same character do not count
  as changing character.
* **Ctrl+click or hold for 600 ms** toggles a stage loop. The loop captures the
  current stage, keeps MercMode on this title, and changes characters between
  rounds. Toggle it off to resume rotation. Clicking does not abort combat.
* The adjacent **triangle** opens stage selection. Check stages, use **Invert**,
  or **Reset defaults**. Moving a weight redistributes the remaining percentage
  across the other included stages. Use **Apply** to save the draft. At least
  one included stage must have positive weight.
* RE6 exposes periodic quick attacks: enabled by default, **4 requests every
  24 seconds**, with count 1–8 and interval 8–120 seconds. Native counters, QTEs,
  recovery and valid combat conditions take priority. Requests and observed
  native actions are separate telemetry; four requests do not imply four hits.

## Selection and persistence

Initial support is RE4 GameCube G4BE08 and the verified RE5/RE6 Switch builds.
Unsupported titles show a reason. Mercenaries 3D does not yet have a verified
unlocked character roster, so it cannot claim a different-character replay.

Stage preferences are per title on the emulator worker, in
`mercs/stage-rotation.json` under its data directory. Other sessions on that
worker see saved changes on their next selection. Replay and loop state belong
to the exact live session. Quick-attack preferences use the existing per-title
bot-logic settings and apply to that title on the worker.

Explicit replay takes precedence over the random stage pool, but never bypasses
a native stage lock. A missing native roster or unavailable included stage makes
the menu wait and reports the reason. RE4 uses native menus while these controls
are active so a cached round cannot bypass the selected stage or character.
The coordinator mirrors acknowledged stage preferences and rejects excluded
prepared warm rounds instead of resuming them into gameplay.

The session RPC is `merc_round_controls`, with operations `status`, `replay`,
`stages`, and `quick_attack`. Mutations require a UUID request ID and the existing
execute permission. A timed-out mutation is never automatically resent: status
looks for its receipt. Receipts are bounded; session tombstones prevent a reused
old request ID from executing after its detailed receipt expires.

## Validation limits

Unit and browser checks cover selection, normalized weights, receipts, session
isolation, rejected inputs, native identity, menu targeting and layout. Live
round acceptance is separate: this document does not claim a completed campaign,
perfect accuracy, guaranteed counters, or a demonstrated mastered stage.
