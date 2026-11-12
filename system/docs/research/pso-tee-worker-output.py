"""Tee the local worker/server child's stdout and stderr into the readable log.

`workerChannel` consumes the child's output for the handoff protocol, and `run()`'s helper streams other commands through `logPush`. This adds an explicit tee
on the child that main.js spawns at line ~183 (the local worker/server tree), so **its** stdout and stderr are on disk no matter what the protocol does with
them.

It is additive: two `.on("data")` listeners that append to the same file, wrapped in try/catch, and they do not consume the stream - other listeners still get
every chunk.

With this and the `logPush` change, the next app start writes every line the server produces to `D:\\gBox\\pso-ds\\app-console.log` - including the vpad
diagnostics, which is the whole point.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js")
text = path.read_text(encoding="utf-8")

anchor = 'const child=spawn(py,[\' -P\','
# use a simpler unique anchor
anchor = 'const child=spawn(py,'
count = text.count(anchor)
print("spawn anchor count:", count)

if "teeChild" in text:
    print("tee already present")
elif count >= 1:
    # insert the helper next to the console file definition
    marker = 'const fsConsole = (() => { try { return require("fs"); } catch { return null; } })();'
    helper = marker + """
// Tee a spawned child's output into the readable log (does not consume the stream).
const teeChild = (child, label) => {
  try {
    if (!fsConsole || !child) return;
    const write = chunk => { try { fsConsole.appendFileSync(CONSOLE_FILE, `${new Date().toISOString().slice(11, 23)} [${label}] ${String(chunk).replace(/\\s+$/, "")}\\n`); } catch {} };
    child.stdout?.on("data", write);
    child.stderr?.on("data", write);
  } catch {}
};"""
    if text.count(marker) == 1:
        text = text.replace(marker, helper, 1)
        print("teeChild helper added")

    # call it for every spawn of the local server tree
    old_spawn = 'const child=spawn(py,[\' -P\','
    # find the actual spawn call and add teeChild right after its closing
    import re
    match = re.search(r"(const child=spawn\(py,\[[^\]]*\],\{[^}]*\}\));", text, re.S)
    if match:
        text = text[:match.end(1)] + "\nteeChild(child, 'worker');" + text[match.end(1):]
        print("teeChild wired to the worker spawn")
    else:
        print("could not locate the spawn call's end - helper added but not wired")

    path.write_text(text, encoding="utf-8")
else:
    print("no spawn anchor")

print("--- verify ---")
lines = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if "teeChild" in line or "CONSOLE_FILE =" in line:
        print(f"{index + 1}: {line[:150]}")
