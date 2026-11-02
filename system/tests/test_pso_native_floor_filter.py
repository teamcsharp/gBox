import hashlib,json,math,struct
from types import SimpleNamespace
from pso_owned_evidence import original_test_path, owned_dol_read
from pathlib import Path
import pytest
from gbox import pso_coop_geometry as G
from gbox.pso_coop_nav import RoomMap,room_key
from test_pso_geometry import plane,player,state,fixture_memory,allow

ROOT=original_test_path('native-floor-filter/test_native_floor_filter.py').parent
D=SimpleNamespace(read=owned_dol_read)
POSITIONS=[(479.5273742675781,29.970409393310547,-60.747215270996094),
 (463.2242126464844,28.565731048583984,-67.22724914550781),
 (550.008,32.928,-15.904),(531.607,32.122,-28.214),(548.877,32.774,-22.134),
 (531.718,33.387,-22.392),(513.428,31.377,-44.747)]

@pytest.fixture(scope='module')
def forest():
    return json.loads((ROOT.parent/'observer-v1/field-geometry-receipt-1793622503722814000.json').read_text())['result']['triangles']

def memory(triangles):
    ad,regions,base,table=fixture_memory(triangles, owned_code=True)
    for address,size,digest in G.PLAYER_FLOOR_CODE:
        regions[address]=D.read(address,size)
        assert hashlib.sha256(regions[address]).hexdigest()==digest
    return ad,regions,base,table

@pytest.mark.parametrize('flags,expected',[(0,False),(1,True),(0x40,True),(0x41,True),
 (2,False),(4,False),(8,False),(0x10,False),(0x100,False),(0x101,True),
 (0x104,False),(0x105,True),(0x144,True),(0x8001,False)])
def test_positive_main_floor_bits_and_mixed_auxiliary_flags(flags,expected):
    triangles=[(*t[:3],flags,t[4]) for t in plane()]
    atlas=G.Atlas(triangles);local=G.LocalConnectors(atlas)
    assert bool(atlas.project(player())) is expected
    assert (local._point_height((22.25,22.5)) is not None) is expected
    assert bool(G._player_floor(flags,(0,1,0))) is expected

def test_genuine_stacked_main_floors_stay_separate_and_ambiguous_feet_refuse():
    atlas=G.Atlas(plane()+plane(y=30))
    assert atlas.project(player())['geometry_layer']!=atlas.project(player(y=30))['geometry_layer']
    close=G.LocalConnectors(G.Atlas(plane()+plane(y=.01)))
    assert close._native_surface(player(x=22.25),'ambiguous') is None

def test_auxiliary_plane_never_enters_fine_floor_or_native_component():
    triangles=plane()+[(*t[:3],0x104,t[4]) for t in plane(y=1.2)]
    atlas=G.Atlas(triangles);local=G.LocalConnectors(atlas);p=player(x=22.25)
    proof=local._native_surface(p,'main')
    assert proof and proof['surface_triangles']==[0,1]
    assert all(h==0 for h in proof['path_heights'])
    view=local._local((22.25,22.5),0)
    assert len(view['floors'])==2 and set(view['base'].values())=={0}

def test_flagless_wall_still_blocks_normal_and_local_route():
    wall=[((30,0,0),(30,20,0),(30,20,100),0,(1,0,0)),
          ((30,0,0),(30,20,100),(30,0,100),0,(1,0,0))]
    atlas=G.Atlas(plane()+wall);view=atlas.project(player(x=17.5))
    assert RoomMap(**view['collision_grid']).route((17.5,22.5),(42.5,22.5)) is None
    local=G.LocalConnectors(atlas);fine=local._local((29.25,22.5),0)
    assert fine is None or not local.clear((29.25,22.5),(31.25,22.5),0,0,fine)

@pytest.mark.parametrize('xyz',POSITIONS)
def test_original_spawn_and_all_held_points_now_have_normal_main_floor(forest,xyz):
    atlas=G.Atlas(forest);p=player(x=xyz[0],y=xyz[1],z=xyz[2]);view=atlas.project(p)
    assert view and view['geometry_layer']=='3574e623f76944e6786c8c2acc28f6385ffd13f632d95529bd42c4fd5c01d5b9'
    nav=RoomMap(**view['collision_grid'])
    assert nav.route((p['x'],p['z']),(512.5,-192.5))
    assert nav.route((p['x'],p['z']),(463.2242126464844,-67.22724914550781))
    # Prior v3 expected a reduced-clearance escape because it counted0x104 as
    # floor. This exact build's native player query excludes that auxiliary
    # result from actor foot height, so normal projection is now correct.
    assert len(atlas.heights[atlas.cell(p)])==1

def current_provider(forest):
    ad,regions,base,table=memory(forest);s=state()
    for slot,xyz in enumerate(POSITIONS[:2],1):
        s['players'][slot].update(x=xyz[0],y=xyz[1],z=xyz[2])
    return G.Provider(ad),ad,regions,s

def test_current_both_provider_normal_routes_freshness_and_wall_key(forest):
    provider,ad,regions,s=current_provider(forest)
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert set(first['geometry_players'])=={1,2} and not first['geometry_recovery_players']
    assert first['geometry_source']['triangles_sha256']=='2f1c7a9652eebdf1fc62add0416c4a0f56adc9e4607194a9f48106367ec289a1'
    for slot in (1,2):
        st=dict(s,geometry_players=first['geometry_players'])
        old=dict(first['geometry_players'][slot],geometry_layer='a2608a43913f2dc59ee91006840962d3fb00f85bb501028651dccc38d4df9607')
        assert room_key(st,s['players'][slot])!=room_key(dict(st,geometry_players={slot:old}),s['players'][slot])
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_players']==first['geometry_players']

@pytest.mark.parametrize('index',range(3))
def test_exact_code_guard_rejects_changed_query_wrapper_or_player_consumer(forest,index):
    provider,ad,regions,s=current_provider(forest)
    assert provider.snapshot(s)['geometry_verified']
    address,_,_=G.PLAYER_FLOOR_CODE[index]
    regions[address]=bytes(len(regions[address]))
    assert provider.snapshot(s)=={'geometry_verified':False,'geometry_diagnostic':'Native player floor query code changed'}
    assert provider.atlas is None

def test_code_change_during_projection_refuses_and_clears_cached_view(forest,monkeypatch):
    provider,ad,regions,s=current_provider(forest);original=G.Atlas.project
    def mutate(self,p):
        result=original(self,p)
        address=G.PLAYER_FLOOR_CODE[2][0];regions[address]=bytes(len(regions[address]))
        return result
    monkeypatch.setattr(G.Atlas,'project',mutate)
    assert not provider.snapshot(s)['geometry_verified'] and provider.atlas is None

def test_code_guard_missing_read_fails_closed(forest):
    provider,ad,regions,s=current_provider(forest)
    del regions[G.PLAYER_FLOOR_CODE[0][0]]
    assert not provider.snapshot(s)['geometry_verified']

def test_query_guard_bytes_and_effective_mask_are_exact_owned_build():
    assert G.PLAYER_FLOOR_MASK==0x5f&0xffffffe1==0x41
    assert D.read(0x801b79a0,4)==bytes.fromhex('38a0005f')
    assert D.read(0x8007925c,4)==bytes.fromhex('565b07f4')
    assert D.read(0x801b7a9c,8)==bytes.fromhex('c0040004d01d003c')
    assert sum(size for _,size,_ in G.PLAYER_FLOOR_CODE)*2==3040
