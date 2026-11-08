"""Install a RE4 Switch save into the emulator's NAND data, with a backup and a verified copy.

Why this exists: the title **auto-loads its save at boot**, so a save that is mid-load does not merely greet a run with a prompt - it
boot-loops the title (measured 2026-11-07: boot `40.2 -> 19.4`, and after answering "Yes" it returns to `19.4`). A fresh save boots
cleanly but has no Mercenaries unlock. So a run needs a save that is *past the village* and *written at a menu*, and getting one in has
to be a one-line operation rather than a manual copy into a hex-named directory.

The layout, as the emulator keeps it:

    <user>/nand/user/save/0000000000000000/<account>/<title id>/SAVEDATA000/savegame00.sav

`install` refuses to overwrite without `replace=True`, keeps the previous file as `<name>.bak-<timestamp>`, and verifies the copy by
sha256 before reporting success.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path

TITLE_ID = "010099A00BC1E000"
SAVE_NAME = "savegame00.sav"
SAVE_ROOT = Path("nand") / "user" / "save" / "0000000000000000"


class SaveError(RuntimeError):
    """The save cannot be installed or checked; the message says which path and why."""


def _sha(path: Path) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def title_dir(user: Path, account: str | None = None) -> Path:
    """The title's SAVEDATA000 folder inside one emulator user directory."""
    root = Path(user) / SAVE_ROOT
    if not root.is_dir():
        raise SaveError(f"{root} does not exist: is this the emulator's user folder?")
    accounts = [root / account] if account else sorted(p for p in root.iterdir() if p.is_dir())
    for candidate in accounts:
        folder = candidate / TITLE_ID / "SAVEDATA000"
        if folder.is_dir():
            return folder
    raise SaveError(f"no {TITLE_ID}/SAVEDATA000 under {root}")


def status(user: Path) -> dict:
    """Every save file this title has, with size, mtime and sha256 - the inventory a page can show."""
    folder = title_dir(user)
    files = []
    for path in sorted(folder.glob("*")):
        if not path.is_file():
            continue
        files.append({"name": path.name, "bytes": path.stat().st_size,
                      "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
                      "sha256": _sha(path)[:16]})
    current = folder / SAVE_NAME
    return {"folder": str(folder), "current": current.name if current.is_file() else None,
            "current_sha256": _sha(current)[:16] if current.is_file() else None, "files": files}


def install(user: Path, save: Path, *, replace: bool = False, account: str | None = None) -> dict:
    """Copy `save` in as the title's live save, keeping the previous one beside it."""
    save = Path(save)
    if not save.is_file():
        raise SaveError(f"{save} does not exist")
    folder = title_dir(user, account)
    target = folder / SAVE_NAME
    if target.is_file() and not replace:
        raise SaveError(f"{target} already exists; pass replace=True to overwrite it (the previous file is kept as a backup)")
    backup = None
    if target.is_file():
        backup = folder / f"{SAVE_NAME}.bak-{int(time.time())}"
        shutil.copyfile(target, backup)
    shutil.copyfile(save, target)
    if _sha(target) != _sha(save):
        raise SaveError(f"the copy at {target} does not match {save}: installation failed")
    return {"installed": str(target), "backup": str(backup) if backup else None,
            "bytes": target.stat().st_size, "sha256": _sha(target)}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inspect or install a RE4 Switch save")
    parser.add_argument("--user", required=True, help="the emulator's user folder (the one holding nand/)")
    parser.add_argument("--save", help="the save file to install")
    parser.add_argument("--replace", action="store_true", help="overwrite the live save (the old one is backed up)")
    parser.add_argument("--account", help="the account folder, when there is more than one")
    args = parser.parse_args(argv)
    user = Path(os.path.expanduser(args.user))
    try:
        if args.save:
            import json
            print(json.dumps(install(user, Path(os.path.expanduser(args.save)), replace=args.replace,
                                     account=args.account), indent=1))
        else:
            import json
            print(json.dumps(status(user), indent=1))
    except SaveError as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
