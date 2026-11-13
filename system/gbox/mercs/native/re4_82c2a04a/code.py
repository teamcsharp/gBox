"""Generated instructions from the adjacent gBox-authored native source (`dispatch.S`).

No game binary data. `build_dispatch.py` reproduces these bytes from the assembly with keystone and checks them
with capstone; the checked-in bytes are what the controller installs.

The dispatcher is the RE4 harness's only guest-side code (E0(c)): it runs from the vetted zero padding at
`main+0x655880`, invoked through the player object's cloned vtable (slot +0xA0, the player per-frame virtual), and
tail-calls that character's original virtual every time so the game is unaffected while it is attached. The final `ret`
(after the tail `br`) is the harness's own self-test target: a mailbox call to it proves the whole path without
running any game code (checkpoint E6's no-op).
"""

CAVE_AT, CAVE_SIZE = 0x655880, 0x780          # scripts/verify_re4_caves.py: 1920 bytes, 64-byte line, unused
CAVE_END = CAVE_AT + CAVE_SIZE                # 0x656000, the RX page boundary
ORIGINAL_TICK = 0x312600                 # base player callback; Krauser and another player class override it
TICK_BY_CLASS = {0xB068A0: 0x312600, 0xB069C0: 0x312EB0, 0xB06B78: 0x312600,
                 0xB097E8: 0x312600, 0xB098B0: 0x31EB60, 0xB09A60: 0x312600, 0xB0C0A0: 0x312600}
SLOT_TICK = 0xA0                         # its vtable slot
CLONE_ENTRIES = 32                            # copied from the live player vtable (256 bytes)
CLONE_MAILBOX_OFF = 0x100                     # entry 32 carries the mailbox pointer (the dispatcher reads it here)
CLONE_ORIGINAL_OFF = 0x108
CLONE_SIZE = CLONE_ORIGINAL_OFF + 8
CLONE_AT = CAVE_AT + 0x180                    # legacy RX reservation; clones now use private data below
CLONE_DATA_OFF = 0x600                        # after scratch [0x100,0x500), in the proven private 4 KiB page
CLONE_CLASSES = tuple(sorted(TICK_BY_CLASS))
assert CLONE_DATA_OFF + len(CLONE_CLASSES) * CLONE_SIZE <= 0x1000
SELFTEST_AT = CAVE_AT + 0x84                  # the dispatcher's own `ret`: the no-op call target
MAILBOX_SIZE = 0x80
MAILBOX = {"state": 0x00, "target": 0x08, "args": 0x10, "result": 0x48, "generation": 0x50, "ticks": 0x58}
STATE = {"idle": 0, "requested": 1, "running": 2, "done": 3}

DISPATCH = (
    CAVE_AT, "dispatch", 136,
    "ccc0910b831abe9286f80b7aea07774757e165c6e400f9322fd9148869d87f3f",
    bytes.fromhex("fd7bbca9fd030091f35301a9f55b02a9f30300aa740240f9948240f9740200b4892e40f929050091892e00f9890240b93f050071a101005449008052890200b9880640f9e80000b4800641a9820e42a9841643a9861e44a900013fd6802600f969008052890200b9e00313aa690240f9298540f9f35341a9f55b42a9fd7bc4a820011fd6c0035fd6"),
)

IMAGES = {"dispatch": DISPATCH[4]}

# Checked native item-use wrapper, assembled from first_aid.S.
FIRST_AID_AT = CAVE_AT + 0x300
FIRST_AID = (FIRST_AID_AT, "first_aid", 292,
    "fc57b46b3153f3a660346d8724d4890fcc2184230c20cc8226d39702b54e5d44",
    bytes.fromhex(
        "fd7bbda9f35301a9f55b02a9f30300aaf40301aac85f0090086124917f0208eb81070054282600b0080547f99f0008eb"
        "01070054e8560090087940f95f0008eba0000054285700d008cd41f95f0008eb01060054481041b97f00086ba1050054"
        "887840b96805f0368820409108fd5b39080500358814409109514079a90400340a5540793f010a6b42040054683240b9"
        "1f010671e1030054681240f9a80300b4890208eb63030054ca0180d22b09ca9a7f0106f1e202005469a50a9ba90200b5"
        "880240791f15007141020054881240390802003688164039c801003588064079880100341f0900716200005448008052"
        "88060079756a40397f6a0039e00313aae10314aa8b07f197756a003902000014000080d2f35341a9f55b42a9fd7bc3a8"
        "c0035fd6"
    ),
)
IMAGES["first_aid"] = FIRST_AID[4]

# Checked native mine-dart detonation wrapper.
MINE_DETONATE_AT = CAVE_AT + 0x500
MINE_DETONATE = (MINE_DETONATE_AT, "detonate_mine", 452,
    "ca77b6d15c71d1bae1a1ec0629b70e75e3e500d53e3bdb12692ac24913ef8a3c",
    bytes.fromhex("fd7bbea9f35301a9f30300aae8560090087940f95f0008eba0000054285700d008cd41f95f0008eb210c0054020c00b4481041b97f00086ba10b0054282600b0080547f9097940b9290bf0360921409129fd5b39c90a00350815409108514079680a0034882400b008e13b91090540f9e90900b40a1140b95f010871880900546a0900340b1540b90c1982527f010c6be1080054690209eba30800542c09cb9a9f010aeb4208005489a50b9b090800b5680240f9c924009029811c911f0109eb61070054681241b93f00086b01070054680a40b9294080520801090a1f05007161060054686244391f7d017101060054686644391f050071a8050054685244391f05007141050054685644391f110071e804005460a640bd41a440bd0038211e0008201e61aa40bd42a840bd2138221e2000011f61ae40bd42ac40bd2138221e2000011f0900261e297917533ffd0371e002005468065539096b83520a7182521f0500714901891a0a7781521f0100714901891a2101221e2108211e0020211ea9010054e00313aa867bed97682a42791f051471800000541f051871e0179f1a060000142000805204000014000080520200001440008052f35341a9fd7bc2a8c0035fd6"))
IMAGES["detonate_mine"] = MINE_DETONATE[4]
