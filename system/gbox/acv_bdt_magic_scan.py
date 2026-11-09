"""Bounded BDT magic stream-scan results for Armored Core V (Xbox 360).

Companion to acv_inventory.py.  The scan was a single linear pass over the
owned dvdbnd.bdt (3,298,094,700 bytes; BDT LBA 12314; 19,747 BHD5 records
spanning absolute BDT offsets 16..3,298,094,700) searching for the container
magics "DCX\\0", "DCS\\0", "DCP\\0", "BND3", "TPF" and recording, per magic,
the hit count, the first 16 absolute BDT offsets, and -- for DCX -- the
position relative to the owning BHD5 record (in/out of the record region and
min/median delta to the record start).

Verdict: all 14,981 "DCX\\0" hits sit exactly at their record's offset 0
(dcx_delta_min = dcx_delta_median = 0, dcx_out_region = 0), so the BHD5
record offset is the container base.  This corrects the earlier full-census
note (commit c294ac53): its ad-hoc record reader (not in this repo) had a
base-offset bug.  The raw scan artifact is kept in the task workspace at
system/evidence/acv_bdt_magic_scan.json (sha256
e169f024a54b0c02762478c284523506f8c2b5e29c5bac94266e7c41f36e1c1d); this
module is the committed, publishable record of the same numbers.

Read-only evidence; nothing in this module touches the disc or the binder.
"""
from __future__ import annotations

ISO_PATH = ("/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/"
            "roms/Armored Core V.iso")

SCAN = {
    "iso": ISO_PATH,
    "bdt_lba": 12314,
    "bdt_size": 3298094700,
    "records": 19747,
    "record_region_min": 16,
    "record_region_max_end": 3298094700,
    "hits": {
        "DCX": {
            "count": 14981,
            "first16": [
                23670971, 23710404, 67840318, 68041378,
                72079241, 72463837, 73045646, 73583682,
                74257853, 74818399, 75517224, 75817474,
                76453337, 76843576, 77015151, 77619224,
            ],
        },
        "DCS": {
            "count": 15998,
            "first16": [
                8080774, 8096598, 8104614, 8108662,
                23670995, 23710428, 67840342, 68041402,
                72079265, 72463861, 73045670, 73583706,
                74257877, 74818423, 75517248, 75817498,
            ],
        },
        "DCP": {
            "count": 14982,
            "first16": [
                23671007, 23710440, 67840354, 68041414,
                72079277, 72463873, 73045682, 73583718,
                74257889, 74818435, 75517260, 75817510,
                76453373, 76843612, 77015187, 77619260,
            ],
        },
        "BND3": {
            "count": 746,
            "first16": [
                65541, 149317, 1785237, 3873605,
                7944581, 7960821, 11365653, 11418773,
                11427173, 11505797, 11535189, 11770037,
                11803605, 12293921, 12304210, 12317395,
            ],
        },
        "TPF": {
            "count": 934,
            "first16": [
                8131013, 23400411, 23588907, 23629931,
                23823614, 23889214, 23954814, 24020414,
                24086014, 24151614, 24217214, 24282814,
                24348414, 24414014, 24479614, 24545214,
            ],
        },
    },
    "dcx_in_region": 14981,
    "dcx_out_region": 0,
    "dcx_delta_min": 0,
    "dcx_delta_median": 0,
}
