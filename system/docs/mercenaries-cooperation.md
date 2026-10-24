`mercs.cooperation.FollowProtect` is a reusable planning policy, not a verified co-op input adapter. It does not
send controller events, write RAM, teleport, share items or invent a revive interaction. Actual RE5/RE6 Player 2
support requires the title driver to verify its independent actor, camera, action prompts and controller path.

Construct with the adapter's explicit world scale: `FollowProtect(units_per_m=100., title='BLUS30491')` for RE5;
the RE4 GameCube scale is 1000 units/metre. Future adapters must declare their own scale. Standoff, body clearance,
arrival and protection distances are expressed in metres and converted through this scale. Actor identity is an
opaque positive integer or string owned by the title verifier; the shared policy assumes no title's RAM range.

Call `plan(snap, mesh, now, ownership=proof, session_id=actual_session_id, hazards=(), exposures=(),
blocked_links=(), avoid=(), penalties=None, traversal_check=None)`. Timestamps use the same monotonic clock as `now`.
The ownership observation must be no more than 0.75 seconds old and must match the exact session, actor identities
and full geometry/topology signature. Required proof fields are:

```python
{
    'verified': True,
    'controller2_verified': True,
    'camera2_verified': True,
    'prompt2_verified': True,
    'control_player': 2,
    'p1_actor': native_human_actor,
    'p2_actor': native_bot_actor,
    'geometry': mesh.learning_sig,
    'session_id': actual_session_id,
    'observed_at': current_monotonic_observation,
    'title': 'BLUS30491',  # compared when supplied
}
```

The current `snap.player` must be Player 2 with matching position and health. `snap.players` must separately identify
`p1`/slot 1/human and `p2`/slot 2/bot, each with `actor`, current position/HP and provenance containing
`native_actor_verified: true` and `control_source: operator_assignment_and_bot_input_fence`. Missing, changed,
ambiguous or stale ownership returns `unavailable`; it never creates a Player 1 fallback.

The result contains `state`, `reason`, `goal`, `route`, `protect_target`, `threat_bias` and provenance. States are
`unavailable`, `paused`, `blocked`, `hold`, `follow` or `protect`. A result without a goal/route authorizes no walking.
The route consists of measured floor waypoints; ordinary floor support, body clearance and current mine margins
are rechecked. A native action link is rejected by default. An optional title-owned
`traversal_check(waypoint, ownership)` must return exactly `True` for each action waypoint; the caller still owns
the real live Player 2 prompt and legal button sequence. A callback failure rejects the action.

The policy chooses a roughly 3.5-metre standoff, with a 2.7-metre alternative for tighter geometry. It follows beyond
6 metres, stops within 4.2 metres, moves away below 2.2 metres and releases the retreat after 3 metres. A wall or
different storey prevents treating Euclidean closeness as arrival: the standoff point must lie on supported floor
from the human. Goal identity and a 1.2-metre human-motion hysteresis avoid retargeting every frame. Session, actor
or geometry changes reset the goal; healing pauses retain it. Newly blocked portals invalidate the cached route
immediately. No unsupported route produces a blind walk.

Protection preferences require explicit fresh Player 2 exposure records:

```python
{'observer_actor': native_bot_actor, 'target_actor': native_enemy_actor,
 'verified': True, 'clear': True, 'observed_at': current_monotonic_observation,
 'source': 'native_first_hit'}
```

Allowed sources are `native_first_hit`, `native_raycast` and `native_line_of_sight`. A floor corridor, finite camera,
another player's laser or an old observation is insufficient. Exposed enemies within 12 metres of the human receive
a bounded `threat_bias` from 0 to 1 (larger means higher priority); the closest threat to the human is preferred over
distant enemies. This is a target preference, not permission to fire: the title combat controller retains weapon,
friendly-fire, obstruction and actual-shot validation.

The caller must run mandatory QTE/recovery, self healing and mine retreat before cooperation. Explicit snapshot flags
`mandatory_qte`, `recovery_active`, `healing`, `mine_escape` and `cooperation_pause` also pause this policy. Player 2 at
or below 40% HP pauses for the existing legal healing/health-seeking controller. Human HP is reported as context;
the policy does not claim that an item-transfer or revival behavior has been implemented.

`tests/test_mercs_cooperation.py` covers measured routes, actor/session/controller/camera/prompt proof, stale data,
unchanged input snapshots, hysteresis, health/QTE/mine priorities, blocked links, current hazards, native exposure,
unit scales and default refusal of unconfirmed action links. These fixtures are not live co-op acceptance evidence.

The PiP right-click menu's Team / training controls preserve assisted training by default. Automatic reduction is
an explicit preference; no reduction or original-rules mastery is claimed from merely saving that preference.
Unmodified evaluation waits for verified original gameplay rules. Assisted or unknown rounds cannot become evidence
of unmodified S-rank mastery by turning modifiers off at the results screen.

To teach a path, select human observation for the exact running session and play the round as Player 1. In the run
reviewer, select the recorded human participant and timeline segment, save and adopt its demonstration, then assign
it to a compatible live session. The bot follows its ordered positions through normal controls, rechecking current
geometry, hazards, pickups and mandatory interactions. This records positions and events, not human button presses.

Player 2 preparation creates a separate controller configuration for a future launch; it does not restart the game
or prove that a second player has joined. The native scoped readers distinguish inventory, actor actions, prompts
and damage evidence, but the shipped `re5_coop.for_player` still returns unavailable. A real teammate requires live
controller response and native camera/prompt ownership acceptance. The isolated diagnostic stopped before RE5
launched because its private Xvfb display crashed. It produced no gameplay or training evidence.

Until further native evidence exists, P2 inventory-menu control and automatic mine placement remain unavailable.
All observed mines remain navigation hazards. Shared enemy damage and kills do not train individual aim accuracy;
team totals do not use the solo rank thresholds or the global character roster. RE6 native teammate control is
also unverified. The shared follow/protect policy is prepared and tested, but is not an active P2 gameplay adapter.
