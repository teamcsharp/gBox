"""Make the app's console output readable: `logPush` also appends to a file on disk.

The operator asked for this directly, and it is the thing that has blocked every diagnostic in this session.

`main.js` keeps everything in one in-memory string:

```js
let CONSOLE = "";
const logPush = (src, text) => { CONSOLE = (CONSOLE + `${time} [${src}] ${text}\\n`).slice(...); };
```

and exposes it only through `ipcMain.handle("console:tail")` - an Electron IPC channel, which nothing outside the app can call. That is why the vpad probes never
appeared anywhere: the server's stdout is streamed into the renderer and into this string, and the string is invisible from the filesystem.

**The fix**: `logPush` also appends the same line to `D:\\gBox\\pso-ds\\app-console.log`. One `fs.appendFileSync` with a try/catch, so a logging failure can
never break the app. The in-memory buffer and the IPC channel are untouched - nothing that reads them changes.

With that, every diagnostic the app already collects - the main process, both webviews, the worker and task streams - is on disk and can be read.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js")
text = path.read_text(encoding="utf-8")

old = 'const logPush = (src, text) => { CONSOLE = (CONSOLE + `${new Date().toISOString().slice(11, 23)} [${src}] ${String(text).replace(/\\n+$/, "")}\\n`).slic'

if "app-console.log" in text:
    print("already writes a file")
else:
    anchor = "let CONSOLE = \"\";"
    if text.count(anchor) != 1:
        raise SystemExit(f"anchor count {text.count(anchor)}")
    addition = """let CONSOLE = "";
// The same lines go to a file, so the server's and worker's output can be read without the app's IPC channel.
const CONSOLE_FILE = "D:\\\\gBox\\\\pso-ds\\\\app-console.log";
const fsConsole = (() => { try { return require("fs"); } catch { return null; } })();"""
    text = text.replace(anchor, addition, 1)

    # append inside logPush
    if old in text:
        replacement = old.replace(
            "const logPush = (src, text) => { CONSOLE = (CONSOLE + ",
            "const logPush = (src, text) => { try { if (fsConsole) fsConsole.appendFileSync(CONSOLE_FILE, `${new Date().toISOString().slice(11, 23)} [${src}] ${String(text).replace(/\\n+$/, \"\")}\\n`); } catch {} CONSOLE = (CONSOLE + ")
        text = text.replace(old, replacement, 1)
        print("logPush now appends to the file too")
    else:
        raise SystemExit("logPush anchor not found")

    path.write_text(text, encoding="utf-8")

print("--- the patched region ---")
lines = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if "CONSOLE_FILE" in line or ("logPush = " in line and "appendFileSync" in line):
        print(f"{index + 1}: {line[:170]}")
