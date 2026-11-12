"""Two fixes: the last `@launch`, and the orphan guard must never cancel a real launch.

**The tool name.** One call site still posts `@launch`; the server only knows `launch_game`. A direct test proved `launch_game` is accepted and creates a job
(`id 647c333b9dbb4741`), so that is the name everywhere.

**The guard was destructive.** That same job then reported:

```
state: failed
error: cancelled by the operator
```

with no operator involved. `orphan_guard.py` cancels **any queued job whose `require_worker` is falsy**, and `launch_game` jobs from the panel have no worker
requirement - so **the guard I wrote to unblock launches was killing them.** That is worse than the stall it fixed.

The guard now only ever cancels the specific orphan that caused the stall: a **`characters`** job with no worker and empty inputs. Everything else is left alone.
"""
import pathlib

# 1. the last @launch
picker = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = picker.read_text(encoding="utf-8")
before = text.count("'@launch'")
text = text.replace("'@launch'", "'launch_game'")
picker.write_text(text, encoding="utf-8")
print("picker: replaced", before, "'@launch' -> 'launch_game'")

import subprocess
result = subprocess.run(["node", "--check", str(picker)], capture_output=True, text=True, timeout=120)
print("picker node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:200])

# 2. the guard: never cancel anything but the empty characters orphan
guard = pathlib.Path(r"C:\_tools\gBox\.tmp\orphan_guard.py")
gtext = guard.read_text(encoding="utf-8")

old_condition = """                if worker:
                    first_seen.pop(job_id, None)
                    continue"""
new_condition = """                # ONLY the empty `characters` orphan is cancelled. A `launch_game` job from the PiP panel legitimately
                # has no worker requirement, and cancelling it killed real launches.
                if worker or tool != "characters":
                    first_seen.pop(job_id, None)
                    continue
                payload = job.get("input") or {}
                if any(str(payload.get(key) or "").strip() for key in ("character", "session_id", "game_id", "game")):
                    first_seen.pop(job_id, None)
                    continue"""
if old_condition in gtext:
    gtext = gtext.replace(old_condition, new_condition, 1)
    guard.write_text(gtext, encoding="utf-8")
    print("guard: only the empty characters orphan is cancelled")
else:
    print("guard anchor count", gtext.count(old_condition))

import py_compile
py_compile.compile(str(guard), doraise=True)
print("guard compiles")

gsrc = guard.read_text(encoding="utf-8")
print("scoped to characters:", 'tool != "characters"' in gsrc)
print("skips real payloads:", 'any(str(payload.get(key) or "").strip()' in gsrc)
