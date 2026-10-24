# Local desktop authority

The Windows shell starts a real loopback gBox service on `127.0.0.1:18765`,
using the installed local configuration, database, token, runtime and cache.
Ordinary startup selects **This PC**. A saved remote PiP stays attached to its
original remote server; reconnecting never changes the selected authority or
replays a launch. The titlebar connection control selects an authority explicitly.

Local and remote health checks run independently. Remote credential lookup uses
one asynchronous, bounded attempt, so an unavailable SMB share or SSH host does
not block local readiness. Credentials, API caches and session IDs are scoped to
the exact server origin.

The local catalog retains original game IDs, profiles and launch recipes. While
both services are reachable, cached catalog metadata is imported only after the
local service verifies the corresponding local file or cache copy. No remote
job, launch, session or token is imported. Configured local libraries are indexed
in the background; network library roots are not touched by that indexer.

An existing docked native game remains visible through API or guest-page loss.
Only a successful native-window probe confirming its disappearance releases
the retained session. A connection switch cannot replace an active native view.
Desktop refresh also requires the actual local service's signed idle handshake
and verified process lineage before restarting its process.

## Ownership and current limits

There is one local game worker. If an older worker still owns a live emulator,
the local worker waits and leaves that game intact. The new process does not
adopt the older worker's in-memory adapters. Such a legacy remote-owned game
keeps its docked surface, but its API controls require its original authority.
Fresh local sessions use the local authority for mods, input and autobot tools.

The outbound desktop federation bridge mirrors actual worker/session identity
and verified local catalog metadata to the paired central service. It forwards
central commands through durable local submission identities; lost responses
never create another launch. An uncertain submission or oversized result is held
explicitly while other commands and media continue. It starts no second worker
and imports no session from a legacy active owner.

Each federated desktop keeps its local automatic scheduler. Central MercMode
configuration is delegated as an exact local job; observed local settings and
history are mirrored separately from a pending requested change. This preserves
offline scheduling without two control planes independently launching demos.
Explicit central autoplay-on-launch requests are handed to the local scheduler
once, with an atomic marker that cannot reappear after consumption. Existing
central-owned runs retain their exact parent mapping through completion.

Player handover reports are recorded locally before transmission and replayed on
reconnect. Automatic stops for that exact handed-over session are refused at
submission and again before the native stop call; operator Stop remains available.
Verified local launch paths retain the original central request hash and a separate
resolved execution hash for recovery and review.

The separate Mercenaries evidence synchronizer exports completed, source-scoped
round records and bounded artifacts through a durable content-hash outbox.
Unproven old source identities remain unsynced; it does not copy a live database
or fabricate native observations.

Media uses the sole worker's existing cropped desktop capture on viewer demand,
with one continuous length-prefixed upload per watched game. Scoped input/RPC
uses expiring central requests and a measured clock offset; disconnect releases
only remote-leased inputs while local/autobot holds remain. Uncertain mutating
RPCs are not repeated. This Windows federation path currently relays JPEG video;
it does not carry Windows game audio to Pine. Native local game audio is separate.

## Validation

The desktop lifecycle and polling suite passes 81 tests. The 39 focused Python tests
cover catalog identity, local-file verification, configuration preservation,
native-owner exclusion, job delivery and remote input leases. The Python 3.11 runtime
successfully compiled `gbox` and started an isolated authenticated HTTP service
with a real online worker, 269 registered tools, and zero game sessions in
10.44 seconds. A second HTTP acceptance dispatched a harmless central echo job,
validated its real artifact, recovered 13 replies/retries as one local execution,
then executed another local job after central disconnection. A fixture-only HTTP
transport acceptance delivered four JPEGs in one upload, completed a real scoped
RPC round trip, and preserved a local hold when the remote lease ended. No smoke
or transport test launched an emulator or touched a user profile. The final two
HTTP acceptances passed together in 27.59 seconds, including a real queued central
request with an unavailable UNC path resolved locally without executing a game.
