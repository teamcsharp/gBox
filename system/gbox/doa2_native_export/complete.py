"""Complete native costume donor assembly from owned archives and analysis cache.

No raw fallback model, inferred actor root, gameplay acceptance or native
physics claim is introduced. The explicit neutral source pose freezes the
native components; target fighting animation remains a separate pipeline.
"""
from __future__ import annotations
import base64
import hashlib
import json
import struct
from pathlib import Path
import numpy as np

try:
    from . import native_components as C,acs_chain_vertices as V
    from . import native_cloth_cache as N,acs_cloth_grids as L
    from . import actor_attachment_frame as A,sup_seams as S
except ImportError:
    import native_components as C,acs_chain_vertices as V
    import native_cloth_cache as N,acs_cloth_grids as L
    import actor_attachment_frame as A,sup_seams as S
try:
    from gbox import doa2_bindings as B,doa2_geometry as G
except ImportError:
    import doa2_bindings as B,doa2_geometry as G

ROLES={'hip':2,'chest':0,'head':1,'l_upper':8,'l_fore':4,'l_hand':5,
       'r_upper':14,'r_fore':10,'r_hand':11,'l_thigh':6,'l_shin':7,
       'l_foot':3,'r_thigh':12,'r_shin':13,'r_foot':9}
CORE_PARENTS=[2,0,-1,7,8,4,2,6,0,13,14,10,2,12,0,1,1]
CHAIN_POSE='configured native gravity/length initialization; stage/body collision is not simulated'


def _hash(data):return hashlib.sha256(data).hexdigest()


def configured_displacements(acs_data,descriptor,world,count,parent,base_world=None):
    C._require(acs_data,descriptor+4,56,'Configured chain controls')
    values=np.array(struct.unpack_from('<14f',acs_data,descriptor+4))
    if not np.isfinite(values).all():raise ValueError('Configured chain controls must be finite')
    length,gravity=values[:2]
    if length<0:raise ValueError('Native chain length cannot be negative')
    frame=base_world if parent==15 else world[parent]
    if frame is None and count:raise ValueError('Configured actor chain lacks an authored frame')
    if not count:return np.zeros((0,3))
    current=C._affine(frame,'Configured chain frame')[:3,:3]@values[7:10]
    result=[]
    for _ in range(count):
        candidate=current.copy();candidate[1]-=gravity
        result.append(C._unit(candidate,'Configured chain direction')*length if length else np.zeros(3))
        current*=values[10]
    return np.asarray(result)


def _mark(prims,role,identity):
    for mesh_index,primitive in enumerate(prims):
        primitive['native_role']=role
        primitive['native_instance']=identity
        primitive['name']=f'{role}_{identity}_{mesh_index}_'+primitive['name']
    return prims


def _rig(profile,executable,binding,acs_data,model_count):
    if profile.get('executable_sha256',B.EXECUTABLE_SHA256)!=_hash(executable):
        raise ValueError('Source rig executable hash differs from native binding build')
    world=np.asarray(profile['world'],float).copy()
    if world.ndim!=3 or world.shape[1:]!=(4,4) or len(world)<17:
        raise ValueError('Complete native export requires 17 verified source matrices')
    world=world[:17]
    for matrix in world:C._affine(matrix,'Source neutral matrix')
    eyes=C.eye_attachments(executable,binding['render_slot'],world[1])
    for joint,matrix in eyes['world'].items():world[joint]=matrix
    wings=C.wing_attachments(acs_data,world[0],model_count=model_count)
    parents=list(CORE_PARENTS)
    if wings['world']:
        world=np.concatenate([world,np.array([wings['world'][j] for j in range(17,23)])])
        parents.extend(wings['parent'][j] for j in range(17,23))
    return world,parents,eyes,wings


def _actor_frame(acs_data,world):
    """Last active publisher in native special-controller -> held-prop order."""
    controllers=[]
    for entry in C.entries(acs_data):
        if entry['mode']==4:
            C._require(acs_data,entry['pointer'],4,'Native actor controller')
            model=struct.unpack_from('<H',acs_data,entry['pointer']+2)[0]
            controllers.append(A.source_controller_frame(acs_data,world,model))
    publishers=controllers+A.source_held_prop_frames(acs_data,world)
    return publishers[-1] if publishers else None


def _remap_actor(instance,frame):
    result=dict(instance)
    if result['parent']==15:
        if frame is None:raise ValueError('Actor instance lacks an authored source publisher')
        result['parent']=frame['parent']
        result['actor_publisher']=frame['descriptor']
    return result


def assemble_native(executable,stem,chr_data,bin_data,sup_data,acs_data,profile,
                    *,cache_directory=None,chain_displacements=None,acs_filename=None):
    """Return a complete skinned neutral donor, retaining every actual draw.

    Ordinary ACS draws occur before SUP/body draws. Mode1 directives execute
    in their native chain-list order; FFFF writes and draws get separate CHR
    snapshots. Mode2 grids then merge exact native cached records in their
    grid-list order. Native mode4 root meshes use the generated next-draw
    snapshot, explicitly recorded, rather than their initial placeholder.
    """
    binding=B.resolve_archive_binding(executable,stem+'.CHR')
    from .source_binding import native_acs
    acs_binding=native_acs(executable,binding)
    if acs_filename is not None and acs_filename.replace('\\','/').rsplit('/',1)[-1].casefold()!=acs_binding['filename'].casefold():
        raise ValueError('Supplied ACS filename differs from the verified native costume binding')
    archive=G.decode_chr(chr_data)
    world,parents,eyes,wings=_rig(profile,executable,binding,acs_data,len(archive['models']))
    directives=C.entries(acs_data)
    if any(e['mode'] not in (0,1,2,4,5,6,7,8,9,10,252,253,254) for e in directives):
        raise ValueError('Complete export encountered an unverified native controller mode')
    frame=_actor_frame(acs_data,world)
    base=None if frame is None else frame['world']
    evidence=None if frame is None else {k:v for k,v in frame.items() if k!='world'}
    chains={c['descriptor']:c for c in V.decode_chains(acs_data,chr_data)}
    grids=L.decode_grids(acs_data,chr_data)
    mapping={model:joint for joint,model in enumerate(binding['sections']['primary'])}
    mapping.update({model:15+side for side,model in enumerate(binding['sections']['extra'])})
    mapping.update(wings['models'])
    prims=[];draws=[];chain_reports=[];hidden=[];projected=[];scene_components=[]
    working=chr_data
    supplied={} if chain_displacements is None else chain_displacements
    for entry in directives:
        if entry['mode'] in (7,10):
            p=entry['pointer'];mode=entry['mode'];size=4 if mode==7 else 88
            C._require(acs_data,p,size,'Native procedural effect metadata')
            hidden.append({'descriptor':p,'mode':mode,'raw_descriptor_sha256':_hash(acs_data[p:p+size]),
                           'source_model':struct.unpack_from('<H',acs_data,p)[0],
                           'initializer':'0x8c0da9ac' if mode==7 else '0x8c0db54c',
                           'consumer':'0x8c0daa32' if mode==7 else '0x8c0db5b2',
                           'initial_particle_records':32 if mode==7 else 16,
                           'reason':'native initializer clears controller state and particle activity; procedural combat trails/emitters are not static costume parts',
                           'scope':'inactive initialized effect metadata preserved; no combat history, live particle evolution or generated effect mesh is included'})
        elif entry['mode']==6:
            p=entry['pointer'];C._require(acs_data,p,48,'Dormant native mode6 metadata')
            hidden.append({'descriptor':p,'mode':6,'raw_descriptor_sha256':_hash(acs_data[p:p+48]),
                           'reason':'native0x8c0da750 returns without draw unless control state is 2 or 3; explicit neutral control state0',
                           'scope':'combat-only blade/effect controller is preserved as source metadata, not placeholder donor geometry'})
        elif entry['mode']==8:
            p=entry['pointer'];C._require(acs_data,p,28,'Native shared-scene accessory metadata')
            scene_components.append({'descriptor':p,'mode':8,'shared_model':struct.unpack_from('<H',acs_data,p)[0],
                                     'source_owner':acs_data[p+2],'required_state':acs_data[p+3],'parent':acs_data[p+4],
                                     'raw_descriptor_sha256':_hash(acs_data[p:p+28]),
                                     'consumer':'0x8c0db028; owner IDs0x8c236299, scene state0x8c236398, external model table0x8c23d92c',
                                     'reason':'separate shared scene asset pool is not part of this costume CHR; no selected scene owners in neutral donor export'})
        elif entry['mode']==9:
            p=entry['pointer'];C._require(acs_data,p,52,'Native event controller metadata')
            hidden.append({'descriptor':p,'mode':9,'raw_descriptor_sha256':_hash(acs_data[p:p+52]),
                           'reason':'native0x8c0d91ee initializes state0; 0x8c0db0e4 draws only after an external scene event activates the controller',
                           'scope':'neutral event flags cleared; authored event-only geometry is not exported as a static body part'})

    def draw(instances,snapshot,role):
        for instance in instances:
            adjusted=_remap_actor(instance,frame)
            identity=f'{instance["descriptor"]}_{instance["link"]}'
            result=C.assemble_instances(snapshot,bin_data,[adjusted])
            prims.extend(_mark(result['prims'],role,identity))
            draws.append({'role':role,'descriptor':instance['descriptor'],'link':instance['link'],
                          'model':instance['model'],'source_parent':instance['parent'],
                          'skin_parent':adjusted['parent'],'triangles':result['report']['triangles'],
                          'snapshot_sha256':_hash(snapshot),
                          'actor_publisher':adjusted.get('actor_publisher')})
            if instance.get('native_projected_uv_flag'):
                projected.append({'descriptor':instance['descriptor'],'model':instance['model'],
                                  'role':role,'link':instance['link']})

    # Native runtime groups descriptors into separate lists, not source interleaving.
    for entry in directives:
        if entry['mode']!=0:continue
        result=C.accessory_attachments(acs_data,world,model_count=len(archive['models']),
                                      base_world=base,descriptor_offsets={entry['pointer']})
        hidden.extend(result['hidden']);draw(result['instances'],working,'held_prop')
    for entry in directives:
        if entry['mode']!=1:continue
        p=entry['pointer'];count,parent=acs_data[p:p+2]
        if parent==15 and frame is None:
            hidden.append({'descriptor':p,'mode':1,'reason':'native actor-root-valid is zero; chain update/draw is gated'})
            continue
        vectors=np.asarray(supplied[p],float) if p in supplied else configured_displacements(acs_data,p,world,count,parent,base)
        pose='caller supplied native world-chain records' if p in supplied else CHAIN_POSE
        if p in chains:
            result=V.bake_chain_positions(working,acs_data,world,{p:vectors},pose_evidence=pose,
                                         base_world=base,base_evidence=evidence,descriptor_offsets={p})
            working=result['chr_data'];chain_reports.append(result['report'])
            for instance in result['instances']:draw([instance],instance['chr_data'],'deformed_chain')
        else:
            result=C.accessory_attachments(acs_data,world,model_count=len(archive['models']),
                                          chain_displacements={p:vectors},base_world=base,descriptor_offsets={p})
            if result['unsupported']:raise ValueError('Unsupported native rigid chain draw style')
            draw(result['instances'],working,'rigid_chain')
    if grids:
        if cache_directory is None:raise ValueError('Complete source donor needs its verified native cloth cache')
        cloth=N.apply_native_cache(working,acs_data,world,original_chr=chr_data,
                                   stem=stem,cache_directory=cache_directory)
        if cloth['report']['unverified_actor_effects']:
            raise ValueError('Complete source donor has an unverified actor-root cloth effect')
        working=cloth['chr_data']
        for instance in cloth['instances']:draw([instance],instance['chr_data'],'native_cloth')
    else:cloth={'report':{'verified_native_grids':[],'unverified_actor_effects':[]}}
    core=S.assemble_core(working,sup_data,bin_data,world,mapping,S.native_coefficients(executable))
    prims.extend(_mark(core['prims'],'native_body','final'))
    shadow=set(binding['sections']['shadow'])
    emitted={p['native_model'] for p in prims}
    if emitted&shadow:raise ValueError('Source donor improperly includes a native shadow volume')
    _validate_primitives(prims,len(world))
    declared={m for values in binding['sections'].values() for m in values}
    bound_extra=set(binding['sections']['primary']+binding['sections']['extra'])
    represented={p['native_model'] for p in core['prims']}
    missing=[m for m in bound_extra-represented if any(mesh['triangles'] for mesh in archive['models'][m]['meshes'])]
    if missing:raise ValueError(f'Native bound source parts were not exported: {missing}')
    report={'format':'doa2-complete-native-source-v1','stem':stem,
            'render_slot':binding['render_slot'],'render_costume':binding['costume'],
            'source_hashes':{'executable':_hash(executable),'CHR':_hash(chr_data),'BIN':_hash(bin_data),
                             'SUP':_hash(sup_data),'ACS':_hash(acs_data)},
            'triangles':sum(len(p['tris']) for p in prims),'vertices':sum(len(p['pos']) for p in prims),
            'joints':len(world),'roles':dict(ROLES),'source_rig_provenance':profile.get('evidence',profile.get('status')),
            'native_binding':binding['sections'],'emitted_models':sorted(emitted),'shadow_models_excluded':sorted(shadow),
            'native_acs_binding':acs_binding,
            'native_draws':draws,'native_eyes':eyes['evidence'],'native_wings':wings['evidence'],
            'native_actor_frame':evidence,'native_chains':chain_reports,'native_cloth':cloth['report'],
            'native_core':core['report'],'hidden_components':hidden,
            'shared_scene_components':scene_components,
            'unemitted_models':[{'model':m,'classification':'declared non-body render component' if m in declared else 'no verified native draw role'}
                               for m in range(len(archive['models'])) if m not in emitted|shadow],
            'projected_uv_unreplayed':projected,
            'limits':{'pose':'SUP-constrained recovered neutral source; native gameplay acceptance remains separate',
                      'chain_physics':CHAIN_POSE,'chain_normals':'optional native normal arrays not reconstructed; source normals retained',
                      'cloth_physics':'original SH4 generated in explicit neutral studio (actor Y+2, no-stage floorY1), frozen under original parent',
                      'mode4_draw':'actor-root mesh uses generated next-draw cloth snapshot; initial placeholder omitted',
                      'seam_skin':'sample/16 two-joint skin approximation, not the arbitrary-pose native curved seam solver',
                      'projected_uv':'native high-bit projected UV requires view-dependent renderer; original UV retained and flagged',
                      'scene_props':'separate shared scene asset pool is recorded as metadata; selected scene owners and external scene assets are not part of a costume donor',
                      'procedural_effects':'native combat trails/emitters retained as source metadata in their inactive initialized state; no live effect meshes or combat history',
                      'animations':'no native ACS physics/animation clip is bundled in this source donor'},
            'assembly_order':'special attachments/held props -> ordered chain writes/immediate draws -> ordered native cloth -> SUP -> primary/eyes',
            'complete_source_components':True,'gameplay_verified':False}
    return {'prims':prims,'baked_chr':core['baked_chr'],'world':world,'parent':parents,
            'profile':{**profile,'world':world.tolist(),'parent':parents,'roles':dict(ROLES)},'report':report}


def _validate_primitives(prims,joint_count):
    if not prims:raise ValueError('Complete source donor contains no geometry')
    names=set()
    for primitive in prims:
        if primitive['name'] in names:raise ValueError('Native draw instance primitive identity is duplicated')
        names.add(primitive['name']);count=len(primitive['pos'])
        for key,width in (('pos',3),('nrm',3),('uv',2),('J',4),('W',4)):
            value=np.asarray(primitive[key])
            if value.shape!=(count,width) or not np.isfinite(value).all():raise ValueError(f'Invalid source primitive {key}')
        if np.any(primitive['J']<0) or np.any(primitive['J']>=joint_count):raise ValueError('Source skin joint outside rig')
        if np.any(primitive['W']<0) or not np.allclose(np.sum(primitive['W'],axis=1),1):raise ValueError('Source skin weights invalid')
        triangles=np.asarray(primitive['tris'])
        if triangles.ndim!=2 or triangles.shape[1]!=3 or np.any(triangles<0) or np.any(triangles>=count):
            raise ValueError('Source triangle index outside vertex buffer')


def write_complete(path,result,name=None):
    """Self-contained GLTF with exact authored joint matrices/inverse binds."""
    from gbox.melee_models import write_gltf
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    world=result['world'];parents=result['parent'];count=len(world)
    names={v:k for k,v in ROLES.items()};names.update({15:'eye_left',16:'eye_right'})
    joints=[{'parent':parents[j],'world':world[j]} for j in range(count)]
    write_gltf(path,joints,result['prims'],1,name or result['report']['stem'],
               [names.get(j,f'wing_{j-17}') for j in range(count)],result['report'])
    gl=json.loads(path.read_text(encoding='utf-8'))
    for j in range(count):
        node=gl['nodes'][j];node.pop('translation',None)
        local=np.linalg.inv(world[parents[j]])@world[j] if parents[j]>=0 else world[j]
        node['matrix']=local.T.reshape(-1).tolist()
    accessor=gl['accessors'][gl['skins'][0]['inverseBindMatrices']]
    view=gl['bufferViews'][accessor['bufferView']]
    offset=view.get('byteOffset',0)+accessor.get('byteOffset',0)
    blob=bytearray(base64.b64decode(gl['buffers'][0]['uri'].split(',',1)[1]))
    inverse=np.asarray([np.linalg.inv(matrix).T.reshape(16) for matrix in world],np.float32)
    blob[offset:offset+inverse.nbytes]=inverse.tobytes()
    gl['buffers'][0]['uri']='data:application/octet-stream;base64,'+base64.b64encode(blob).decode()
    for material,primitive in zip(gl['materials'],result['prims']):
        tex=primitive['tex']
        if tex is not None and np.any((tex[...,3]!=0)&(tex[...,3]!=255)):material['alphaMode']='BLEND'
    gl['asset']['generator']='gBox native DOA2 complete source export'
    path.write_text(json.dumps(gl,separators=(',',':')),encoding='utf-8')
    return path
