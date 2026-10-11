"""Reconstruct ACS mode1 vertex writes from owned data and supplied chain pose.

The native consumer0x8c0d5dfe changes inline CHR positions using per-link
displacements, authored local vertex payloads, and model-relative destinations.
The implementation bounds every native write, retains UVs, and reports physics
as supplied input. It does not claim that a configured collision-free chain pose
reproduces the native collision solver or arbitrary-frame cloth simulation.
"""
import hashlib
import struct
import numpy as np
try:
    from . import native_components as C
except ImportError:
    import native_components as C
try:
    from gbox import doa2_geometry as G
except ImportError:
    import doa2_geometry as G


def _word(data,offset,what):
    C._require(data,offset,4,what)
    return struct.unpack_from('<I',data,offset)[0]


def decode_chains(acs_data,chr_data):
    archive=G.decode_chr(chr_data);result=[]
    for entry in C.entries(acs_data):
        if entry['mode']!=1:continue
        p=entry['pointer'];C._require(acs_data,p,96,'Chain descriptor')
        count,parent,flags,style=struct.unpack_from('<4B',acs_data,p)
        table=_word(acs_data,p+0x44,'Chain draw table');C._require(acs_data,table,4,'Chain draw command')
        marker,model_flags=struct.unpack_from('<2H',acs_data,table)
        if marker not in (0xfffe,0xffff):continue
        model_id=model_flags&0x7fff
        if model_id>=len(archive['models']):raise ValueError('ACS chain deformation model exceeds CHR bounds')
        model=archive['models'][model_id]
        inline={r['offset']-model['offset'] for m in model['meshes'] for r in m['records'] if not r['reference']}
        source=_word(acs_data,p+0x48,'ACS chain vertex-source pointer')
        destination=_word(acs_data,p+0x4c,'ACS chain destination pointer')
        source_start,destination_start=source,destination
        groups=[]
        for link in range(count):
            vertices=[]
            while True:
                C._require(acs_data,source,12,'ACS chain vertex payload')
                vector=np.array(struct.unpack_from('<3f',acs_data,source));source+=12
                if vector[0]==999:break
                if not np.isfinite(vector).all():raise ValueError('ACS chain payload is non-finite')
                offsets=[]
                word=_word(acs_data,destination,'ACS chain vertex destination');destination+=4
                if word!=0xffffffff:
                    while True:
                        offset=word&0xfffffffe
                        if offset not in inline or model['offset']+offset+24>model['end_offset']:
                            raise ValueError('ACS deformation target is not a complete inline CHR vertex')
                        offsets.append(offset)
                        if not word&1:break
                        word=_word(acs_data,destination,'ACS chain vertex alias');destination+=4
                        if word==0xffffffff:raise ValueError('ACS chain alias cannot end with a skipped vertex')
                vertices.append({'position':vector,'offsets':offsets})
            groups.append(vertices)
        # Native final copies are triplets: destination,source,reserved. The
        # copy loop at 8c0d60ae writes three floats. Original records also copy
        # a vertex to the model/submesh sphere centre, never their radii or
        # stream-header words. Authorised centres are derived from CHR layout.
        centres={8}|{m['offset']-model['offset']+16 for m in model['meshes']}
        copy_destinations=inline|centres
        alias_table=_word(acs_data,p+0x50,'ACS chain seam-alias pointer')
        seam_aliases=[]
        if alias_table:
            while True:
                a=_word(acs_data,alias_table,'ACS seam alias');alias_table+=4
                if a==0xffffffff:break
                C._require(acs_data,alias_table,8,'ACS seam-alias record')
                b,reserved=struct.unpack_from('<2I',acs_data,alias_table);alias_table+=8
                if a not in copy_destinations or b not in inline:
                    raise ValueError('ACS seam alias is not a verified vertex or bounding-sphere centre')
                if model['offset']+a+16>model['end_offset']:
                    raise ValueError('ACS seam alias copy exceeds its model allocation')
                seam_aliases.append((a,b,reserved))
        anchor=np.array(struct.unpack_from('<3f',acs_data,p+0x14))
        if not np.isfinite(anchor).all():raise ValueError('ACS deformation anchor must be finite')
        result.append({'descriptor':p,'count':count,'parent':parent,'style':style,
                       'marker':marker,'model':model_id,'model_offset':model['offset'],
                       'projected_uv':bool(model_flags&0x8000),'anchor':anchor,
                       'groups':groups,'seam_aliases':seam_aliases,'bounding_centres':sorted(centres),
                       'source_bytes':source-source_start,'destination_bytes':destination-destination_start,
                       'normal_pointers':[_word(acs_data,p+offset,'ACS normal pointer') for offset in (0x54,0x58,0x5c)]})
    return result


def bake_chain_positions(chr_data,acs_data,world,displacements,*,pose_evidence,
                         base_world=None,base_evidence=None,descriptor_offsets=None):
    """Native0x8c0d5dfe position writes for explicitly supplied world vectors.

    ``displacements`` maps descriptor offsets to count x3 world vectors. Missing
    native pose records cause an error; no placeholder positions are exported.
    The exact native position transform is independent of ordinary chain draw
    style. The donor can subsequently freeze those surfaces onto their parent.
    """
    if not pose_evidence:raise ValueError('ACS chain bake needs explicit pose provenance')
    world=np.asarray(world,dtype=float)
    if world.ndim!=3 or world.shape[1:]!=(4,4):raise ValueError('ACS deformation needs Nx4x4 world pose')
    for m in world:C._affine(m,'ACS world')
    chains=decode_chains(acs_data,chr_data);output=bytearray(chr_data)
    if descriptor_offsets is not None:
        selected=set(descriptor_offsets)
        found={chain['descriptor'] for chain in chains}
        if selected-found:raise ValueError('Selected ACS chain descriptor is absent')
        chains=[chain for chain in chains if chain['descriptor'] in selected]
    written={};models={};evidence=[];instances=[];shared_models=set()
    for chain in chains:
        p,parent,count=chain['descriptor'],chain['parent'],chain['count']
        if parent>=len(world):raise ValueError('ACS chain needs a verified parent joint')
        parent_world=None
        if count or chain['marker']==0xffff:
            if parent==15:
                if base_world is None or not base_evidence:
                    raise ValueError('ACS parent15 needs an explicit actor base_world and provenance')
                parent_world=C._affine(base_world,'Actor base world')
            else:parent_world=world[parent]
        if count and p not in displacements:raise ValueError(f'ACS chain {p} lacks observed or explicitly reconstructed displacement vectors')
        vector=np.asarray(displacements.get(p,[]),dtype=float).reshape(count,3)
        if vector.shape!=(count,3) or not np.isfinite(vector).all():raise ValueError('ACS deformation displacement shape is invalid')
        local=vector@np.linalg.inv(parent_world[:3,:3]).T if count else vector
        endpoint=chain['anchor'].copy() if chain['marker']==0xfffe else np.zeros(3)
        for link,group in enumerate(chain['groups']):
            endpoint+=local[link]
            direction=local[link] if link==count-1 else local[link]+local[link+1]
            matrix=C._chain_basis(direction);matrix[:3,3]=endpoint
            for vertex in group:
                position=matrix[:3,:3]@vertex['position']+matrix[:3,3]
                payload=struct.pack('<3f',*position)
                payload=struct.pack('<I',struct.unpack_from('<I',payload)[0]|1)+payload[4:]
                for offset in vertex['offsets']:
                    absolute=chain['model_offset']+offset
                    output[absolute:absolute+12]=payload
                    written[absolute]={'model':chain['model'],'parent':parent,'descriptor':p,'link':link}
        for a,b,reserved in chain['seam_aliases']:
            absolute=chain['model_offset']+a;source=chain['model_offset']+b
            # FUN_8c0d4e92 initializes alias destination+12 from triplet word3
            # before the three-position copy. For centre aliases this is the
            # sphere radius; an inline alias restores its authored normal X.
            struct.pack_into('<I',output,absolute+12,reserved)
            output[absolute:absolute+12]=output[source:source+12]
            written[absolute]={'model':chain['model'],'parent':parent,'descriptor':p,'alias_source':b}
        if chain['marker']==0xffff:
            matrix=parent_world.copy()
            matrix[:3,3]=(matrix@np.r_[chain['anchor'],1])[:3]
            # Native 0x8c0d5dfe draws immediately after each descriptor's writes.
            # Shared mesh buffers are overwritten again by later descriptors.
            # Preserve each draw's snapshot instead of merging its transforms.
            instances.append({'descriptor':p,'link':0,'mode':1,'model':chain['model'],
                              'parent':parent,'world':matrix,'chr_data':bytes(output),
                              'pose':pose_evidence,'native_projected_uv_flag':chain['projected_uv']})
            previous=models.get(chain['model'])
            if previous is not None:
                shared_models.add(chain['model'])
                models.pop(chain['model'])
            elif chain['model'] not in shared_models:
                models[chain['model']]={'parent':parent,'world':matrix}
        evidence.append({'descriptor':p,'consumer':'0x8c0d5dfe','model':chain['model'],
                         'marker':hex(chain['marker']),'parent':parent,'vertices':sum(len(v['offsets']) for g in chain['groups'] for v in g),
                         'seam_aliases':len(chain['seam_aliases']),
                         'bounding_centres_updated':sum(a in chain['bounding_centres'] for a,b,r in chain['seam_aliases']),
                         'normal_pointers':chain['normal_pointers'],
                         'pose_provenance':pose_evidence,'projected_uv':chain['projected_uv']})
    return {'chr_data':bytes(output),'models':models,'instances':instances,'vertex_owners':written,
            'report':{'native_chain_deformations':evidence,'written_positions':len(written),
                      'native_draw_instances':len(instances),'shared_models':sorted(shared_models),
                      'source_chr_sha256':hashlib.sha256(chr_data).hexdigest(),
                      'baked_chr_sha256':hashlib.sha256(output).hexdigest(),
                      'native_positions':'original ACS local payload transformed by0x8c0d5dfe basis/endpoint rules',
                      'normals':'original normals retained except authored alias field+12 initialization; native optional normal reconstruction requires separate validation'}}


def assemble_deformed_instances(bin_data,result,*,actor_root_joint=None,actor_root_evidence=None):
    """Export every actual FFFF draw at its own native CHR snapshot."""
    primitives=[];rows=[]
    for native in result['instances']:
        instance={k:v for k,v in native.items() if k!='chr_data'}
        if instance['parent']==15:
            if actor_root_joint is None or not actor_root_evidence:
                raise ValueError('Native actor attachment needs a proved donor root mapping')
            instance['parent']=int(actor_root_joint)
        assembled=C.assemble_instances(native['chr_data'],bin_data,[instance])
        primitives.extend(assembled['prims']);rows.append(assembled['report'])
    return {'prims':primitives,'report':{'draw_instances':len(rows),'triangles':sum(r['triangles'] for r in rows),
                                      'vertices':sum(r['vertices'] for r in rows),
                                      'shared_model_policy':'each native immediate draw has a separate geometry snapshot',
                                      'normals':result['report']['normals']}}
