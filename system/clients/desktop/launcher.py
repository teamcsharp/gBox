"""gBox.exe: start the gBox desktop app from <root>/system (root = gBox.exe + system/).

First run on a PC installs the pieces (Electron runtime, Windows worker venv) by running the repo's own installers,
then launches. Works from the Spark share or from a GitHub clone.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
if not (ROOT / "system").exists():                      # running the .py from system/clients/desktop
    ROOT = ROOT.parents[2] if (ROOT.parents[2] / "system").exists() else ROOT
SYSTEM = ROOT / "system"
APP = SYSTEM / "clients" / "desktop"
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "gbox"
ELECTRON = LOCAL / "app" / "gBox.exe"                 # branded Electron runtime (icon + "gBox" everywhere)
VENV_PY = LOCAL / "venv" / "Scripts" / "python.exe"
NEW_CONSOLE = 0x00000010


def ps(script: Path):
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                   creationflags=NEW_CONSOLE, check=False)


def main():
    if not APP.exists():
        subprocess.run(["msg", "*", f"gBox: system folder not found next to gBox.exe ({SYSTEM})"])
        return 1
    if not ELECTRON.exists():                           # first run on this PC
        ps(APP / "install.ps1")
    if not VENV_PY.exists():
        ps(SYSTEM / "scripts" / "bootstrap-windows.ps1")
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    subprocess.Popen([str(ELECTRON), str(APP)], cwd=str(ELECTRON.parent), env=env, close_fds=True,
                     creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return 0


if __name__ == "__main__":
    sys.exit(main())
