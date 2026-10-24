# Pine gameplay HLS bridge

This extension upgrades Pine's selected gBox gameplay from remote 1 fps JPEGs
to the existing shared H.264/AAC broadcast encoder. It does not create an extra
encode. The current gBox broadcast settings provide the canvas, bitrate and
frame rate (normally 30 fps); an emulator running below 30 fps still repeats
source frames. The player waits for 7.5 seconds of contiguous playable media and targets eight
segments behind live, with buffered synchronization and a bounded 24-second
maximum buffer. This allows a larger jitter cushion than the previous two-segment target.

Gameplay has its own **Gameplay volume** slider. It changes only the gameplay
video element. DJ, station video and SFX levels are untouched. Browsers begin
with muted autoplay: click **Enable gameplay audio** to hear the game.
Small secondary tiles retain low-cost JPEG previews. Hidden tabs and a hidden
stage release the gameplay decoder and requests.

The same-origin `/api/gbox/hls` relay checks the existing live tune-in token
and `gboxstream.HUB.allowed_keys()` on every playlist and segment, including
cache hits. House reads and preview signatures keep the existing contract.
Only fixed gBox broadcast paths and numeric MPEG-TS segment names are accepted.
The gBox credential stays in the server-side Authorization header. No gBox
credential or upstream URI is forwarded in a playlist or error. A 32 MiB / 64
object cache coalesces shared segment requests, with at most four upstream
downloads. Blocking HTTP runs outside Pine's event loop.

The pinned official Hls.js 1.7.3 runtime, its license notices and full Apache
license are checked in under `frontend/vendor`; hashes and official download
URLs are in `vendor-manifest.json`. The pinned MSE player is preferred so its
live buffer bounds apply; native HLS is the fallback when MSE is unavailable.
If a browser advertises native HLS but reports an actual media error, the
player falls back to the pinned Hls.js decoder. Fatal media errors use the
documented recovery API before a complete reattach. Resumed playback clears
the recovery status and cancels a pending retry. A canvas holds a decoded
frame through reattachment, refreshed at most once a second at up to 960×540;
selecting another feed clears that held picture. A bounded error history and
the actual transport are available through the player's `state()` method.
It also exposes stall/attachment counts and buffer ahead. Thumbnail/metadata
changes and temporary station-status failures preserve the current decoder;
an explicit station off command still stops it. The centralized connection
contract is [pinbox_gbox.md](../../pinbox_gbox.md).

Install with Python inside the Pine runtime (or a host with FastAPI/httpx):

```sh
python /path/to/this/package/install.py /home/ehm_eckx/pinevoice-stack/spark-agent
```

The installer verifies vendor hashes and the unique existing `gboxstream`
installation hook, compiles the patched application, saves changed originals
under `backups/gbox-hls-<timestamp>`, and writes files atomically. It adds three
integration lines to `app.py`. It never restarts Pine, enables station mode,
changes the stream selection, or edits credentials. Restart the Pine container
once through the operator's existing activation procedure, then reload the
listener page. Restore the backed-up files to roll back.

Run tests using `python -m pytest tests/test_pine_hls.py` and
`node --test tests/test_pine_hls.cjs` from this directory. Live acceptance must
also verify real non-silent emulator audio and playback on the actual external
listener path; passing unit tests alone does not prove either.
