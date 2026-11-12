"""Stop a launch from queueing forever waiting for a worker OS that is not there.

`/api/games/{gid}/launch` picks a worker OS before submitting:

```python
elif e.get("launch", {}).get("kind") == "attract":
    has_core = e.get("core") and (e.get("platform") == "arcade" or systems.core_for(...)[0])
    req.require_os = "linux" if has_core else "windows"
```

PSO's catalogue entry has `launch.kind == "attract"` **and** a core, so a launch asks for **`linux`** - and the only worker here is **Windows** (`i9-NUC`, os `windows`).
The job therefore sits `queued` forever with `require_worker: None`, which is exactly the "it never loads" the operator keeps hitting.

An operator's own Play escapes it by accident:

```python
if not req.require_worker and actor == "operator":
    req.require_worker, req.require_os = here["id"], None
```

**An agent launch does not** - the block is operator-only - so anything launched from an agent, a panel, a scheduled task or the API queues indefinitely.

The fix is one guard before `submit`: if the chosen OS has **no online worker**, do not require it. The existing per-actor resolution still applies afterwards, so an
operator launch still lands on their own PC, and an agent launch lands on any idle worker instead of waiting forever.
"""
import pathlib
import py_compile

path = pathlib.Path(r"C:\_tools\gBox\system\gbox\server.py")
text = path.read_text(encoding="utf-8")

anchor = """        if not req.require_worker and actor == "operator":
            # #2386: the operator's own Play that names no PC boots on the PC it was asked from, never on another one."""
addition = """        if req.require_os and not any(w.get("online") and w.get("os") == req.require_os for w in workers()):
            # No worker of the chosen OS is online: requiring it queues the launch forever (PSO asks for "linux"
            # because its kind is "attract" and it has a core, while the only worker here is Windows). An operator's
            # own Play escaped this through the resolution below; an agent launch did not, and hung silently.
            req.require_os = None
        if not req.require_worker and actor == "operator":
            # #2386: the operator's own Play that names no PC boots on the PC it was asked from, never on another one."""

if "No worker of the chosen OS is online" in text:
    print("guard already present")
else:
    count = text.count(anchor)
    print("anchor count:", count)
    if count != 1:
        raise SystemExit("launch worker-resolution anchor not unique")
    text = text.replace(anchor, addition, 1)
    path.write_text(text, encoding="utf-8")
    print("guard added before submit")

py_compile.compile(str(path), doraise=True)
print("server.py compiles")

source = path.read_text(encoding="utf-8")
lines = source.splitlines()
for index, line in enumerate(lines):
    if "No worker of the chosen OS is online" in line:
        print(f"{index + 1}: {line.strip()[:100]}")
        print(f"{index + 2}: {lines[index + 1].strip()[:100]}")
        print(f"{index + 3}: {lines[index + 2].strip()[:100]}")
        break
