"""Generated instructions from the adjacent gBox-authored native source (`dispatch.S`).

No game binary data. `build_dispatch.py` reproduces these bytes from the assembly with keystone and checks them
with capstone; the checked-in bytes are what the controller installs.

The dispatcher is the RE4 harness's only guest-side code (E0(c)): it runs from the vetted zero padding at
`main+0x655880`, invoked through the player object's cloned vtable (slot +0x20, the unit transform virtual), and
tail-calls the original `main+0x2B6420` every time so the game is unaffected while it is attached. The final `ret`
(after the tail `br`) is the harness's own self-test target: a mailbox call to it proves the whole path without
running any game code (checkpoint E6's no-op).
"""

CAVE_AT, CAVE_SIZE = 0x655880, 0x780          # scripts/verify_re4_caves.py: 1920 bytes, 64-byte line, unused
CAVE_END = CAVE_AT + CAVE_SIZE                # 0x656000, the RX page boundary
ORIGINAL_TRANSFORM = 0x2B6420                 # the unit base-class transform virtual (all unit class vtables)
SLOT_TRANSFORM = 0x20                         # its vtable slot
CLONE_ENTRIES = 32                            # copied from the live player vtable (256 bytes)
CLONE_MAILBOX_OFF = 0x100                     # entry 32 carries the mailbox pointer (the dispatcher reads it here)
CLONE_SIZE = CLONE_MAILBOX_OFF + 8
CLONE_AT = CAVE_AT + 0x180                    # 64-byte aligned, clear of the 0x88-byte dispatcher
SELFTEST_AT = CAVE_AT + 0x84                  # the dispatcher's own `ret`: the no-op call target
MAILBOX_SIZE = 0x80
MAILBOX = {"state": 0x00, "target": 0x08, "args": 0x10, "result": 0x48, "generation": 0x50, "ticks": 0x58}
STATE = {"idle": 0, "requested": 1, "running": 2, "done": 3}

DISPATCH = (
    CAVE_AT, "dispatch", 136,
    "3e3b937d3e32c01dfbeabd1dbca1560e009929a3e8e24cedfc2b4d233448ce55",
    bytes.fromhex(
        "fd7bbca9fd030091f35301a9f55b02a9f30300aa740240f9948240f9740200b4"
        "892e40f929050091892e00f9890240b93f050071a101005449008052890200b9"
        "880640f9e80000b4800641a9820e42a9841643a9861e44a900013fd6802600f9"
        "69008052890200b9e00313aa09e3ffb029811091f35341a9f55b42a9fd7bc4a8"
        "20011fd6c0035fd6"
    ),
)

IMAGES = {"dispatch": DISPATCH[4]}
