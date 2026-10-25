"""Rotten eggs through game-created loadouts or the native ordinary pickup path.

BLUS30491: 0x136 is WP36 EGG_X (uWp36). The native pickup path
8373E0/1AFEF8/1AEE90 reads cItemSetInfo+76, then9D417C/9D693C
constructs the inventory item AND its weapon object. No existing carried
item is relabelled; medicine, bonuses and mines are never pickup donors.
"""
import math
import struct

EGG_ID, EGG_VT = 0x136,0x0162E7F0
EGG_DEF, EGG_NAME = 0x0181B8B0,0x013D0068
DEFAULT_RATE, MAX_RATE = 20.,20.
AMMO_VTABLES = {0x015BD5B8:0x201,0x015BD3E8:0x202,0x015BD218:0x203,
    0x015BD048:0x204,0x015BCE78:0x206,0x015BCCA8:0x207,0x015BCAD8:0x208,
    0x015BC908:0x209,0x015BC738:0x20E,0x015BC568:0x20F,0x015BC398:0x210}
SOURCE_VT, VOLUME_VT, MANAGER_VT = 0x015ADD68,0x01634B00,0x0157B630
NATIVE_SIGNATURES={
    0x009D693C:bytes.fromhex('f821ff017c0802a6fbe100f8f8010110380000007c7f1b78'),
    0x009D3C70:bytes.fromhex('8124000438600000fbc1fff07920c62283c289502f800001'),
}


def state(g):
    return g.orig.setdefault('rotten_eggs',{'on':False,'rate':DEFAULT_RATE,'status':'disabled'})


def _u(memory,address):
    return struct.unpack('>I',memory.rd(address,4))[0]


def world_items(memory,donor=None,*,item_id=EGG_ID,item_vtable=EGG_VT):
    """Bounded ownerless native egg/ammo pickups, fenced against item-list reuse."""
    from . import re5_ps3 as R
    try:
        manager=_u(memory,R.S_ITEM)
        if not R.ptr_ok(manager) or _u(memory,manager)!=MANAGER_VT:return []
        count,array=_u(memory,manager+0x28),_u(memory,manager+0x34)
        if not 0<count<=512 or not R.ptr_ok(array) or array+count*4>0x40000000:return []
        raw=memory.rd(array,count*4);out=[]
        for actor in struct.unpack(f'>{count}I',raw):
            if not R.ptr_ok(actor) or actor%4:continue
            vt=_u(memory,actor);original=AMMO_VTABLES.get(vt)
            if original is None and vt!=item_vtable:continue
            data=memory.rd(actor+0x1BC0,0xB0)
            if struct.unpack_from('>I',data)[0]!=SOURCE_VT:continue
            item=struct.unpack_from('>H',data,0x76)[0];quantity=struct.unpack_from('>I',data,0x78)[0]
            handle=_u(memory,actor+0x1110);owner=_u(memory,actor+0x111C)
            expected_original=item_id if vt==item_vtable else original
            converted=donor is not None and donor.get('actor')==actor and donor.get('handle')==handle \
                and donor.get('vtable')==vt and donor.get('original_id')==original and item==item_id
            if owner or not 0<handle<0xFFFFFFFF or not 0<quantity<=32767 \
                    or item!=expected_original and not converted:continue
            volume=struct.unpack_from('>I',data,0xA0)[0]
            if not R.ptr_ok(volume) or struct.unpack_from('>I',data,0xAC)[0]!=actor:continue
            collision=memory.rd(volume,16)
            if struct.unpack_from('>3I',collision)!=(VOLUME_VT,actor,0x07000000|expected_original<<8) \
                    or collision[12]!=1:continue
            pos=struct.unpack('>3f',memory.rd(actor+0x30,12))
            if not all(math.isfinite(v) and abs(v)<1e7 for v in pos):continue
            if _u(memory,actor)!=vt or _u(memory,actor+0x1110)!=handle \
                    or _u(memory,actor+0x111C)!=0 or memory.rd(actor+0x1BC0,0xB0)!=data \
                    or memory.rd(volume,16)!=collision:continue
            out.append({'ptr':actor,'handle':handle,'id':item,'original_id':expected_original,
                'vtable':vt,'pos':pos,'count':quantity,'volume':volume,
                'evidence':'native ownerless item/cItemSetInfo/pickup volume','converted':converted})
        if _u(memory,R.S_ITEM)!=manager or _u(memory,manager+0x28)!=count \
                or _u(memory,manager+0x34)!=array or memory.rd(array,count*4)!=raw:return []
        return out
    except (ValueError,OSError,struct.error,IndexError,AttributeError):return []


def prepare_pickup(g,snap):
    """Request eggs by changing a spare-ammo source for the native constructor.

    This never grants an inventory item directly. An exact displayed pickup and
    subsequent native0x136 inventory+weapon ownership are required to finish.
    """
    cfg=state(g);p=snap.get('player') or {};mesh=snap.get('nav')
    if not cfg['on'] or (p.get('hp') or 0)<=1 or mesh is None:return None
    if any(g.rd(a,len(raw))!=raw for a,raw in NATIVE_SIGNATURES.items()):
        cfg['status']='native item construction signature differs';return None
    rows=world_items(g,cfg.get('donor'))
    ready=next((row for row in rows if row['id']==EGG_ID),None)
    if ready:return ready
    hazards=[(v['pos'],600.) for v in (snap.get('ground_mines') or {}).values()]
    options=[]
    for row in rows:
        if row['original_id'] not in AMMO_VTABLES.values() or math.dist(p['pos'],row['pos'])>1500.:continue
        route=mesh.route_avoiding_hazards(p['pos'],row['pos'],hazards)
        if not route:continue
        points=[p['pos']]+route
        # Do not send a supply detour through the currently observed crowd.
        if any((e.get('hp') or 0)>0 and any(math.dist(e['pos'],v)<350. for v in points)
               for e in snap.get('enemies') or ()):continue
        options.append((sum(math.dist(a,b) for a,b in zip(points,route)),row))
    if not options:
        cfg['status']='waiting for a safe spare-ammo pickup or fresh native egg loadout'
        return None
    row=min(options,key=lambda entry:entry[0])[1]
    if not any(v['ptr']==row['ptr'] and v['handle']==row['handle'] and v['id']==row['id']
               for v in world_items(g)):return None
    before_id=g.rd(row['ptr']+0x1C36,2);before_count=g.rd(row['ptr']+0x1C38,4)
    donor={'actor':row['ptr'],'handle':row['handle'],'vtable':row['vtable'],
        'original_id':row['id'],'before_id':before_id,'before_count':before_count}
    from . import re5_ps3 as R
    def current():
        sp=_u(g,R.S_PLAYER)
        return R.ptr_ok(sp) and _u(g,sp+0x28)==p['ptr'] and any(
            v['ptr']==row['ptr'] and v['handle']==row['handle'] and v['id']==row['id']
            for v in world_items(g))
    # The original class/pickup-volume key remains intact. Nativepickup reads
    # serialized cItemSetInfo+76, not that visual/collision class key.
    if not current() or not g.wr(row['ptr']+0x1C38,struct.pack('>I',5)):return None
    if not current():return None
    if not g.wr(row['ptr']+0x1C36,struct.pack('>H',EGG_ID)):
        if current() and g.rd(row['ptr']+0x1C38,4)==struct.pack('>I',5):g.wr(row['ptr']+0x1C38,before_count)
        return None
    cfg['donor']=donor
    cfg['status']='native egg pickup prepared; waiting for exact pickup and game-created inventory'
    return next((v for v in world_items(g,donor) if v['ptr']==row['ptr'] and v['id']==EGG_ID),None)


def pickup_request(memory,request,row,donor=None,*,item_id=EGG_ID,item_vtable=EGG_VT):
    from . import re5_ps3 as R
    if not isinstance(request,dict) or request.get('label')!=R.PICKUP_LABEL \
            or request.get('token')!='mash:square' or request.get('kind')!=R.BTN_STAGE \
            or request.get('target')!=row.get('handle') or row.get('id')!=item_id:return None
    keys=('token','button','kind','mode','label','owner','target')
    signature=tuple(request.get(k) for k in keys)
    sp=_u(memory,R.S_PLAYER)
    if not R.ptr_ok(sp) or request.get('owner')!=_u(memory,sp+0x28):return None
    current=R.selected_prompt(memory,include_item_pickups=True)
    if not current or tuple(current.get(k) for k in keys)!=signature:return None
    fresh=next((v for v in world_items(memory,donor,item_id=item_id,item_vtable=item_vtable) if all(v.get(k)==row.get(k)
                for k in ('ptr','handle','id','vtable'))),None)
    latest=R.selected_prompt(memory,include_item_pickups=True)
    return fresh if fresh and latest and tuple(latest.get(k) for k in keys)==signature else None


def inventory_item(memory,player,inventory):
    """A populated native cItem is a legal equip candidate, even before equip."""
    from . import re5_ps3 as R
    for item in inventory or ():
        if item.get('id')!=EGG_ID or item.get('rounds',0)<=0:continue
        try:
            address=player+R.P_INV+item['slot']*R.INV_SLOT
            if not 0<=item['slot']<R.INV_ALL:continue
            raw=memory.rd(address,0x30)
            if struct.unpack_from('>I',raw,8)[0]!=EGG_ID or not raw[0x2D] \
                    or struct.unpack_from('>I',raw,0x0C)[0]<=0:continue
            if memory.rd(address,0x30)==raw:
                return item
        except (ValueError,OSError,struct.error,TypeError):pass
    return None


def carried(memory,player,inventory):
    """Strictly confirm an equipped native uWp36 and its current player owner."""
    from . import re5_ps3 as R
    item=inventory_item(memory,player,[row for row in inventory or () if row.get('hand')])
    if item is None or not item.get('hand'):return None
    try:
        address=player+R.P_INV+item['slot']*R.INV_SLOT
        if _u(memory,address+0x20)!=1:return None
        weapon=_u(memory,address+0x30)
        if R.ptr_ok(weapon) and _u(memory,weapon)==EGG_VT and _u(memory,weapon+0x111C)==player \
                and _u(memory,address+8)==EGG_ID and _u(memory,address+0x20)==1 \
                and _u(memory,address+0x30)==weapon:
            return item
    except (ValueError,OSError,struct.error,TypeError):pass
    return None


def templates(g):
    from ... import re5_mods_tool as M
    from . import re5_mines
    M.verify_main_presets(g)
    re5_mines.verify_original_presets(g)
    owned=state(g).setdefault('template_records',{});count=0;verified=True
    for address,blocks in ((M.TEMPLATE,M.TEMPLATE_BLOCKS),*((a,10) for a in re5_mines.ORIGINAL_BANKS)):
        for block in range(blocks):
            base=address+block*M.TEMPLATE_BLOCK;raw=g.rd(base,M.TEMPLATE_BLOCK)
            rows=[struct.unpack_from('>11I',raw,i*M.TEMPLATE_REC) for i in range(12)]
            index=next((i for i,v in enumerate(rows) if v[0] in (EGG_ID,0x10A) and v[5]<9),None)
            occupied={v[5] for i,v in enumerate(rows) if i!=index and v[0] and v[5]<9}
            old_grid=rows[index][5] if index is not None else None
            grid=old_grid if old_grid is not None and old_grid not in occupied else next(
                (v for v in (7,0,2,4,6,8,1,3,5) if v not in occupied),None)
            if index is None:index=next((i for i,v in enumerate(rows) if v[0]==0 and v[5]<9),None)
            if index is None or grid is None:continue
            at=base+index*M.TEMPLATE_REC;before=g.rd(at,M.TEMPLATE_REC)
            after=struct.pack('>11I',EGG_ID,5,0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,grid,0,0,0,0,0)
            if at not in owned:owned[at]={'before':before,'after':after}
            else:owned[at]['after']=after
            verified=bool(g.wr(at,after)) and verified;count+=1
    return {'verified':verified,'egg_loadout_blocks':count,'effective_next_round':True}


def configure(g,on,rate=None):
    cfg=state(g);value=cfg['rate'] if rate is None else float(rate)
    if not math.isfinite(value) or not 1<=value<=MAX_RATE:raise ValueError('egg rate must be1..20')
    if g.u32(EGG_DEF)!=0x0157C4D0 or g.u32(EGG_DEF+4)!=EGG_NAME \
            or not g.rd(EGG_NAME,10).startswith(b'WP36 EGG_X'):raise ValueError('native rotten egg definition differs')
    if any(g.rd(a,len(raw))!=raw for a,raw in NATIVE_SIGNATURES.items()):
        raise ValueError('native rotten egg construction/consumption code differs')
    cfg.update(on=bool(on),rate=value)
    if on:
        cfg.setdefault('original_noammo',g.rd(EGG_DEF+0x14,4))
        ok=g.wr(EGG_DEF+0x14,struct.pack('>I',1));loadout=templates(g)
        cfg['status']='requested; waiting for game-created rotten egg and ordinary equip'
        return {'verified':bool(ok and loadout['verified']),'rotten_egg_only':True,'egg_rate_x':value,
                'native_equipped':False,**{k:v for k,v in loadout.items() if k!='verified'}}
    donor=cfg.get('donor');ok=True
    if donor:
        row=next((v for v in world_items(g,donor) if v['ptr']==donor['actor'] and v['handle']==donor['handle']),None)
        if row and row['id']==EGG_ID and row['count']==5:
            ok=bool(g.wr(row['ptr']+0x1C38,donor['before_count'])) and ok
            fresh=next((v for v in world_items(g,donor) if v['ptr']==row['ptr'] and v['handle']==row['handle']),None)
            if fresh and fresh['id']==EGG_ID:
                ok=bool(g.wr(row['ptr']+0x1C36,donor['before_id'])) and ok
    for address,record in cfg.get('template_records',{}).items():
        if g.rd(address,len(record['after']))==record['after']:ok=bool(g.wr(address,record['before'])) and ok
    if 'original_noammo' in cfg and g.rd(EGG_DEF+0x14,4)==struct.pack('>I',1):ok=bool(g.wr(EGG_DEF+0x14,cfg['original_noammo'])) and ok
    cfg.pop('donor',None);cfg['status']='disabled; ordinary weapon restore requested'
    return {'verified':ok,'rotten_egg_only':False,'egg_rate_x':value,'native_equipped':False}


def queue_supply(ad):
    """One background preparation, using a fresh native snapshot; no input-tick IO."""
    import threading
    import time
    from ... import re5_mods_tool as M
    with M._HEALTH_LOCK:
        g=M.RE5(ad);cfg=state(g);now=time.monotonic()
        if not cfg['on'] or now<cfg.get('supply_after',0.) \
                or cfg.get('supply_worker') is not None and cfg['supply_worker'].is_alive():return
        cfg['supply_after']=now+3.
        def work():
            try:
                with M._HEALTH_LOCK:
                    fresh=M.RE5(ad)
                    if not state(fresh)['on']:return
                    from . import re5_ps3 as R,re5_mines
                    snap=R.snapshot(fresh);snap['ground_mines']=re5_mines.ground_mines(fresh)
                    prepare_pickup(fresh,snap)
            except Exception as error:
                with M._HEALTH_LOCK:
                    cfg['status']='native egg supply pending: '+type(error).__name__
        cfg['supply_worker']=threading.Thread(target=work,daemon=True,name='re5-egg-supply')
        cfg['supply_worker'].start()
