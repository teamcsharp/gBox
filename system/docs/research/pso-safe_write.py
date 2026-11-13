"""Check a path before writing it: does it already exist, and does it have history?

Twice this session an edit landed on a file that already existed and broke something:

* `system/clients/web/viz/pso-controls.js` - a 55,691-byte module defining `root.GBoxPSO` that `index.html` mounts. The
  write tool said "Updated file"; I read it as "fine" and took the Sessions page down with "GBoxPSO is not defined".
* the Dolphin `[Interface]` section - the key was absent rather than present, which changed what the edit meant.

The rule this encodes: **before writing a path, look at whether it exists, how big it is, when it last changed, and
whether git knows about it.** If it exists with history, the write must be a deliberate replacement - usually a patch or
a new file beside it - not a fresh `write`.

Usage:
    python safe_write.py <path> [<path> ...]

Exit code 0 means "safe to create"; 1 means "this path already exists and must be handled deliberately".
"""
import pathlib
import subprocess
import sys

REPO = pathlib.Path(r"C:\_tools\gBox")


def report(path_text: str) -> bool:
    """True when the path is new (safe to create)."""
    path = pathlib.Path(path_text)
    if not path.is_absolute():
        path = REPO / path_text            # relative paths mean relative to the repo, not to wherever this is run
    if not path.exists():
        print(f"NEW      {path_text}  (safe to create)")
        return True
    size = path.stat().st_size
    try:
        log = subprocess.run(["git", "log", "--oneline", "-3", "--", str(path)],
                             cwd=str(REPO), capture_output=True, text=True, timeout=20)
        history = [line for line in (log.stdout or "").splitlines() if line.strip()]
    except Exception:
        history = []
    print(f"EXISTS   {path_text}  {size} bytes")
    if history:
        print("         git history (this is a real module - do NOT overwrite blindly):")
        for line in history:
            print("           ", line)
    else:
        print("         no git history (untracked or outside the repo)")
    return False


if __name__ == "__main__":
    targets = sys.argv[1:]
    if not targets:
        raise SystemExit(__doc__)
    safe = all(report(target) for target in targets)
    print()
    print("VERDICT:", "all new - safe to create" if safe else "AT LEAST ONE EXISTS - patch it, or write beside it")
    raise SystemExit(0 if safe else 1)
