"""Resident Evil 6 (PS3, RPCS3, BLUS30855) Mercenaries roster and stages for MercMode.

Static catalog companion to the RPCS3 launch pipeline: the disc folder for catalog game
6fc93ff62e4eb868 (BLUS30855, app 01.00) is unpacked in the gBox launch cache and launched
through the existing archive/launch path. Unlike re5_ps3 there is NO measured RAM map for
this revision yet: no verified Mercenaries menu cursor, timer, combat or terminal-round
reader exists (unknown fields stay unknown; the Xbox 360 addresses in re6_x360 must not be
transplanted). gbox/mercmode.py therefore admits RE6 to a host's rotation only after that
host has actually launched BLUS30855 (TITLES['re6']['witnessed_launch_required']) and no
native selection job exists yet (mercmode.selection_job returns None for re6).

Roster/stage lists are the base-disc Mercenaries content; live unlock readback can shrink
or extend them per host once the save path is measured.
"""
from __future__ import annotations

# Mercenaries list order, base disc. 'Agent' is an Xbox 360/PC exclusive and is not on BLUS30855.
CHARACTERS = ("Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada")
MODE_ROSTERS = {"mercenaries": CHARACTERS}
STAGE_NAMES = ("Urban Chaos", "Steel Beast", "Mining the Depths")
