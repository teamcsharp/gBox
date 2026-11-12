"""Read the co-op session's memory directly and find both players.

The buddy launch started "gBox Dolphin" as its own process. This attaches to that pid and reads the entity table, listing every `TObjPlayer` with its
position and HP - which is what CP17 and CP18's "both players" criteria need, and the first proof that the co-op session is a real two-player game
rather than a single-player one with a second pad idle.
"""
import ctypes
import struct
import sys
from ctypes import wintypes

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 28856
TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
FLOOR = 0x805D5FC0
PROCESS_VM_READ, PROCESS_QUERY_INFORMATION = 0x0010, 0x0400

kernel32 = ctypes.windll.kernel32
handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, PID)
if not handle:
    raise SystemExit(f"cannot open pid {PID} (error {kernel32.GetLastError()})")


def read(address, size):
    buffer = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(got))
    if not ok or got.value != size:
        raise OSError(f"read failed at 0x{address:08X} ({got.value}/{size})")
    return buffer.raw


def u32(address):
    return struct.unpack(">I", read(address, 4))[0]


print(f"attached to pid {PID}")
try:
    floor = u32(FLOOR)
    print("floor:", floor)
except OSError as exc:
    print("floor read failed:", exc)

raw = read(TABLE, MAX_ENTRIES * 4)
players = []
others = 0
for index in range(MAX_ENTRIES):
    pointer = struct.unpack(">I", raw[index * 4:index * 4 + 4])[0]
    if not (0x80000000 <= pointer < 0x81800000):
        continue
    try:
        name_pointer = u32(pointer)
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = read(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
    except OSError:
        continue
    if not name:
        continue
    others += 1
    if not name.startswith("TObjPlayer"):
        continue
    try:
        blob = read(pointer, 0x340)
        x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
        hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        tp = struct.unpack(">H", blob[HP + 2:HP + 4])[0]
    except OSError:
        continue
    players.append({"pointer": hex(pointer), "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                    "hp": hp, "tp": tp})

print(f"entities with names: {others} | TObjPlayer found: {len(players)}")
for player in players:
    print("  ", player)
if len(players) >= 2:
    print("TWO PLAYERS PRESENT - this is the co-op session CP17/CP18 require")
elif players:
    print("one player present")
else:
    print("no player actors yet - the game may still be booting")
