"""Read-only exact-build barrier predicates; enable bits never prove traversal."""
import hashlib
import struct

from .registry import Unsupported

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
