"""Native SUP-constrained neutral rig candidates, requiring visual acceptance.

Rest vectors describe physical joint displacement in the neutral body frame.
They must not be rotated by the CHR part's own mesh basis. The native SUP seam
axis relation provides the independent mesh-coordinate rotation constraints.
"""
import struct
import numpy as np
from . import doa2_bindings, doa2_geometry
from .doa2_rest import extract_rest_vectors, EXPECTED_SHA256
from .doa2_axes import solve

PARENT = [2,0,-1,7,8,4,2,6,0,13,14,10,2,12,0,1,1]
ROLES = {'hip':2,'chest':0,'head':1,'l_upper':8,'l_fore':4,'l_hand':5,
         'r_upper':14,'r_fore':10,'r_hand':11,'l_thigh':6,'l_shin':7,
         'l_foot':3,'r_thigh':12,'r_shin':13,'r_foot':9}
IDENTITY=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]

def matmul(a,b):
    return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

def bases_from_sup(audit:dict)->dict:
    result = solve(audit['records'])
    bases = {int(j): matrix for j, matrix in result['rotations'].items()}
    # Eye parts have independent gaze, with neutral basis inherited from head1.
    bases[15]=bases[16]=IDENTITY
    return bases


def collect_axes(disc) -> dict:
    """Recover the shared neutral-coordinate constraints from owned seams."""
    from .doa2_chars import roster
    from .doa2_morphs import inspect_sup
    records = []
    for family in roster(disc.files):
        for costume in family['costumes']:
            name = f"DOA2/{family['key']}{costume.zfill(2)}.SUP"
            if name not in disc.files:
                continue
            data = disc.read(name)
            for seam in inspect_sup(data)['seams']:
                vectors = np.asarray(struct.unpack_from('<18f', data, seam['data_offset'])).reshape(3, 2, 3)
                records.append({'name': name, **seam, 'a_columns': vectors[:, 0].T.tolist(),
                                'b_columns': vectors[:, 1].T.tolist()})
    # The graph must be complete and consistent before any profile is returned.
    solve(records)
    return {'records': records}


def for_archive(disc, archive_name: str, audit: dict | None = None) -> dict:
    """Resolve the actual native fighter/costume before constructing its rig."""
    from pathlib import PurePosixPath
    executable = disc.read('1ST_READ.BIN')
    binding = doa2_bindings.resolve_archive_binding(executable, archive_name)
    stem = PurePosixPath(archive_name).stem
    profile = build_profile(executable, disc.read(archive_name), slot=binding['render_slot'],
                         costume=binding['costume'], fighter=stem[:-2], costume_name=stem[-2:],
                         audit=audit if audit is not None else collect_axes(disc))
    from . import doa2_components as C
    eyes = C.eye_attachments(executable, binding['render_slot'], profile['world'][1])
    for joint, matrix in eyes['world'].items(): profile['world'][joint] = matrix.tolist()
    profile['component_models'] = {model: joint for joint, model in profile['emit_models'].items()}
    profile['evidence']['eyes'] = eyes['evidence']
    from .doa2_native_export.source_binding import owned_path
    native_acs = doa2_bindings.accessory_filename(executable, binding['render_slot'], binding['costume'])
    acs_name = owned_path(disc, native_acs['filename'])
    profile['evidence']['native_acs_binding'] = native_acs
    if acs_name:
        wings = C.wing_attachments(disc.read(acs_name), profile['world'][0],
                                  model_count=len(doa2_geometry.decode_chr(disc.read(archive_name))['models']))
        if wings['world']:
            for joint in range(17,23):
                profile['world'].append(wings['world'][joint].tolist())
                profile['parent'].append(wings['parent'][joint])
            profile['component_models'].update(wings['models'])
            profile['evidence']['wings'] = wings['evidence']
    return profile

def build_profile(executable:bytes, chr_data:bytes, *, slot:int, costume:int,
                  fighter:str, costume_name:str, audit:dict)->dict:
    rest=extract_rest_vectors(executable)['profiles'][slot]
    if not rest['rest_address']:raise ValueError('No native rest profile for slot')
    vectors=rest['local_translations'];rotation=bases_from_sup(audit)
    binding=doa2_bindings.render_part_mapping(executable,slot,costume)
    positions={2:[0.,0.,0.]}
    for _ in range(17):
        for joint,parent in enumerate(PARENT):
            if parent in positions:
                positions[joint]=[positions[parent][k]+vectors[joint][k] for k in range(3)]
    world=[]
    for joint in range(17):
        world.append([rotation[joint][row]+[positions[joint][row]] for row in range(3)]+[[0.,0.,0.,1.]])
    emit={joint:model for joint,model in enumerate(binding['emit_models'])}
    sections=binding['sections']
    archive=doa2_geometry.decode_chr(chr_data)
    body=sorted(set(range(len(archive['models'])))-set(sections['shadow']))
    points=[];head_points=[]
    for joint,model_id in emit.items():
        for mesh in archive['models'][model_id]['meshes']:
            for vertex in mesh['vertices']:
                p=[sum(rotation[joint][row][k]*vertex[k] for k in range(3))+positions[joint][row] for row in range(3)]
                points.append(p)
                if joint==1:head_points.append(p)
    return {'format':'doa2-native-rig-v1','executable_sha256':EXPECTED_SHA256,
            'fighter':fighter,'costume':costume_name,'render_slot':slot,'render_costume':costume,
            'world':world,'parent':list(PARENT),'roles':ROLES,'emit_models':emit,'body_models':body,
            'ground':min(p[1] for p in points),
            'head_h':max(p[1] for p in head_points)-min(p[1] for p in head_points),
            'synthesize_material_headers':True,'retype_argb4444':True,
            'evidence':{'part_mapping':{'table':'0x8c1c85f4','primary_consumer':'0x8c0dd826','extra_consumer':'0x8c0dd906'},
                        'bind_transforms':{'status':'candidate; native SUP neutral-axis inference; gameplay acceptance pending',
                                           'rest_table':'0x8c1949a0','native_solver':'0x8c07a9cc / 0x8c07c570',
                                           'orientation_relation':'R_A = R_B * B_columns because A_columns=identity',
                                           'audited_sup_costumes':len({entry['name'] for entry in audit['records']}),
                                           'extras_15_16':'native eyes parent=head1; gaze neutral; no donor eye roles'},
                        'gameplay_verified':False}}
