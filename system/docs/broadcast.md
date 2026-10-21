# Broadcast: gBox gameplay as a media source for Pine Box

Operator, 2026-10-20: "I need pine box to be able to connect to the active gbox feed of any instance of gbox on the
network showing gameplay and be able to stream and pick up stable streaming video via pine box as a media source."

The control plane on the Spark serves one **program** feed (what is on air) plus one feed per PC and one per session,
covering every gBox PC: the Spark's own sessions and the Windows PCs' (JAYBUILTFINALE, the i9-NUC). Any software that
takes a network media source can use them: Pine Box, OBS, VLC, ffmpeg. Code: `gbox/broadcast.py`; settings:
`[broadcast]` in `gbox.toml`; client control: `clients/web/viz/broadcast.js`.

## The feeds

| Feed | Path | Shows |
|---|---|---|
| Program | `/api/broadcast/program` | The game on air (see [Picking the program](#picking-the-program)). |
| A PC | `/api/broadcast/pc/<pc>` | Whatever game that PC runs now, across relaunches and swaps. `<pc>`: `lilspark`, `i9-nuc`, `jaybuiltfinale`, or Pine Box's own names for them, `spark1`, `i9nuc`, `jaybuilt` (case and dashes do not matter). |
| A session | `/api/broadcast/session/<session id>` | That session; it follows a swap or reset relaunch of it. |

Each feed in four formats. Append the suffix to the path:

| Suffix | Format | Notes |
|---|---|---|
| `.mjpg` | MJPEG over HTTP (`multipart/x-mixed-replace; boundary=gboxframe`, each part with `Content-Length`) | A constant frame rate (default 30; `?fps=1..60`): the newest picture every tick, so a quiet source repeats its picture. Zero encoding cost: the frames the PCs already send pass through. The picture keeps the source's own size, so it changes size when the program switches between games. |
| `.jpg` | One JPEG | The newest picture. Headers `x-gbox-session` and `x-gbox-state` (`live`, `hold`, `slate`). |
| `.ts` | H.264 (+ AAC) in MPEG-TS over HTTP | 1280x720, 30 fps, 2.5 Mbit/s constant, 1 s GOP, every source fitted inside the canvas (letterbox or pillarbox), so the size never changes. A new reader starts on a keyframe at once (the newest GOP is kept for it). |
| `/hls/index.m3u8` | HLS (the same H.264 encode) | 1 s segments, a list of 6. Expect a few seconds of latency (players start about three segments from the live end); `.ts` and `.mjpg` add well under a second on the server side, plus the player's own buffer. |

None of these responses ends while its reader stays: not on a program switch, not when a session ends, not when a
source stalls. What it shows meanwhile:

| Moment | What the feed shows |
|---|---|
| The source pauses (state save, emulator pause, upload reconnect) | The last picture, repeated: up to 8 s for a streamed game (`hold_s`), 15 s for a Windows game's stills, 3 s for its window crop before its stills take over. |
| The source stays silent longer, or the game is not on its PC's screen | A slate: that last picture dimmed and blurred, the game's title and why (for example "on i9-NUC: waiting for the game to show on that PC's screen"). Same size as the picture, so an MJPEG reader sees no size jump. |
| A switch to a game whose picture has not come yet | The previous picture holds up to 4 s, then the slate. |
| The session on air ends | Its last picture holds 2 s (`end_hold_s`), then the program moves on to the next game, or to the "No game on the air" slate. |

The H.264 encoder (one ffmpeg per watched feed, `nice -n 10`) starts when the first `.ts` or HLS reader arrives and
stops 20 s after the last one leaves (`linger_s`). At most 3 run at once (`max_encoders`); MJPEG has no limit because
it encodes nothing. If ffmpeg dies or stops taking pictures for 10 s it is restarted with backoff, and `.ts` readers
stay connected through the restart (the HLS list continues its numbering with a discontinuity mark).

### Sources: what each PC gives

Only a game's own picture goes on air, never a PC's desktop or the gBox window.

| Kind | PC | Where the picture comes from | Rate |
|---|---|---|---|
| `spark_capture` | the Spark | The session's own Xvfb display (x11grab), the same stream the gBox viewers show | up to 60 fps |
| `windows_stream` | Windows | A session its worker streams (RPCS3, RocketLauncher: gdigrab) | up to 60 fps |
| `desktop_crop` | Windows | A native game (Dolphin, RetroArch and the other local-window emulators): that PC's desktop stream (the Other PC view's source), cut once per frame to the game's own window. While a broadcast reader shows such a game, the broadcast keeps that PC's screen capture running, as an open Other PC view does. | 8 fps |
| `stills` | Windows | The same game's window stills, when no crop is available | one every 4 s |

A native Windows game only has a picture while that PC's screen shows its window: minimized, covered, parked
off-screen or a sleeping screen gives the slate ("waiting for the game to show on that PC's screen").

### Sound

The H.264 feeds always carry an AAC track (48 kHz stereo, 128 kbit/s): silence unless the source has sound.

- **Spark sessions**: an emulator that plays through PipeWire (Dolphin does) is copied with
  `parec --monitor-stream=<its stream>`. The stream is found by the session's X display (`window.x11.display`). The
  copy does not move the stream or change what plays on the Spark's outputs, and costs almost nothing (0.2% of one
  core, measured). RetroArch on the Spark plays no sound (`audio_driver = null` in
  `gbox/adapters.py`), so its games are silent. Giving them sound means launching RetroArch with the `pulse` driver,
  which would also play their sound out of the Spark's HDMI output.
- **Windows sessions**: no sound. It plays on that PC; sending it would need a new capture on the worker (WASAPI
  loopback, which is the whole PC's sound, not one game's).
- MJPEG has no sound by nature.

`[broadcast] audio = "off"` drops the track.

## Picking the program

- **Auto (default).** The program follows the game the operator watches in gBox. The web UI and the desktop app (its
  Sessions view is the web UI) report the session they show, on every change and once a minute while visible
  (`POST /api/broadcast/watching`): the game open in Sessions, kept in picture-in-picture, or played on this PC. When
  the app shows no game, the program stays on the game on air while that game has a picture (or while no other game
  has one). When it ends, or loses its picture while another game has one, the next game is the newest one with a
  picture, the operator's games before agents' and bots' (`auto_agents = false` leaves agents' and bots' games out).
- **On air button.** In a running game's header, the broadcast icon is pressed while that game is on air. Clicking it
  pins the game on air whatever you watch; clicking it again on a pinned game gives the program back to auto. A pinned
  game that is swapped or reset stays on air (the pin follows it); one that ends hands the program back to auto.
- **Sessions list.** The Broadcast bar shows what is on air and why, its picture, an **Auto** button, and
  **Media-source links**: make a link (a broadcast token, see below), see its URLs once, revoke links.
- **API.** `POST /api/broadcast/program` with one of:
  - `{"session_id": "<sid>"}`: pin a running session (409 if it is not running);
  - `{"pc": "i9nuc"}`: pin a PC, so the program shows whatever that PC runs (404 for an unknown PC);
  - `{"session_id": "auto"}` or `"auto"`: back to auto.

  Automation (actors `agent`, `hermes`, `mcp`) is refused (403): the operator or Pine Box (with a control token)
  decides what is on air. Every switch is in the audit log (`broadcast.program`).

## Authentication: broadcast tokens

Media sources put credentials in the URL, so they get their own tokens, never the gBox `api_token`.

- A broadcast token looks like `gbb_...`. Use it as `?token=gbb_...` (or `?t=`), or as `Authorization: Bearer gbb_...`.
- **view** tokens (the default) can read the feeds, `GET /api/broadcast` and `GET /api/broadcast/feeds`. **control**
  tokens can also switch the program. Neither works on any other gBox route, and neither can list or make tokens.
- Only a SHA-256 of each token is stored. The token is shown once, when it is made.
- The `api_token` works on these routes in the `Authorization` header only. In a URL it is refused with 401.

Make and revoke them in Sessions > Broadcast > Media-source links, or with the API (`api_token` in the header,
operator only):

```
POST   /api/broadcast/tokens        {"name": "Pine Box", "scope": "view" | "control"}
         -> {id, name, scope, token, program: {lan: {mjpeg, jpeg, ts, hls}, tailnet: {...}}, feeds: {lan, tailnet}}
GET    /api/broadcast/tokens        -> [{id, name, scope, created, last_used, last_from, uses, revoked}]
DELETE /api/broadcast/tokens/{id}   -> revoked at once
```

## API

| Route | Auth | Returns |
|---|---|---|
| `GET /api/broadcast/feeds` | view | `program` (what is on air, `mode` auto/session/pc, `why`, `state` live/hold/slate, the operator's last `watching` report, its URLs), `feeds` (every running session on every PC: `id`, `session_id`, `title`, `pc`, `os`, `kind`, `resolution` [w, h], `fps`, `last_frame_age_s`, `live`, `agent_owned`, `on_air`, `paths`, `lan`, `tailnet`, `pc_paths`), `pcs` (each PC: `online`, `aliases`, the session its feed shows now, URLs), `bases`, `formats`. URLs carry the token they were asked with. |
| `GET /api/broadcast` | view | The program, the feeds being read (viewers, state), the H.264 encoders (pid, readers, frames, restarts, sound). |
| `POST /api/broadcast/program` | control | See [Picking the program](#picking-the-program). |
| `POST /api/broadcast/watching` | api_token (operator) | The app's report: `{"session_id": "<sid>" \| null}`. |
| `GET/POST/DELETE /api/broadcast/tokens` | api_token (operator) | See above. |
| `GET <feed>.mjpg?fps=`, `.jpg`, `.ts`, `/hls/index.m3u8` | view | The pictures. |

## URLs

On the Spark itself (Pine Box runs there):

```
http://127.0.0.1:8765/api/broadcast/program.ts?token=gbb_...
http://127.0.0.1:8765/api/broadcast/program.mjpg?token=gbb_...
http://127.0.0.1:8765/api/broadcast/program/hls/index.m3u8?token=gbb_...
http://127.0.0.1:8765/api/broadcast/feeds?token=gbb_...
```

On the LAN: `http://10.89.1.246:8765/...` (the same paths).

On the tailnet (gBox listens on every interface, so the Spark's tailnet address works from any device on the
tailnet, through Tailscale's encryption):

```
http://100.74.95.59:8765/api/broadcast/program.ts?token=gbb_...
http://lilspark.tail1fec29.ts.net:8765/api/broadcast/program.ts?token=gbb_...   (devices using MagicDNS)
```

The name works only for devices that use MagicDNS. Elsewhere, including the Spark itself, public DNS answers it with
the Tailscale Funnel addresses, where only `https://lilspark.tail1fec29.ts.net/` (Pine Box's app on port 8097) is
served. Set `[broadcast] tailnet_url` to the form your devices use, and `/api/broadcast/feeds` lists tailnet URLs
beside the LAN ones.

gBox is not on the Funnel and should stay off it: Pine Box's listeners reach Pine Box, and Pine Box reads gBox on the
Spark. For HTTPS on the tailnet only (not the public internet), an administrator can add a tailnet-only Tailscale
Serve endpoint. This is optional; nothing here needs it:

```
sudo tailscale serve --bg --https=8443 http://127.0.0.1:8765
# -> https://lilspark.tail1fec29.ts.net:8443/api/broadcast/program.ts?token=gbb_...   (tailnet only)
sudo tailscale serve --https=8443 off          # to remove it
```

Do not use `tailscale funnel` for gBox: it would put the control plane on the public internet.

## Media-source settings

Program feed for a broadcast: `.ts` (constant size, sound, low latency). For a picture in a web page or an app that
shows JPEGs: `.mjpg`.

- **Pine Box.** It runs on the Spark, so it reads gBox over loopback:
  - The stage: `http://127.0.0.1:8765/api/broadcast/program.ts?token=gbb_...`, through the same kind of ffmpeg ingest
    it runs for its own `live.ts` camera (`-fflags nobuffer -flags low_delay -i <url>`), or `program.mjpg` for its
    JPEG relay.
  - Its device locks map to the PC feeds, with its own names: `pc/jaybuilt.mjpg`, `pc/i9nuc.mjpg`, `pc/spark1.mjpg`
    (the feed follows that PC's game across relaunches and swaps, and shows a slate when the PC runs none).
  - Its tiles: `GET /api/broadcast/feeds` lists every live game with title, PC, kind, size, rate and URLs.
  - Its panel can switch what is on air with a control token: `POST /api/broadcast/program`.
  - Its relay today (`gboxstream.py`) reads `/api/sessions`, `/api/workers` and each session's or PC's stream with
    gBox's `api_token`, and falls back to a PC's whole desktop (`view=desktop`). With the broadcast it needs only a
    broadcast token (in `data/gbox_token`; the `api_token` can be removed from Pine Box), and no desktop ever goes on
    air. Those are changes in Pine Box's code, not gBox's.
- **OBS.** Media Source, untick Local File. Input: the `.ts` URL. Input format: `mpegts`. Tick "Restart playback when
  source becomes active". Network buffering 1 MB or less. Reconnect delay 2 s. For MJPEG: input format `mpjpeg`.
  Browser Source with an `<img>` of the `.mjpg` URL also works.
- **VLC.** Media > Open Network Stream: the `.ts` URL (or the HLS one). Show more options: caching 300 ms.
- **ffmpeg.**
  `ffmpeg -fflags nobuffer -i "http://127.0.0.1:8765/api/broadcast/program.ts?token=gbb_..." -c copy out.ts`.
  For MJPEG: `ffmpeg -use_wallclock_as_timestamps 1 -f mpjpeg -i "http://.../program.mjpg?token=gbb_..." ...`. The
  MJPEG rate is exactly the `?fps=` asked for (header `x-gbox-fps`).

## Settings

```toml
[broadcast]
enabled = true
fps = 30               # MJPEG frames a second (each viewer may ask ?fps=1..60)
ts_fps = 30            # H.264
size = "1280x720"      # H.264 canvas
video_kbps = 2500
encoder = "libx264"    # libx264 (ultrafast, zerolatency) | h264_nvenc
audio = "auto"         # auto | off
audio_kbps = 128
hls_segment_s = 1
hold_s = 8.0           # a silent source's last frame holds this long, then the slate
end_hold_s = 2.0       # an ended session's last frame holds this long, then the program moves on
watch_ttl_s = 900.0    # the operator's "watching" report counts this long
linger_s = 20.0        # an H.264 encoder nobody reads stops after this
max_encoders = 3
auto_agents = true     # auto may put an agent's or a bot's game on air when no operator game runs
nice = 10
lan_url = ""           # default: public_url
tailnet_url = ""       # e.g. "http://100.74.95.59:8765"
pc_aliases = { spark1 = "lilspark", jaybuilt = "JAYBUILTFINALE", i9nuc = "i9-NUC" }
```

## Cost on the Spark

The Spark also runs Pine Box's own services (voice, pinelive, pinelink, ollama, whisper). Measured there on
2026-10-20, over an 11-minute run with the load average at 32 to 38 on its 20 cores. Figures are percent of one core:

| Part | CPU | When it runs |
|---|---|---|
| The broadcast in the control plane: the hub, two MJPEG readers at 30 fps, the MPEG-TS fan-out, HLS, the picture and sound writers | +3.2% (the process went from 3.3% to 6.5%) | while anything reads a feed |
| The H.264 encoder: ffmpeg, libx264 ultrafast, 1280x720 at 30 fps, 2.5 Mbit/s, plus AAC 128 kbit/s, at nice 10 | 23.4% on average (20.9 to 25.7%) | only while a `.ts` or HLS reader is connected, plus 20 s |
| The sound tap (`parec`) | 0.2% | while an H.264 feed shows a Spark game that plays sound |

MJPEG encodes nothing: the frames the PCs already send pass through. `h264_nvenc` measured about the same CPU as
libx264 ultrafast on the GB10 (21% against 24% at 720p30), because decoding the JPEGs and scaling them stay on the
CPU. The whole H.264 path is about 1.3% of the Spark.

Stability in the same run: the program feed, read for 11 minutes across three program switches (plus three requests
that kept the same game), a Windows game with no picture on its screen, and two session ends:

| Reader | Result |
|---|---|
| MPEG-TS, `ffmpeg -c copy` | 19,753 frames in 658.4 s: 30.0 fps, every frame 33.33 ms after the last (no gap over 50 ms), one keyframe a second, always 1280x720, 0 decode errors. The AAC track ran the whole time without a gap; it carried the game's sound while a Spark game with a PipeWire stream was on air, silence otherwise. |
| HLS, `ffmpeg -i index.m3u8` | 8,159 frames in 272 s: 30.0 fps, no gap, 0 decode errors, sound as above. |
| MJPEG at `?fps=30`, timed per part | 19,798 parts, 30.06 a second, the longest gap 84 ms, no disconnect. The picture size followed the source (640x480, then 960x720, then 640x480). |
| MJPEG, `ffmpeg -f mpjpeg` | No disconnect, no error. One "EOI missing, emulating" line when it connects (ffmpeg probing the first part), then none. |

ffmpeg's mpjpeg reader stamps frames as 25 fps, because MJPEG over HTTP has no timestamps. Add
`-use_wallclock_as_timestamps 1`, or ask for `?fps=25`, to keep it in real time.

## The recording ring and the app's recording

The broadcast does not use the background replay ring ([ring_recording.md](ring_recording.md)) or the desktop app's
title-bar recording ([recording.md](recording.md)) as a source. Reasons:

- The ring records only while the operator's controller is in use: autoplay, bots, agents' games and idle sessions
  have none.
- It captures the same picture as the live feed: the same Xvfb display on the Spark, the same window on Windows. When
  the live feed stops because the emulator or its display stalled, the ring stalls too.
- A Windows PC's ring is on that PC's disk. The control plane gets it only through an export job, which re-encodes it
  to MP4: seconds late, and heavy on the PC the operator plays on.
- The title-bar recording is a file the desktop app writes on the operator's PC (with the PC's sound). It is not a
  stream.

The feed the gBox apps watch and record (the session stream) is the broadcast's source: the program carries the
same picture. Use the ring for what it does well, replays. A moment that went out on air can still be clipped
afterwards (right-click the record icon, Replay) and played in Pine Box as a clip.

## Checks

- `python -m pytest tests/test_broadcast.py -q -p no:cacheprovider` covers:
  - the program's choice (auto follows what the operator watches, pins, relaunches, ends);
  - the live / hold / slate machine with a fake clock;
  - Windows game crops and stills, and the desktop watch they keep running;
  - tokens and the route rules;
  - the MJPEG rate across a switch and a session end (over a real HTTP server);
  - the MPEG-TS GOP cutter;
  - the encoder's supervision (fake ffmpeg);
  - the sound tap;
  - the client controls (`tests/test_broadcast_control.cjs`, run by node).
- `GBOX_LIVE_FFMPEG=1` adds a run of the real ffmpeg: MPEG-TS across a switch, HLS, both probed.
- Live: `ffmpeg -i "http://127.0.0.1:8765/api/broadcast/program.ts?token=gbb_..." -c copy -t 60 out.ts`, switch the
  program meanwhile, then
  `ffprobe -v error -select_streams v -show_entries frame=pts_time -of csv out.ts` (frames 33.3 ms apart).
