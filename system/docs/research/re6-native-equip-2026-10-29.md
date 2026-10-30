# RE6 native equipment requests

GBox ticket 6107 requests weapon/item changes without wheel input. The production
RE6 driver now routes gun selection, grenade selection, remote-bomb selection,
and returning to a gun through `re6_switch_equip.Controller`.

The Switch build is pinned by its existing signature (061D2A06). The action
manager at player+13A8 publishes action 26; its native init calls B230B0 to
replace the hand attachment. Selection cells and the native request are written;
the active weapon pointer, equipped index, inventory, and executable code are not.
The reader checks player/allocation generations, item owner/type, action context,
request functions, native hand lifecycle, and slot identity. Busy actions defer.
An uncertain publication is not replayed in that player life. Refusal does not
fall back to wheel controls. The modifications-off and operator-control flags
disable requests. Menu navigation remains the driver's normal responsibility.

Live trial on 2026-10-29: owned Spark session
`8b14a71472484560-2161a51e76eb4110`, Citron PID 998673 (birth 1793304228.05),
player generation 20. One request for magnum 0107 progressed requested -> pending
-> equipped, with active index 0 and the owned enabled object confirmed. Four
bounded writes totaled 25 bytes (three preparation cells plus the 13-byte native
request); measured request/readback interval was approximately 37 ms. No controller
input or inventory/model/index assignment was used. A subsequent read-only check
confirmed valid native hand/action identities while the ordinary bot continued.
These historical identities must never be reused as write authorization.

Validation: 232 tests across `test_re6_switch_equip.py`, `test_re6_switch.py`, and
`test_flashbang_5972.py`. Tests cover changed/busy identities, missing lifecycle
proof, consumed-write exceptions, no repeated uncertain requests, and the bot's
gun/flash/remote-item/return-to-magnum paths without wheel output.

The live trial proves native attachment, not damage, hit accuracy, native flash
detonation, remote detonation while holding a gun, or a twenty-projectile burst.
Those require separate native evidence and remain open requirements.
