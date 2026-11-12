"""Three plain log lines in _setup_vpad so one launch names the gate that refuses the pad.

Nothing here changes behaviour - three `print(...)` statements with `%r` formatting (no f-strings, no regex) at the three places that can return None:

  1. the `_want_vpad()` verdict;
  2. the exception inside `make()`'s `VGamepad()` attempt;
  3. the detected slot before `make()` returns it.

If the pad is still refused, the launch log will say which of the three it was - the question I have been unable to answer by inspection, and which two
standalone `VGamepad()` tests contradict.

Discipline: timestamped backup, exact unique anchors, compile and import before anything restarts, restore command printed.
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

# 1. the want verdict
anchor1 = """        self.vpad = self.vpad2 = self.vpad3 = None
        if not self._want_vpad():
            return None"""
replacement1 = """        self.vpad = self.vpad2 = self.vpad3 = None
        _want = self._want_vpad()
        print("vpad: _want_vpad() -> %r" % (_want,), flush=True)
        if not _want:
            return None"""
if text.count(anchor1) == 1:
    text = text.replace(anchor1, replacement1, 1)
    edits += 1
    print("1. want verdict logged")

# 2. the creation exception
anchor2 = """                except Exception as e:                       # noqa: BLE001 - no driver/pad: keyboard path
                    last = e"""
replacement2 = """                except Exception as e:                       # noqa: BLE001 - no driver/pad: keyboard path
                    print("vpad: VGamepad() attempt %d failed: %r" % (attempt + 1, e), flush=True)
                    last = e"""
if text.count(anchor2) == 1:
    text = text.replace(anchor2, replacement2, 1)
    edits += 1
    print("2. creation failure logged")

# 3. the detected slot
anchor3 = """                if vp.slot is not None and vp.slot not in used:
                    used.add(vp.slot)
                    return vp"""
replacement3 = """                print("vpad: attempt %d detected slot %r" % (attempt + 1, vp.slot), flush=True)
                if vp.slot is not None and vp.slot not in used:
                    used.add(vp.slot)
                    return vp"""
if text.count(anchor3) == 1:
    text = text.replace(anchor3, replacement3, 1)
    edits += 1
    print("3. detected slot logged")

print("edits applied:", edits)
if edits != 3:
    shutil.copyfile(BACKUP, PATH)
    print("not all anchors matched - restored and stopping")
    raise SystemExit(1)

PATH.write_text(text, encoding="utf-8")

import py_compile
try:
    py_compile.compile(str(PATH), doraise=True)
    print("compile: OK")
except Exception as exc:                                          # noqa: BLE001
    print("COMPILE FAILED:", str(exc)[:300])
    shutil.copyfile(BACKUP, PATH)
    print("restored from backup")
    raise SystemExit(1)

import subprocess
import sys
check = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, r'C:\\_tools\\gBox\\system');"
                        "from gbox import adapters; print('import OK')"],
                       capture_output=True, text=True, timeout=120)
print(check.stdout.strip() or check.stderr.strip()[:300])
if check.returncode != 0:
    shutil.copyfile(BACKUP, PATH)
    print("import failed - restored")
    raise SystemExit(1)

print("restore:", BACKUP.name)
