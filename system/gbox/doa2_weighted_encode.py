"""Native CHR/SUP adapter for the influence-preserving seam planner."""
from __future__ import annotations
import struct,collections
import numpy as np
from gbox import doa2_geometry as G,doa2_swap as SW,doa2_materials as M,doa2_pvr as P
from .doa2_sup_plan import plan_seams
from .doa2_sup_writer import groups_for_model,encode_sup
from .doa2_sup_payload import symmetric_seam,bind_payload
from .doa2_strip_encode import encode_model


def _raw(attributes):
    result=bytearray(struct.pack('<8f',*attributes))
    for offset in (0,28):
        struct.pack_into('<I',result,offset,struct.unpack_from('<I',result,offset)[0]|1)
    return bytes(result)


def encode_weighted(chr_data,bin_data,primitives,profile,coefficients,*,chr_budget,sup_budget=None,
                    allow_downscale=False,synthesize_headers=True,retype_argb4444=True):
    archive=G.decode_chr(chr_data)
    target=SW.validate_profile(profile,archive)
    plan=plan_seams(primitives)
    body=set(target['body_models']);world=target['W']
    spare=sorted(body-set(target['emit_models'].values()))
    if len(spare)<len(plan['models']):
        raise ValueError(f'weighted topology requires{len(plan["models"])} seam model slots but only{len(spare)} are spare')
    retained_slots={mesh['texture_id'] for model in archive['models'] if model['id'] not in body
                    for mesh in model['meshes'] if mesh['texture_id']>=0}
    materials=M.allocate(archive,bin_data,primitives,allow_downscale=allow_downscale,
                         excluded_slots=retained_slots,synthesize_headers=synthesize_headers,
                         retype_argb4444=retype_argb4444)
    model_meshes={m:[] for m in body}
    metadata={};draw_bones={};seam_models={}
    for a,chunks in plan['rigid'].items():
        m=target['emit_models'][a]
        metadata[m]=[];draw_bones[m]=a
        inverse=np.linalg.inv(target['model_world'][m])
        for chunk in chunks:
            p=chunk['pos']@inverse[:3,:3].T+inverse[:3,3]
            n=chunk['nrm']@np.linalg.inv(inverse[:3,:3])
            n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12)
            _add_mesh(model_meshes[m],metadata[m],chunk,p,n,materials)
    for m,model in zip(spare,plan['models']):
        a=model['bone_a'];draw_bones[m]=a;metadata[m]=[]
        seam_models[m]=model
        inv=np.linalg.inv(world[a])
        for chunk in model['chunks']:
            p=chunk['pos']@inv[:3,:3].T+inv[:3,3]
            n=chunk['nrm']@world[a,:3,:3]
            _add_mesh(model_meshes[m],metadata[m],chunk,p,n,materials)
    placeholder=next(mesh['header'] for meshes in model_meshes.values() for mesh in meshes)
    replacements={m:encode_model(archive['models'][m],meshes) if meshes else
                  G.invisible_model(archive['models'][m],placeholder) for m,meshes in model_meshes.items()}
    rebuilt=G.replace_models(chr_data,replacements,size_budget=chr_budget)
    if materials['report']['descriptor_retypes']:
        updated=bytearray(rebuilt);offset=G.decode_chr(rebuilt)['texture_table_offset']
        updated[offset:offset+len(materials['descriptor_bytes'])]=materials['descriptor_bytes']
        rebuilt=bytes(updated)
    decoded=G.decode_chr(rebuilt)
    seams=[];provenance=[]
    for m,model_metadata in sorted(metadata.items()):
        output_model=decoded['models'][m]
        if len(output_model['meshes'])!=len(model_metadata):
            raise AssertionError('encoded model mesh count changed')
        decoded_source={}
        for mi,(mesh,meta) in enumerate(zip(output_model['meshes'],model_metadata)):
            keys=collections.defaultdict(list)
            for vi,attrs in enumerate(meta['attributes']):
                keys[_raw(attrs)].append(vi)
            for record in mesh['records']:
                if record['reference']:continue
                candidates=keys[record['raw']]
                signatures={(int(meta['chunk'].get('sup_bone_b',np.full(len(meta['attributes']),-1))[vi]),
                             int(meta['chunk'].get('sup_sample',np.zeros(len(meta['attributes']),int))[vi])) for vi in candidates}
                if len(signatures)!=1:
                    raise ValueError('native compact vertex merge combines different skin weights')
                vi=candidates[0];decoded_source[(mi,record['vertex'])]=(meta,vi)
                provenance.append({'model':m,'mesh':mi,'vertex':record['vertex'],
                    'logical_ids':sorted(set(int(meta['chunk']['logical_vertex_id'][v]) for v in candidates)),
                    'logical_id':int(meta['chunk']['logical_vertex_id'][vi]),
                    'draw_bone':draw_bones[m], 'inline_model_offset':record['offset']-output_model['offset'],
                    'source_primitive':int(meta['chunk']['source_primitive']),
                    'source_vertex':int(meta['chunk']['source_vertices'][vi])})
        if m not in seam_models:continue
        model=seam_models[m];a=model['bone_a']
        for b in model['bone_bs']:
            seam={**symmetric_seam(world,a,b),'model_id':m,'initialized':0}
            payloads={}
            for key,(meta,vi) in decoded_source.items():
                chunk=meta['chunk']
                sample=int(chunk['sup_sample'][vi]) if int(chunk['sup_bone_b'][vi])==b else 0
                payload=bind_payload(seam,world,chunk['pos'][vi:vi+1],chunk['nrm'][vi:vi+1],
                                     np.asarray([sample],int),coefficients)
                payloads[key]={'sample':sample,'position':payload['payload_positions'][0],
                               'normal':payload['payload_normals'][0]}
            seam['groups']=groups_for_model(output_model,payloads)
            seams.append(seam)
    sup=encode_sup(seams,chr_data=rebuilt,maximum_bytes=sup_budget)
    report={**plan['report'],'chr_bytes':len(rebuilt),'chr_budget':chr_budget,
            'sup_bytes':len(sup),'sup_budget':sup_budget,'materials':materials['report'],
            'model_draw_bones':{str(m):a for m,a in draw_bones.items()},
            'seam_model_ids':sorted(seam_models),'provenance':provenance,
            'unmodified_model_ids':sorted(set(range(len(decoded['models'])))-body),
            'gameplay_verified':False}
    return {'chr_data':rebuilt,'bin_data':materials['bin_data'],'sup_data':sup,'report':report}


def _add_mesh(meshes,metadata,chunk,p,n,materials):
    source=int(chunk['source_primitive'])
    material=materials['primitives'][source]
    attributes=np.concatenate((p,n,chunk['uv']),axis=1)
    meshes.append({'vertices':[tuple(v) for v in attributes],
                   'triangles':[tuple(map(int,t)) for t in chunk['tris']],
                   'header':P.sampler(material['header'],chunk.get('wrap',(10497,10497))),
                   'texture_id':material['texture_id']})
    metadata.append({'chunk':chunk,'attributes':attributes})
