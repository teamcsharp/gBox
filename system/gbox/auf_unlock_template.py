"""Embedded AUF unlock template (mirror of profiles/gamedata/65b7187589166b26-unlock.json)."""
import json

TEMPLATE = json.loads(r'''{
 "categories": {
  "characters": {
   "count": 45,
   "note": "body models on the disc; campaign playable is Bond only",
   "source": "gbox.auf_swap.NAMES"
  },
  "costumes": {
   "bond_variants": 4,
   "note": "tux / combat / greysuit / jetpack, mission-scripted"
  },
  "extras": {
   "note": "no trophies/collectibles system in this revision",
   "present": false
  },
  "hidden_characters": {
   "count": 15,
   "note": "multiplayer selectable bodies (Malprave, Griffin, Jackal, Bloch, Zoe and the rig twins)",
   "source": "gbox.auf_swap.MP_KEYS"
  },
  "items": {
   "runtime": "gbox.auf_live give_item (Sentient::giveGadget @0x8011B1F4)",
   "verified": "docs/auf-gadget-validation.json"
  },
  "levels": {
   "mission_levels": 24,
   "multiplayer_maps": 16,
   "source": "gbox.auf_swap.MISSION_CAST / MP_MAPS",
   "total": 38
  },
  "modes": {
   "campaign": 1,
   "driving": 1,
   "multiplayer": 1
  },
  "stages": {
   "multiplayer_maps": 16
  }
 },
 "executable": {
  "file": "/base.elf/Bond.elf",
  "format": "ELF32 PowerPC big-endian, RAM-linked addresses",
  "sha256": "1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f",
  "size": 4729888,
  "symbols": 17636
 },
 "game_id": "65b7187589166b26",
 "platform": "gamecube",
 "progression": {
  "current_unlocked": {
   "address": "0x804e366c",
   "symbol": "pCurrentUnlocked"
  },
  "game_gold_medal": {
   "address": "0x8011f6d4",
   "symbol": "G_GoldMedalForMission__Fv"
  },
  "game_medal_flags": {
   "address": "0x8011f704",
   "symbol": "G_GetMedalFlags__Fv"
  },
  "level_unlock_table": {
   "address": "0x8023df90",
   "meaning": "one word per campaign level; non-zero means the level is unlocked",
   "size": 48,
   "symbol": "UI_Level_Unlocked"
  },
  "medal_earned": {
   "address": "0x8023e028",
   "readers": [
    "UI_CollectInfoToBeSaved @0x801ac490",
    "SaveBeforeRaceMission @0x801aa6e8"
   ],
   "symbol": "pMedalEarned",
   "writers": [
    "UI_RestoreSavedInfo @0x801ac174"
   ]
  },
  "medal_flags_table": {
   "address": "0x8023dfc0",
   "decoded_from": "UI_CurrentMissionGetMedalFlags @0x8001ac60 (lis r4,0x8024 -> 0x80240000 / addi r5,r4,-0x2040 (imm 0xdfc0))",
   "entries": 13,
   "entry_size": 4,
   "meaning": "one u32 per mission; a non-zero entry sets bit i of the medal bitmask",
   "note": "the addi immediate is -0x2040, so the table is 0x8023dfc0, not 0x801ddfc0",
   "symbol": "UI_Level_Unlocked_Gold"
  },
  "medal_levels_table": {
   "address": "0x80407c88",
   "symbol": "gSC_MedalLevels",
   "writers": [
    "SetGoldMedalLevel__12ScriptThreadFP5Event @0x800fb0b4",
    "SetSilverMedalLevel__12ScriptThreadFP5Event @0x800fb130",
    "SetBronzeMedalLevel__12ScriptThreadFP5Event @0x800fb1ac"
   ]
  },
  "player_model_gate": {
   "function": "_IsPlayerModelAvailable @0x801d4d98",
   "gates": {
    "10": {
     "table": "0x8023df90",
     "table_symbol": "UI_Level_Unlocked",
     "word": 2
    },
    "11": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    },
    "12": {
     "table": "0x8023df90",
     "table_symbol": "UI_Level_Unlocked",
     "word": 6
    },
    "13": {
     "table": "0x8023df90",
     "table_symbol": "UI_Level_Unlocked",
     "word": 9
    },
    "14": {
     "table": "0x8023df90",
     "table_symbol": "UI_Level_Unlocked",
     "word": 10
    },
    "15": {
     "table": "0x8023df90",
     "table_symbol": "UI_Level_Unlocked",
     "word": 11
    },
    "3": {
     "table": "0x8023df90",
     "table_symbol": "UI_Level_Unlocked",
     "word": 4
    },
    "4": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    },
    "5": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    },
    "6": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    },
    "7": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    },
    "8": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    },
    "9": {
     "table": "0x803c1790",
     "table_symbol": "gGamePrefs",
     "word": 11
    }
   },
   "jump_table": "0x8028790c",
   "models": "3..15"
  },
  "save_slots": {
   "mp_write": "MPM_SaveToSaveFileSlot @0x801ab984",
   "mpp_write": "MPP_SaveToSaveFileSlot @0x801abe3c",
   "read": "LoadFromSaveFileSlot @0x801abf90",
   "write": "SaveToSaveFileSlot @0x801abf04"
  },
  "script_variables": {
   "restore": "G_RestoreGameVariables__FP18ScriptVariableList @0x800926c4",
   "save": "G_SaveGameVariables__FP18ScriptVariableList @0x8009275c"
  }
 },
 "runtime_acceptance": {
  "performed": false,
  "required": [
   "fresh boot, actually select and play every unlocked multiplayer body and campaign level",
   "second launch and rollback",
   "original save hash before and after"
  ]
 },
 "status": "static analysis complete; on-load unlock NOT yet runtime-verified",
 "title": "007: Agent Under Fire (GameCube, GW7E69) - unlock profile (planning stage)"
}
''')
