"""Generated instructions from the adjacent gBox-authored native source (`dispatch.S`).

No game binary data. `build_dispatch.py` reproduces these bytes from the assembly with keystone and checks them
with capstone; the checked-in bytes are what the controller installs.

The dispatcher is the RE4 harness's only guest-side code (E0(c)): it runs from the vetted zero padding at
`main+0x655880`, invoked through the player object's cloned vtable (slot +0x20, the unit transform virtual), and
tail-calls the original `main+0x2B6420` every time so the game is unaffected while it is attached.
"""

CAVE_AT, CAVE_SIZE = 0x655880, 0x780          # scripts/verify_re4_caves.py: 1920 bytes, 64-byte line, unused
CAVE_END = CAVE_AT + CAVE_SIZE                # 0x656000, the RX page boundary
ORIGINAL_TRANSFORM = 0x2B6420                 # the unit base-class transform virtual (all unit class vtables)
SLOT_TRANSFORM = 0x20                         # its vtable slot
CLONE_ENTRIES = 32                            # copied from the live player vtable (256 bytes)
CLONE_MAILBOX_OFF = 0x100                     # entry 32 carries the mailbox pointer (the dispatcher reads it here)
CLONE_SIZE = CLONE_MAILBOX_OFF + 8
CLONE_AT = CAVE_AT + 0x180                    # 64-byte aligned, clear of the 0x84-byte dispatcher
MAILBOX_SIZE = 0x80
MAILBOX = {"state": 0x00, "target": 0x08, "args": 0x10, "result": 0x48, "generation": 0x50, "ticks": 0x58}
STATE = {"idle": 0, "requested": 1, "running": 2, "done": 3}

DISPATCH = (
    CAVE_AT, "dispatch", 132,
    "2a6e9911fd3fe27cc3676b973aaf80d90980d4d15829e46d1b11a2566ec247e2",
    bytes.fromhex(
        "fd7bbca9fd030091f35301a9f55b02a9f30300aa740240f9948240f9740200b4892e40f9"
        "29050091892e00f9890240b93f050071a101005449008052890200b9880640f9e80000b4"
        "800641a9820e42a9841643a9861e44a900013fd6802600f969008052890200b9e00313aa"
        "09e3ffb029811091f35341a9f55b42a9fd7bc4a820011fd6"
    ),
)

IMAGES = {"dispatch": DISPATCH[4]}
