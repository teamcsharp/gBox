"""Switch Citron's renderer to OpenGL, with a backup, and prove the value changed.

Vulkan cannot create a device on this host (the GPU is in a reset state), but OpenGL may still work through the driver's GL path. This is
reversible: the original file is kept beside it and the change is one integer in `[Renderer]`.
"""
import os
import shutil
import sys
import time

CONFIG = os.path.expanduser("~/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux/config/citron/qt-config.ini")
BACKUP = CONFIG + f".bak-{int(time.time())}"


def main() -> int:
    value = sys.argv[1] if len(sys.argv) > 1 else "1"
    text = open(CONFIG, encoding="utf-8", errors="replace").read()
    if "backend=" not in text:
        print("no backend key found")
        return 1
    shutil.copyfile(CONFIG, BACKUP)
    out, changed = [], 0
    section = ""
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            section = line
        elif section == "[Renderer]" and line.startswith("backend=") and not line.startswith("backend\\"):
            out.append(f"backend={value}")
            changed += 1
            continue
        out.append(line)
    open(CONFIG, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"backup: {BACKUP}")
    print(f"changed {changed} line(s) to backend={value}")
    for line in open(CONFIG, encoding="utf-8"):
        if line.startswith("backend="):
            print("now:", line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
