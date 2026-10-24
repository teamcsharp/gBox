"""Install the reviewed Pine bridge, with backups, without restarting anything."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

HOOK = "gboxstream.install(app, globals())"
MARK = "import gbox_hls  # [gbox-hls] shared H.264/AAC gameplay channel"
SERVER_FILES = ('gbox_hls.py','media_gateway.py','install_gateway.py')


def patched_app(text):
    if MARK in text:
        return text
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith(HOOK)]
    if len(matches) != 1:
        raise ValueError("expected exactly one existing gboxstream installation")
    lines.insert(matches[0] + 1, MARK + "\n" +
                 "gbox_hls.install(app, globals(), gboxstream)\n" +
                 "_PUBLIC_GET |= set(gbox_hls.PUBLIC_GET)\n")
    return "".join(lines)


def install(target, *, package=None):
    target = Path(target).resolve()
    package = Path(package).resolve() if package else Path(__file__).resolve().parent
    app = target / "app.py"
    for name in ("gboxstream.py", "frontend/gbox-tune.js", "frontend/gbox-tune.css"):
        if not (target / name).is_file():
            raise ValueError("not the expected Pine application: " + name)
    new_app = patched_app(app.read_text(encoding="utf-8"))
    compile(new_app, str(app), "exec")
    manifest = json.loads((package / "vendor-manifest.json").read_text())
    for entry in manifest["files"]:
        raw = (package / entry["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("vendor checksum mismatch: " + entry["path"])
    for name in SERVER_FILES:
        if not (package/name).is_file():
            raise ValueError('reviewed Pine integration module is absent: '+name)
    sources = [*(package/name for name in SERVER_FILES), *(package / "frontend").rglob("*")]
    sources = [p for p in sources if p.is_file()]
    planned = {str(p.relative_to(package)): p.read_bytes() for p in sources}
    planned["app.py"] = new_app.encode()
    changed = {name: raw for name, raw in planned.items()
               if not (target / name).is_file() or (target / name).read_bytes() != raw}
    backup = target / "backups" / ("gbox-hls-" + time.strftime("%Y%m%d-%H%M%S"))
    receipts = []
    for name, raw in changed.items():
        dest = target / name
        if dest.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, saved)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".gbox-hls.tmp")
        tmp.write_bytes(raw)
        tmp.replace(dest)
        receipts.append({"file": name, "sha256": hashlib.sha256(raw).hexdigest()})
    server_changed = any(name in changed for name in ('app.py','gbox_hls.py'))
    return {"changed": receipts, "backup": str(backup) if changed else None,
            "activation": ("Pine container restart required; not performed" if server_changed else
                           "Reload listener page; static files are served immediately" if changed else
                           "No changes; no activation required"), "station_mode_changed": False,
            "gateway_config_applied": False,
            "gateway_activation": ("Gateway source installed; opt-in hash-guarded app/compose patch and explicit "
                                   "gateway service activation remain required; not performed"
                                   if any(name in changed for name in ('media_gateway.py','install_gateway.py')) else
                                   "Gateway source unchanged; no gateway activation performed")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.target), indent=2))
