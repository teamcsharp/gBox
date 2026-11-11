"""Prove the memory-write channel works on the current session, with a no-op write.

The game was relaunched under the current worker, so the job channel should own it now. Writing the CURRENT value back to the same address
changes nothing in the game but exercises the whole path, which is the thing that failed all session with SessionGone.
"""
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

ADDRESS = 0x8050EA10


def read(address, length):
    return S.read_memory(address, length)


before = read(ADDRESS, 4)
print("session:", S.session_id())
print("before:", before.hex() if before else None)

state, result, error = S.job("write_memory", {"session_id": S.session_id(), "address": ADDRESS,
                                             "hex_bytes": (before or b"\x00" * 4).hex()}, timeout=60)
print("write job:", state, "| error:", error)
if result:
    print("result:", json.dumps(result)[:300])

after = read(ADDRESS, 4)
print("after:", after.hex() if after else None)
print("unchanged:", before == after)
