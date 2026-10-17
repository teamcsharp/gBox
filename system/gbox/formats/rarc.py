"""Bounded read-only Nintendo RARC tables and directory traversal.

Directory entries reference node indices; physical node order is not a tree.
No extraction, payload decoding, or writer support is implied.

Layout reference: zeldaret/tww include/JSystem/JKernel/JKRArchive.h
(SArcHeader, SArcDataInfo, SDIDirEntry, SDIFileEntry).
"""
import struct

class RARCError(ValueError):
    pass

def parse(raw):
    if len(raw)<0x40 or raw[:4]!=b'RARC':
        raise RARCError('Truncated or invalid RARC header')
    size,dh,data_rel,data_size=struct.unpack_from('>4I',raw,4)
    if size<0x40 or size>len(raw) or dh!=0x20:
        raise RARCError('Invalid RARC size or metadata header')
    nn,no,nf,fo,ss,so=struct.unpack_from('>6I',raw,dh)
    no+=dh;fo+=dh;so+=dh;data_off=data_rel+dh
    def extent(off,n,label):
        if off<0x40 or off>size or n>size-off:
            raise RARCError('Invalid RARC '+label+' extent')
    extent(no,nn*16,'node');extent(fo,nf*20,'entry')
    extent(so,ss,'string');extent(data_off,data_size,'data')
    if not nn or nn>65536 or nf>1000000:
        raise RARCError('Invalid RARC table count')
    spans=sorted((off,off+n) for off,n in ((no,nn*16),(fo,nf*20),(so,ss),(data_off,data_size)) if n)
    if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):
        raise RARCError('Overlapping RARC tables or payload')
    strings=raw[so:so+ss]
    def name(off):
        end=strings.find(b'\0',off) if 0<=off<len(strings) else -1
        if end<0:raise RARCError('Invalid or unterminated RARC name')
        result=strings[off:end].decode('latin-1')
        if not result or '/' in result or '\\' in result or ':' in result:
            raise RARCError('Invalid RARC path component')
        return result
    nodes=[]
    for i in range(nn):
        off=no+i*16;nm,_,count,first=struct.unpack_from('>IHHI',raw,off+4)
        if first>nf or count>nf-first:raise RARCError('RARC child range outside entry table')
        nodes.append({'type':raw[off:off+4].decode('latin-1'),'name':name(nm),'nchild':count,'first':first})
    files=[]
    for i in range(nf):
        off=fo+i*20;flags_name,loc,n=struct.unpack_from('>III',raw,off+4)
        flags=flags_name>>24;nm=name(flags_name&0xffffff)
        if bool(flags&1)==bool(flags&2):raise RARCError('Invalid RARC entry kind')
        if flags&2:
            if nm not in ('.','..') and loc>=nn:raise RARCError('RARC directory node outside table')
        elif loc>data_size or n>data_size-loc:
            raise RARCError('RARC member outside payload')
        files.append({'name':nm,'type':flags,'offset':data_off+loc if flags&1 else None,'node_index':loc if flags&2 else None,'size':n})
    return {'size':size,'data_off':data_off,'data_size':data_size,'str_size':ss,'nodes':nodes,'files':files}

def walk(raw):
    table=parse(raw);nodes=table['nodes'];files=table['files']
    stack=[(0,'')];seen=set();paths=set();out=[]
    while stack:
        i,path=stack.pop()
        if i in seen:raise RARCError('RARC directory cycle or multiple parents')
        seen.add(i);node=nodes[i];children=[]
        for entry in files[node['first']:node['first']+node['nchild']]:
            name=entry['name']
            if name in ('.','..'):
                if not entry['type']&2:raise RARCError('RARC dot entry is not a directory')
                continue
            full=path+name
            if full in paths:raise RARCError('Duplicate RARC path')
            paths.add(full)
            if entry['type']&2:children.append((entry['node_index'],full+'/'))
            else:out.append((full,entry['offset'],entry['size']))
        stack.extend(reversed(children))
    if len(seen)!=len(nodes):raise RARCError('Unreachable RARC directory nodes')
    return out
