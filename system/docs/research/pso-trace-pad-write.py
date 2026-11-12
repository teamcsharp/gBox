"""Trace exactly what the launch writes: read the code from the template to the write."""
import pathlib

source = pathlib.Path(r"C:\_tools\gBox\system\gbox\adapters.py").read_text(encoding="utf-8", errors="replace")
lines = source.splitlines()

print("--- the template (3025) ---")
for index in range(3024, 3030):
    print(f"{index + 1}: {lines[index][:120]}")

print()
print("--- the write path (3125-3155) ---")
for index in range(3124, 3155):
    print(f"{index + 1}: {lines[index][:150]}")

print()
# which class holds the template
for index in range(3025, 0, -1):
    if lines[index].startswith("class "):
        print("class holding the template:", lines[index][:100])
        break
