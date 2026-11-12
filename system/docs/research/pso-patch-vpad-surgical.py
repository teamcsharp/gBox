"""Replace `_vpad_works` carefully: backup, exact method boundaries, compile check, import check.

Round 30 broke this file twice with a rushed regex. The lesson is not "do not fix it", it is "do it like a surgeon":

1. **back up** `adapters.py` with a timestamp before touching it;
2. locate the method by its **exact class-level signature** (`    def _vpad_works(self) -> bool:`) and end it at the next line that starts with
   `    def ` at the same indentation - so nothing outside the method can be swallowed;
3. replace it with a body at the **same 4-space indentation**;
4. **compile** and **import** the module before anything restarts;
5. report what changed, and leave the backup in place.

What changes and why: `_vpad_works` pressed A and required the emulator to react. At the title screen - where every launch begins - a press need not change
anything observable, so the probe failed, the pad was treated as absent, and input fell back to the keyboard, which needs a foreground window that a headless
agent session can never have. A pad that exists with a slot is the device Dolphin polls; if it ever stops reporting, the press fails at the game rather than
here.
"""
import pathlib
import shutil
import time

PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox\adapters.py")
BACKUP = PATH.with_name(f"adapters.py.bak-{time.strftime('%H%M%S')}")

# 1. backup
shutil.copyfile(PATH, BACKUP)
print("backup:", BACKUP.name, f"({BACKUP.stat().st_size} bytes)")

text = PATH.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)

SIGNATURE = "    def _vpad_works(self) -> bool:"
start = None
for index, line in enumerate(lines):
    if line.rstrip("\n") == SIGNATURE:
        start = index
        break
if start is None:
    raise SystemExit(f"signature not found: {SIGNATURE!r}")

# the method ends at the next line beginning with '    def ' at class level
end = len(lines)
for index in range(start + 1, len(lines)):
    if lines[index].startswith("    def ") or lines[index].startswith("    @"):
        end = index
        break

print(f"method spans lines {start + 1} .. {end} ({end - start} lines)")
print("first line of the block:", repr(lines[start]))
print("last line before the next method:", repr(lines[end - 1]))

body = '''    def _vpad_works(self) -> bool:
        """True when a virtual pad exists on a real XInput slot - the press probe is not required.

        The old probe pressed A and required the emulator to react. At the title screen, where the bot begins, that reaction is not guaranteed, so the
        probe disabled the pad and input fell back to the keyboard - which needs a foreground window that a headless agent session can never have. A pad
        that exists with a slot is the device Dolphin polls; if it ever stops reporting, the press fails at the game rather than here.
        """
        pad = getattr(self, "vpad", None)
        return pad is not None and getattr(pad, "slot", None) is not None

'''

new_lines = lines[:start] + [body] + lines[end:]
PATH.write_text("".join(new_lines), encoding="utf-8")
print("method replaced")

# 4. compile and import
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
result = subprocess.run([sys.executable, "-c",
                         "import sys; sys.path.insert(0, r'C:\\_tools\\gBox\\system');"
                         "from gbox import adapters;"
                         "print('import OK');"
                         "print('template:', [l for l in adapters.DolphinWinAdapter.PAD_INI_WIN.splitlines() if l.startswith('Device')][:1])"],
                        capture_output=True, text=True, timeout=120)
print(result.stdout.strip() or result.stderr.strip()[:300])
if result.returncode != 0:
    shutil.copyfile(BACKUP, PATH)
    print("import failed - restored from backup")
    raise SystemExit(1)

print()
print("restore if needed:  Copy-Item", BACKUP, PATH)
