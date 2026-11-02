"""Read-only exact-build barrier predicates; enable bits never prove traversal.

Also the room's forward-progression gate model (pure, reloadable): classify the
forward affordances in a cleared room so the controller drives P1 onto each
switch/panel and then through the door it gates, with gusto (operator 2026-11-02:
open and pass through EVERY door, never dither). These classifiers decide the
approach ORDER and the walk-through target; they never claim a door is open and
never read or write memory. Constants live here so no name crosses the
non-reloadable pso_coop_setup boundary.
"""
import hashlib
import math
import struct

from .registry import Unsupported

# A floor switch / door panel is stood on or activated first; then the door /
# fence / energy barrier it gates is walked through. TObjDoorKey is a panel to
# activate, not a wall to route around (it starts with TObjDoor but gates a door).
SWITCH_CLASSES = frozenset({'TLazerFenceSw', 'TObjDoorKey'})
DOOR_CLASSES = frozenset({'TObjDoor', 'TObjLazerFenceNorm', 'TOBarrierEnergy01'})
FORWARD_CLASSES = SWITCH_CLASSES | DOOR_CLASSES


def _finite(entity, keys=('x', 'z')):
    return all(type(entity.get(k)) in (int, float) and math.isfinite(entity[k]) for k in keys)


def forward_candidates(entities, room, px, pz, *, cooldown=None, now=0.0, prefer_room=True, exclude=None, skip_switches=False):
    """Ordered forward affordances for a cleared room (pure, read-only).

    Switches/panels (is_switch=0) sort before doors (is_switch=1) so the gate is
    opened before it is crossed; nearest-first within a class. A gkey-cooled
    affordance (already pressed, or abandoned as stalled) is skipped, as is any
    gkey in `exclude` (a panel the buddy already claimed, so a two-player room's
    two panels are split rather than both chased). `skip_switches` drops the
    panels entirely - used once the room's gate flags are already set (pressing a
    done panel is pointless; the job is now to walk THROUGH the open door). When
    the player's own room holds nothing forward, fall back to the whole floor so
    the pair always has an exit. Returns rows (is_switch, distance, gkey, entity, kind)."""
    cooldown = cooldown or {}
    exclude = exclude or ()

    def collect(same_room):
        rows = []
        for entity in list(entities)[:512]:
            cls = str(entity.get('class', ''))
            if cls not in FORWARD_CLASSES or not _finite(entity):
                continue
            if skip_switches and cls in SWITCH_CLASSES:
                continue
            if same_room and entity.get('room') != room:
                continue
            gkey = (cls, round(entity['x'], 1), round(entity['z'], 1))
            if cooldown.get(gkey, 0) > now or gkey in exclude:
                continue
            is_switch = 0 if cls in SWITCH_CLASSES else 1
            rows.append((is_switch, math.hypot(entity['x'] - px, entity['z'] - pz),
                         gkey, entity, 'switch' if is_switch == 0 else 'door'))
        rows.sort(key=lambda row: (row[0], row[1]))
        return rows

    return (collect(True) if prefer_room else []) or collect(False)


def count_switches(entities, room):
    """How many switch/panel affordances the room holds (two-panel detection)."""
    return sum(1 for e in list(entities)[:512] if str(e.get('class', '')) in SWITCH_CLASSES
               and _finite(e) and e.get('room') == room)


# --- Verified native stage-flag array (3OE2) ---------------------------------
# Reverse-engineered 2026-11-02 from the barrier's flag accessor 0x80229220:
#   get/set/clear(group, index) address ONE array. group = extsh(*(r13-0x4640)),
#   and r13 = 0x805DA600 (lis 0x805D; ori 0xA600 at 0x8000C188), so the group
#   pointer is 0x805D5FC0 - which gates.py's _binding already reads as `floor`.
#   The set routine (0x80229318, `or`) and clear (0x80229258, `andc`) both do:
#     base = 0x80510000 + 0x5CC8 = 0x80515CC8; n = index + 1;
#     byte = base + group*32 + (n>>3 adjusted); bit = MSB-first within the byte.
#   Net layout: 18 groups (one per floor 0..17) x 32 bytes; flag `index` (0..255)
#   is byte (group*32 + index//8), mask (0x80 >> index%8). Writing the per-object
#   native_state (+0xAC) is futile - it is recomputed each frame FROM this flag.
STAGE_FLAG_BASE = 0x80515CC8
STAGE_FLAG_GROUP_PTR = 0x805D5FC0        # == current floor (the accessor's group index)
STAGE_GROUP_SIZE = 32
STAGE_FLAG_GROUPS = 18
# Build signature: the set+clear routines (contain the base literal + bit math).
STAGE_FLAG_CODE = (0x80229258, 0x150,
                   '97a3b1513e7078442c2c0021acc9e65514f39f1e013956eafaf7b7d6640a3804')
STAGE_FLAG_R13 = (0x8000C184, '6042fd003da0805d61ada6004e800020')   # pins r13 = 0x805DA600


def stage_flag_locus(group, index):
    """Byte address + OR mask for stage flag `index` in `group` (MSB-first bit
    array, 32 bytes/group). None if either is outside the verified range."""
    if type(group) is not int or type(index) is not int:
        return None
    if not (0 <= group < STAGE_FLAG_GROUPS and 0 <= index <= 255):
        return None
    return STAGE_FLAG_BASE + group * STAGE_GROUP_SIZE + index // 8, 0x80 >> (index % 8)


def stage_flag_code_ok(read):
    """True only on the exact 3OE2 build: the accessor and the r13 setup match."""
    try:
        addr, length, digest = STAGE_FLAG_CODE
        if hashlib.sha256(read(addr, length)).hexdigest() != digest:
            return False
        r13_addr, r13_hex = STAGE_FLAG_R13
        return read(r13_addr, len(r13_hex) // 2).hex() == r13_hex
    except Exception:
        return False


def forward_gate_flag_indices(entities, room, limit=16):
    """Stage-flag indices that gate `room`'s forward progress: every switch/panel
    in the room, plus the nearest energy barrier (its +0xC8 low16 flag index).
    Reads flag_index decorated onto each entity by the controller (object +0xC8).
    Pure; returns a sorted de-duplicated list bounded to `limit`."""
    flags = set()
    for entity in list(entities)[:512]:
        cls = str(entity.get('class', ''))
        idx = entity.get('flag_index')
        if type(idx) is not int or not 0 <= idx <= 255:
            continue
        if cls in SWITCH_CLASSES and entity.get('room') == room:
            flags.add(idx)
        elif cls == 'TOBarrierEnergy01':
            flags.add(idx)
    return sorted(flags)[:limit]


def through_point(px, pz, gx, gz, overshoot=16.0):
    """A target just BEYOND the gate along the player->gate vector, so the actor
    commits across the threshold with gusto instead of stopping short of it."""
    distance = math.hypot(gx - px, gz - pz)
    if distance < 1e-3:
        return gx, gz
    return gx + (gx - px) / distance * overshoot, gz + (gz - pz) / distance * overshoot

CLASS = 'TOBarrierEnergy01'
VTABLE = 0x804AFB60
GUARDS = {
    0x8015DBC4: (360, 'da4bcb0886e563fdfd19101563782f93627b94d769f639390f482e91edae99b4'),
    0x8015DAE4: (224, '96a3d0615e42567f144bce811a644f21d5acb25a468064a6ff111ad75bbbba06'),
    0x80157E2C: (100, '522e17e5cb8e7dbbee79d11477a67a24c6d9862f357a67b19bfef809e355feae'),
    VTABLE: (84, '79d29c6386f3a64b05980685e6251e3113b91d0ea970dcafdb5a2ad8eb994f4e'),
}


def _read(ad, address, size):
    if address & 3 or not 0x80000000 <= address <= 0x81800000-size or not 0 < size <= 1024:
        raise ValueError('Barrier memory range')
    value=ad.read_memory(address,size)
    if len(value)!=size:
        raise ValueError('Short barrier observation')
    return value


def _binding(ad):
    return tuple(struct.unpack('>I',_read(ad,a,4))[0] for a in (0x804FE120,0x805D6060,0x805D5FC0,0x805D49B8)) + struct.unpack('>2I',_read(ad,0x8050EA10,8))


def _guards(ad):
    for address,(length,expected) in GUARDS.items():
        if hashlib.sha256(_read(ad,address,length)).hexdigest()!=expected:
            raise ValueError('Barrier executable/vtable differs')


def _critical(raw):
    return (raw[:4],raw[0x18:0x20],raw[0x28:0x2a],raw[0x38:0x44],
            raw[0xac:0xb0],raw[0xc8:0xd4])


def observe(ad, state):
    """Return a new state decorated with at most 16 strictly observed barriers.

    8015DAE4 mode 1 sets D0.0 without consulting a flag. Modes 2/3 call
    80229220(C8 & 0xffff), whose gameplay meaning is not yet established.
    80157E2C keeps state 2 while the enable bit remains set. Neither fact
    alone establishes collision passability, room clear, or a completed exit.
    """
    out=dict(state)
    out['door_requirements']={'state':'unverified','objects':[],
                              'reason':'No supported exact native barrier observed'}
    candidates=[e for e in state.get('entities',[])[:512] if e.get('class')==CLASS]
    if not candidates:
        return out
    try:
        players=state.get('players') or {}
        if (state.get('verified') is not True or state.get('phase')!=14 or state.get('travelling')
                or set(players)!={1,2} or state.get('episode') not in (1,2)
                or type(state.get('floor')) is not int or not 0<=state['floor']<=17):
            raise ValueError('Barrier needs fresh verified offline state')
        expected=(14,state['episode']-1,state['floor'],0,*(int(players[k]['ptr'],16) for k in (1,2)))
        if _binding(ad)!=expected:
            raise ValueError('Barrier area/actors changed')
        _guards(ad)
        rows=[];decorated={}
        for entity in candidates[:16]:
            pointer=int(entity['ptr'],16);raw=_read(ad,pointer,0xd4)
            name=struct.unpack_from('>I',raw)[0]
            if (struct.unpack_from('>I',raw,0x18)[0]!=VTABLE or
                    _read(ad,name,len(CLASS)+1)!=CLASS.encode()+b'\0' or
                    struct.unpack_from('>H',raw,0x1c)[0]!=entity.get('entity_id')):
                raise ValueError('Barrier object/class identity differs')
            mode,flags=struct.unpack_from('>2I',raw,0xcc)
            native_state=struct.unpack_from('>I',raw,0xac)[0]
            flag_index=struct.unpack_from('>I',raw,0xc8)[0]&0xffff
            if _critical(_read(ad,pointer,0xd4))!=_critical(raw):
                raise ValueError('Barrier changed during observation')
            requirement=dict(source='3OE2:8015DAE4',code_verified=True,mode=mode,
                native_state=native_state,enable_bit=bool(flags&1),passability_verified=False,
                room_clear_verified=False,predicate='unknown_native_mode',
                predicate_scope='native mode branch; global update overrides not evaluated')
            if mode==1:
                requirement.update(predicate='unconditional_enable',predicate_verified=True,
                                   enemy_or_switch_test_in_this_predicate=False)
            elif mode in (2,3):
                requirement.update(predicate='native_stage_flag_accessor_unknown',predicate_verified=False,
                                   flag_index=flag_index,accessor='80229220')
            else:
                requirement['predicate_verified']=False
            rows.append(dict(ptr=entity['ptr'],entity_id=entity['entity_id'],**requirement))
            decorated[entity['ptr']]=requirement
        if _binding(ad)!=expected:
            raise ValueError('Barrier area/actors changed during observation')
        _guards(ad)
        out['entities']=[dict(e,door_requirements=decorated[e['ptr']]) if e.get('ptr') in decorated else e
                         for e in state.get('entities',[])]
        out['door_requirements']={'state':'partial_verified','objects':rows,
                                  'objects_truncated':len(candidates)>16,
                                  'room_clear_verified':False,'passability_verified':False}
    except (ValueError,TypeError,KeyError,struct.error,OSError,Unsupported) as error:
        out['door_requirements']['reason']=str(error)
    return out
