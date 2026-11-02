from pso_owned_evidence import original_test_path
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from gbox import pso_coop_geometry as G
from gbox.pso_coop_nav import Maps, RoomMap, geometry_view, room_key

BASE = original_test_path('native-geometry/test_geometry.py').resolve().parent


def plane(x0=0, x1=100, z0=0, z1=100, y=0, slope=0):
    a, b, c, d = ((x0, y, z0), (x1, y + slope * (x1-x0), z0),
                  (x1, y + slope * (x1-x0), z1), (x0, y, z1))
    normal = (-slope / math.sqrt(1+slope*slope), 1 / math.sqrt(1+slope*slope), 0)
    return [(a, b, c, 257, normal), (a, c, d, 257, normal)]


def player(x=22.5, y=0, z=22.5, slot=1):
    return {'x': x, 'y': y, 'z': z, 'ptr': f'{0x80DA0000 + slot*4096:08X}', 'controller': slot, 'room': 16}


def state():
    return {'verified': True, 'phase': 14, 'travelling': False, 'episode': 1, 'floor': 1,
            'players': {1: player(), 2: player(slot=2)}, 'entities': []}


def fixture_memory(triangles):
    base, entry, mesh, vp = 0x81000000, 0x81000010, 0x81000040, 0x81000100
    vb = b''.join(struct.pack('>3f', *v) for t in triangles for v in t[:3])
    fp = vp + len(vb)
    fb = b''.join(struct.pack('>4H3f16x', i*3, i*3+1, i*3+2, t[3], *t[4]) for i, t in enumerate(triangles))
    blob = bytearray(0x100 + len(vb) + len(fb))
    struct.pack_into('>I4fI', blob, 0x10, mesh, 0, 0, 0, 100, 0)
    struct.pack_into('>4I', blob, 0x40, len(triangles)*3, vp, len(triangles), fp)
    blob[0x100:0x100+len(vb)] = vb
    blob[fp-base:] = fb
    manager = 0x80DA2BA0
    table = struct.pack('>I', entry) + bytes(G.MAX_MESHES * 4)
    regions = {base: bytes(blob), manager+0x1c: table,
               0x8007A728: bytes.fromhex('806db0504e800020')}
    for address, value in zip(G.ROOTS, (entry, base, len(blob), manager)):
        regions[address] = struct.pack('>I', value)
    for address, value in zip((0x804FE120,0x805D6060,0x805D5FC0,0x805D49B8), (14,0,1,0)):
        regions[address] = struct.pack('>I', value)
    regions[0x8050EA10] = struct.pack('>2I', 0x80DA1000, 0x80DA2000)
    class Memory:
        reads = 0
        callback = None
        def read_memory(self, address, length):
            self.reads += 1
            if self.callback:
                self.callback(address, length)
            for start, data in regions.items():
                if start <= address and address + length <= start + len(data):
                    return data[address-start:address-start+length]
            raise OSError(f'Unexpected read {address:x}/{length}')
    return Memory(), regions, base, table


def allow(monkeypatch, triangles):
    h = hashlib.sha256()
    for a,b,c,f,n in triangles:
        h.update(struct.pack('>12fH', *a,*b,*c,*n,f))
    monkeypatch.setitem(G.KNOWN, (1,1,h.hexdigest()), 'synthetic-test-only')


def test_bridge_keeps_both_layers_and_player_specific_grids(tmp_path):
    atlas = G.Atlas(plane() + plane(y=30))
    low, high = atlas.project(player()), atlas.project(player(y=30, slot=2))
    assert low['geometry_layer'] != high['geometry_layer']
    assert set(low['_heights'].values()) == {0}
    assert set(high['_heights'].values()) == {30}
    st = state()
    st['players'][2]['y'] = 30
    st['geometry_players'] = {1: dict(low, geometry_identity='same-layout'), 2: dict(high, geometry_identity='same-layout')}
    assert room_key(st, st['players'][1]) != room_key(st, st['players'][2])
    maps = Maps(tmp_path)
    assert set(maps.get(st, st['players'][1]).heights.values()) == {0}
    assert set(maps.get(st, st['players'][2]).heights.values()) == {30}


def test_missing_player_layer_does_not_borrow_other_grid():
    st = state(); st.update(geometry_players={1: {'geometry_layer':'low'}}, geometry_layer='global')
    assert geometry_view(st, st['players'][2]) == {}


def test_ramp_connects_without_height_band_flattening():
    a = G.Atlas(plane(slope=.2))
    v = a.project(player(y=4.5))
    m = RoomMap(**v['collision_grid'])
    assert m.route((22.5,22.5), (82.5,22.5))
    assert m.heights[(16,4)] > m.heights[(4,4)]


def test_cliff_and_height_discontinuity_are_blocked():
    a = G.Atlas(plane(x1=50) + plane(x0=50,y=25))
    v = a.project(player())
    assert RoomMap(**v['collision_grid']).route((22.5,22.5), (82.5,22.5)) is None
    m = RoomMap(size=5, floor=[(0,0),(1,0)], heights=[(0,0,0),(1,0,25)])
    assert not m.allowed((0,0),(1,0))
    corner=RoomMap(size=5,floor=[(0,0),(1,0),(0,1),(1,1)],
                   heights=[(0,0,0),(1,0,0),(0,1,0),(1,1,6)])
    assert not corner.allowed((0,0),(1,1))


def test_wall_below_bridge_does_not_block_upper_layer():
    wall = [((50,0,0),(50,18,0),(50,18,100),2336,(1,0,0)),
            ((50,0,0),(50,18,100),(50,0,100),2336,(1,0,0))]
    a = G.Atlas(plane()+plane(y=30)+wall)
    low, high = a.project(player()), a.project(player(y=30))
    assert RoomMap(**low['collision_grid']).route((22.5,22.5),(82.5,22.5)) is None
    assert RoomMap(**high['collision_grid']).route((22.5,22.5),(82.5,22.5))


def test_trigger_volume_not_a_solid_wall():
    trigger = ((50,0,0),(50,100,0),(50,100,100),32768,(1,0,0))
    a = G.Atlas(plane()+[trigger])
    assert RoomMap(**a.project(player())['collision_grid']).route((22.5,22.5),(82.5,22.5))


def test_falling_and_edge_player_return_no_projection():
    a = G.Atlas(plane())
    assert a.project(player(y=15)) is None
    assert a.project(player(x=2.5)) is None


def test_cached_projection_reused_only_on_same_height():
    a = G.Atlas(plane()+plane(y=30))
    low = a.project(player())
    assert a.project(player(x=32.5)) is low
    assert a.project(player(y=30)) is not low


def test_provider_exact_loaded_bytes_cache_and_area_binding(monkeypatch):
    triangles = plane(); allow(monkeypatch, triangles)
    ad, regions, _, _ = fixture_memory(triangles)
    p = G.Provider(ad); first = p.snapshot(state()); atlas = p.atlas
    assert first['geometry_verified'] and first['geometry_refreshed']
    second = p.snapshot(state())
    assert second['geometry_verified'] and not second['geometry_refreshed'] and p.atlas is atlas
    regions[0x805D5FC0] = struct.pack('>I',2)
    assert not p.snapshot(state())['geometry_verified'] and p.atlas is None


@pytest.mark.parametrize('change', ['code','actor','manager','allocation','vertex','unknown_area','unverified','transition'])
def test_provider_rejects_untrusted_inputs(monkeypatch, change):
    triangles = plane(); allow(monkeypatch, triangles)
    ad, regions, base, _ = fixture_memory(triangles); st = state()
    if change=='code': regions[0x8007A728] = bytes(8)
    if change=='actor': regions[0x8050EA10] = struct.pack('>2I',0x80DA1000,0x80DA1000)
    if change=='manager': regions[0x805D5650] = struct.pack('>I',0)
    if change=='allocation': regions[0x805D6014] = struct.pack('>I',G.MAX_BYTES+4)
    if change=='vertex':
        blob=bytearray(regions[base]);struct.pack_into('>f',blob,0x100,float('nan'));regions[base]=bytes(blob)
    if change=='unknown_area': st['episode']=2
    if change=='unverified': st['verified']=False
    if change=='transition': st['travelling']=True
    assert G.Provider(ad).snapshot(st)['geometry_verified'] is False


def test_same_pointer_reused_changed_geometry_rejected(monkeypatch):
    triangles=plane();allow(monkeypatch,triangles)
    ad,regions,base,_=fixture_memory(triangles);p=G.Provider(ad)
    assert p.snapshot(state())['geometry_verified']
    b=bytearray(regions[base]);struct.pack_into('>f',b,0x100,3);regions[base]=bytes(b)
    assert not p.snapshot(state())['geometry_verified'] and p.atlas is None


def test_relocated_same_layout_keeps_persistent_identity_but_invalidates_cache(monkeypatch):
    triangles=plane();allow(monkeypatch,triangles)
    ad,regions,base,table=fixture_memory(triangles);p=G.Provider(ad)
    first=p.snapshot(state());atlas=p.atlas
    offset=0x100000
    blob=bytearray(regions.pop(base))
    for pos in (0x10,0x44,0x4c):
        struct.pack_into('>I',blob,pos,struct.unpack_from('>I',blob,pos)[0]+offset)
    regions[base+offset]=bytes(blob)
    regions[0x805D6000]=struct.pack('>I',base+offset)
    regions[0x805D4E68]=struct.pack('>I',base+offset+16)
    regions[0x80DA2BA0+0x1c]=struct.pack('>I',base+offset+16)+table[4:]
    second=p.snapshot(state())
    assert second['geometry_verified'] and p.atlas is not atlas
    assert first['geometry_loaded_fingerprint']!=second['geometry_loaded_fingerprint']
    assert first['geometry_identity']==second['geometry_identity']
    assert first['geometry_players'][1]['geometry_layer']==second['geometry_players'][1]['geometry_layer']


def test_proven_layout_wall_memory_survives_destroyed_container(tmp_path):
    st=state();p=st['players'][1]
    st['entities']=[{'kind':'object','class':'TObjContainerItem','room':16,'x':30.,'y':0.,'z':30.}]
    unknown=room_key(st,p)[0]
    st['geometry_players']={1:{'geometry_identity':'canonical','geometry_layer':'ground','collision_grid':{'size':5,'floor':[[4,4],[5,4]],'walls':[]}}}
    first=room_key(st,p)[0];maps=Maps(tmp_path);nav=maps.get(st,p);nav.blocked.add(((4,4),(5,4)));nav.save()
    st['entities']=[]
    assert room_key(st,p)[0]==first
    assert ((4,4),(5,4)) in Maps(tmp_path).get(st,p).blocked
    del st['geometry_players']
    assert room_key(st,p)[0]!=unknown


def test_area_change_during_read_rejected(monkeypatch):
    triangles=plane();allow(monkeypatch,triangles)
    ad,regions,base,_=fixture_memory(triangles)
    def swap(address,length):
        if address==base: regions[0x805D49B8]=struct.pack('>I',1)
    ad.callback=swap
    assert not G.Provider(ad).snapshot(state())['geometry_verified']


def test_unknown_exact_hash_produces_no_grid():
    ad,_,_,_=fixture_memory(plane())
    result=G.Provider(ad).snapshot(state())
    assert not result['geometry_verified'] and 'geometry_players' not in result


@pytest.mark.parametrize('kind',['out_of_allocation','unterminated','duplicate','face_index'])
def test_malformed_native_mesh_rejected(kind):
    _,regions,base,table=fixture_memory(plane())
    blob=bytearray(regions[base])
    if kind=='out_of_allocation':struct.pack_into('>I',blob,0x44,base-4)
    if kind=='unterminated':table=struct.pack('>257I',*([base+16]*257))
    if kind=='duplicate':table=struct.pack('>3I',base+16,base+16,0)
    if kind=='face_index':
        fp=struct.unpack_from('>I',blob,0x4c)[0];struct.pack_into('>H',blob,fp-base,65000)
    with pytest.raises(ValueError):G.parse_loaded(base,bytes(blob),table)


@pytest.mark.parametrize('name', ['field-geometry-receipt-1793622503722814000.json', 'field-geometry-receipt-1793622319731800300.json'])
def test_real_exact_loaded_layout_and_route(name):
    r=json.loads((BASE.parent/'observer-v1'/name).read_text())['result']
    ad,regions,base,table=fixture_memory(r['triangles'])
    triangles,digest=G.parse_loaded(base,regions[base],table)
    assert digest==r['geometry_sha256'] and (r['state']['episode'],r['state']['floor'],digest) in G.KNOWN
    a=G.Atlas(triangles)
    if r['state']['floor']==1:
        layers=[]
        for p in r['state']['players'].values():
            view=a.project(p);assert view
            layers.append(view['geometry_layer'])
            m=RoomMap(**view['collision_grid'])
            route=m.route((p['x'],p['z']),(230,510))
            assert route and len(route)<100
            for first,second in zip(route,route[1:]):assert m.allowed(m.cell(first),m.cell(second))
        # A controller restarted farther down this real corridor must load the
        # same saved wall map even when native allocations and seed cells differ.
        advanced=player(x=317.5,y=23.25,z=547.5)
        restarted=G.Atlas(triangles).project(advanced)
        assert restarted and restarted['geometry_layer']==layers[0]


def test_raster_work_budget_rejects_giant_triangle():
    with pytest.raises(ValueError):G.Atlas(plane(x1=90000,z1=90000))


@pytest.mark.parametrize('keeps_changing', [False, True])
def test_reader_reobserves_positions_and_context_after_new_raster(monkeypatch, keeps_changing):
    from gbox import pso_coop as C
    current=state();calls=[]
    for slot,p in current['players'].items():
        p.update(kind='player', **{'class':'TObjPlayer','entity_id':slot-1})
    current['entities']=list(current['players'].values())
    def native(_):
        calls.append('native')
        result=copy.deepcopy(current)
        for p in result['entities']:p['x'] += 30 * len(calls)
        return result
    monkeypatch.setattr(C.solo.Reader,'snapshot',native)
    monkeypatch.setattr(C,'native_context',lambda _: {'fresh_context_read':len(calls)})
    class Geometry:
        def snapshot(self, observed):
            return {'geometry_verified':True,'geometry_refreshed':keeps_changing or len(calls)==1}
    reader=C.Reader.__new__(C.Reader)
    reader.ad=SimpleNamespace(read_memory=lambda a,n:struct.pack('>2I',0x80DA1000,0x80DA2000))
    reader.gc=SimpleNamespace(ptr=lambda *a:None,u32=lambda a:C.VT_UPDATE-12)
    reader.geometry=Geometry()
    result=reader.snapshot()
    assert len(calls)==2
    if keeps_changing:
        assert result['verified'] is False
    else:
        assert result['verified'] is True and result['players'][1]['x']==82.5
        assert result['fresh_context_read']==2
