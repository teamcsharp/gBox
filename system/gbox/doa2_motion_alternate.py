"""Typed inspection of the owned TINA_C legacy26 motion container.

Seven interleaved signed-short triples, four signed-short pairs and fifteen
scalar record streams expand to 44 components. All counts, stream boundaries,
record headers and finite float payloads are checked. Component semantics and
the legacy runtime consumer have not yet been established, so no legacy
polynomial evaluator or importer is exposed.
"""
from bisect import bisect_right
from collections import Counter
import hashlib
import math
import struct

try:
    from .doa2_motion import MotionFormatError,_indexed_directory,quantized_base
except ImportError:
    from doa2_motion import MotionFormatError,_indexed_directory,quantized_base

LEGACY_TRIPLES=(0,1,2,10,15,20,25)
LEGACY_PAIRS=(9,14,19,24)
LEGACY_SCALARS=tuple(i for i in range(26) if i not in LEGACY_TRIPLES+LEGACY_PAIRS)


def read_float_track(data:bytes,start:int,end:int)->dict:
    if not 0<=start<end<=len(data) or start%4:
        raise MotionFormatError('Invalid legacy scalar bounds')
    records=[];cursor=start
    while cursor+4<=end:
        header,base=struct.unpack_from('<HH',data,cursor)
        duration=(header&0xffc)>>2
        if header&3:
            raise MotionFormatError('Unsupported legacy scalar codec bits')
        if not duration:
            cursor+=4
            padding=2 if data[cursor:end]==bytes(2) else 0
            return {'offset':start,'end':cursor+padding,'bound':end,
                    'encoding':'legacy-float-coefficients','records':records,
                    'terminator_header':header,'final_quantized_base':quantized_base(header,base),
                    'duration':sum(r['duration'] for r in records),
                    'padding':padding,'unreferenced_tail_bytes':end-cursor-padding,
                    'runtime_consumer_verified':False}
        if cursor+12>end:
            raise MotionFormatError('Truncated legacy float coefficient record')
        coefficients=struct.unpack_from('<2f',data,cursor+4)
        if not all(math.isfinite(v) for v in coefficients):
            raise MotionFormatError('Nonfinite legacy float coefficient')
        records.append({'offset':cursor,'header':header,'duration':duration,
                        'quantized_base':quantized_base(header,base),
                        'coefficient_values':list(coefficients),
                        'payload_hex':data[cursor+4:cursor+12].hex()})
        cursor+=12
    raise MotionFormatError('Missing legacy scalar terminator')


def inspect_legacy26(data:bytes,*,include_clips=False,include_tracks=False)->dict:
    directory=_indexed_directory(data,26)
    ts=sorted(set(directory['clip_offsets']));de=directory['end']
    clips={t:struct.unpack_from('<26I',data,t) for t in ts}
    kinds={};starts=sorted({p for ps in clips.values() for p in ps})
    for ps in clips.values():
        for i,p in enumerate(ps):
            kind=3 if i in LEGACY_TRIPLES else 2 if i in LEGACY_PAIRS else 1
            if p in kinds and kinds[p]!=kind:
                raise MotionFormatError('Legacy stream reused with different component count')
            kinds[p]=kind
    for p in starts:
        t=bisect_right(ts,p)-1
        if p<de or p%4 or p+4>len(data) or t>=0 and p<ts[t]+104:
            raise MotionFormatError('Legacy channel pointer outside data')
    bs=sorted(set(starts+ts+[len(data)]))
    bounds={p:bs[bisect_right(bs,p)] for p in starts}
    tracks={p:read_float_track(data,p,bounds[p]) for p in starts if kinds[p]==1}
    durations={};descriptions=[]
    for t,ps in clips.items():
        ds={tracks[ps[i]]['duration'] for i in LEGACY_SCALARS}
        if len(ds)!=1:
            raise MotionFormatError('Legacy clip scalar durations disagree')
        duration=next(iter(ds))
        for i in LEGACY_TRIPLES+LEGACY_PAIRS:
            p=ps[i]
            if p in durations and durations[p]!=duration:
                raise MotionFormatError('Legacy sample stream shared with different duration')
            durations[p]=duration
        descriptions.append({'offset':t,'duration':duration,'channel_offsets':list(ps)})
    for p,duration in durations.items():
        components=kinds[p];count=duration+1;stop=p+count*components*2
        if stop>bounds[p]:
            raise MotionFormatError('Truncated legacy raw sample stream')
        padding=2 if data[stop:bounds[p]]==bytes(2) else 0
        tracks[p]={'offset':p,'end':stop+padding,'bound':bounds[p],
                   'encoding':f'raw-i16x{components}','components':components,
                   'samples':count,'duration':duration,
                   'first_sample':list(struct.unpack_from('<%dh'%components,data,p)),
                   'payload_hex':data[p:stop].hex(),'padding':padding,
                   'runtime_consumer_verified':False}
    intervals=sorted([(0,de)]+[(t,t+104) for t in ts]+[(t['offset'],t['end']) for t in tracks.values()])
    gaps=[];cursor=0
    for start,end in intervals:
        if start<cursor:
            raise MotionFormatError('Overlapping legacy decoded intervals')
        if start>cursor:gaps.append({'offset':cursor,'bytes':start-cursor})
        cursor=end
    if cursor<len(data):gaps.append({'offset':cursor,'bytes':len(data)-cursor})
    result={'format':'doa2-indexed-mot-legacy26','bytes':len(data),
            'sha256':hashlib.sha256(data).hexdigest(),'clips':len(directory['clip_offsets']),
            'unique_clips':len(ts),'channels_per_clip':26,'scalar_components_per_clip':44,
            'validated_tracks':26*len(ts),'unique_tracks':len(tracks),
            'stream_encodings':dict(Counter(t['encoding'] for t in tracks.values())),
            'animation_interpolation_decoded':False,'runtime_consumer_verified':False,
            'interpolation_status':'Legacy float payloads and raw sample boundaries typed; runtime semantics unverified',
            'unreferenced_bytes':sum(g['bytes'] for g in gaps),'unreferenced_ranges':gaps}
    if include_clips:result.update(clip_ids=directory['clip_ids'],clip_offsets=directory['clip_offsets'],clip_tables=descriptions)
    if include_tracks:result['tracks']=list(tracks.values())
    return result
