"""Write the vpad diagnostics to a file, because the app's server prints go to its console and vanish.

The instrumentation is in the loaded code (the servers started at 04:11, after the 04:10 patch), yet no `vpad:` line exists in any log file. That is not the
instrumentation failing - it is that the app starts its server with output going to its own console, so `print` has nowhere on disk to land.

So the three diagnostics append to `D:\\gBox\\pso-ds\\vpad_debug.log` instead. A file always exists afterwards, and its absence is itself informative: if the
file does not appear on the next launch, `_setup_vpad` was not reached at all.

Same discipline: backup, exact anchors, compile, import, restore path.
"""
import pathlib
import shutil
import time

PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox\adapters.py")
BACKUP = PATH.with_name(f"adapters.py.bak-{time.strftime('%H%M%S')}")
shutil.copyfile(PATH, BACKUP)
print("backup:", BACKUP.name)

text = PATH.read_text(encoding="utf-8")
edits = 0

# replace the three prints with file writes
pairs = [
    ('        print("vpad: _want_vpad() -> %r" % (_want,), flush=True)',
     '        open(r"D:\\gBox\\pso-ds\\vpad_debug.log", "a", encoding="utf-8").write("want_vpad=%r\\n" % (_want,))'),
    ('                    print("vpad: VGamepad() attempt %d failed: %r" % (attempt + 1, e), flush=True)',
     '                    open(r"D:\\gBox\\pso-ds\\vpad_debug.log", "a", encoding="utf-8").write("attempt %d failed: %r\\n" % (attempt + 1, e))'),
    ('                print("vpad: attempt %d detected slot %r" % (attempt + 1, vp.slot), flush=True)',
     '                open(r"D:\\gBox\\pso-ds\\vpad_debug.log", "a", encoding="utf-8").write("attempt %d slot=%r\\n" % (attempt + 1, vp.slot))'),
]

for old, new in pairs:
    if text.count(old) == 1:
        text = text.replace(old, new, 1)
        edits += 1
        print("replaced:", old.strip()[:60])
    else:
        print("anchor count", text.count(old), "for", old.strip()[:60])

print("edits:", edits)
if edits != 3:
    shutil.copyfile(BACKUP, PATH)
    print("not all anchors matched - restored")
    raise SystemExit(1)

PATH.write_text(text, encoding="utf-8")

import py_compile
try:
    py_compile.compile(str(PATH), doraise=True)
    print("compile: OK")
except Exception as exc:                                          # noqa: BLE001
    print("COMPILE FAILED:", str(exc)[:300])
    shutil.copyfile(BACKUP, PATH)
    print("restored")
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
