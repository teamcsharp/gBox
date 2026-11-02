"""RE5 Switch's owned aim camera, guarded writer and final target feedback.
The legacy re5_switch.AIM_LOCK remains off; apply() uses elapsed-time bounded
corrections and independently observed target contact to authorize firing.

Found statically in main EBFFDB22 and read live (read-only, MercMode 2026-10-27 19:44-19:52, 2600 samples, 317 aimed):
sUnit move line 9 holds two uCameraCtrl units (vtable main+0x1ACB410); the player's is the one whose +0x130 points at
the player. Its +0x198 is the ACTIVE camera: the uCameraQFPS embedded at ctrl+0xDB0 (vtable main+0x1ACBCF0, size 0x680:
the class RE6's #1367 locks, there at camera+0x16A0). Its update is main+0x249400.
  QFPS+0x1B0 f32  the PITCH, radians, + = up, clamped to [-1, +1] (0x2499b4..0x2499cc; 1 rad = the aim's +-57 deg
                  limits seen live), integrated from the right stick each frame (0x249970 ldr / 0x249978 fadd /
                  0x24997c str): persistent state. Live: player +0x3F5C = -0.9989 x QFPS+0x1B0 + 0.004 (sd 1.0 deg), and
                  it keeps its value with the gun down - the pitch the next raise starts from (the +57 deg raises).
  QFPS+0x1B4 f32  this frame's yaw delta (recomputed: not a state).
The yaw's state is the player's own heading, the quaternion at +0x70: the aiming motion (0x96cd30) reads the rotation,
adds the frame's turn and sets it back (0x96cf54 / 0x96cf78), so a written heading should persist (one held with the
gun down, 2026-10-27). Live: the laser's yaw - the heading over 139 long rays, median -0.3 deg.
aim_writer validates camera ownership, player generation and snapshot freshness,
then reads each write back. The final feedback controller releases input after a
failed validation/write and reacquires from a fresh snapshot.
"""
from __future__ import annotations

import math
import struct
import time

CTRL_VT, QFPS_VT = 0x1ACB410, 0x1ACBCF0
CTRL_PLAYER, CTRL_ACTIVE, CTRL_QFPS = 0x130, 0x198, 0xDB0
QF_PITCH = 0x1B0
PITCH_LIMIT = 1.0                        # rad: the game's clamp
P_ROT = 0x70
CAM_LINE, S_UNIT, UNIT_LINES, LINE_STRIDE, UNIT_NEXT = 9, 0x26A3270, 0x18, 0x30, 0x18
LOCK_TOL = 2e-3                          # rad: a read-back this close is the write
ERRORS = (ValueError, OSError, OverflowError, struct.error, RuntimeError)


def _q(m, a):
    return struct.unpack("<Q", m.rd(a, 8))[0]


def _ok(p):
    return isinstance(p, int) and 0x1000000 <= p < (1 << 40)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def player_qfps(m, base: int, player: int) -> int | None:
    """The player's active uCameraQFPS (ctrl+0xDB0 of line 9's uCameraCtrl whose +0x130 is the player, when it is the
    ctrl's active camera); None otherwise. Never raises."""
    try:
        su = _q(m, base + S_UNIT)
        if not _ok(su):
            return None
        u, n = _q(m, su + UNIT_LINES + LINE_STRIDE * CAM_LINE), 0
        while _ok(u) and n < 16:
            if _q(m, u) == base + CTRL_VT and _q(m, u + CTRL_PLAYER) == player:
                qf = u + CTRL_QFPS
                return qf if _q(m, qf) == base + QFPS_VT and _q(m, u + CTRL_ACTIVE) == qf else None
            u, n = _q(m, u + UNIT_NEXT), n + 1
    except ERRORS:
        return None
    return None


def aim_state(m, base: int, player: int) -> dict | None:
    """{"qfps", "pitch" (rad, + = up), "heading" (rad, from the quaternion)}; None without the player's camera."""
    qf = player_qfps(m, base, player)
    if qf is None:
        return None
    try:
        pitch = struct.unpack("<f", m.rd(qf + QF_PITCH, 4))[0]
        _qx, qy, _qz, qw = struct.unpack("<4f", m.rd(player + P_ROT, 16))
        generation = _q(m, player + 0x1A00)
    except ERRORS:
        return None
    if not (math.isfinite(pitch) and abs(pitch) <= PITCH_LIMIT + 1e-3 and math.isfinite(qy) and math.isfinite(qw)):
        return None
    return {"qfps": qf, "player": player, "pitch": pitch, "heading": wrap(2.0 * math.atan2(qy, qw)),
            "base": base, "generation": generation, "sampled_at": time.monotonic()}


def aim_writer(m):
    """The aim lock's writer for this session: write(state, pitch, heading) -> True once each written value reads back
    (pitch into QFPS+0x1B0, clamped; the heading as the player's quaternion about y; either may be None). None without
    the session's adapter or with modifications off."""
    ad = getattr(m, "adapter", None)
    if ad is None or getattr(m, "mercs_no_modifications", False):
        return None

    def write(st: dict, pitch: float | None, heading: float | None) -> bool:
        try:
            # A camera pointer from a previous life/raise is never a write capability.
            if any(v is not None and not math.isfinite(v) for v in (pitch, heading)):
                return False
            if not 0 <= time.monotonic() - st.get("sampled_at", -math.inf) <= 0.15 \
                    or player_qfps(m, st["base"], st["player"]) != st["qfps"] \
                    or _q(m, st["player"] + 0x1A00) != st["generation"]:
                return False
            if pitch is not None:
                p = max(-PITCH_LIMIT, min(PITCH_LIMIT, float(pitch)))
                ad.write_memory(st["qfps"] + QF_PITCH, struct.pack("<f", p))
                if abs(struct.unpack("<f", ad.read_memory(st["qfps"] + QF_PITCH, 4))[0] - p) > LOCK_TOL:
                    return False
            if heading is not None:
                h = wrap(float(heading))
                # Preserve any x/z tilt (slopes, animations); only the y/w yaw components are rewritten.
                qx, _qy, qz, _qw = struct.unpack("<4f", ad.read_memory(st["player"] + P_ROT, 16))
                if not (math.isfinite(qx) and math.isfinite(qz)):
                    return False
                norm = math.sqrt(qx * qx + qz * qz)
                if norm > 0.99:                     # a near-pure x/z rotation: not a simple upright player heading
                    return False
                ad.write_memory(st["player"] + P_ROT, struct.pack("<4f", qx, math.sin(h / 2), qz, math.cos(h / 2)))
                _qx2, qy2, _qz2, qw2 = struct.unpack("<4f", ad.read_memory(st["player"] + P_ROT, 16))
                if abs(wrap(2.0 * math.atan2(qy2, qw2) - h)) > LOCK_TOL:
                    return False
        except ERRORS:
            return False
        return True
    return write


# Target feedback lives beside the established camera writer so existing workers
# track and reload both together, including before the first process restart.
STICKS = frozenset({'rleft', 'rright', 'rup', 'rdown'})
YAW_RATE, PITCH_RATE = math.radians(140), math.radians(90)
MAX_DT = 0.05
GUN_FAMILIES = frozenset({'handgun', 'magnum', 'shotgun', 'automatic', 'rifle'})
ACQUIRE_S, REPOSITION_S, REPOSITION_CM = .75, .65, 100.
ACQUIRE_MAX_S, PROGRESS_GRACE_S = 2., .25
COMBAT_AIM = frozenset({'aim', 'fire', 'raise', 'reraise', 'restale'})


def keep_active(bot, snap, act, now):
    """Bound an unproductive raise; move through a clear gap, then reacquire.

    Called after the firing gate and before movement/animation governors. Never
    interrupts a throw, mine, heal, QTE, human control or native equip handover.
    Target changes do not reset the deadline; an actual firing action does.
    """
    from . import re5_switch as R
    p, keys = snap.get('player') or {}, set(act.get('hold') or ())
    identity = p.get('ptr'), p.get('generation')
    state = getattr(bot, '_aim_wait', None)
    if (bot.stats.get('operator_control') is True or bot.doing not in COMBAT_AIM
            or 'zl' not in keys
            or not p.get('pos') or (p.get('hp') or 0) <= 0
            or p.get('motion') in R.MOTION_HELD or p.get('motion') == R.MOTION_RELOAD
            or 'zr' in keys or p.get('motion') == R.MOTION_SHOT
            or now < getattr(bot, '_shot_until', -math.inf)
            or keys & {'lup', 'ldown', 'lleft', 'lright'}):
        bot._aim_wait = None
        bot.stats['aim_wait_s'] = 0.
        return act
    if state is None or state['identity'] != identity or now < state['seen']:
        state = bot._aim_wait = {'identity': identity, 'since': now, 'seen': now, 'until': None}
    state['seen'] = now
    bot.stats['aim_wait_s'] = round(now - state['since'], 2)
    if p.get('motion') == 22 and now - state['since'] < R.LASER_STUCK_S:
        return act  # let the native raise complete; the existing laser timeout remains bounded
    # A smooth correction can need more than .75 s after a rear target/raise.
    # Keep it while observed error improves; a successful RAM write by itself
    # is not progress. The hard cap still bounds a moving/unreachable target.
    target = bot.stats.get('target_feedback_target')
    yaw, pitch = bot.stats.get('target_feedback_yaw_deg'), bot.stats.get('target_feedback_pitch_deg')
    if target is not None and isinstance(yaw, (int, float)) and isinstance(pitch, (int, float)):
        error = math.hypot(yaw, pitch)
        if state.get('target') != target:
            state.update(target=target, best_error=error)
        elif math.isfinite(error) and error < state.get('best_error', math.inf) - 1.:
            state.update(best_error=error, progress_at=now)
    if state['until'] is None and now - state['since'] < ACQUIRE_S:
        return act
    if state['until'] is None and now - state['since'] < ACQUIRE_MAX_S \
            and now - state.get('progress_at', -math.inf) <= PROGRESS_GRACE_S:
        return act
    px, py, pz = p['pos']
    crowd = [e for e in snap.get('enemies') or () if (e.get('hp') or 0) > 0 and e.get('pos')
             and abs(e['pos'][1]-py) <= R.LEVEL_DY
             and math.hypot(e['pos'][0]-px, e['pos'][2]-pz) <= R.THREAT_CAP_R]
    if not crowd:
        bot._aim_wait = None
        return act
    ray = snap.get('laser') or {}
    origin, dot = ray.get('from'), ray.get('at')
    if (state['until'] is not None and p.get('motion') == R.MOTION_AIMED
            and ray.get('up') and origin and dot
            and all(math.isfinite(v) for v in (*origin, *dot))
            and math.dist(origin, (px, py + R.MUZZLE_H, pz)) < 200
            and any(R.dot_on(dot, e['pos']) for e in crowd)):
        bot._aim_wait = None  # movement opened a shot: let the raise settle and fire
        return act
    if state['until'] is not None and now >= state['until']:
        bot._aim_wait = None  # a fresh, bounded acquisition attempt after moving
        return act
    if state['until'] is None:
        state['until'] = now + REPOSITION_S
        bot.stats['aim_repositions'] = bot.stats.get('aim_repositions', 0) + 1
    # Evaluate all eight local directions, including backward/sideways ones;
    # the ordinary mesh guard only checks forward travel. Recheck each tick.
    options = ((0, ('lup',)), (45, ('lup', 'lleft')), (90, ('lleft',)),
               (135, ('ldown', 'lleft')), (180, ('ldown',)),
               (-135, ('ldown', 'lright')), (-90, ('lright',)), (-45, ('lup', 'lright')))
    mesh, candidates = snap.get('nav'), []
    desired = set(R.Bot._escape_keys(p, crowd))
    for angle, movement in options:
        head = p.get('rot', 0.) + math.radians(angle)
        end = (px + REPOSITION_CM*math.sin(head), py, pz + REPOSITION_CM*math.cos(head))
        clear = None
        if mesh is not None and hasattr(mesh, 'floor_segment'):
            try:
                if mesh.member(p['pos']) is not None:
                    clear = bool(mesh.floor_segment(p['pos'], end))
            except Exception:  # unavailable geometry: bounded probe, never invent a clear corridor
                pass
        if clear is False:
            continue
        distance = min(math.hypot(e['pos'][0]-end[0], e['pos'][2]-end[2]) for e in crowd)
        candidates.append((distance, int(set(movement) == desired), movement))
    bot._gun_down()
    bot._feedback_at = None
    bot.doing, bot.why = 'escape', 'aim stalled; make space and reacquire a live target'
    if candidates:
        movement = max(candidates)[2]
    else:
        # No valid step on this mesh: turn toward a new sightline without pushing
        # into known geometry. Wall feedback still receives the final action.
        movement = ('rleft',) if bot.stats['aim_repositions'] % 2 else ('rright',)
    return {'hold': movement}


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
    # Permission to fire/flash belongs to THIS snapshot. Every early return
    # must leave a prior target's accepted contact behind.
    bot.stats.update(target_feedback_on=False, target_feedback_ram=False,
                     target_feedback_gate='no verified target this tick')
    previous = getattr(bot, '_feedback_at', None)
    bot._feedback_at = now
    if bot.stats.get('operator_control') is True or 'zl' not in keys \
            or bot.doing not in ('aim', 'fire', 'raise', 'reraise', 'restale'):
        bot._feedback_at = None
        bot._feedback_contact = None
        return act
    held = next((s for s in snap.get('inventory') or () if s.get('hand')), None)
    spec = re5_weapons.WEAPONS.get(held.get('item')) if held else None
    if not spec or spec.family not in GUN_FAMILIES or not p.get('pos'):
        bot._feedback_contact = None
        return act
    if not cam:
        bot._feedback_contact = None
        # Production snapshots include this key even during camera transitions.
        # A temporarily inactive QFPS must not hand aim back to amplified digital
        # sticks; wait for ownership or let keep_active make space. Older readers
        # without camera support retain their existing controller.
        if 'aim_cam' in snap:
            bot._feedback_at = None
            bot._trigger(False, now)
            return dict(act, hold=tuple(sorted(keys - STICKS - {'zr'})))
        return act
    if cam.get('player') != p.get('ptr') or cam.get('generation') != p.get('generation'):
        bot._feedback_contact = None
        bot._trigger(False, now)
        bot.doing = 'aim'
        bot.stats['target_feedback_gate'] = 'camera owner changed'
        return dict(act, hold=tuple(sorted(keys - STICKS - {'zr'})))
    candidates = [e for e in snap.get('enemies') or () if (e.get('hp') or 0) > 0 and e.get('pos')]
    target = visible_target(snap) or next((e for e in candidates if e.get('ptr', e.get('slot')) == bot.target), None)
    if target is None:
        bot._feedback_contact = None
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
    if writer:
        keys -= STICKS  # also while lowering/raising between writable motions
    if writer and p.get('motion') in R.MOTION_AIM and (p.get('hp') or 0) > 0:
        pitch = max(-1.0, min(1.0, cam['pitch'] + step(pitch_error, PITCH_RATE, dt)))
        heading = R.wrap(cam['heading'] + step(yaw_error, YAW_RATE, dt))
        written = writer(cam, pitch, heading)
        key = 'target_feedback_writes' if written else 'target_feedback_write_failures'
        bot.stats[key] = bot.stats.get(key, 0) + 1
        if not written:
            bot._feedback_contact = None
            bot._trigger(False, now)
            return dict(act, hold=tuple(sorted(keys - {'zr'})))
    # The write above is an intention. Only this snapshot's actual aim can
    # authorize fire; it must be observed aligned on a later sample.
    body_contact = bool(valid_ray and bot._crowd_hit(origin, dot, foot, False))
    spread_contact = bool(valid_ray and not body_contact and spec.family == 'shotgun'
                          and bot._crowd_hit(origin, dot, foot, True))
    contact_kind = ('body endpoint' if body_contact and R.dot_on(dot, foot) else
                    'body segment' if body_contact else 'shotgun spread' if spread_contact else '')
    on = bool(p.get('motion') in (R.MOTION_AIMED, R.MOTION_SHOT) and (body_contact or spread_contact))
    # A nearby target and a long ray do not establish body contact. In particular,
    # UNLOAD's broad yaw/pitch window let the M29 fire beside a target at 4-5 m.
    # Keep correcting above while blocked; keep_active bounds failed acquisition.
    # An actual body segment (including close hips/shoulders) needs no extra
    # chest-angle window. Only a shotgun may use the measured spread cone.
    d = max(dist, 1.0)
    # Recoil motion 29 briefly hides the laser. The legacy crowd controller
    # preserves its held trigger through that interval; this final gate must not
    # cancel the same verified shot on every recoil frame. Continue ONLY a shot
    # accepted on the preceding sample, for one shot-tail window, with the same
    # owner/target and stationary, aligned aim. Never refresh the contact from a
    # missing ray or ignore a newly observed obstruction.
    contact = getattr(bot, '_feedback_contact', None)
    recoil = bool(not on and not valid_ray and not laser.get('up') and contact
                  and contact.get('kind') in ('body endpoint', 'body segment', 'shotgun spread')
                  and p.get('motion') == R.MOTION_SHOT
                  and 0 <= now - contact['at'] <= R.SHOT_TAIL_S
                  and contact['identity'] == (p.get('ptr'), p.get('generation'))
                  and contact['weapon'] == held.get('item')
                  and contact['target'] == target.get('ptr', target.get('slot'))
                  and math.dist(p['pos'], contact['pos']) <= R.WALL_SLACK
                  and abs(R.wrap(cam['heading'] - contact['heading'])) <= math.radians(3)
                  and abs(cam['pitch'] - contact['pitch']) <= math.radians(3)
                  and abs(yaw_error) <= max(math.radians(3), math.atan2(R.BODY_R, d))
                  and abs(pitch_error) <= math.radians(10))
    if recoil:
        on = True
        bot.stats['target_feedback_recoil_holds'] = bot.stats.get('target_feedback_recoil_holds', 0) + 1
    if not on:
        bot._feedback_contact = None
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
        feedback_origin = contact['origin'] if recoil else origin
        feedback_dot = contact['dot'] if recoil else dot
        accepted_kind = contact['kind'] if recoil else contact_kind
        bot._aimctx = dict(getattr(bot, '_aimctx', None) or {}, target=key, dist=dist,
                          yaw_err=yaw_error, pitch_err=pitch_error, foot=tuple(foot),
                          origin=tuple(feedback_origin), dot=tuple(feedback_dot),
                          where=R.dot_on(feedback_dot, foot), laserless=False,
                          contact_kind=accepted_kind, ray_observed=not recoil,
                          body_contact=contact['body'] if recoil else body_contact,
                          gate='verified shot recoil' if recoil else 'measured ' + accepted_kind)
        keys |= bot._trigger(True, now)
        bot.doing = 'fire'
        if not recoil:
            bot._feedback_contact = {'at': now, 'identity': (p.get('ptr'), p.get('generation')),
                                     'target': key, 'pos': tuple(p['pos']),
                                     'heading': cam['heading'], 'pitch': cam['pitch'], 'weapon': held.get('item'),
                                     'origin': tuple(origin), 'dot': tuple(dot),
                                     'kind': contact_kind, 'body': body_contact}
    bot.stats['target_feedback_gate'] = 'recoil continuation' if recoil else contact_kind if on else \
        'waiting for aimed motion' if p.get('motion') not in (R.MOTION_AIMED, R.MOTION_SHOT) else \
        'no current laser' if not valid_ray else 'ray misses or stops before target'
    if not on:
        bot.why = (f"aim correction: {bot.stats['target_feedback_gate']} "
                   f"(yaw {math.degrees(yaw_error):+.1f}, pitch {math.degrees(pitch_error):+.1f} deg)")
    bot.stats.update(target_feedback_target=target.get('ptr', target.get('slot')),
                     target_feedback_yaw_deg=round(math.degrees(yaw_error), 2),
                     target_feedback_pitch_deg=round(math.degrees(pitch_error), 2),
                     target_feedback_on=bool(on), target_feedback_ram=written,
                     target_feedback_camera_pitch_deg=round(math.degrees(cam['pitch']), 2),
                     target_feedback_wanted_pitch_deg=round(math.degrees(want_pitch), 2))
    return dict(act, hold=tuple(sorted(keys)))
