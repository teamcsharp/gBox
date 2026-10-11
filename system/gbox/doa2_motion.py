"""Inspect native DOA2 compact44, mixed44 and legacy26 MOT containers.

Compact quantization and polynomial formulas are grounded in native decoder
8c0e86c2; the evaluator has not yet been compared with runtime samples. Mixed
raw and legacy float stream boundaries are fully typed, with their unverified
runtime semantics labeled explicitly. Channels are inverse kinematics
parameters, not 44 skeleton bones. Original bytes are retained; this module is
not an animation importer, exporter or skeleton retargeter.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
import hashlib
import struct

CHANNELS = 44
TABLE_BYTES = CHANNELS * 4
PAYLOAD_BYTES = (6, 0, 2, 4)
INTERPOLATION_STATUS = 'Native compact quantization/formulas decoded from 8c0e86c2; runtime equivalence not yet verified'
BASE_SCALE=struct.unpack('<f',bytes.fromhex('17b7d138'))[0]
TANGENT24_SCALE=struct.unpack('<f',bytes.fromhex('bd378635'))[0]


def _signed(value: int, bits: int) -> int:
    return value-(1 << bits) if value & (1 << (bits-1)) else value


def quantized_base(header: int, low_word: int) -> int:
    """Native signed20 value: header's high nibble followed by the low16 word."""
    return _signed(((header & 0xf000) << 4) | (low_word & 0xffff),20)


class MotionFormatError(ValueError):
    """Unsupported layout or inconsistent native MOT boundaries."""


def _check_tables(data: bytes, offsets: list[int], directory_end: int, table_bytes: int = TABLE_BYTES) -> None:
    if not offsets:
        raise MotionFormatError('No MOT clips')
    if min(offsets) < directory_end:
        raise MotionFormatError('MOT clip table overlaps its directory')
    tables = sorted(set(offsets))
    if any(b - a < table_bytes for a, b in zip(tables, tables[1:])):
        raise MotionFormatError('Overlapping MOT clip tables')


def _indexed_directory(data: bytes, channels: int = CHANNELS) -> dict:
    offsets = []
    for cursor in range(0, len(data) - 3, 4):
        value = struct.unpack_from('<I', data, cursor)[0]
        if value == 0:
            directory_end = cursor + 4
            break
        if value % 4 or value + channels*4 > len(data):
            raise MotionFormatError(f'Unsupported indexed 44-channel MOT clip pointer at {cursor:#x}')
        offsets.append(value)
    else:
        raise MotionFormatError('Missing MOT clip-directory terminator')
    _check_tables(data, offsets, directory_end, channels*4)
    return {'layout': 'indexed', 'clip_ids': list(range(len(offsets))),
            'clip_offsets': offsets, 'end': directory_end}


def _paired_directory(data: bytes) -> dict:
    ids, offsets = [], []
    for cursor in range(0, len(data) - 7, 8):
        clip_id, value = struct.unpack_from('<II', data, cursor)
        if clip_id == 0xffffffff:
            if value:
                raise MotionFormatError('Nonzero paired MOT sentinel offset')
            directory_end = cursor + 8
            break
        if clip_id > 0xffff or value % 4 or value + TABLE_BYTES > len(data):
            raise MotionFormatError(f'Unsupported paired 44-channel MOT entry at {cursor:#x}')
        ids.append(clip_id)
        offsets.append(value)
    else:
        raise MotionFormatError('Missing paired MOT clip-directory terminator')
    if len(set(ids)) != len(ids):
        raise MotionFormatError('Duplicate paired MOT clip ID')
    _check_tables(data, offsets, directory_end)
    return {'layout': 'paired', 'clip_ids': ids, 'clip_offsets': offsets,
            'end': directory_end}


def read_directory(data: bytes, *, layout: str = 'auto') -> dict:
    """Read a complete validated directory; auto requires a supported sentinel."""
    if layout not in ('auto', 'indexed', 'paired'):
        raise ValueError('MOT layout must be auto, indexed, or paired')
    if layout == 'indexed':
        return _indexed_directory(data)
    if layout == 'paired':
        return _paired_directory(data)
    try:
        return _indexed_directory(data)
    except MotionFormatError as indexed_error:
        try:
            return _paired_directory(data)
        except MotionFormatError as paired_error:
            raise MotionFormatError(f'Unsupported compact MOT layout: {indexed_error}; '
                                    f'{paired_error}') from paired_error


def clip_offsets(data: bytes) -> list[int]:
    """Read the indexed directory, allowing shared clip tables."""
    return _indexed_directory(data)['clip_offsets']


def read_track(data: bytes, start: int, end: int, *, allow_tail: bool = False) -> dict:
    """Read one scalar stream with a hard bound, preserving opaque coefficients.

    Default behavior requires exact stream termination plus at most two zero
    alignment bytes. Container inspection permits unreferenced bytes after a
    terminated stream, reporting the decoded extent separately from its bound.
    """
    if not 0 <= start < end <= len(data) or start % 2 or end % 2:
        raise MotionFormatError('Invalid MOT track bounds')
    records = []
    cursor = start
    while cursor + 4 <= end:
        header, value = struct.unpack_from('<Hh', data, cursor)
        if header & 0xfff == 0:
            cursor += 4
            padding = data[cursor:end]
            if padding not in (b'', b'\0\0') and not allow_tail:
                raise MotionFormatError(f'Unexpected trailing MOT track bytes at {cursor:#x}')
            padding_bytes = len(padding) if padding in (b'', b'\0\0') else 0
            return {'offset': start, 'end': cursor + padding_bytes, 'bound': end,
                    'terminator_offset': cursor - 4, 'terminator_header': header,
                    'records': records,
                    'final_value': value, 'final_quantized_base': quantized_base(header,value),
                    'encoding': 'compact-scalar',
                    'duration': sum(r['duration'] for r in records),
                    'padding': padding_bytes, 'unreferenced_tail_bytes': end - cursor - padding_bytes}
        codec = header & 3
        duration = (header & 0xfff) >> 2
        size = 4 + PAYLOAD_BYTES[codec]
        if not duration or cursor + size > end:
            raise MotionFormatError(f'Truncated or zero-duration MOT record at {cursor:#x}')
        records.append({'offset': cursor, 'header': header, 'codec': codec,
                        'duration': duration, 'signed_base': value,
                        'quantized_base': quantized_base(header,value),
                        'upper_nibble': header >> 12,
                        'payload_hex': data[cursor + 4:cursor + size].hex()})
        cursor += size
    raise MotionFormatError(f'Missing MOT channel terminator at {start:#x}')


def _inspect_compact(data: bytes, *, layout: str = 'auto', include_clips: bool = False,
                     include_tracks: bool = False) -> dict:
    """Validate supported MOT records, including shared/reordered channels.

    Global boundaries support channels shared between clips and channels stored
    in a different order from their 44-channel pointer tables.
    Every pointer is checked against directory and clip-table intervals before
    any record decode. Summary counts use logical channels; unique track count
    separately describes physical stream reuse.
    """
    directory = read_directory(data, layout=layout)
    offsets = directory['clip_offsets']
    tables = sorted(set(offsets))
    directory_end = directory['end']
    clips = {clip: struct.unpack_from('<44I', data, clip) for clip in tables}
    starts = sorted({pointer for pointers in clips.values() for pointer in pointers})
    for pointer in starts:
        if pointer < directory_end or pointer % 2 or pointer + 4 > len(data):
            raise MotionFormatError(f'MOT channel pointer outside data at {pointer:#x}')
        index = bisect_right(tables, pointer) - 1
        if index >= 0 and pointer < tables[index] + TABLE_BYTES:
            raise MotionFormatError(f'MOT channel pointer enters clip table at {pointer:#x}')
    boundaries = sorted(set(starts + tables + [len(data)]))
    bounds={start: boundaries[bisect_right(boundaries,start)] for start in starts}
    raw={}
    for clip,pointers in clips.items():
        candidates={p:tuple(i for i,v in enumerate(pointers) if v==p) for p in set(pointers)}
        candidates={p:cs for p,cs in candidates.items() if cs in ((3,4,5),(6,7,8),(9,10,11))}
        if not candidates:
            continue
        duration_set={read_track(data,p,bounds[p],allow_tail=True)['duration']
                      for p in set(pointers)-candidates.keys()}
        if len(duration_set)!=1:
            continue
        duration=next(iter(duration_set))
        for p,cs in candidates.items():
            if bounds[p]-p == 6*(duration+1):
                if p in raw and raw[p]['duration'] != duration:
                    raise MotionFormatError('Shared raw MOT samples disagree on duration')
                raw[p]={'offset':p,'end':bounds[p],'bound':bounds[p],
                        'encoding':'raw-i16x3','duration':duration,
                        'samples':duration+1,'components':3,
                        'first_sample':list(struct.unpack_from('<3h',data,p)),
                        'payload_hex':data[p:bounds[p]].hex(),
                        'records':[],'padding':0,'unreferenced_tail_bytes':0,
                        'runtime_consumer_verified':False}
    tracks = {start: raw[start] if start in raw else read_track(data,start,bounds[start],allow_tail=True)
              for start in starts}
    codecs = Counter()
    track_count = 0
    descriptions = []
    for clip, pointers in clips.items():
        durations = {tracks[pointer]['duration'] for pointer in pointers}
        if len(durations) != 1:
            raise MotionFormatError(f'MOT clip channels disagree on duration at {clip:#x}')
        for pointer in pointers:
            codecs.update(record['codec'] for record in tracks[pointer]['records'])
            track_count += 1
        descriptions.append({'offset': clip, 'duration': durations.pop(),
                             'channel_offsets': list(pointers),
                             'unique_channels': len(set(pointers))})
    first_values = []
    first_quantized=[]
    for pointer in clips[offsets[0]]:
        track = tracks[pointer]
        if track['encoding']=='raw-i16x3':
            group=[i for i,v in enumerate(clips[offsets[0]]) if v==pointer]
            first_values.append(track['first_sample'][len(first_values)-group[0]])
            first_quantized.append(None)
        else:
            first_values.append(track['records'][0]['signed_base'] if track['records'] else track['final_value'])
            first_quantized.append(track['records'][0]['quantized_base'] if track['records'] else track['final_quantized_base'])
    intervals = sorted([(0, directory_end)] + [(table, table + TABLE_BYTES) for table in tables]
                       + [(track['offset'], track['end']) for track in tracks.values()])
    unreferenced = []
    cursor = 0
    for start, end in intervals:
        if start < cursor:
            raise MotionFormatError('Overlapping decoded MOT intervals')
        if start > cursor:
            unreferenced.append({'offset': cursor, 'bytes': start - cursor})
        cursor = end
    if cursor < len(data):
        unreferenced.append({'offset': cursor, 'bytes': len(data) - cursor})
    result = {'format': f"doa2-{directory['layout']}-mot-44", 'bytes': len(data),
              'sha256': hashlib.sha256(data).hexdigest(),
              'clips': len(offsets), 'unique_clips': len(tables),
              'channels_per_clip': CHANNELS, 'validated_tracks': track_count,
              'unique_tracks': len(starts), 'record_codecs': dict(sorted(codecs.items())),
              'raw_vector_tracks':len(raw),
              'first_clip_signed_bases': first_values,
              'first_clip_quantized_bases':first_quantized,
              'interpolation_status': INTERPOLATION_STATUS,
              'native_compact_polynomials_decoded':True,
              'runtime_interpolation_verified':False,
              'animation_interpolation_decoded': False,
              'unreferenced_bytes': sum(gap['bytes'] for gap in unreferenced),
              'unreferenced_ranges': unreferenced}
    if include_clips:
        result['clip_ids'] = directory['clip_ids']
        result['clip_offsets'] = offsets
        result['clip_tables'] = descriptions
    if include_tracks:
        result['tracks'] = list(tracks.values())
    return result


def inspect_mot(data: bytes, *, layout: str = 'auto', include_clips: bool = False,
                include_tracks: bool = False, encoding: str = 'auto') -> dict:
    """Inspect compact44/mixed44 or the fully validated legacy26 container.

    Alternate raw sample fields are typed from byte boundaries. Their native
    consumer/semantic interpretation remains explicitly unverified.
    """
    if encoding not in ('auto','compact44','legacy26'):
        raise ValueError('MOT encoding must be auto, compact44, or legacy26')
    compact_error=None
    if encoding != 'legacy26':
        try:
            return _inspect_compact(data,layout=layout,include_clips=include_clips,include_tracks=include_tracks)
        except MotionFormatError as error:
            compact_error=error
            if encoding=='compact44' or layout!='auto':
                raise
    try:
        from .doa2_motion_alternate import inspect_legacy26
    except ImportError:
        from doa2_motion_alternate import inspect_legacy26
    try:
        return inspect_legacy26(data,include_clips=include_clips,include_tracks=include_tracks)
    except MotionFormatError as error:
        if compact_error:
            raise MotionFormatError(f'{compact_error}; legacy26: {error}') from error
        raise


def scalar_polynomials(track: dict) -> list[dict]:
    """Decode native codec coefficients in ascending power order.

    Evidence: FUN8c0e86c2 and literal masks/scales at 8c0e8798..8c0e8ad0.
    Returned values are in native float parameter units (angles are radians).
    """
    if track.get('encoding')!='compact-scalar':
        raise MotionFormatError('Native compact scalar required for interpolation')
    output=[];start=0
    records=track['records']
    for i,r in enumerate(records):
        y0=r['quantized_base']*BASE_SCALE
        y1=(records[i+1]['quantized_base'] if i+1<len(records) else track['final_quantized_base'])*BASE_SCALE
        n=r['duration'];delta=y1-y0;p=bytes.fromhex(r['payload_hex']);codec=r['codec']
        if codec==1:
            c=[y0,delta/n,0.0,0.0]
        elif codec==2:
            q=struct.unpack('<h',p)[0]/32768.0
            c=[y0,q*n+delta/n,-q,0.0]
        else:
            if codec==3:
                a,b=struct.unpack('<2h',p);a/=131072.0;b/=131072.0
            else:
                lo,mid,hi=struct.unpack('<3H',p)
                a=_signed(lo | ((mid&0xff)<<16),24)
                b=_signed(hi | ((mid&0xff00)<<8),24)
                a*=TANGENT24_SCALE;b*=TANGENT24_SCALE
            c=[y0,a,(3*delta-(2*a+b)*n)/(n*n),((a+b)*n-2*delta)/(n*n*n)]
        output.append({'start':start,'duration':n,'coefficients':c,'codec':codec})
        start+=n
    return output


def evaluate_scalar(track: dict, frame: float) -> float:
    """Evaluate the decoded native compact polynomial inside its known extent."""
    if not 0 <= frame <= track['duration']:
        raise MotionFormatError('MOT frame is outside decoded track extent')
    for p in scalar_polynomials(track):
        if frame < p['start']+p['duration']:
            t=frame-p['start'];c=p['coefficients']
            return ((c[3]*t+c[2])*t+c[1])*t+c[0]
    return track['final_quantized_base']*BASE_SCALE
