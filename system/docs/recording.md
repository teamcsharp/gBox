# Application and gameplay recordings

Click the title-bar recording icon to record **gameplay only** with playback audio. Click it again to stop.
Start a game first and keep its picture visible; missing gameplay never falls back to capturing the app.
Open the adjacent arrow (▾) to change **Record icon captures** to **Whole application**, or use either one-time recording button.

The menu also stores size, speed, capture mode, original retention and export folder in this desktop instance's
`settings.json` (`recording`), independent of other PCs or standalone installations. Choose or paste a folder;
the managed LAN desktops initially export to `\\10.89.1.246\spark_ext\samples_grabbed\user\gBox`.
Standalone installations initially use their local recordings folder. Each instance can change its own destination.
An empty export setting keeps processed videos locally. Existing size/speed choices migrate from the old browser
preference; the new defaults capture gameplay and keep originals.

Full-size originals remain in `%LOCALAPPDATA%/gbox/recordings`. **Keep full-size original locally** defaults on.
Turning it off permits deletion only after processing/export succeeds and the original is unchanged. Network/export
failure retains the original and the local compressed file, with their paths in the error. Output is staged, flushed,
and checked with SHA-256. Same-name files from other instances are preserved with a unique export filename.
Compressed local staging copies are removed after verified external export. Clips already below the limit are also
exported without another encode; with no size limit, the original recording is exported as-is. Existing recordings
are not retroactively moved or deleted. **Open export folder** and **Open originals folder** are separate menu actions.

Right-click the icon for **Replay**: export the last 30 s to 2 min of play after the fact, from the background gameplay ring that records while the controller is in use ([ring_recording.md](ring_recording.md)).
Replay's **Export clip** uses this same per-instance export folder, including from
the embedded Sessions panel, and confirms the saved path. A failed share copy offers
**Retry saving clip** and preserves the clip for recovery and attachments.

Both choices capture PC playback audio, including audible gameplay, through Electron's system loopback. They do not capture the microphone. Other audio playing on the PC is included. Compression retains an AAC audio track and reserves 128 kbps for it within the file-size budget.

Native games use the embedded client rectangle; streamed games use the image's actual aspect-fitted picture. Recording follows moves and resizes on the original display, keeps its initial output dimensions, and stops if the game is no longer visible or moves off that display. This is a crop of the visible screen, so content covering the game can appear in the recording.

Implementation details: the display-media handler permits the main application renderer only while a recording is active. The cropped canvas receives the loopback audio track. Explicit canvas frame requests keep video frames flowing when animation callbacks are suspended. Recorded chunks are queued and fully written before the file is finalized. A failed start closes capture tracks and removes the partial file.

References: [Electron desktop capture](https://www.electronjs.org/docs/latest/api/desktop-capturer), [HandBrake audio encoding options](https://handbrake.fr/docs/en/1.10.0/cli/command-line-reference.html).

Validation on Windows with Electron 38.8.6: actual application and gameplay recordings contained H.264 video and non-silent AAC audio. The 320×240 gameplay recording excluded the surrounding red test frame and window controls present in the 660×520 application recording. The production ffmpeg compression handler reduced a 2,918,033-byte recording to 145,102 bytes under a 0.15 MiB test limit, retaining both video and audible AAC. JavaScript syntax and whitespace checks passed. HandBrake's audio flags were checked against its documented CLI; its executable was not installed for a runtime test.
