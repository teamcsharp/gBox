"""Serialize native DOA2 SUP seam writes, including CHR inline aliases.

Native init8c0e6dc8 allocates240 bytes/resource, stores16-byte seam handles
and a zero sentinel. Owned files contain at most14 seams. Offsets are relative
to the selected CHR model, not to the CHR archive or GPU vertex queue.
"""
from __future__ import annotations
import math,struct
from gbox import doa2_geometry as G,doa2_seams as S

MAX_SEAMS = 14

def _floats(values, count, label):
    flat=[]
    def visit(value):
        try:
            iterator=iter(value)
        except TypeError:
            flat.append(float(value));return
        for item in iterator:visit(item)
    visit(values)
    if len(flat)!=count or not all(math.isfinite(v) for v in flat):
        raise ValueError(f'{label} requires{count} finite floats')
    try:return struct.pack('<'+str(count)+'f',*flat)
    except (OverflowError,struct.error) as error:
        raise ValueError(f'{label} does not fit native float32') from error

def make_groups(records: list[dict], *, aliases: bool = True) -> list[dict]:
    """Pack per-inline-vertex curve payloads into native sample groups.

    ``records`` carry sample1..16, model-relative offset, position and normal.
    Equal float32 payloads in one group share the native alias marker. Sample0
    is intentionally omitted by the caller: it stays bone-A-local in the CHR.
    """
    by_sample={16:[]}
    offsets=set()
    for row in records:
        sample=int(row['sample']);target=int(row['offset'])
        if not 1<=sample<=16 or target<=0 or target&3:
            raise ValueError('SUP record requires sample1..16 and aligned nonzero model offset')
        if target in offsets:
            raise ValueError('An inline vertex cannot belong to two SUP sample groups')
        offsets.add(target)
        payload=_floats((row['position'],row['normal']),6,'SUP vertex payload')
        by_sample.setdefault(sample,[]).append((target,payload))
    groups=[]
    for sample in [16]+sorted(set(by_sample)-{16}):
        entries=by_sample[sample]
        buckets={}
        for i,(target,payload) in enumerate(entries):
            key=payload if aliases else (i,payload)
            buckets.setdefault(key,[]).append((target,payload))
        vertices=[]
        for bucket in buckets.values():
            for j,(target,payload) in enumerate(bucket):
                vertex={'offset':target,'alias':bool(j)}
                if not j:
                    values=struct.unpack('<6f',payload)
                    vertex.update(position=values[:3],normal=values[3:])
                vertices.append(vertex)
        groups.append({'sample':sample,'vertices':vertices})
    return groups

def groups_for_model(model: dict, payloads: dict, *, aliases: bool = True) -> list[dict]:
    """Map decoded unique vertices to every mutable CHR occurrence.

    Keys are ``(mesh_index, decoded_unique_vertex_index)``; values contain
    sample0..16, position and normal from the exact inverse native curve.
    All compact backreferences use their preceding inline record automatically.
    """
    records=[];seen=set()
    for mi,mesh in enumerate(model['meshes']):
        if mesh['shader']==-3:
            raise ValueError('Native SUP writes float32 normals; packed-normal NL3 is unsupported')
        for record in mesh['records']:
            if record['reference']:continue
            key=(mi,record['vertex'])
            if key not in payloads:
                raise ValueError(f'Missing SUP payload for inline vertex{key}')
            row=payloads[key];sample=int(row['sample'])
            if not 0<=sample<=16:raise ValueError('SUP sample exceeds native0..16')
            seen.add(key)
            if not sample:continue
            records.append({'sample':sample,'offset':record['offset']-model['offset'],
                            'position':row['position'],'normal':row['normal']})
    if seen!=set(payloads):
        raise ValueError('SUP payload keys include a vertex outside this decoded model')
    return make_groups(records,aliases=aliases)

def encode_sup(seams: list[dict], *, chr_data: bytes|None=None,
               maximum_bytes: int|None=None) -> bytes:
    """Encode a bounded native SUP file; optional CHR proves every write address.

    A seam carries bone_a, bone_b, model_id, axis_pairs[3,2,3], controls[4,3],
    and decoded-format groups. New writers must use initialized0; round trips
    can preserve the owned original0/1 marker. The file is not padded because
    its final directory payload terminator defines the serialized file length.
    """
    if len(seams)>MAX_SEAMS:
        raise ValueError('More than14 SUP seams would exceed the native runtime slot plus sentinel')
    archive=G.decode_chr(chr_data) if chr_data is not None else None
    output=bytearray(4*(len(seams)+1));starts=[]
    written=set()
    for seam in seams:
        a,b,model=(int(seam[k]) for k in ('bone_a','bone_b','model_id'))
        initialized=int(seam.get('initialized',0))
        if not 0<=a<44 or not 0<=b<44 or a==b or not 0<=model<128 or initialized not in (0,1):
            raise ValueError('SUP header has unsupported joint/model/initialization fields')
        inline=None
        if archive is not None:
            if model>=len(archive['models']):raise ValueError('SUP model outside CHR archive')
            target_model=archive['models'][model]
            if any(mesh['shader']==-3 for mesh in target_model['meshes']):
                raise ValueError('SUP target model contains packed normals')
            inline={r['offset']-target_model['offset'] for mesh in target_model['meshes']
                    for r in mesh['records'] if not r['reference']}
        start=len(output);starts.append(start)
        output.extend(struct.pack('<IBBBB',start+8,a,b,model,initialized))
        output.extend(_floats(seam['axis_pairs'],18,'SUP axis controls'))
        output.extend(_floats(seam['controls'],12,'SUP position controls'))
        groups=seam['groups'];samples=set()
        if not groups or int(groups[0]['sample'])!=16:
            raise ValueError('SUP requires an initial direct-B sample16 group, including an empty one')
        for group in groups:
            sample=int(group['sample'])
            if not 1<=sample<=16 or sample in samples:
                raise ValueError('SUP sample is invalid or repeated')
            samples.add(sample);output.extend(struct.pack('<I',sample))
            last_payload=None
            for vertex in group['vertices']:
                target=int(vertex['offset']);alias=bool(vertex.get('alias',False))
                if target<=0 or target&3 or target>0xfffffffc:
                    raise ValueError('SUP vertex offset must be aligned, positive and native32-bit')
                if inline is not None and target not in inline:
                    raise ValueError('SUP write misses a complete inline CHR vertex')
                if (model,target) in written:
                    raise ValueError('SUP writes one model vertex more than once')
                written.add((model,target))
                output.extend(struct.pack('<I',target|int(alias)))
                if alias:
                    if last_payload is None:raise ValueError('SUP alias precedes its source payload')
                else:
                    last_payload=_floats((vertex['position'],vertex['normal']),6,'SUP vertex payload')
                    output.extend(last_payload)
            output.extend(struct.pack('<I',0))
        output.extend(struct.pack('<I',0))
    for i,start in enumerate(starts):struct.pack_into('<I',output,i*4,start)
    result=bytes(output)
    if maximum_bytes is not None and len(result)>maximum_bytes:
        raise ValueError(f'Native SUP requires{len(result)} bytes, exceeding allocation{maximum_bytes}')
    S.decode_sup(result) # prove self-consistent pointers, float fields and group terminators
    return result
