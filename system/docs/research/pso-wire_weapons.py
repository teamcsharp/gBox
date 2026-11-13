"""Wire the weapon-class rule into the loop."""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

if "from weapons import ensure_equipped" in text:
    print("import already present")
else:
    anchor = "from walk_to import walk_to"
    if text.count(anchor) != 1:
        raise SystemExit("walk_to import anchor count: %d" % text.count(anchor))
    text = text.replace(
        anchor,
        "from walk_to import walk_to\n"
        "from weapons import ensure_equipped       # class-aware weapon choice + the 2-5 min timer",
        1,
    )
    print("imported ensure_equipped")

CALL = (
    "        # WEAPON CLASS RULE: fliers need the gun because melee cannot reach them at all; otherwise the\n"
    "        # operator's strict 2-5 minute timer decides which weapon is equipped.\n"
    "        try:\n"
    "            ensure_equipped(pad, now.get('entities') or [], log)\n"
    "        except Exception:                              # noqa: BLE001 - a swap must never stop the loop\n"
    "            pass\n"
    "\n"
    "        if enemies:"
)

anchor = "        if enemies:"
count = text.count(anchor)
print("enemy anchor count:", count)
if count != 1:
    raise SystemExit("enemy branch anchor is not unique")
text = text.replace(anchor, CALL, 1)
print("ensure_equipped is called each iteration")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
