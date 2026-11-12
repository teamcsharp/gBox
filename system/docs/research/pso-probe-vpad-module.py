"""Probe vpad_win itself with file writes: does VGamepad() get created, and what slot does it get?

The app captures its server's stdout for its own UI, so `print` diagnostics are unreachable. A file write is not: any process that touches this module leaves a
trace on disk, and `vpad_win.py` is a small, self-contained file that only does virtual-pad work.

Two probes, both appending one line to `D:\\gBox\\pso-ds\\vpad_probe.log`:

  * at the start of `VGamepad.__init__`, so we know the constructor was reached at all;
  * at the end, with `self.slot`, so we know whether slot detection succeeded.

If the file stays absent after a launch, `_setup_vpad` is not calling `VGamepad()` - which would mean the refusal happens before it, in the gate. If it exists
with `slot=None`, detection is the problem. Either way the answer is on disk.

Backup, compile, import, restore path - the same discipline.
"""
import pathlib
import shutil
import time

PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox\vpad_win.py")
BACKUP = PATH.with_name(f"vpad_win.py.bak-{time.strftime('%H%M%S')}")
shutil.copyfile(PATH, BACKUP)
print("backup:", BACKUP.name)

text = PATH.read_text(encoding="utf-8")
edits = 0

# find __init__'s first line after the docstring/body start
anchor = "        self.slot = self._detect_slot()"
if text.count(anchor) == 1:
    text = text.replace(anchor, anchor + """
        try:
            open(r"D:\\gBox\\pso-ds\\vpad_probe.log", "a", encoding="utf-8").write(
                "VGamepad created: slot=%r\\n" % (self.slot,))
        except Exception:
            pass""", 1)
    edits += 1
    print("probe after slot detection added")

# and one at the very start of __init__
start_anchor = "    def __init__(self):"
if text.count(start_anchor) == 1:
    text = text.replace(start_anchor, start_anchor + """
        try:
            open(r"D:\\gBox\\pso-ds\\vpad_probe.log", "a", encoding="utf-8").write("VGamepad() called\\n")
        except Exception:
            pass""", 1)
    edits += 1
    print("probe at __init__ entry added")

print("edits:", edits)
if edits != 2:
    shutil.copyfile(BACKUP, PATH)
    print("anchors did not both match - restored")
    raise SystemExit(1)

PATH.write_text(text, encoding="utf-8")

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
                        "import sys; sys.path.insert(0, r'C:\\_tools\\gBox\\system');"
                        "from gbox import vpad_win; print('import OK, available:', vpad_win.available())"],
                       capture_output=True, text=True, timeout=120)
print(check.stdout.strip() or check.stderr.strip()[:300])
print("restore:", BACKUP.name)
