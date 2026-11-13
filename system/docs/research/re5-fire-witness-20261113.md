# RE5 Switch firearm witness investigation, 2026-11-13

This is static research and read-only sampling, not an enabled discharge detector.
The Switch main build is EBFFDB223149A725A93CD9B60979F6AA; the ELF SHA-256 is
674c88288eda98b8974e4185853d0b7c2f3fe6b623c823124326d14834856f5c.
Addresses below are runtime module offsets. Ghidra exports use these plus 0x100000.

`cPlAction_pl_act_weapon_fire` has vtable 0x1C7F678 and DTI 0x1D7B1A0.
Its update at 0x96D540 advances the action step and sets weapon+0x27F9 to request
emission. The common weapon update at 0x7E3A00 checks the native owner, calls
weapon virtual+0x420, and clears the request. The clear also occurs when the owner
check fails. Motion 29, action-step advancement, rearm, and request clearing alone
therefore do not establish that the gun discharged.

A read-only live sample found item 0x16 (M3 shotgun), vtable 0x1C59ED8, emission
virtual 0x81A7B0 and postshot virtual 0x7E6E20. The sampled player was already dying
and did not fire; this sample is not cadence evidence. The emission function
allocates actual pellets from the pool at global 0x1D3F120, sets pellet+0x2910
active, records its owning weapon at +0x1A10, and assigns attack-volume+0x144 a
monotonic serial from global 0x1D79060. A new owned pellet/attack serial is a
potential actual-emission witness, but polling can miss short-lived pellets.
Pellets from one shotgun discharge must not become multiple trigger pulls.

The common postshot callback at 0x7E6E20 updates an effect handle at weapon+0x280C,
sets +0x2855, and calls 0xF66E0. These are research candidates, not verified shot
counters: the shotgun can reach postshot after pool exhaustion. Other firearm
families and the meaning/reset sites of these fields still need inspection.

Artifacts on Spark:

- `/home/ehm_eckx/gBox_alt/analysis/merc-full/re5-fire-research-20261113/`
  contains targeted decompiles of 0x96D0B0, 0x96D540, 0x96F090, 0x7E3A00, and
  0x81A7B0. Temporary Ghidra analysis transactions were rolled back after export.
- `/home/ehm_eckx/gBox/system/gbox-data/mercs/analysis/re5-native-fire-20261113.json`
  contains 370 read-only samples over ten seconds, with no observed discharge.

The current Switch animation boost still uses host snapshot polling. Its configured
20x flag is not proof of actual shot frequency or zero animation carryover between
ticks. No unverified native shot witness was enabled by this investigation.
