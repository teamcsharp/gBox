"""Apply verified original-game cloth snapshots to a neutral donor export.

The cache is produced by original SH4 code using original archive controls in
an explicit neutral studio frame (actor Y+2, native no-stage floor Y=1).
It is frozen source geometry, not an animation solver or live-pose claim.
"""
import hashlib,json,struct
from pathlib import Path, PurePosixPath
import numpy as np
try:
    from . import acs_cloth_grids as V,native_components as C,actor_attachment_frame as A
except ImportError:
    import acs_cloth_grids as V
    import native_components as C
    import actor_attachment_frame as A
try:
    from gbox import doa2_geometry as G
except ImportError:
    import doa2_geometry as G


def _hash(data):return hashlib.sha256(data).hexdigest()


def cache_name(value):
    """Resolve a private cache artifact basename across Windows/Linux hosts."""
    if not isinstance(value,str):raise ValueError('Native cache artifact path must be a string')
    name=PurePosixPath(value.replace('\\','/')).name
    if not name or name in ('.','..'):raise ValueError('Native cache artifact path has no filename')
    return name


def apply_native_cache(chr_data,acs_data,world,*,original_chr,stem,cache_directory):
    directory=Path(cache_directory)
    verification=json.loads((directory/'verification.json').read_text())
    rows={(r['stem'],r['descriptor']):r for r in verification['grids']}
    source=G.decode_chr(original_chr);current=G.decode_chr(chr_data)
    if len(chr_data)!=len(original_chr) or [m['offset'] for m in source['models']]!=[m['offset'] for m in current['models']]:
        raise ValueError('Native cloth cache requires unchanged source CHR layout')
    world=np.asarray(world,float)
    if world.ndim!=3 or world.shape[1:]!=(4,4):raise ValueError('Native cloth world pose must be Nx4x4')
    output=bytearray(chr_data);instances=[];reports=[];unverified=[];allowed=set()
    for grid in V.decode_grids(acs_data,original_chr):
        row=rows.get((stem,grid['descriptor']),{})
        root_frame=None
        if grid['parent']==15 and row.get('native_actor_root_verified'):
            error=row['native_actor_root_verified'].get('maximum_matrix_error')
            if error is None or not np.isfinite(error) or not 0<=error<=1e-5:
                raise ValueError('Native actor root comparison is unverified')
            root_frame=A.source_controller_frame(acs_data,world,grid['model'])
            proof=row['native_actor_root_verified'].get('root_source',{})
            if any(proof.get(field)!=root_frame[field] for field in ('descriptor','parent','model')):
                raise ValueError('Native actor root source controller mismatch')
        elif grid['parent']==15:
            unverified.append({'descriptor':grid['descriptor'],'model':grid['model'],
                               'reason':'actor-root effect requires verified base frame; cached initializer only'})
            continue
        key=(stem,grid['descriptor'])
        if key not in rows:raise ValueError(f'Native cloth cache lacks {stem} grid{grid["descriptor"]}')
        row=rows[key]
        if 'error' in row or not row.get('generated') or not row.get('changed_bytes_confined_to_source_model_vertices'):
            raise ValueError('Native cloth cache entry is not fully verified')
        if row.get('source_chr_sha256')!=_hash(original_chr):raise ValueError('Native cloth source CHR hash mismatch')
        # Resolve names locally so copied cache directories do not depend on
        # absolute paths embedded by the Linux research runner.
        prefix=directory/cache_name(row['seed'])
        cached_acs=prefix.with_suffix('.ACS').read_bytes()
        if cached_acs!=acs_data:raise ValueError('Native cloth source ACS differs from cached controls')
        seed_world=np.frombuffer(prefix.with_suffix('.world').read_bytes(),dtype='<f4').reshape(-1,4,4).transpose(0,2,1).copy()
        seed_world[:,1,3]-=2
        if world.shape[0]<15 or not np.allclose(world[:15],seed_world[:15],rtol=0,atol=1e-5):
            raise ValueError('Frozen native cloth cache requires the recovered neutral rig frame')
        path=directory/cache_name(row['output'])
        baked=Path(str(path)+'.component.CHR').read_bytes()
        if row.get('cached_chr_sha256')!=_hash(baked):raise ValueError('Native cloth cached component hash mismatch')
        if row.get('source_acs_sha256')!=_hash(acs_data):raise ValueError('Native cloth source ACS hash mismatch')
        if len(baked)!=len(original_chr):raise ValueError('Native cached CHR byte count mismatch')
        G.decode_chr(baked)
        model=source['models'][grid['model']]
        inline={r['offset'] for mesh in model['meshes'] for r in mesh['records'] if not r['reference']}
        scope={i for offset in inline for i in range(offset,offset+32)}
        if any(a!=b and i not in scope for i,(a,b) in enumerate(zip(original_chr,baked))):
            raise ValueError('Native cached writes escaped original model vertex records')
        # Every mapped position is authoritative even where one float happens
        # to match the untouched original placeholder exactly.
        mapped={model['offset']+offset for col in grid['mappings'] for group in col for offset in group}
        for address in mapped:
            output[address:address+12]=baked[address:address+12]
            allowed.update(range(address,address+12))
        normal_count=uv_count=0
        for address in inline:
            for start,size,label in ((12,12,'normal'),(24,8,'uv')):
                pos=address+start
                if baked[pos:pos+size]!=original_chr[pos:pos+size]:
                    output[pos:pos+size]=baked[pos:pos+size];allowed.update(range(pos,pos+size))
                    if label=='normal':normal_count+=1
                    else:uv_count+=1
        if grid['draw'] or root_frame is not None:
            parent=grid['parent'] if root_frame is None else root_frame['parent']
            frame=world[parent].copy() if root_frame is None else root_frame['world'].copy()
            instances.append({'descriptor':grid['descriptor'],'link':0,'mode':2,'model':grid['model'],
                              'parent':parent,'world':frame,'chr_data':bytes(output)})
        reports.append({'descriptor':grid['descriptor'],'model':grid['model'],'parent':grid['parent'],
                        'position_records':len(mapped),'native_normal_records':normal_count,'native_uv_records':uv_count,
                        'draw_instance':bool(grid['draw'] or root_frame is not None),
                        'native_actor_attachment':None if root_frame is None else {k:v for k,v in root_frame.items() if k!='world'},
                        'native_consumer':'0x8c0d664c ->0x8c0d6162',
                        'frame':row['pose'],'floor':row['floor']})
    return {'chr_data':bytes(output),'instances':instances,'written_bytes':allowed,
            'report':{'verified_native_grids':reports,'unverified_actor_effects':unverified,
                      'source_chr_sha256':_hash(original_chr),'baked_chr_sha256':_hash(output),
                      'scope':'frozen source donor in recovered neutral rig; fighting animations retained by target pipeline'}}


def assemble_cloth_instances(bin_data,result):
    primitives=[];reports=[]
    for instance in result['instances']:
        mesh=C.assemble_instances(instance['chr_data'],bin_data,[instance])
        primitives.extend(mesh['prims']);reports.append(mesh['report'])
    return {'prims':primitives,'report':{'draw_instances':len(reports),
                                       'triangles':sum(r['triangles'] for r in reports),
                                       'vertices':sum(r['vertices'] for r in reports),
                                       'frame':'verified frozen original native cloth; rigid donor attachment to original parent',
                                       'unverified_actor_effects':result['report']['unverified_actor_effects']}}
