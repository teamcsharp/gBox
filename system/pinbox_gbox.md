# Pine Box → central gBox on Spark1

Use **lilspark (Spark1)** as Pine Box's single gBox discovery and media origin. It aggregates gameplay from
lilspark, i9-NUC and JAYBUILTFINALE. Discover streams from this service; do not have Pine discover emulator windows
or connect separately to each computer's desktop capture.

| Caller | Central gBox base URL |
|---|---|
| Pine on the Spark host / host-network container | `http://127.0.0.1:8765` |
| Home LAN | `http://10.89.1.246:8765` |
| Device connected to the Tailscale network | `http://100.74.95.59:8765` |

The Tailscale address was verified on the Spark. A device must have a working route into that tailnet to use the
private `100.74.95.59` address. Use the IP form when MagicDNS is unavailable. Pine's existing public HTTPS listener
is **`https://lilspark.tail1fec29.ts.net`**, forwarded to its tune-in-only port `8097`; it relays gameplay server-side.
The gBox control plane does not need a public Funnel endpoint. An HTTPS listener page should use Pine's same-origin
relay, rather than trying to embed an HTTP gBox URL directly.

## Connect Pine's service

Set `GBOX_URL=http://127.0.0.1:8765` for Pine running on Spark host networking. For a bridged container, use the
reachable host LAN address instead. Keep a dedicated gBox broadcast **view** token in Pine's existing
`data/gbox_token` secret file or `GBOX_TOKEN` environment variable. The operator creates that token in gBox's
Broadcast → Media-source links. A control token is needed only if Pine must change the on-air selection.

Pine sends this token in its upstream `Authorization: Bearer …` header. Browser listeners receive Pine's own
tune-in credentials; the upstream gBox credential stays on the server. The gBox main API token is not a media URL
parameter and is not needed for ordinary stream consumption.

Read `GET /api/broadcast/feeds` for the program, available PCs, sessions, freshness, and media paths. Read
`GET /api/broadcast` for encoder progress, restart/error counts, source identity and isolated audio availability.
These are discovery/status requests, not commands to stop or relaunch a game.

| Desired channel | Stable path prefix |
|---|---|
| Whatever gBox has on air | `/api/broadcast/program` |
| Current gameplay on Spark1 | `/api/broadcast/pc/spark1` |
| Current gameplay on i9 | `/api/broadcast/pc/i9nuc` |
| Current gameplay on Jaybuilt | `/api/broadcast/pc/jaybuilt` |
| A particular session and its replacement chain | `/api/broadcast/session/<exact-session-id>` |

Use the program or PC path when following MercMode between titles. Reusing a stable channel avoids rebuilding the
decoder on every round, title change or worker/session replacement. Trust returned discovery paths and PC aliases;
do not invent a new session ID from a title or reuse an ended worker's ID.

## Select the media transport

**For Pine's browser stage:** use the existing same-origin H.264/AAC HLS relay:

```text
/api/gbox/hls?k=program
/api/gbox/hls?k=pc-spark1
/api/gbox/hls?k=pc-i9nuc
/api/gbox/hls?k=pc-jaybuilt
```

Gameplay media runs in the independent `gbox-pine-media.service` user service. The public HTTPS listener still
uses port `8097`; this gateway serves HLS directly from gBox and forwards other listener requests to Pine's
existing tune-in-only door on loopback `127.0.0.1:18097`. It never imports Pine's station application or runs DJs.
The private studio remains on `8096`. Its player sends only HLS and player assets to the same host on `18098`,
with CORS restricted to that host's studio origin. This keeps station computation and large JSON responses
from blocking video admission. Both media listeners validate current token revocation and stage permissions
from bounded local state files; they do not call the station API to authorize each segment.

The listener page supplies its current Pine tune-in token through the existing relay contract. The bridge validates
that token and the permitted stage channels on every playlist and segment request. It rewrites only known gBox
media objects and shares the upstream encoder/cache between listeners.
Connecting the service does not turn gameplay on air. The operator must enable Pine's gameplay stage and select
the permitted channel through its existing controls; other channel keys are rejected by the guest relay.

The upstream HLS path is `<prefix>/hls/index.m3u8`. The pinned Pine player targets eight segments behind live and
waits for 7.5 seconds of contiguous playable media before startup or resuming after a stall. It uses buffered live
synchronization, a bounded 24-second maximum buffer and a 16 MiB buffer-size setting.
The central encoder retains a 12-segment playlist plus 12 recently referenced segments by default. This trades a
few seconds of latency for a steadier stream; it does not add another encode per browser. Normal settings are
720p30 H.264 with 48 kHz stereo AAC. The actual game may produce fewer distinct frames than the encoder rate.

**For an ffmpeg/OBS ingest or native media pipeline:** use `<prefix>.ts`, a continuous H.264/AAC MPEG-TS stream.
Use one upstream connection and fan out its decoded/compressed media as the consumer requires. Give it a modest
network buffer and reconnect after a genuine disconnect. Do not reopen it on a five-second status poll.

**For thumbnails:** use `<prefix>.jpg`. MJPEG `<prefix>.mjpg` is available for low-latency video-only consumers;
it has no audio and uses more bandwidth than H.264. Avoid continuously decoding many full-rate thumbnails.

## Playback and mixer behavior

- Keep the selected decoder attached while title, score, thumbnail URL or station metadata changes. Change its
  source only when the selected channel actually changes. Temporary metadata failures preserve current playback.
- Honor an explicit station `show:false` or listener hide action. A failed status poll is not an off command.
- Preserve the last decoded frame during reconnection, then resume the same stable channel. Report buffering and
  reconnecting separately from an intentionally paused game or a slate awaiting a replacement source.
- Pine's **Gameplay volume** controls only game audio. Keep DJ, SFX and station-video levels separate. Browser
  autoplay starts muted; the listener enables gameplay sound with the existing button.
- Release media requests/decoders when the listener hides the stage or background tab. On return, rejoin the same
  channel. Do not launch another emulator to recover a viewer.

Spark audio is captured from the exact emulator process, not the microphone or whole desktop mix. Windows
per-process audio relay is not yet implemented in this bridge; discovery/audio status must state that limitation.

## MCP for the Pine agent

The existing gBox MCP service on Spark listens at **`http://127.0.0.1:8766/mcp`**. Its HTTP authentication uses the
trusted gBox API bearer credential supplied through the agent's existing secret configuration, not a media token.
That loopback endpoint is for a co-located agent; it is not a public browser/player URL. A remote agent can use its
authenticated SSH tunnel, or run gBox's stdio MCP client against the central API with the matching secret config.

Call these read-only tools first:

```text
get_broadcast_feeds({})
get_broadcast_status({})
list_workers({})
```

Prefer ordinary broadcast HTTP endpoints for ongoing media traffic. MCP discovers and diagnoses feeds; it should
not carry video frames, poll every frame or repeatedly start autoplay. Existing `job_*` tools perform explicit
game actions only when requested. Pine's media bridge does not need to launch games to tune into MercMode.

## Diagnose a pause

Compare source `/api/sessions/<sid>/stream/health`, central `/api/broadcast`, and Pine player state during the same
interval. If source sequence/frame counts and encoder byte counts advance while the playhead stops, investigate
the player buffer/segment requests. If source sequence stops, inspect that worker/emulator capture. If encoder
counts stop while source advances, inspect encoder errors and load. Do not equate a healthy HTTP response with
advancing video.

Pine exposes `GBoxTune.state()` and its `gameplay` state, including attachments, stalls, buffer ahead and recent
errors. Healthy metadata polls must not increase decoder attachments. A rollout should be checked with sustained
decoded frames and non-silent emulator audio on the actual LAN/Tailscale listener path, including a game restart.
Inspect `systemctl --user status gbox-pine-media.service` separately from the Pine container. If HLS requests
still reach private port `8096`, the listener has an older player and should reload its static assets.

Each managed desktop runs its own loopback authority on `127.0.0.1:18765` for installed games, mods and autobots.
The desktop pairs an outbound bridge with the configured central service; Pine still connects only to Spark.
There is one native worker on the desktop. Its real session IDs, command identities and ownership survive the
bridge, and a central disconnect leaves its local game running. Reconnecting renews discovery and viewer demand;
it never repeats a launch. A stale/offline bridge is different from a positively ended session.

Central commands are submitted once to the local authority with durable central/local job mappings. Input has a
short expiry and its own held-key lease; delayed mutating RPCs are not blindly retried. Media relays reuse the
owning worker's cropped game capture only while a central viewer is watching. They do not launch another emulator.
An older remote-owned emulator must remain with its original adapter until it ends; the new local process does
not adopt that adapter. See [desktop ownership and fallback](docs/desktop-local.md).

MercMode is configured per host through `GET/POST /api/mercmode` or the desktop MercMode panel. The verified
rotation currently covers RE4 GameCube and RE5 PS3, including RE5 original/Reunion selection. RE6 is reported
unavailable until its native combat/menu/round readers exist. A title is ready only after that host's actual launch
or a fresh local ROM-access probe. RPCS3 retains installed data and shader caches but still boots through native
menus. See [MercMode readiness and run data](docs/mercmode.md).

Closed RE4/RE5 rounds with matching Atlas and Notebook records sync through a durable, content-addressed outbox.
The central reviewer receives measured paths, enemies, health samples, available checkpoint events and source identity,
plus score samples when the title reader supplies them, and regenerates its map and guide. RE4 score and rank
remain unknown. Offline data stays local until the exact package is acknowledged. Transfers are
bounded to 8 MiB raw/4 MiB compressed per round; missing provenance or oversized evidence remains local with a reason.
This is not a full RAM, damage-save or tactical-stream archive transfer. Importing a path does not authorize a
cross-PC navigation-policy transplant or prove semantic-vector delivery; KB delivery requires its own real ACK.

Implementation: [broadcast server](gbox/broadcast.py), [Pine bridge](integrations/pinebox/README.md),
[broadcast API reference](docs/broadcast.md). Buffer semantics follow the pinned
[Hls.js API](https://github.com/video-dev/hls.js/blob/v1.7.3/docs/API.md#initiallivemanifestsize) and
[FFmpeg HLS muxer](https://ffmpeg.org/ffmpeg-formats.html#hls-2).
