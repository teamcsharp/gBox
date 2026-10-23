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

The authenticated API is under `/api/mercs/reviewer`: `catalog`, `runs`, `round`, `live` and `suggestions`.
Round samples are paged with `after`/`next_after`; no recorded frame is synthesized to fill missing evidence.
