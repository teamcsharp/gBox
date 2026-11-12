"""Disable the teeChild call, which may be starving the control handoff.

`workerChannel(child, …)` reads the child's stdout for the handoff protocol. `teeChild` attaches `child.stdout.on("data", …)` **before** that call, and attaching a
`data` listener switches a stream into flowing mode - which can starve a consumer that reads with `read()` or an async iterator. The worker's symptom fits exactly: it
writes its config line and then never sends `ready`.

This comments the call out (the helper stays, so it can be restored) and syntax-checks the file.
"""
import pathlib
import subprocess

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js")
text = path.read_text(encoding="utf-8")

old = 'teeChild(child, "worker");'
count = text.count(old)
print("call count:", count)

if count == 1:
    text = text.replace(
        old,
        '// teeChild disabled: its data listener can starve the control handoff, which reads this same stdout',
        1)
    path.write_text(text, encoding="utf-8")
    print("teeChild call disabled")
elif count == 0:
    print("already disabled")
else:
    raise SystemExit("unexpected call count")

result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
    if "teeChild" in line:
        print(f"{index + 1}: {line.strip()[:110]}")
