The Mercenaries tab in gBox and `/mercenaries` open the run reviewer independently of gameplay. It displays the latest
100 saved review records per title; older atlas, Notebook, incident and lesson evidence is preserved. No retention
delete is performed. Titles without recorded spatial data can still expose genuine Notebook reviews.

Select a game, stage geometry and character, then overlay the latest 1, 5, 10, 20 or 100 paths. Paths from other geometry
identities are excluded. Playback uses recorded sample times, native player/enemy health, score, combo and confirmed
checkpoint events. Entity disappearance alone is not a verified kill. Interpolation stops across missing samples or
implausible position jumps. Large path histories are sampled and marked as sampled in the API.

Live polling uses the existing tactical RAM publisher only when its current autoplay round UUID and full geometry
match an active atlas row. Live telemetry is explicitly separate from durable samples. Pausing or scrubbing selects
recorded playback. Every sidebar field can open its raw value and source; the complete payload is also inspectable.
Notebook joins require exact round ID, stage geometry and mode. Stored performance vectors and semantic-recall source
IDs are shown as evidence; opening the reviewer does not perform or pretend to perform a vector search. Navigation
and mine-site learning is a current per-geometry aggregate, labelled as such rather than a historical snapshot.

Draw a suggested route on the map, drag points to adjust it, choose each point's floor Y and validate/save. Suggestions
are retained separately in `mercs/reviewer.sqlite` with the title, full geometry identity, operator provenance and per
segment validation. Ordinary floor segments must follow actual directed native floor links. Unsupported segments or
candidate action links remain drafts; an enemy navigation link does not prove that the player can use a ladder,
window or jump. Drawing never declares a route optimal or teleports a player.

Navigation integrations may read `validated_suggestions(data_dir, title, mesh)`. This rechecks every segment against
the current exact mesh. The planner must still check live mines, threats, prompts and goal applicability before using
a hint. The reviewer itself sends no game inputs or memory writes.

Recorded human routes can also be taught. Select the recorded player, scrub to a start/end and use **Mark start** /
**Mark end**, or choose **Use entire run**, then **Teach this route / have bot practice**. P1 human and P2 bot have
separate paths, markers and HP playback. Legacy traces retain unknown controller ownership and cannot be relabelled
as human. Teaching requires a native actor identity plus an explicit operator assignment and the bot input fence in
every selected sample. Human button capture is not required: these are RAM position demonstrations, and
`inputs_observed: false` remains in the saved provenance. Controller inputs are never replayed.

Demonstrations are stored in the same annotation database with an independent UUID, exact title/mode/full geometry,
player identity, source round and sample range, position digest, assistance context and per-segment validation. The
server extracts positions from durable samples and rejects controller changes, actor changes, missing samples and
implausible jumps. An unmodified label requires verified context throughout the selection. Known modifications stay
labelled mod-assisted even when a complete original-rules audit is unavailable. Missing context remains unknown;
teaching a route does not qualify an assisted score as an unmodified S rank.

Unsupported crossings remain drafts. An action link can be included only when an exact saved `traversal_completed`
event identifies the same player, actor, full geometry, sample endpoints, directed floor nodes, approach, landing and
portal with `verified: true` and `evidence.source: native_player_traversal`. The current native topology is rechecked.
The running title controller still requires its real live action prompt before executing the crossing. Recording
ordinary position changes or seeing an enemy navigation link never manufactures such a completion event.

An adopted demonstration is available for practice; **Stop practicing** revokes adoption without deleting any source
run. To choose it for an actual running instance, use **Find live sessions**, select the exact matching title/session,
then **Use in selected session**. This submits only `mercs_team.configure(selected_route_id=...)` to that session's
worker and confirms a separate status readback. It does not change the team role, modifiers, controller inputs or
autoplay state. Ended or replaced instances require a fresh explicit selection.

`Guidance.route(..., mode=..., selected_route_id=...)` can use an applicable local portion of a demonstration.
`Guidance.practice(mesh, position, now, mode=..., selected_route_id=..., hazards=..., blocked_links=...)` provides
ordered waypoint goals for the whole selected path. It starts at the recorded first point, advances only on measured
same-floor arrivals within 60 world units, retains progress during combat pauses and latches completion until the
selection changes. A blocked segment returns no movement route. Combat, healing, mine escape, ownership and live
prompts remain higher priorities in the caller; practice never teleports or infers bonus collection.

The authenticated API is under `/api/mercs/reviewer`: `catalog`, `runs`, `round`, `live`, `suggestions`,
`POST demonstrations`, `GET demonstrations/{id}` and `POST demonstrations/{id}/adopt`.
Teaching accepts `{title, round_id, player_id, start_seq, end_seq, name?, adopt: true}`; coordinates and controller
ownership are read from stored evidence rather than accepted from the request.
Round samples are paged with `after`/`next_after`; no recorded frame is synthesized to fill missing evidence.
