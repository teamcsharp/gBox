"""Armored Core V (Xbox 360) unlock evidence, pinned to the owned revision.

game_id 0d09faf82c4c77d8, platform xbox360, owned ISO
  /mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Armored Core V.iso

Everything in this module is derived from the owned disc and from the static
analysis of the owned executable (default.xex, XEX2, image base 0x82000000).
The addresses recorded here are STRING addresses inside the analysed image
(the game exposes its logic through its own script/property names); they are
not code addresses, and they are used to identify a surface, not to patch it.

This module is read-only evidence. It never writes to the disc, the binder or
any save, and it never touches a running game. The unlock routine that will
consume this inventory is not implemented yet: every category that still reads
"unknown" must be resolved by runtime selection on an authorised test worker
before any profile may claim unlock-all coverage.
"""
from __future__ import annotations

import copy

ACV_GAME_ID = '0d09faf82c4c77d8'
ACV_PLATFORM = 'xbox360'

# ---------------------------------------------------------------- owned revision
ACV_ISO_SHA256 = 'd028051a745c20f6ed18c11e80496471086f096168a2fb819547debfbcab6189'
ACV_XEX_SHA256 = '818a8e2269437291bcf3b0de2e17a23782979766524144f20a689b8323750041'
ACV_IMAGE_SHA256 = 'f832f2a64072d650e121063400eeb4bc1fc055275caeb0c354b6e959154edb28'
ACV_ELF_SHA256 = '0f1deec676b95301a758b8aa241fb48e0ad6b5e8e3cc420d42cdba183b7adeac'
ACV_BHD5_SHA256 = '7656d45f09b4ad43a3e16be81bfd621bba39cce187f85c9af954a62308dfee6e'
# Ghidra headless export (program default.xex.elf, language PowerPC:BE:32:e500).
ACV_GHIDRA_ARTIFACT_SHA256 = '75a9c44c1ac3d84ac5a5ac3b7e0540739e8f5e924e25e257c73a4b1ae5d2f3e5'

CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

# ---------------------------------------------------------------- proven lock surface
# The game's own script layer names the eligibility predicates. These are the
# names to trace in the Ghidra project; none of them is a patch target yet.
LOCK_SURFACE = {
    'IsWeaponLocked': '0x82014d50',
    'GetMainLockedTime': '0x820166c4',
    'GetSubLockedTime': '0x820166e8',
    'GetMissionProgressTotal': '0x82018fd0',
    'Scr_GetMissionClearNum': '0x82004898',
    'ScrDB_MissionClear': '0x82004914',
    'Scr_IsGameClear': '0x820046bc',
    'Scr_ClearMissionSaveData': '0x8204c82c',
    'Scr_ClearMissionSortieInfo': '0x8204c794',
    'Scr_GetPrice': '0x82020770',
    'GetPrice': '0x82022654',
    'IsCurSelPartsNameEnable': '0x820239f8',
    'IsFixedDLCParts': '0x820219c8',
    'ToggleExtractPartsListBySubCategory': '0x82022600',
    'ACVRequestMessage.RequestUnlockBattleSession': '0x82166908',
    'ACVRequestMessage.RequestUnlockNpcDecisiveBattle': '0x82166c0c',
    'ACVRequestMessage.LockBattleSessionResult': '0x821668dc',
    'ACVRequestMessage.DLCStatusList': '0x821676bc',
    'ACVRequestMessage.AreaIDList': '0x821655dc',
}

# The greyed-out set proven in the owned build: the online/server features this
# offline disc cannot offer. These are NOT unlockable content.
OFFLINE_GREYOUT = {
    '@Grayout_Shop': '0x82059af8',
    '@Grayout_GarageCustom': '0x82059b10',
    '@Grayout_Setting': '0x82031024',
    '@grayout_Enlist': '0x820394a4',
    '@grayout_Trade': '0x8203999c',
    '@grayout_Operation': '0x820399bc',
    '@grayout_Chat': '0x820399dc',
    '@grayout_Conquest': '0x8206de84',
    '@grayout_Join': '0x8206dea0',
    '@grayout_FreeMatch': '0x8206debc',
    '@grayout_Ranking': '0x8206def0',
    'Load_grayout': '0x82055e0c',
}

# ---------------------------------------------------------------- data surfaces
DATA_SURFACE = {
    'AcvParts.bin': '0x82002ac0',
    'ACVEnemyParts.bin': '0x82024c1c',
    'CustomMapParts.bin': '0x820d132c',
    'Shop.mrb': '0x8205957c',
    'StoryMission.mrb': '0x820499cc',
    'Arena_%04d.xml': '0x82049e4c',
    'PartsSubCategory_$(Lang).fmg': '0x82024c48',
    'achievementreward.bin': '0x820d5b40',
    '$(MissionSaveData)': '0x82000eb4',
    '$(ArenaSaveData)': '0x8204d6b4',
}

_INVENTORY = {
    'characters': {
        'status': 'not_present',
        'entries': [],
        'evidence': (
            'No player-character roster exists in the owned revision. The 14,316-string '
            'inventory of default.xex.elf (sha256 0f1deec676b95301a758b8aa241fb48e0ad6b5e8e3cc420d42cdba183b7adeac, '
            'image base 0x82000000) contains no character/roster/pilot identifier; the only matches are '
            'engine internals SetCharacterSet (0x82118bf8) and CharaLODSolver (0x8208ded4). '
            'Armored Core V is a mech game: the selectable chassis are parts data, not characters.'),
    },
    'hidden_characters': {
        'status': 'not_present',
        'entries': [],
        'evidence': (
            'Same owned-revision string inventory: the only Hidden tokens are enemy AI action names '
            'JellyFishActionHidden (0x820ae474) and MechEnemyActionHidden (0x820ae5c8). There is no '
            'hidden-character roster, no hidden-pilot table, and no character DLC payload '
            '(DLCStatusList 0x821676bc carries the parts/lineup payload only).'),
    },
    'modes': {
        'status': 'unknown',
        'entries': [],
        'evidence': (
            'Mode surfaces proven present: Story ($(MenuResource)\\StoryMission.mrb 0x820499cc, @StoryMission '
            '0x8205b880), Arena ($(Data)\\mission\\Arena_%04d.xml 0x82049e4c, @MissionInfo_Arena 0x82038374), '
            'Versus ($(VersusDefaultMap) 0x82001178, @VersusInfo 0x820659a8), Tutorial (AC_Tutorial 0x8203f0fc), '
            'Training (@TrainingBriefing 0x8206be5c), FreePlay (Scr_IsFreePlayEnabled 0x82004514), Multiplay '
            '(Scr_IsEnableMultiplay 0x820673f8). The per-mode lock status is NOT yet resolved: the only proven '
            'grey-out set is the offline/server set (@Grayout_Shop 0x82059af8, @grayout_Enlist 0x820394a4, '
            '@grayout_Trade 0x8203999c, @grayout_Operation 0x820399bc, @grayout_Chat 0x820399dc, '
            '@grayout_Conquest 0x8206de84, @grayout_Join 0x8206dea0, @grayout_FreeMatch 0x8206debc, '
            '@grayout_Ranking 0x8206def0), which is not unlockable content.'),
    },
    'levels': {
        'status': 'unknown',
        'entries': [],
        'evidence': (
            'Level/mission surface proven: $(Data)\\mission\\Arena_%04d.xml 0x82049e4c plus 230 <?xml payloads '
            'inside bind/dvdbnd.bdt (FromSoftware binder: dvdbnd5.bhd sha256 7656d45f...8dfee6e, 19,731 verified '
            'file records accounting for 3,298,094,684 of the 3,298,094,700 B payload; 14,981 DCX, 746 BND3, '
            '934 TPF, 3 FLVER, 1 PVMD containers). The level count and the per-level lock flags are not yet '
            'enumerated. Progress predicates to trace: GetMissionProgressTotal 0x82018fd0, Scr_GetMissionClearNum '
            '0x82004898, ScrDB_MissionClear 0x82004914, Scr_IsGameClear 0x820046bc.'),
    },
    'stages': {
        'status': 'unknown',
        'entries': [],
        'evidence': (
            'Stage/map surface proven: $(MapModelData)\\worldtop\\worldtop_env.msb 0x8203fa04, '
            '$(MapModelData)\\ch_env\\%s 0x820cf0ec, $(MapModelData)\\ch_nav\\%s 0x820cf0c8, $(VersusDefaultMap) '
            '0x82001178, $(TutorialMap) 0x82001168, $(CoOpDefaultMapID) 0x82000ec8. Which stage/arena IDs are '
            'selectable and which are gated is unresolved pending runtime selection.'),
    },
    'costumes': {
        'status': 'not_present',
        'entries': [],
        'evidence': (
            'Zero occurrences of "costume" in the 14,316-string owned-revision inventory and no costume asset in '
            'the disc file table (24 files: 18 cutscene .wmv, default.xex, NxeArt and the bind/ payload). This '
            'revision ships cosmetics as parts colouring and emblems instead: ACPartsColoring 0x820c7034, '
            'ACPartsPaint 0x820c7044, ColorPalette.bin / ColoringSet.bin, @Emblem 0x8207d8cc, '
            '@EmblemColorPalette 0x8207ad30, DecalPartsSelect 0x8207a464.'),
    },
    'items': {
        'status': 'unknown',
        'entries': [],
        'evidence': (
            'Item surface proven: $(Common)\\Param\\AcvParts.bin 0x82002ac0, @PartsNormalShop 0x8204dd60, '
            '$(MenuResource)\\Shop.mrb 0x8205957c, Scr_GetPrice 0x82020770, GetPrice 0x82022654, '
            'ACVRequestMessage.RequestBuyPlayerShopForParts 0x82166208, '
            'ACVRequestMessage.PlayerShopLineupForPartsList 0x82166174, ACVRequestMessage.FixedPartsInfo '
            '0x8216755c, $(BuyStorageParts) 0x8207cdec. Item IDs/count and the purchase eligibility predicate are '
            'not yet enumerated; the proven per-part lock predicates are IsWeaponLocked 0x82014d50 and '
            'GetMainLockedTime 0x820166c4.'),
    },
    'extras': {
        'status': 'unknown',
        'entries': [],
        'evidence': (
            'Extra surfaces proven: emblem/decal editing (@Emblem 0x8207d8cc, DecalLayerSelect1 0x82079ff4, '
            'EmblemLayerSelect1 0x8207b464, @ExtraInfo 0x82038244), arena ranking (@AreaRankList 0x82061ac4, '
            '@MyRanking 0x82061ad4, @AreaRanking 0x820617bc), arena progress ($(ArenaSaveData) 0x8204d6b4) and '
            'battle-session unlock (ACVRequestMessage.RequestUnlockBattleSession 0x82166908, '
            'ACVRequestMessage.RequestUnlockNpcDecisiveBattle 0x82166c0c, '
            'ACVRequestMessage.LockBattleSessionResult 0x821668dc). Which extras are gated, and by which '
            'predicate, is unresolved.'),
    },
}


def inventory() -> dict:
    """A copy of the category inventory for the owned revision."""
    return copy.deepcopy(_INVENTORY)


def assert_revision(executable_sha256: str) -> str:
    """Guard every write against a different revision. Raises ValueError."""
    if not isinstance(executable_sha256, str) or executable_sha256.lower() != ACV_XEX_SHA256:
        raise ValueError(
            'Armored Core V unlock scope is pinned to the owned executable '
            f'sha256 {ACV_XEX_SHA256}; got {executable_sha256!r}.')
    return ACV_XEX_SHA256


def unresolved(inv: dict | None = None) -> list:
    """Categories whose lock status is still unknown, in category order."""
    inv = inventory() if inv is None else inv
    return [c for c in CATEGORIES if inv.get(c, {}).get('status') == 'unknown']


def profile_body(inv: dict | None = None) -> dict:
    """The custom-build unlock profile body for this game.

    The custom-build contract accepts only unlocked/not_present for every
    category, so this refuses to describe an inventory that still holds an
    unknown category. That refusal is deliberate: a partial inventory is not
    unlock-all coverage.
    """
    inv = inventory() if inv is None else inv
    if set(inv) != set(CATEGORIES):
        raise ValueError('inventory must account for every unlock category')
    pending = unresolved(inv)
    if pending:
        raise ValueError('unresolved categories, not unlock-all coverage yet: ' + ', '.join(pending))
    for category, row in inv.items():
        if row.get('status') not in ('unlocked', 'not_present') or not str(row.get('evidence') or '').strip():
            raise ValueError(f'{category}: record unlocked/not_present and supporting evidence')
        entries = row.get('entries')
        if not isinstance(entries, list) or any(not isinstance(x, str) or not x.strip() for x in entries):
            raise ValueError(f'{category}: enumerate the unlockable entries')
        if (row['status'] == 'unlocked') != bool(entries):
            raise ValueError(f'{category}: unlocked entries must be enumerated; absent categories must be empty')
    return {'executable_sha256': ACV_XEX_SHA256, 'inventory': inv, 'inventory_complete': True}
