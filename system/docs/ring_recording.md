# Replay: the background gameplay ring (#1084)

While you play, gBox keeps the last couple of minutes of the game on disk, so a moment can be clipped **after** it
happened. Right-click the title-bar record icon (desktop app; the web client has a **🎬 Replay** button in the session
panel): a small pop-up shows what the ring holds, lets you set **In** and **Out** on a timeline, a **size goal** in MB,
and **Export clip**. The clip opens / saves, or attaches to a request (as a message attachment) or a mod card (its
video). In the desktop app, **Export clip** also saves the MP4 to this instance's
configured recording export folder (the same folder as processed title-bar recordings).
This includes Replay opened from the embedded Sessions panel. The popup confirms
**Saved to** with the exact path and offers **Show in folder**. A plain browser
continues to offer its normal **Open / save** download.
The ▾ next to the icon keeps the app recording options (application / gameplay-only recording, size limit).

Code: `gbox/ring_record.py` (the ring), `tools.recording` (the worker tool), the hooks in `tools._launch_game`
(start), `tools._pump` (streamed pad events, session end), `tools.session_op` / `_close_previous_games` (stop).
Client: the `replay ring pop-up (#1084)` section in both `clients/desktop/index.html` and `clients/web/index.html`.

## When it records

Only while the controller is in use: capture starts on the first press and stops **20 s** after the last one
(`[recording] idle_s`). Nothing is recorded while nobody plays, while the agent or autoplay drives the game, or in
menus you left idle, so an idle session costs nothing. Each active stretch is one ffmpeg run; the clip timeline joins
the runs and skips the idle gaps.

The pad signal is the one gBox already has; there is no second poller:

| Where | Signal |
|---|---|
| Windows (local window) | `padstate.watch_xinput`, the XInput slot-0 poll that feeds the controller glyph, stamps `padstate.PLAYER_TOUCH` |
| Streamed sessions (the Spark) | the operator's pad events passing through `tools._pump` (`ring_record.touch`, next to `rewind.feed`); only events with a `player` number count (physical pads), not gBox's own presses |

## What it captures and how

| Node | Source | Notes |
|---|---|---|
| Windows | `gdigrab` of the emulator window's area on screen | what the screen shows (like `win_grab`'s desktop path): a window covering the game is recorded too |
| Windows, window parked off-screen | `gdigrab` of the window itself (`hwnd=` with ffmpeg 7.1+, else `title=`) | GPU-rendered windows may come out black this way |
| Windows, `capture = "ddagrab"` | Desktop Duplication on the GPU, straight into NVENC (zero copy) | primary monitor only; needs NVENC, falls back to gdigrab |
| The Spark | `x11grab` of the session's own Xvfb display | |

Encoder: `h264_nvenc` when ffmpeg lists it **and** a 5-frame test encode passes (the NVIDIA GPU encodes; the RGB to
YUV conversion happens there too), else `libx264 -preset ultrafast -threads 2`. The choice and the reason are in the
status (`encoder`, `encoder_note`, shown at the bottom of the pop-up). If NVENC fails twice during a session, the ring
switches to libx264 and says why. ffmpeg runs below the emulator's priority (`priority = "low"`: Windows below-normal,
Linux `nice 10`); on a PC whose CPU is saturated by other work a below-normal capture can be starved on Windows, which
`priority = "normal"` avoids.

The ring is ffmpeg's segment muxer: MPEG-TS segments of `segment_s` (5 s), `-segment_wrap` so one run rewrites its
own files, a csv segment list the worker reads incrementally once a second. No frame passes through Python.

**Disk** per session: at most `seconds` (120) of recorded time plus the segment being written, and at most `max_mb`
(512). The wrap count is chosen so one run fits `max_mb` at the capture bitrate; across runs the oldest segments are
deleted. Files live under `<runtime>/ring_record/<session id>/`. When a session ends its ring is **kept**
(`keep_ended`, default 1: the newest ended session) so the last minutes before a crash or a stop can still be
exported; older ones are deleted, and a worker restart sweeps rings nothing points at.

## Export

`recording` tool, `op = "export"`, `in_s` / `out_s` = seconds before the newest recorded moment (in = the older edge;
`in_s = 90, out_s = 0` is "the last 90 s"), `target_mb` (1..200):

1. the segments covering the range are copied aside (the ring keeps recording meanwhile; the segment being written is
   cut at a whole TS packet),
2. concatenated (ffmpeg concat demuxer) and trimmed exactly with output-side `-ss` / `-t`,
3. re-encoded at `video_kbps = target_mb * 8 * 2^20 * 0.97 / seconds` (3 % left for the MP4 container, never above the
   capture bitrate), with the resolution stepped down (1080 / 900 / 720 / 540 / 480 / 360 / 240) when that bitrate
   would give fewer than 0.04 bits per pixel per frame,
4. if the file still overshoots the goal by more than 2 %, encoded once more at a proportionally lower bitrate.

NVENC failing on the export falls back to libx264 (reported in `encoder_note` and `attempts`). The clip is uploaded as
an artifact (`replay-<game>-<time>.mp4`, provenance: session, game, range, encoder) and deleted from the worker.
There is no audio track (the capture is video only; the app recording keeps PC playback audio).

Desktop export streams the artifact from its configured Spark using authentication,
verifies its byte count and SHA-256, then copies it through the existing verified
recording exporter. The destination is read from current per-instance preferences
at save time, including a custom UNC share; an empty setting uses local recordings.
Duplicate names receive unique filenames. The popup reports folder/download errors
without claiming a save or silently changing destination. The Spark artifact remains
available for attachment, and **Retry saving clip** retries that artifact without
encoding the gameplay again. A verified local copy is retained if the export folder
is unavailable. Corrupt or incomplete downloads are discarded.

This client/main-process change takes effect after reopening the desktop app; it
does not require a backend restart or modify full-size-original retention settings.

## The tool

```
recording {session_id, op: "status"}                      -> {status: {state, span_s, segments [[ago_start, ago_end]], encoder, ...}}
recording {session_id, op: "export", in_s, out_s, target_mb} -> {clip: {sha256, name, bytes, seconds, kbps, width, height, encoder, fits}}
recording {session_id, op: "enable" | "disable"}           -> switches the capture for this session
```

`state`: `waiting` (no pad activity), `recording`, `retrying` (ffmpeg failed; backs off up to 60 s), `off`, `ended`.
Jobs go to the worker that runs the session (`require_worker`). Request messages accept an attachment that names an
artifact gBox already holds (`{"sha256", "name", "type"}`), which is how the pop-up attaches a clip.

## Settings

```toml
[recording]
enabled = true          # false: no background capture (op=enable switches it on per session)
seconds = 120           # how far back a clip can reach
encoder = "auto"        # auto | h264_nvenc | hevc_nvenc | libx264
max_mb = 512            # disk cap per session ring
fps = 30
bitrate_kbps = 8000     # capture bitrate; the export re-encodes to the size goal
idle_s = 20.0           # records while the pad was used within this long
segment_s = 5
capture = "auto"        # auto | gdigrab | ddagrab | x11grab
priority = "low"        # low | normal
keep_ended = 1          # ended sessions whose ring is kept for a late export
```

## Checks

- `python -m pytest tests/test_ring_record.py -q -p no:cacheprovider` (fake ffmpeg `tests/fake_ffmpeg.py`: the idle
  gate, wrap rotation, range to segments, bitrate math, encoder fallback, export, the tool, request attachments);
  `GBOX_LIVE_FFMPEG=1` adds a run against the real ffmpeg (lavfi test picture, NVENC when present, export probed).
- `node tests/test_ring_popup.cjs` (the pop-up in both clients).
- Live: play a game for a minute with the controller, right-click the record icon, Export the last 30 s at 10 MB; the
  pop-up shows `Encoder: h264_nvenc (NVIDIA GPU)` on an NVIDIA PC and the clip opens at about 10 MB.
