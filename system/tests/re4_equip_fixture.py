"""Native selection/refresh simulator; inventory and active object are separate."""
import struct
import threading
from types import SimpleNamespace
from gbox.mercs.titles import re4_switch as R, re4_weapons as W
from gbox.mercs.titles import re4_switch_weapon_native as E


def controller(ad, base, player, item):
    wep, obj = player + 0x10000, player + 0x20000
    ad.put(player, bytes(0xA00))
    ad.put(wep, bytes(0x100))
    ad.put(obj, bytes(0x500))
    ad.put(base + E.REFRESH, E.REFRESH_HEAD)
    ad.put(base + E.SELECT, E.SELECT_HEAD)
    ad.write_memory(player + R.PL_WEP, struct.pack('<Q', wep))
    ad.write_memory(wep + R.WEP_OBJ, struct.pack('<Q', obj))
    ad.write_memory(obj + R.OBJ_ITEM, ad.read_memory(item, 2))
    ctl = SimpleNamespace(base=base, player=player, lock=threading.RLock(), calls=[],
                          ready=lambda: (player, 7), rd=ad.read_memory, write=ad.write_memory,
                          ensure_attached=lambda: None)
    ctl.q = lambda a: struct.unpack('<Q', ctl.rd(a, 8))[0]
    def call(off, *args, **kw):
        ctl.calls.append((off, args))
        selected = struct.unpack('<H', ctl.rd(item, 2))[0]
        rows = W.decode_weapon_table(ctl.rd(base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
        if off == E.SELECT:
            ctl.write(base + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack('<H', selected))
            lv = W.max_levels(selected) or {k: 0 for k in ('firepower','firing_speed','capacity','reload')}
            ctl.write(base + W.GAME_OBJ + W.G_FIREPOWER,
                      bytes(lv[k] for k in ('firepower','firing_speed','capacity')))
            ctl.write(base + W.GAME_OBJ + W.G_RELOAD, bytes((lv['reload'],)))
        elif off == E.REFRESH:
            selected = struct.unpack('<H', ctl.rd(base + W.ITEM_MGR + W.M_EQUIPPED_ID, 2))[0]
            row = rows[selected]
            want = bytes((row['class'], row['variant']))
            # Exactly the real synchronizer's short circuit. A data-only swap
            # that publishes class too early leaves the pistol object intact.
            if ctl.rd(base + W.GAME_OBJ + W.G_CLASS, 2) != want:
                ctl.write(obj + R.OBJ_ITEM, struct.pack('<H', selected))
                ctl.write(base + W.GAME_OBJ + W.G_CLASS, want)
        return 0
    ctl.call = call
    def equip(i, **kw):
        # Supply this fake engine's phase without hiding the production checks
        # in tests that use the helper with their own phase reader.
        from unittest.mock import patch
        with patch.object(R, 'game_state', return_value={'phase':'playing','in_control':True}):
            return E.replace(ctl, i, **kw)
    ctl.equip_primary = equip
    ad.writes.clear()
    return ctl
