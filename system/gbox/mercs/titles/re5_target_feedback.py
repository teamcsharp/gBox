"""One final target-aware controller for RE5's raised gun.

The legacy crowd/PS3 paths can disagree about pitch and accept a body bearing
without a reachable target. Use the owned QFPS camera as persistent feedback;
short muzzle rays are collision evidence, not reliable camera pitch readings.
No digital aim input accompanies a successful bounded RAM correction, so aim
speed and shot-animation multipliers cannot multiply that correction again.
"""
from __future__ import annotations

import math

STICKS = frozenset({'rleft', 'rright', 'rup', 'rdown'})
YAW_RATE, PITCH_RATE = math.radians(140), math.radians(90)
MAX_DT = 0.05
GUN_FAMILIES = frozenset({'handgun', 'magnum', 'shotgun', 'automatic', 'rifle'})


def step(error, rate, dt):
    """Actual elapsed time, never a minimum frame or accumulated stall budget."""
    limit = rate * max(0.0, min(MAX_DT, dt))
    return max(-limit, min(limit, error))


def visible_target(snap):
    """A reachable live body already in front of the raised gun wins over a turn."""
    from . import re5_switch as R, re5_weapons
    p, cam, ray = snap.get('player') or {}, snap.get('aim_cam'), snap.get('laser') or {}
    held = next((s for s in snap.get('inventory') or () if s.get('hand')), {})
    spec = re5_weapons.WEAPONS.get(held.get('item'))
    if not spec or spec.family not in GUN_FAMILIES or not cam or p.get('motion') not in (26, 29) \
            or cam.get('player') != p.get('ptr') or cam.get('generation') != p.get('generation') \
            or not ray.get('up') or not ray.get('from') or not ray.get('at'):
        return None
    origin, dot = ray['from'], ray['at']
    px, py, pz = p['pos']
    if not all(math.isfinite(v) for v in (*origin, *dot)) \
            or math.dist(origin, (px, py+R.MUZZLE_H, pz)) >= 200:
        return None
    candidates = [e for e in snap.get('enemies') or () if (e.get('hp') or 0) > 0 and e.get('pos')
                  and abs(e['pos'][1]-py) <= R.LEVEL_DY
                  and math.hypot(e['pos'][0]-px, e['pos'][2]-pz) <= R.THREAT_CAP_R
                  and abs(R.wrap(R.heading(e['pos'][0]-px, e['pos'][2]-pz)-cam['heading'])) <= R.CROWD_FRONT
                  and R.dot_on(dot, e['pos'])]
    return min(candidates, key=lambda e: math.dist(origin, e['pos']), default=None)


def apply(bot, snap, act, now):
    from . import re5_switch as R, re5_weapons

    keys = set(act.get('hold') or ())
    p, cam = snap.get('player') or {}, snap.get('aim_cam')
    previous = getattr(bot, '_feedback_at', None)
    bot._feedback_at = now
    if bot.stats.get('operator_control') is True or 'zl' not in keys \
            or bot.doing not in ('aim', 'fire', 'raise', 'reraise', 'restale'):
        bot._feedback_at = None
        return act
    held = next((s for s in snap.get('inventory') or () if s.get('hand')), None)
    spec = re5_weapons.WEAPONS.get(held.get('item')) if held else None
    if not spec or spec.family not in GUN_FAMILIES or not p.get('pos') or not cam:
        return act
    if cam.get('player') != p.get('ptr') or cam.get('generation') != p.get('generation'):
        return dict(act, hold=tuple(sorted(keys - STICKS - {'zr'})))
    candidates = [e for e in snap.get('enemies') or () if (e.get('hp') or 0) > 0 and e.get('pos')]
    target = visible_target(snap) or next((e for e in candidates if e.get('ptr', e.get('slot')) == bot.target), None)
    if target is None:
        bot._trigger(False, now)
        return dict(act, hold=tuple(sorted(keys - STICKS - {'zr'})))

    px, py, pz = p['pos']
    foot = target['pos']
    dist = math.hypot(foot[0] - px, foot[2] - pz)
    aim_h = bot._aim_h(target, dist, now)
    chest = (foot[0], foot[1] + aim_h, foot[2])
    want_pitch = math.atan2(chest[1] - py - R.MUZZLE_H, max(dist, 1.0))
    yaw_error = R.wrap(R.heading(foot[0] - px, foot[2] - pz) - cam['heading'])
    pitch_error = want_pitch - cam['pitch']
    laser = snap.get('laser') or {}
    origin, dot = laser.get('from'), laser.get('at')
    valid_ray = bool(laser.get('up') and origin and dot
                     and all(math.isfinite(v) for v in (*origin, *dot))
                     and math.dist(origin, (px, py + R.MUZZLE_H, pz)) < 200
                     and math.dist(origin, dot) >= 1)
    if valid_ray:
        # At arm's length the muzzle can be well below and beside the nominal
        # standing camera. Aim from that actual origin, not a fixed 140 cm eye.
        want_pitch = math.atan2(chest[1] - origin[1],
                               max(1., math.hypot(chest[0]-origin[0], chest[2]-origin[2])))
        pitch_error = want_pitch - cam['pitch']
        # Recoil/short collision rays can point in the opposite vertical direction
        # to QFPS. Never integrate their error back into the camera.
        ray_yaw = R.heading(dot[0] - origin[0], dot[2] - origin[2])
        ray_pitch = math.atan2(dot[1] - origin[1], math.hypot(dot[0] - origin[0], dot[2] - origin[2]))
        coherent = (abs(R.wrap(ray_yaw - cam['heading'])) <= math.radians(15)
                    and abs(ray_pitch - cam['pitch']) <= math.radians(12))
        if coherent:
            yaw_error, pitch_error = R.ray_error(origin, dot, chest)

    dt = 0.0 if previous is None else now - previous
    writer = bot._writer()
    written = False
    if writer and p.get('motion') in R.MOTION_AIM and (p.get('hp') or 0) > 0:
        pitch = max(-1.0, min(1.0, cam['pitch'] + step(pitch_error, PITCH_RATE, dt)))
        heading = R.wrap(cam['heading'] + step(yaw_error, YAW_RATE, dt))
        written = writer(cam, pitch, heading)
        key = 'target_feedback_writes' if written else 'target_feedback_write_failures'
        bot.stats[key] = bot.stats.get(key, 0) + 1
        keys -= STICKS
        if not written:
            bot._trigger(False, now)
            return dict(act, hold=tuple(sorted(keys - {'zr'})))
    # The write above is an intention. Only this snapshot's actual aim can
    # authorize fire; it must be observed aligned on a later sample.
    on = (valid_ray and p.get('motion') in (R.MOTION_AIMED, R.MOTION_SHOT)
          and (R.dot_on(dot, foot) or (
              abs(yaw_error) <= max(math.radians(3), math.atan2(R.BODY_R, max(dist, 1)))
              and abs(pitch_error) <= math.radians(10)
              and bot._crowd_hit(origin, dot, foot, spec.family == 'shotgun'))))
    if not on:
        if 'zr' in keys:
            bot.stats['target_feedback_fire_blocks'] = bot.stats.get('target_feedback_fire_blocks', 0) + 1
        keys.discard('zr')
        bot._trigger(False, now)
        bot.doing = 'aim'
    elif now - (bot.aim_since if bot.aim_since is not None else now) >= R.READY_S:
        # Legacy guards may have disabled themselves after contradictory feedback.
        # The fresh, reachable body is sufficient evidence to resume firing.
        key = target.get('ptr', target.get('slot'))
        if key != bot.target:
            setter = getattr(bot, '_set_target', None)
            if callable(setter): setter(key, now)
            else: bot.target = key
        bot._aimctx = dict(getattr(bot, '_aimctx', None) or {}, target=key, dist=dist,
                          yaw_err=yaw_error, foot=tuple(foot), origin=tuple(origin), dot=tuple(dot),
                          where=R.dot_on(dot, foot), laserless=False, gate='verified live target')
        keys |= bot._trigger(True, now)
        bot.doing = 'fire'
    bot.stats.update(target_feedback_target=target.get('ptr', target.get('slot')),
                     target_feedback_yaw_deg=round(math.degrees(yaw_error), 2),
                     target_feedback_pitch_deg=round(math.degrees(pitch_error), 2),
                     target_feedback_on=bool(on), target_feedback_ram=written,
                     target_feedback_camera_pitch_deg=round(math.degrees(cam['pitch']), 2),
                     target_feedback_wanted_pitch_deg=round(math.degrees(want_pitch), 2))
    return dict(act, hold=tuple(sorted(keys)))
