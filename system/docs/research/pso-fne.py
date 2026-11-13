"""Make the note channel robust: strip a BOM, and never let a console encoding kill a log line.

The failure was exact and is worth recording: `Set-Content -Encoding UTF8` writes a **BOM**, `read_text(encoding="utf-8")` handed it to `print`, and the Windows console's cp1252 codec raised
`UnicodeEncodeError` on `\\ufeff` - which aborted `read_notes` before it could act, so the note was silently ignored.

Two fixes, both defensive:

* read the file as **`utf-8-sig`**, which strips a leading BOM whatever wrote it;
* make `log()` **ASCII-safe** so no console can ever take the loop down over a character - a note in Japanese, an emoji, or a stray BOM becomes `?` rather than an exception.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. BOM-tolerant read
old_read = '        raw = OPERATOR_NOTES.read_text(encoding="utf-8", errors="replace").strip()'
new_read = '        raw = OPERATOR_NOTES.read_text(encoding="utf-8-sig", errors="replace").strip()'
if text.count(old_read) == 1:
    text = text.replace(old_read, new_read, 1)
    print("notes are read as utf-8-sig (BOM stripped)")
else:
    print("read anchor count:", text.count(old_read))

# 2. ASCII-safe log
old_log = """def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)"""
new_log = """def log(message: str) -> None:
    \"\"\"Print a timestamped line, ASCII-safe.

    The console here is cp1252, so a BOM or any non-Latin character in a note or an entity class would raise
    UnicodeEncodeError and take the loop down. Anything unprintable becomes '?' - a mangled log line is always better
    than a dead bot.
    \"\"\"
    safe = str(message).encode("ascii", "replace").decode("ascii")
    print(f"[{time.strftime('%H:%M:%S')}] {safe}", flush=True)"""
if text.count(old_log) == 1:
    text = text.replace(old_log, new_log, 1)
    print("log() is now ASCII-safe")
else:
    print("log anchor count:", text.count(old_log))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
