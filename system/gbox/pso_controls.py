"""PSO session capabilities and boot defaults. Never apply Dreamcast addresses to GameCube."""
import threading

from .psoitems import CLASSES

DEFAULTS = {"equip_any": True, "permanent_scape": False, "legendary": False,
            "enemy_drops": False, "enemy_codes": [], "enemy_max_grind": True, "walk_through": False}
_locks = {}
_locks_guard = threading.Lock()


def session_lock(sid):
    # Serialize native dispatcher calls as well as UI/stat edits for a single emulator.
    with _locks_guard:
        return _locks.setdefault(sid, threading.RLock())


def serialized(fn):
    from functools import wraps
    @wraps(fn)
    def run(inp, ctx):
        with session_lock(inp.session_id):
            return fn(inp, ctx)
    return run


def is_pso(game):
    return game.get("platform") in ("dreamcast", "gamecube") and "phantasy star online" in game.get("title", "").lower()


def capabilities(game, read):
    if game.get('platform') == 'gamecube':
        from types import SimpleNamespace
        from .pso_gc_live import GC
        supported, reason = False, 'This is not a PSO game'
        if is_pso(game):
            try:
                GC(SimpleNamespace(read_memory=read, write_memory=None)).check()
                supported, reason = True, ''
            except Exception as error:
                reason = str(error)
        adventure=False
        if supported:
            try:
                from .pso_gc_adventure import Adventure
                Adventure(SimpleNamespace(read_memory=read,write_memory=None)).check()
                adventure=True
            except Exception: pass
        return {'version': 'gc', 'label': 'GameCube Plus US revision 2', 'supported': supported, 'reason': reason,
                'character_class': None, 'classes': list(CLASSES),
                'features': {k: supported for k in ('floor_spawn','floor_rares','floor_clear','give','equip_any','multi_equip','stat','survival','revive','mag','randomized')} |
                            {k:adventure for k in ('enemy_drops','walk_through','boss_warp')},
                'pending': {'areas': 'Teleporter progression needs a verified GameCube patch.',
                            'skins': 'Imported wardrobe cycling needs a native GameCube skin loader.',
                            'npcs': 'NPC model replacement and movement need verified GameCube bindings.'},
                'multi_equip_note': 'Stacks weapon effects; one active weapon is drawn. This does not add dual-wield animations.'}
    from .pso_mods_tool import SIGNATURE, PATCHES, CHAR_PTR
    dc = game.get("platform") == "dreamcast"
    supported = dc and is_pso(game) and read(SIGNATURE[0], len(SIGNATURE[1])) == SIGNATURE[1]
    if supported:
        # The class-name string alone is insufficient to authorize executable writes on a different revision.
        supported = all(read(a, len(orig)) in (orig, patched) for addr, orig, patched in PATCHES.values()
                        for a in (addr if isinstance(addr, tuple) else (addr,)))
    character_class = None
    if supported:
        import struct
        try:
            ptr = struct.unpack("<I", read(CHAR_PTR, 4))[0]
            if 0x8C000000 <= ptr <= 0x8D000000 - 0x428 and read(ptr + 0x424, 4) == bytes.fromhex("64b005a2"):
                index = read(ptr + 0x3A1, 1)[0]
                if index < 9:
                    character_class = list(CLASSES)[index]
        except (ValueError, IndexError, struct.error):
            pass
    reason = "" if supported else ("Live patches need verification for this GameCube executable revision." if not dc
                                   else "Live controls require the US Dreamcast Ver. 2 executable.")
    return {"version": "dcv2" if dc else "gc", "supported": supported, "reason": reason, "character_class": character_class,
            "classes": list(CLASSES)[:9] if dc else list(CLASSES),
            "features": {k: supported for k in ("floor_spawn", "floor_rares", "equip_any", "multi_equip", "stat")},
            "pending": {"areas": "Teleporter progression flags still need a revision-specific verified patch.",
                        "skins": "Imported skin banks and the Start + L/R native loader are not implemented yet.",
                        "npcs": "Shop/gang NPC model bindings and guarded movement are not implemented yet."},
            "multi_equip_note": "Stacks equipment effects; PSO still draws one active weapon. This is not dual-wield animation."}


def preferences(ctx):
    import httpx
    r = httpx.get(f"{ctx.server}/api/pso/preferences", headers=ctx.headers, timeout=5)
    r.raise_for_status()
    return DEFAULTS | r.json()


def on_launch(sid, ad, game, ctx):
    """One lightweight boot watcher. Rechecks original/patch bytes after reset/state load; no save-state/JIT round trip.

    This starts before the title's equip routine is first compiled. Never force a JIT flush or load/save an operator's
    state in the background. Other revisions return an explicit unsupported capability rather than receiving writes.
    """
    if not is_pso(game):
        return None
    state = {"state": "waiting", "equip_any": None}
    def watch():
        from .tools import SESSIONS
        from .pso_mods_tool import PSO
        import time
        last_fetch, prefs = 0, None
        while sid in SESSIONS:
            try:
                if time.monotonic() - last_fetch >= 15 or getattr(ad,'_pso_preferences_dirty',False):
                    ad._pso_preferences_dirty=False
                    last_fetch,prefs=0,None
                    prefs = preferences(ctx)
                    last_fetch = time.monotonic()
                if prefs is not None and game.get('platform')=='gamecube':
                    from .models import Permission
                    if Permission.MEMORY_WRITE not in ctx.config.granted_permissions:
                        raise PermissionError('memory_write permission is required for PSO defaults')
                    from .pso_gc_extras import legendary
                    with session_lock(sid):
                        if getattr(ad,'_pso_preferences_dirty',False):raise RuntimeError('PSO defaults changed; refreshing preferences')
                        legendary(ad,bool(prefs.get('legendary',False)))
                cap = capabilities(game, ad.read_memory)
                if not cap["supported"]:
                    state.update(state="unsupported", reason=cap["reason"])
                elif prefs is not None:
                    with session_lock(sid):
                        if getattr(ad,'_pso_preferences_dirty',False):raise RuntimeError('PSO defaults changed; refreshing preferences')
                        m = PSO(ad.read_memory, ad.write_memory)
                        want = bool(prefs["equip_any"])
                        if game.get('platform') == 'gamecube':
                            from .pso_gc_live import GC, EQUIP_PATCH
                            from .pso_gc_extras import Extras
                            gc = Extras(ad)
                            if (gc.read(EQUIP_PATCH,4).hex() == '38000005') != want:
                                gc.equip_any(want)
                            gc.hook()
                            from .pso_gc_live import SURVIVAL
                            survive=bool(prefs.get('permanent_scape',False))
                            if bool(gc.u32(SURVIVAL))!=survive:gc.survival(survive)
                            from .pso_gc_adventure import apply_preferences
                            apply_preferences(ad,prefs,ctx)
                            state.update(state='applied', equip_any=want, reason='')
                        else:
                            before = m.patch_state("equip_any")
                            if before in ("on", "off"):
                                if (before == "on") != want:
                                    m.patch("equip_any", want)
                                state.update(state="applied", equip_any=want, reason="")
                            else:
                                state.update(state="unsupported", reason="Equip code bytes do not match this revision.")
            except Exception as e:
                state.update(state="waiting", reason=str(e)[:180])
            time.sleep(2)
        with _locks_guard:
            _locks.pop(sid, None)
    threading.Thread(target=watch, name="pso-defaults-" + sid, daemon=True).start()
    return state
