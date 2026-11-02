from pso_owned_evidence import original_test_path, owned_dol_read
import hashlib
import json
import math
from pathlib import Path
import struct

import pytest
from gbox import pso_coop_geometry as G, psomap
from gbox.pso_coop_nav import RoomMap

ROOT=original_test_path('forest2-coverage/test_forest2.py').resolve().parent
RECEIPT=json.loads((ROOT/'source-receipt-1793629926152574700.json').read_text())


def captured_layout(name, base=0x81000000):
    path='Scene/'+name
    raw=(ROOT/'sources'/name).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==RECEIPT['expected'][path]['file_sha256']
    # Keep the exact disc allocation and convert only parser-addressed pointer
    # fields, constructing a native-memory fixture; this is not a live capture.
    data=bytearray(raw)
    root=psomap.rel_root(raw)
    cursor=struct.unpack_from('>I',raw,root)[0]
    struct.pack_into('>I',data,root,base+cursor)
    entries=[]
    while (mesh:=struct.unpack_from('>I',raw,cursor)[0]):
        entries.append(base+cursor)
        nv,vp,nf,fp=struct.unpack_from('>4I',raw,mesh)
        struct.pack_into('>I',data,cursor,base+mesh)
        struct.pack_into('>4I',data,mesh,nv,base+vp,nf,base+fp)
        cursor+=24
        assert len(entries)<=G.MAX_MESHES
    table=struct.pack('>'+str(len(entries)+1)+'I',*entries,0)
    manager=0x80DA2BA0
    regions={base:bytes(data),manager+0x1c:table+bytes((G.MAX_MESHES+1)*4-len(table)),
             0x8007A728:bytes.fromhex('806db0504e800020')}
    for addr,value in zip(G.ROOTS,(base+root,base,len(data),manager)):regions[addr]=struct.pack('>I',value)
    for addr,value in zip((0x804FE120,0x805D6060,0x805D5FC0,0x805D49B8),(14,0,2,0)):regions[addr]=struct.pack('>I',value)
    regions[0x8050EA10]=struct.pack('>2I',0x80DA1000,0x80DA2000)
    regions[0x80513920+24]=struct.pack('>3I',2,0,3)
    regions[0x805D5FC4]=struct.pack('>2I',2,0)
    for addr,code in G.FLOOR_CODE:regions[addr]=code
    for addr,size,_ in G.PLAYER_FLOOR_CODE:regions[addr]=owned_dol_read(addr,size)
    class Memory:
        reads=0
        callback=None
        def read_memory(self,address,length):
            self.reads+=1
            if self.callback:self.callback(address,length)
            for start,blob in regions.items():
                if start<=address and address+length<=start+len(blob):return blob[address-start:address-start+length]
            raise OSError('Unexpected read')
    return Memory(),regions,base,table


def state():
    return {'verified':True,'phase':14,'travelling':False,'episode':1,'floor':2,'entities':[],
            'players':{s:{'ptr':f'{0x80DA0000+s*4096:08X}','x':0.,'y':0.,'z':0.,'room':1} for s in (1,2)}}


@pytest.mark.parametrize('name',['map_forest02c.rel','map_aforest02c.rel'])
def test_exact_disc_relocation_and_native_capture_match_catalog(name):
    ad,regions,base,table=captured_layout(name)
    triangles,digest=G.parse_loaded(base,regions[base],table)
    assert triangles==psomap.collision((ROOT/'sources'/name).read_bytes())
    expected=RECEIPT['expected']['Scene/'+name]
    assert digest==expected['geometry_sha256'] and len(triangles)==expected['triangles']
    provider=G.Provider(ad);first=provider.snapshot(state())
    assert first['geometry_verified'] and first['geometry_source']['path']=='Scene/'+name
    assert first['geometry_refreshed']
    calls=ad.reads;second=provider.snapshot(state())
    assert second['geometry_verified'] and not second['geometry_refreshed'] and ad.reads>calls
    assert len(regions[base])<G.MAX_BYTES


@pytest.mark.parametrize('name',['map_forest02c.rel','map_aforest02c.rel'])
def test_actual_geometry_raster_and_route_fit_existing_budgets(name):
    atlas=G.Atlas(psomap.collision((ROOT/'sources'/name).read_bytes()))
    view=None
    for cell in sorted(atlas.heights)[::100]:
        x,z=atlas.center(cell)
        view=atlas.project({'x':x,'y':atlas.heights[cell][0],'z':z})
        if view:break
    assert view and len(atlas.heights)<=G.MAX_CELLS
    nav=RoomMap(**view['collision_grid'])
    start=next(iter(view['_heights']));end=next(c for c in view['_heights'] if math.dist(c,start)>5)
    assert nav.route(atlas.center(start),atlas.center(end))


@pytest.mark.parametrize('change',['episode','floor','map_index','variant','selected_map','selected_variant','accessor','selector','digest','unknown_boss'])
def test_new_layout_requires_every_live_binding(change):
    ad,regions,base,_=captured_layout('map_forest02c.rel');s=state()
    if change=='episode':s['episode']=2
    elif change=='floor':s['floor']=1
    elif change in ('map_index','variant'):regions[0x80513920+24]=struct.pack('>3I',3 if change=='map_index' else 2,1 if change=='variant' else 0,3)
    elif change in ('selected_map','selected_variant'):regions[0x805D5FC4]=struct.pack('>2I',3 if change=='selected_map' else 2,1 if change=='selected_variant' else 0)
    elif change in ('accessor','selector'):
        addr=G.FLOOR_CODE[change=='selector'][0];regions[addr]=bytes(len(regions[addr]))
    elif change=='digest':
        blob=bytearray(regions[base]);blob[0]^=1;regions[base]=bytes(blob)
    else:s['floor']=11
    assert not G.Provider(ad).snapshot(s)['geometry_verified']


def test_floor_record_change_mid_capture_rejects_cached_and_new_reads():
    ad,regions,base,_=captured_layout('map_forest02c.rel');provider=G.Provider(ad)
    assert provider.snapshot(state())['geometry_verified']
    def mutate(address,length):
        if address==base:regions[0x80513920+24]=struct.pack('>3I',2,0,4)
    ad.callback=mutate
    assert not provider.snapshot(state())['geometry_verified'] and provider.atlas is None


def test_relocation_changes_raw_fingerprint_not_canonical_geometry():
    values=[]
    for base in (0x81000000,0x81200000):
        ad,_,_,_=captured_layout('map_forest02c.rel',base)
        values.append(G.Provider(ad).snapshot(state()))
    assert all(x['geometry_verified'] for x in values)
    assert values[0]['geometry_identity']==values[1]['geometry_identity']
    assert values[0]['geometry_loaded_fingerprint']!=values[1]['geometry_loaded_fingerprint']
