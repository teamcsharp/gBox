"""Are the Sonic player archives the same size as the ones on the disc? If so, an ISO patch is a seek and a write.

`GCDisc` reads the disc's file table; a rebuild is not needed when the replacement is the same length as the original,
because the FST stores fixed offsets. This only measures - it prints the offsets a patch would use.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

SRC = os.path.expanduser("~/gBox_alt/re4-lab/gc/re4-d1.iso")
PATCHED = os.path.expanduser("~/gBox_alt/re4-lab/re4gc-sonic")

disc = GCDisc(SRC)
table = getattr(disc, "files", None) or getattr(disc, "_files", None) or {}
print("file-table entries:", len(table))
wanted = ("pl00.drs", "pl08.drs", "pl09.drs", "pl10.drs")
for name in wanted:
    entry = table.get(name) if isinstance(table, dict) else None
    local = os.path.join(PATCHED, name)
    local_size = os.path.getsize(local) if os.path.isfile(local) else None
    if entry is None:
        print(f"{name}: not in the FST (keys sample: {list(table)[:4] if isinstance(table, dict) else type(table)})")
        continue
    print(f"{name}: disc {entry} | patched {local_size} | same size: {entry.get('size') == local_size}")
