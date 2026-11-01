"""PSO session capabilities and boot defaults. Never apply Dreamcast addresses to GameCube."""
import math
import threading
import time

from .psoitems import CLASSES

DEFAULTS = {"equip_any": True, "always_hit": True, "permanent_scape": False, "legendary": False,
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


def autoplay_speed_status(adapter, available):
    """Only expose a fresh native measurement for the current timing context."""
    requested = getattr(adapter, 'autoplay_speed', 1)
    result = {'available': available, 'requested': requested, 'choices': [1, 2, 4, 8, 10],
              'known': getattr(adapter, '_autoplay_speed_known', False) is True,
              'changing': bool(getattr(adapter, '_autoplay_speed_changing', False)),
              'paused': bool(getattr(adapter, '_pso_timing_paused', False) or
                             getattr(adapter, 'paused', False) or getattr(adapter, 'paused_tids', None)),
              'measurement_verified': False, 'achieved_verified': False}
    observation = getattr(adapter, '_autoplay_speed_observed', None)
    card = getattr(adapter, '_pso_coop_new_card', None)
    if (not available or not result['known'] or result['changing'] or result['paused'] or
            not isinstance(card, dict) or card.get('isolated') is not True or
            not card.get('session_id') or not card.get('path') or
            set(getattr(adapter, '_pso_verified_player_slots', ())) != {0, 1} or
            not isinstance(observation, dict) or observation.get('verified') is not True or
            observation.get('source') != '3OE2 native timebase 0x80375F20' or
            observation.get('requested') != requested or
            observation.get('timing_epoch') != getattr(adapter, '_pso_timing_epoch', 0)):
        return result
    fields = ('actual', 'lower', 'upper', 'monotonic', 'sample_seconds')
    if any(type(observation.get(k)) not in (int, float) or not math.isfinite(observation[k]) for k in fields):
        return result
    actual, lower, upper, at, duration = (observation[k] for k in fields)
    age = time.monotonic() - at
    if not (0 <= age < 2 and .5 <= duration <= 2 and 0 < lower <= actual <= upper <= 12
            and (upper - lower) / actual <= .05):
        return result
    achieved = type(requested) in (int, float) and lower >= requested * .95 and upper <= requested * 1.05
    result.update(measurement_verified=True, achieved_verified=achieved, actual=actual, lower=lower, upper=upper,
                  sample_seconds=duration, sample_age_seconds=age, valid_for_ms=(2 - age) * 1000,
                  measurement_source='native_game_clock')
    return result


def capabilities(game, read, *, player_index=0, adapter=None):
    if game.get('platform') == 'gamecube':
        from types import SimpleNamespace
        from .pso_gc_live import GC
        ad=adapter or SimpleNamespace(read_memory=read,write_memory=None)
        players=[]
        for index in (0,1):
            entry={'index':index,'label':f'Player {index+1}','available':False,'verified':False}
            try:
                actor=GC(ad,player_index=index)
                pointer=actor.check(require_probe=False)
                entry.update(available=True,entity_id=index)
                actor.check()
                entry['verified']=True
            except Exception as error:entry['reason']=str(error)
            players.append(entry)
        supported, reason = False, 'This is not a PSO game'
        if is_pso(game):
            try:
                GC(ad,player_index=player_index).check()
                supported, reason = True, ''
            except Exception as error:
                reason = str(error)
        adventure=False
        accuracy=False
        if supported and player_index==0:
            try:
                from .pso_gc_adventure import Adventure
                Adventure(SimpleNamespace(read_memory=read,write_memory=None)).check()
                adventure=True
            except Exception: pass
            try:
                from .pso_accuracy import GameCube
                GameCube(SimpleNamespace(read_memory=read,write_memory=None)).check()
                accuracy=True
            except Exception: pass
        speed=bool(adapter and getattr(adapter,'_pso_coop_new_card',False) and callable(getattr(adapter,'set_autoplay_speed',None)))
        features={k:supported for k in ('give','stat','mag','randomized','equip')}
        features.update({k:supported and player_index==0 for k in ('floor_spawn','floor_rares','floor_clear','equip_any','multi_equip','survival','revive')})
        features.update({k:adventure for k in ('enemy_drops','walk_through','boss_warp')})
        features.update(always_hit=accuracy,autoplay_speed=speed)
        return {'version': 'gc', 'label': 'GameCube Plus US revision 2', 'supported': supported, 'reason': reason,
                'player_index':player_index,'players':players,
                'selection_note':'Equipment targets the selected verified player. Shared patches and survival controls remain on player 1.',
                'autoplay_speed':autoplay_speed_status(adapter, speed),
                'character_class': None, 'classes': list(CLASSES),
                'features':features,
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
            "features": {k: supported for k in ("floor_spawn", "floor_rares", "equip_any", "multi_equip", "stat")} | {'always_hit': False},
            "pending": {"areas": "Teleporter progression flags still need a revision-specific verified patch.",
                        "skins": "Imported skin banks and the Start + L/R native loader are not implemented yet.",
                        "npcs": "Shop/gang NPC model bindings and guarded movement are not implemented yet."},
            "multi_equip_note": "Stacks equipment effects; PSO still draws one active weapon. This is not dual-wield animation."}


def preferences(ctx):
    import httpx
    r = httpx.get(f"{ctx.server}/api/pso/preferences", headers=ctx.headers, timeout=5)
    r.raise_for_status()
    return DEFAULTS | r.json()


def apply_defaults(sid, ad, game, ctx, prefs):
    """One idempotent application for boot watchers and explicit reconnects.

    Caller owns session_lock(sid). Read preferences before calling; no launch,
    reset, state load or duplicate background thread is used to reconnect.
    """
    from .models import Permission
    from .pso_live import deadline
    from .pso_mods_tool import PSO
    deadline(ctx)
    if Permission.MEMORY_WRITE not in getattr(getattr(ctx, 'config', None), 'granted_permissions', ()):
        raise PermissionError('memory_write permission is required for PSO defaults')
    prefs = DEFAULTS | prefs
    if getattr(ad, '_pso_preferences_dirty', False):
        raise RuntimeError('PSO defaults changed; refreshing preferences')
    gc = game.get('platform') == 'gamecube'
    if gc:
        from .pso_accuracy import running
        from .pso_gc_extras import legendary
        running(ad)
        deadline(ctx)
        legendary(ad, bool(prefs['legendary']))
    cap = capabilities(game, ad.read_memory)
    if not cap['supported']:
        return {'state': 'unsupported', 'reason': cap['reason'], 'equip_any': None, 'always_hit': None}
    want = bool(prefs['equip_any'])
    result = {'state': 'applied', 'equip_any': want, 'reason': '', 'always_hit': None}
    if gc:
        from .pso_gc_live import EQUIP_PATCH, SURVIVAL
        from .pso_gc_extras import Extras
        from .pso_gc_adventure import apply_preferences
        from . import pso_accuracy
        m = Extras(ad)
        deadline(ctx)
        if (m.read(EQUIP_PATCH, 4).hex() == '38000005') != want:
            m.equip_any(want)
        m.hook()
        survive = bool(prefs['permanent_scape'])
        if bool(m.u32(SURVIVAL)) != survive:
            deadline(ctx)
            m.survival(survive)
        result['permanent_scape'] = survive
        if cap['features'].get('always_hit'):
            deadline(ctx)
            result['always_hit'] = pso_accuracy.set_enabled(ad, 'gamecube', prefs['always_hit'])['always_hit']
        else:
            result['always_hit_reason'] = 'The running GameCube accuracy instructions need verification.'
        deadline(ctx)
        apply_preferences(ad, prefs, ctx)
    else:
        m = PSO(ad.read_memory, ad.write_memory)
        before = m.patch_state('equip_any')
        if before not in ('on', 'off'):
            return {'state': 'unsupported', 'reason': 'Equip code bytes do not match this revision.',
                    'equip_any': None, 'always_hit': None}
        if (before == 'on') != want:
            deadline(ctx)
            m.patch('equip_any', want)
        result['always_hit_reason'] = 'Dreamcast hit resolution needs a separately verified patch.'
    return result


def on_launch(sid, ad, game, ctx):
    """One lightweight boot watcher. Rechecks original/patch bytes after reset/state load; no save-state/JIT round trip.

    This starts before the title's equip routine is first compiled. Never force a JIT flush or load/save an operator's
    state in the background. Other revisions return an explicit unsupported capability rather than receiving writes.
    """
    if not is_pso(game):
        return None
    state = {"state": "waiting", "equip_any": None, "always_hit": None}
    def watch():
        from .tools import SESSIONS
        import time
        last_fetch, prefs = 0, None
        while sid in SESSIONS:
            try:
                if time.monotonic() - last_fetch >= 15 or getattr(ad,'_pso_preferences_dirty',False):
                    ad._pso_preferences_dirty=False
                    last_fetch,prefs=0,None
                    prefs = preferences(ctx)
                    last_fetch = time.monotonic()
                if prefs is not None:
                    with session_lock(sid):
                        state.update(apply_defaults(sid, ad, game, ctx, prefs))
            except Exception as e:
                state.update(state="waiting", reason=str(e)[:180])
            time.sleep(2)
        with _locks_guard:
            _locks.pop(sid, None)
    threading.Thread(target=watch, name="pso-defaults-" + sid, daemon=True).start()
    return state
