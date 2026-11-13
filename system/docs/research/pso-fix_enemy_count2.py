"""Remove the misplaced `enemy_count_before` line and drop the cosmetic kill counter that needed it."""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
lines = ENDLESS.read_text(encoding="utf-8").splitlines()

kept = [line for line in lines if line.strip() != "enemy_count_before = len(enemies)"]
print("removed misplaced lines:", len(lines) - len(kept))
text = "\n".join(kept) + "\n"

# the kill counter was cosmetic and depended on it; a killed enemy simply leaves the list
old = """                if len(enemies) < enemy_count_before:
                    killed += 1
                    log(f"  killed one - {len(enemies)} left")"""
new = """                killed += 0"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("dropped the cosmetic kill counter")
else:
    print("kill-counter anchor count:", text.count(old))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
print("enemy_count_before references left:", text.count("enemy_count_before"))
