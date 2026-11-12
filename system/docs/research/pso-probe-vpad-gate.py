"""Probe _want_vpad's four gates with file writes: which one says no?

`VGamepad()` is never called during a launch (the module probe file stayed empty), so `_setup_vpad` returns at the gate. `_want_vpad` has four:

1. `os.name != "nt"` or a `capture_backend`;
2. `GBOX_DOLPHIN_VPAD` set to off/false;
3. `gecko_id` must start with `GPO`;
4. `vpad_win.available()`.

A file write at each one names the refusing gate without depending on stdout, which the app swallows. Small, additive, and removable: the same anchors plus a
timestamped backup, compile and import checked.
"""
import pathlib
import shutil
import time

PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox\adapters.py")
BACKUP = PATH.with_name(f"adapters.py.bak-{time.strftime('%H%M%S')}")
shutil.copyfile(PATH, BACKUP)
print("backup:", BACKUP.name)

text = PATH.read_text(encoding="utf-8")

old = """        if os.name != "nt" or getattr(self, "capture_backend", None):
            return False
        flag = os.environ.get("GBOX_DOLPHIN_VPAD", "").strip().lower()
        if flag in ("0", "off", "false", "no"):
            return False
        if not (str(getattr(self, "gecko_id", "") or "").startswith("GPO")
                or flag in ("1", "on", "true", "yes", "all")):
            return False
        from . import vpad_win
        return vpad_win.available()"""

new = """        _log = lambda m: open(r"D:\\\\gBox\\\\pso-ds\\\\vpad_gate.log", "a", encoding="utf-8").write(m + "\\\\n")
        _log("want_vpad: os=%r capture=%r flag=%r gecko=%r" % (
            os.name, getattr(self, "capture_backend", None),
            os.environ.get("GBOX_DOLPHIN_VPAD", ""), getattr(self, "gecko_id", None)))
        if os.name != "nt" or getattr(self, "capture_backend", None):
            _log("  -> False (platform or capture)")
            return False
        flag = os.environ.get("GBOX_DOLPHIN_VPAD", "").strip().lower()
        if flag in ("0", "off", "false", "no"):
            _log("  -> False (env flag off)")
            return False
        if not (str(getattr(self, "gecko_id", "") or "").startswith("GPO")
                or flag in ("1", "on", "true", "yes", "all")):
            _log("  -> False (not a GPO disc and flag not set)")
            return False
        from . import vpad_win
        _available = vpad_win.available()
        _log("  -> %r (available=%r)" % (_available, _available))
        return _available"""

count = text.count(old)
print("anchor count:", count)
if count != 1:
    shutil.copyfile(BACKUP, PATH)
    print("anchor did not match exactly - restored")
    raise SystemExit(1)

text = text.replace(old, new, 1)
PATH.write_text(text, encoding="utf-8")
print("all four gates now log to vpad_gate.log")

import py_compile
try:
    py_compile.compile(str(PATH), doraise=True)
    print("compile: OK")
except Exception as exc:                                          # noqa: BLE001
    print("COMPILE FAILED:", str(exc)[:300])
    shutil.copyfile(BACKUP, PATH)
    raise SystemExit(1)

import subprocess
import sys
check = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, r'C:\\_tools\\gBox\\system'); from gbox import adapters; print('import OK')"],
                       capture_output=True, text=True, timeout=120)
print(check.stdout.strip() or check.stderr.strip()[:300])
if check.returncode != 0:
    shutil.copyfile(BACKUP, PATH)
    print("import failed - restored")
    raise SystemExit(1)

print("restore:", BACKUP.name)
