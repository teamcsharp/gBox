# Making the server's output readable

## Why this is the fix that has been missing all night

`main.js` collects everything the app and its children print into **one in-memory string**:

```js
let CONSOLE = "";
const logPush = (src, text) => { CONSOLE = (CONSOLE + `${time} [${src}] ${text}\n`).slice(...); };
```

and exposes it **only** through `ipcMain.handle("console:tail")` - an Electron IPC channel, which nothing outside the app can call. **That is why every
diagnostic I wrote this session vanished**: the server's stdout is consumed for the handoff protocol and the app's own UI, and never lands on the filesystem.

## Two small additions

**1. `logPush` also appends to a file.** Every line the app already collects - main process, both webviews, task streams - now goes to
`D:\gBox\pso-ds\app-console.log`, through one `appendFileSync` in a try/catch so a logging failure cannot break anything. The in-memory buffer and the IPC
channel are untouched.

**2. The worker child is teed.** The local server tree is spawned at line 183 and its output consumed by `workerChannel`. A `teeChild(child, "worker")` call -
added just before that - attaches two `.on("data")` listeners that append to the same file. It **does not consume the stream**, so the handoff protocol and
the app's UI still receive every chunk.

Verified: `node --check main.js` passes, and the two additions are at lines 102 (`CONSOLE_FILE`), 105 (`teeChild` helper) and 199 (`teeChild(child, "worker")`).

## What it gives us after the reboot

* every line the server prints is on disk, including the app's own `_p(50, "virtual pad unavailable ...")` message when a launch declines to build a pad;
* the vpad question can be answered by reading a file rather than by racing processes;
* the same file becomes the reference for any future launch or worker problem.

## What to do

**Reboot gBox** (as planned), then **launch PSO once**. Then `D:\gBox\pso-ds\app-console.log` exists and contains the server's own account of the launch -
including whether a virtual pad was created, and why not if it was not.

That is the diagnostic I could not get any other way tonight.
