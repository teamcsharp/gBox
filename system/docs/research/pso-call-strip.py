"""Call recentStrip() inside the real mount, before its refresh (line ~527, not the earlier one)."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

if "recentStrip().catch" in text:
    print("already called")
else:
    lines = text.splitlines()
    # find the const ready = refresh() that lives inside function mount (after line 183)
    mount_at = next(i for i, line in enumerate(lines) if line.startswith("  function mount(root, io) {") or line.strip().startswith("function mount(root, io)"))
    print("mount at line", mount_at + 1)
    target = None
    for index in range(mount_at, len(lines)):
        if "const ready = refresh();" in lines[index]:
            target = index
            break
    print("ready at line", (target + 1) if target is not None else None)
    if target is None:
        raise SystemExit("no ready in mount")
    lines.insert(target, "    recentStrip().catch(() => {});")
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    print("recentStrip called on mount")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

lines = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if "recentStrip" in line:
        print(f"{index + 1}: {line.strip()[:90]}")
