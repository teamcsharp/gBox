# Application and gameplay recordings

Click the title-bar recording icon to record the application. Click it again to stop.
Right-click the icon and choose **Record gameplay only + audio** to record the visible game picture without the surrounding application or emulator window. Start a game first and keep its picture visible. The adjacent arrow also opens these choices and the existing size/compression options.

Both choices capture PC playback audio, including audible gameplay, through Electron's system loopback. They do not capture the microphone. Other audio playing on the PC is included. Compression retains an AAC audio track and reserves 128 kbps for it within the file-size budget.

Native games use the embedded client rectangle; streamed games use the image's actual aspect-fitted picture. Recording follows moves and resizes on the original display, keeps its initial output dimensions, and stops if the game is no longer visible or moves off that display. This is a crop of the visible screen, so content covering the game can appear in the recording.

Implementation details: the display-media handler permits the main application renderer only while a recording is active. The cropped canvas receives the loopback audio track. Explicit canvas frame requests keep video frames flowing when animation callbacks are suspended. Recorded chunks are queued and fully written before the file is finalized. A failed start closes capture tracks and removes the partial file.

References: [Electron desktop capture](https://www.electronjs.org/docs/latest/api/desktop-capturer), [HandBrake audio encoding options](https://handbrake.fr/docs/en/1.10.0/cli/command-line-reference.html).

Validation on Windows with Electron 38.8.6: actual application and gameplay recordings contained H.264 video and non-silent AAC audio. The 320×240 gameplay recording excluded the surrounding red test frame and window controls present in the 660×520 application recording. The production ffmpeg compression handler reduced a 2,918,033-byte recording to 145,102 bytes under a 0.15 MiB test limit, retaining both video and audible AAC. JavaScript syntax and whitespace checks passed. HandBrake's audio flags were checked against its documented CLI; its executable was not installed for a runtime test.
