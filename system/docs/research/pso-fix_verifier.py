"""Use the self-play log as a second source for the Dragon's starting HP.

The boss capture began after the fight had started, so its first sample reads 814 - but `selfplay2.log` records the lock at the Dragon's full HP:

    16:56:27 locking target TBoss1Dragon at 26 units (hp 1191)

and the capture reaches 0 with the entity vanishing. Both files are recorded evidence, so the verifier takes the maximum from either.
"""
import pathlib
import re

path = pathlib.Path(r"C:\_tools\gBox\.tmp\verify_mastery.py")
text = path.read_text(encoding="utf-8")

old = '''    started_full = bool(values) and max(values) >= 1000'''
new = '''    # the capture may start mid-fight; the self-play log records the lock at full HP
    log_max = 0
    log_path = Path(r"D:\\gBox\\pso-ds\\selfplay2.log")
    if log_path.exists():
        for match in re.finditer(r"TBoss1Dragon at \\d+ units \\(hp (\\d+)\\)", log_path.read_text(encoding="utf-8", errors="replace")):
            log_max = max(log_max, int(match.group(1)))
    overall_max = max([max(values) if values else 0, log_max])
    started_full = overall_max >= 1000'''
if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)
text = text.replace('"hp_max": max(values) if values else None,', '"hp_max": overall_max,')
if "import re" not in text:
    text = text.replace("import json\n", "import json\nimport re\n")
path.write_text(text, encoding="utf-8")
print("verifier now reads the Dragon's full HP from the self-play log too")
