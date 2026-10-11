"""Pure ISO extent planning using only modified CHR/BIN trailing sectors.

No file is sacrificed or aliased to unrelated content. An unmodified alias
pins its original extent. Planning must complete before a caller writes the
copied track or changes any ISO directory record.
"""
from __future__ import annotations
import collections

SECTOR = 2048


def _sectors(size):
    return (size + SECTOR - 1) // SECTOR


def _subtract(start,end,blocked):
    ranges=[(start,end)]
    for low,high in sorted(blocked):
        output=[]
        for a,b in ranges:
            if high<=a or low>=b:output.append((a,b));continue
            if a<low:output.append((a,min(b,low)))
            if high<b:output.append((max(a,high),b))
        ranges=output
    return ranges


def plan_modified_slack(original_files, modifications, *, track_start,
                        track_end=None, reserved_ranges=(), donor_suffixes=('.CHR','.BIN')):
    """Plan exact changed extents without overwriting an unmodified resource.

    ``original_files`` maps ISO names to (LBA, original byte length).
    ``modifications`` maps changed names to bytes (preferred) or new lengths.
    Bytes allow identical fully modified aliases to keep one shared extent.
    ``track_end`` and every reserved range use exclusive end LBAs. Pass all
    directory sectors as reserved ranges. File slack is eligible only when
    every alias is modified and its in-place CHR/BIN replacement is shorter.
    Unknown bounds are conservative: the last extent ends at its old rounded
    size, never at unused trailing track sectors.
    """
    if not isinstance(track_start,int) or track_start<0 or (track_end is not None and
            (not isinstance(track_end,int) or track_end<=track_start)):
        raise ValueError('invalid patched data-track bounds')
    originals={}
    groups=collections.defaultdict(list)
    for name,extent in original_files.items():
        lba,size=extent
        if not isinstance(name,str) or not isinstance(lba,int) or not isinstance(size,int) or lba<0 or size<0:
            raise ValueError('original ISO names/extents must be finite nonnegative integers')
        originals[name]=(lba,size);groups[lba].append(name)
    sizes={};contents={}
    for name,data in modifications.items():
        if name not in originals:raise ValueError(f'{name} is not on this disc')
        if isinstance(data,(bytes,bytearray,memoryview)):
            contents[name]=bytes(data);size=len(data)
        elif isinstance(data,int) and not isinstance(data,bool) and data>=0:
            size=data
        else:raise ValueError('modifications require bytes or nonnegative byte lengths')
        if originals[name][0]<track_start:raise ValueError(f'{name} is outside the patched data track')
        sizes[name]=size
    blocked=[]
    for low,high in reserved_ranges:
        if not isinstance(low,int) or not isinstance(high,int) or low<0 or high<=low:
            raise ValueError('reserved ISO ranges require increasing nonnegative LBAs')
        blocked.append((low,high))
    order=sorted(groups)
    bounds={}
    for index,lba in enumerate(order):
        if lba<track_start:continue
        maximum=max(originals[name][1] for name in groups[lba])
        next_lba=order[index+1] if index+1<len(order) else lba+_sectors(maximum)
        end=min(next_lba,track_end) if track_end is not None else next_lba
        if end<lba or lba+_sectors(maximum)>end:
            raise ValueError(f'original extent at LBA{lba} crosses the next original extent or track end')
        bounds[lba]=end
    plan={};pending=[];free=[];protected_aliases=[]
    # Pass one commits safe in-place replacements and derives their free tails.
    for lba in order:
        names=sorted(groups[lba]);changed=[name for name in names if name in sizes]
        if not changed:continue
        unchanged=[name for name in names if name not in sizes]
        end=bounds[lba];capacity=end-lba
        batches=[]
        for name in changed:
            equal=next((batch for batch in batches if name in contents and
                        batch[0] in contents and contents[name]==contents[batch[0]]),None)
            if equal is None:batches.append([name])
            else:equal.append(name)
        if unchanged:
            protected_aliases.append({'lba':lba,'unmodified_names':unchanged,
                                      'modified_names_requiring_relocation':changed})
            for batch in batches:pending.append((batch,'unmodified alias protects original extent'))
            continue
        possible=[batch for batch in batches if max(1,_sectors(sizes[batch[0]]))<=capacity]
        # Deterministic source order; differing modified aliases cannot overwrite
        # each other. If all aliases match bytes, their one batch stays shared.
        selected=min(possible,key=lambda batch:batch[0]) if possible else None
        if selected is None:
            pending.extend((batch,'new file exceeds original allocation') for batch in batches)
            continue
        first=selected[0];need=max(1,_sectors(sizes[first]))
        if any(a<lba+need and b>lba for a,b in blocked):
            raise ValueError(f'{first} in-place write overlaps reserved ISO metadata')
        for name in selected:
            plan[name]={'file':name,'old_lba':lba,'old_bytes':originals[name][1],
                        'lba':lba,'new_bytes':sizes[name],'sectors':need,'relocated':False,
                        'capacity_sectors':capacity,'shared_modified_aliases':selected,
                        'reason':'fits original extent','donor':None}
        for batch in batches:
            if batch is not selected:pending.append((batch,'modified aliases require different content'))
        maximum=max(originals[name][1] for name in names)
        if first.upper().endswith(tuple(s.upper() for s in donor_suffixes)) and sizes[first]<maximum:
            for low,high in _subtract(lba+need,end,blocked):
                if low<high:free.append({'start_lba':low,'end_lba':high,'donor':first,
                                        'original_extent_lba':lba,'original_extent_end':end,
                                        'modified_aliases':selected})
    initial_free=[dict(row) for row in free]
    # Pass two places largest overflowing/alias batches first, using best fit.
    for batch,reason in sorted(pending,key=lambda item:(-max(1,_sectors(sizes[item[0][0]])),item[0][0])):
        first=batch[0];need=max(1,_sectors(sizes[first]))
        candidates=[row for row in free if row['end_lba']-row['start_lba']>=need]
        if not candidates:
            raise ValueError(f'{first}: {sizes[first]} bytes need{need} sectors; no modified CHR/BIN tail can preserve all original resources')
        chosen=min(candidates,key=lambda row:(row['end_lba']-row['start_lba']-need,row['start_lba'],row['donor']))
        destination=chosen['start_lba'];chosen['start_lba']+=need
        donor={'file':chosen['donor'],'start_lba':destination,'end_lba':destination+need,
               'original_extent_lba':chosen['original_extent_lba'],
               'original_extent_end':chosen['original_extent_end']}
        for name in batch:
            old_lba,old_size=originals[name]
            plan[name]={'file':name,'old_lba':old_lba,'old_bytes':old_size,
                        'lba':destination,'new_bytes':sizes[name],'sectors':need,'relocated':True,
                        'capacity_sectors':need,'shared_modified_aliases':batch,'reason':reason,'donor':donor}
    output=[plan[name] for name in sorted(plan)]
    # Verify preservation and non-overlap independently of the allocator above.
    for row in output:
        a,b=row['lba'],row['lba']+row['sectors']
        if a<track_start or (track_end is not None and b>track_end):raise AssertionError('plan escaped data track')
        if any(a<high and b>low for low,high in blocked):raise AssertionError('plan overlaps reserved ISO metadata')
        for name,(low,size) in originals.items():
            if name in sizes:continue
            high=low+_sectors(size)
            if a<high and b>low:raise AssertionError(f'plan overwrites unmodified resource{name}')
    for i,row in enumerate(output):
        for other in output[i+1:]:
            a,b=row['lba'],row['lba']+row['sectors'];c,d=other['lba'],other['lba']+other['sectors']
            if a<d and b>c:
                if (row['shared_modified_aliases']!=other['shared_modified_aliases'] or a!=c or b!=d):
                    raise AssertionError('plan overlaps different modified resources')
    return {'plan':output,'report':{'sector_bytes':SECTOR,
              'relocated_files':[row['file'] for row in output if row['relocated']],
              'modified_files':sorted(sizes),'unmodified_resource_count':len(originals)-len(sizes),
              'original_aliases_protected':protected_aliases,
              'initial_modified_slack':initial_free,
              'remaining_modified_slack':[row for row in free if row['start_lba']<row['end_lba']],
              'sacrificed_resources':[],'unused_track_tail_consumed':False,
              'planning_policy':'two-pass modified CHR/BIN tails; unmodified extents and aliases preserved'}}
