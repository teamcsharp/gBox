# PSO map and run reviewer

Open **Map and run reviewer** in a PSO session's equipment sidebar. The same
shared panel works in the desktop app and web client. It can show the live
observations or replay a recorded ten-minute segment. Selecting a critical
moment moves the playback slider to that observation. **Export run crystal**
downloads the segment's source samples, events and SHA-256 digest.

The worker samples its existing cooperative controller snapshot once per second.
It adds a bounded `pso_review` block to normal autoplay telemetry, which is sent
every five seconds. No extra game inputs or memory reads are issued by recording.
The server archives delivered samples and deduplicates bridge retransmissions.
The UI names receipt age and source age; delayed samples, clock differences,
ended sessions and duplicate packets cannot turn old evidence into a live map.

The map distinguishes:

- Native player/enemy/object/gate positions in the selected player's room and
  height band. A container retains its actual native class.
- Observed walking cells and learned blocked edges. A stationary observation
  is logged for review; it does not establish a collision wall.
- Verified collision cells only when the provider supplies a matching native
  geometry identity and floor layer. Bounded displays disclose omitted cells.
- Current controller goals, which are intended destinations rather than proof
  of an open door or traversable route.

Paths and displacement comparisons are separated by session, episode, floor,
difficulty, actor identity and randomized layout identity. Gaps longer than
twelve seconds break path segments. The table reports observed displacement,
not inferred optimal travel distance or a percentage of the level mapped.

Critical events include area/room changes, observed HP loss, enemy HP becoming
zero, goal changes, new blocked edges, and fifteen seconds within a six-unit
radius. Enemy damage attribution is not inferred. An empty entity list never
proves a room is cleared; door requirements remain unknown until an exact-build
provider publishes them. A recording segment ending does not complete a zone.
The panel shows the latest 120 returned events. An API response is capped at
2,000 events and reports `events_truncated` when more are stored; the panel
discloses that limit and the database retains the omitted events.

Storage uses `gbox-data/pso/reviewer.sqlite3`. Runs are tied to exact session,
game and autoplay job identities. Each segment permits at most 4,096 archived
samples. At 512 MB the recorder reports a storage limit instead of deleting
historical evidence. Recording errors do not stop the bot or reject its normal
telemetry. Exported crystals have no input or navigation authority; facts must
be revalidated against the current build and layout before reuse.

The current worker sampler is integrated through a small `pso_coop.play` hook.
The server installs `pso_run_review` routes and archives the block from the
existing authenticated telemetry endpoint. This requires a matched worker and
server update; merely reloading the browser does not install either hook.
