"""Cloud's two native 32x32 field face banks, without borrowing another face.

FIELD.BIN at 0x800a0000 selects FIELD.TDB images for each facial expression.
The packet builder relocates bank 0 per model at VRAM (768,256), bank 1 at
(768,416), and palette row 0 per model at (320,480). Keep those allocations.
"""
from __future__ import annotations

import gzip
import hashlib
import struct

import numpy as np

EYES = 0x3FCA4
MOUTHS = 0x3FD94
FACES = 34


def key(prim):
    image=np.asarray(prim['tex'],dtype=np.uint8)
    return image.shape,hashlib.sha256(image.tobytes()).digest(),tuple(prim['color'][:3])


def face_tim(tdb_bytes,field_bytes):
    """Cloud's native face at model slot zero, for exact payload readback previews."""
    from .ff7_models import lzs
    tdb=lzs(tdb_bytes);field=gzip.decompress(field_bytes[8:])
    _,count,palettes,images_at,palettes_at=struct.unpack_from('<IHHII',tdb)
    eyes,mouth=field[EYES+1],field[MOUTHS+1]
    if max(eyes,mouth)>=count or palettes<1:raise ValueError('Invalid Cloud face image index')
    def image(index):
        packed=np.frombuffer(tdb,np.uint8,512,images_at+index*512).reshape(32,16)
        pixels=np.zeros((32,32),np.uint8);pixels[:,0::2]=packed&15;pixels[:,1::2]=packed>>4
        return pixels
    pixels=np.zeros((192,64),np.uint8);pixels[:32,:32]=pixels[:32,32:]=image(eyes);pixels[160:192,:32]=image(mouth)
    rows=np.frombuffer(tdb,'<u2',palettes*16,palettes_at).reshape(palettes,16).copy()
    return {'bpp':4,'x':768,'y':256,'idx':pixels,'clut':{'x':320,'y':480,'rows':rows}}


class FieldAtlas:
    """Pack selected donor images into Cloud-only expression images/palette.

    At most eight 16x16 cells fit. Spare cells widen the images with greatest
    opaque colour variation to 32x16. UVs retain the original aspect on mesh.
    The limited PS1 allocation is recorded, never advertised as full resolution.
    """
    field=True

    def __init__(self,tdb_bytes,field_bytes,prims):
        from PIL import Image
        from .ff7_models import lzs
        tdb=bytearray(lzs(tdb_bytes))
        if len(tdb)<16:raise ValueError('Truncated FF7 field texture database')
        size,count,palettes,images_at,palettes_at=struct.unpack_from('<IHHII',tdb)
        if size!=len(tdb) or palettes!=FACES or images_at+count*512>palettes_at or palettes_at+palettes*32>len(tdb):
            raise ValueError('Unsupported FF7 field texture database allocation')
        if len(field_bytes)<8:raise ValueError('Truncated FF7 field module')
        raw=gzip.decompress(field_bytes[8:]);field=bytearray(raw)
        if len(field)<=MOUTHS+FACES*3 or struct.unpack_from('<I',field_bytes)[0]!=len(raw):
            raise ValueError('Unsupported FF7 field module layout')
        eyes=[list(field[EYES+7*i:EYES+7*i+7]) for i in range(FACES)]
        mouths=[list(field[MOUTHS+3*i:MOUTHS+3*i+3]) for i in range(FACES)]
        if eyes[0]!=[count-1,0,1,2,3,4,7] or mouths[0]!=[count-1,5,6]:
            raise ValueError('Unsupported Cloud expression table; original code is unchanged')
        # Cloud's original open-eye and mouth images. Never overwrite the shared
        # transparent image 126 or an index another face uses.
        slots=(eyes[0][1],mouths[0][1])
        others={v for i in range(1,FACES) for v in eyes[i]+mouths[i]}
        if len(set(slots))!=2 or any(v>=count or v in others for v in slots):
            raise ValueError('Cloud field texture banks are shared; refusing to overwrite another face')
        unique={key(p):p for p in prims if p['tex'] is not None}
        if not unique or len(unique)>8:raise ValueError('Donor color maps exceed Cloud field texture allocation (eight cells)')
        def variation(item):
            a=np.asarray(item[1]['tex']);mask=a[...,3]>=128 if a.shape[2]==4 else np.ones(a.shape[:2],bool)
            return float(a[mask,:3].std(axis=0).sum()) if mask.any() else 0
        ordered=sorted(unique.items(),key=variation,reverse=True)
        widened=min(len(ordered),8-len(ordered));self.rects={};self.pages=[]
        canvas=np.zeros((32,64,4),np.uint8);cell=0
        for i,(ident,p) in enumerate(ordered):
            cells=2 if i<widened else 1
            # Packing two equal 32x32 banks, each made of two horizontal rows.
            page=cell//4;row=(cell%4)//2;column=(cell%2)*16
            if cells==2 and column:raise AssertionError('Invalid field atlas packing')
            width=16*cells;patch=np.asarray(Image.fromarray(np.asarray(p['tex'],dtype=np.uint8)).convert('RGBA').resize((width,16),Image.Resampling.NEAREST)).copy()
            patch[...,:3]=np.clip(patch[...,:3].astype(float)*np.asarray(p['color'][:3])/255,0,255)
            canvas[row*16:row*16+16,page*32+column:page*32+column+width]=patch
            self.rects[ident]=(page,column,row*16,width,16);cell+=cells
        mask=canvas[...,3]>=128
        if not mask.any():raise ValueError('Donor field textures have no opaque pixels')
        quantized=Image.fromarray(canvas[...,:3][mask].reshape(1,-1,3)).quantize(colors=15)
        palette=quantized.getpalette()+[0]*45;indices=np.zeros((32,64),np.uint8)
        indices[mask]=np.asarray(quantized).ravel()+1
        colors=np.zeros(16,dtype='<u2')
        for i in range(15):
            r,g,b=(int(x)>>3 for x in palette[3*i:3*i+3]);colors[i+1]=(r|g<<5|b<<10) or 0x8000
        tdb[palettes_at:palettes_at+32]=colors.tobytes()
        from .ff7_models import _c15
        for page,index in enumerate(slots):
            pixels=indices[:,32*page:32*page+32]
            packed=pixels[:,0::2]|(pixels[:,1::2]<<4)
            tdb[images_at+index*512:images_at+(index+1)*512]=packed.tobytes()
            self.pages.append(_c15(colors.astype(np.int64))[pixels])
        # Static donor maps must survive blink and mouth KAWAI updates; only
        # Cloud's expression selection row changes. Skeletal animation is intact.
        field[EYES:EYES+7]=bytes([slots[0]])*7
        field[MOUTHS:MOUTHS+3]=bytes([slots[1]])*3
        from .formats.lz import lzss_compress_optimal
        encoded=lzss_compress_optimal(bytes(tdb))
        self.tdb=struct.pack('<I',len(encoded))+encoded;compressed=gzip.compress(bytes(field),mtime=0)
        self.field=struct.pack('<II',len(field),len(compressed))+compressed
        if len(self.tdb)>len(tdb_bytes) or len(self.field)>len(field_bytes):
            raise ValueError(f'Enhanced field textures exceed the original compressed file allocation: TDB {len(self.tdb)}/{len(tdb_bytes)}, module {len(self.field)}/{len(field_bytes)}')
        self.report={'banks':2,'bank_size':[32,32],'palette_colors':15,'maps':len(unique),
                     'static_expressions':True,'tdb_bytes':len(self.tdb),'module_bytes':len(self.field),
                     'image_indices':list(slots),'palette_index':0}
        # The disc directory retains its original file size. Clear the old
        # compressed tail as well: gzip readers can otherwise interpret stale
        # trailing bytes as a second malformed member.
        self.tdb+=bytes(len(tdb_bytes)-len(self.tdb))
        self.field+=bytes(len(field_bytes)-len(self.field))

    def uv(self,prim,ids):
        page,x,y,w,h=self.rects[key(prim)]
        uv=[]
        wrap=prim.get('wrap',(10497,10497))
        for index in ids:
            values=[]
            for value,mode in zip(prim['uv'][index],wrap):
                value=float(value)
                if mode==10497:value=value%1 if value<0 or value>1 else value
                elif mode==33648:
                    value=value%2;value=2-value if value>1 else value
                values.append(min(max(value,0),1))
            uv.append((x+min(int(values[0]*w),w-1),y+min(int(values[1]*h),h-1)+(160 if page else 0)))
        return page,uv
