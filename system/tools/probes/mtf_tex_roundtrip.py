"""Decode and CPU-reencode one local ARC texture, emitting evidence only.

python tools/probes/mtf_tex_roundtrip.py --arc ../.scratch-merc-recovery/assets/uEm10.arc \
    --entry 'pawn\\em\\em10\\model\\em1000_104_BM' --out ../.scratch-merc-recovery/tex-codec
Requires gbox[textures]. The source archive is never written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from PIL import Image, ImageDraw
from gbox import mt_arc, mtf_tex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arc',type=Path,required=True)
    parser.add_argument('--entry',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    source = args.arc.read_bytes()
    entries = [e for e in mt_arc.parse(source).entries if e.name == args.entry]
    if len(entries) != 1:
        raise ValueError('exactly one named archive texture is required')
    original = zlib.decompress(entries[0].data)
    tex = mtf_tex.parse(original)
    decoded = mtf_tex.decode(original)
    changed = mtf_tex.replace_image(original,decoded)
    after = mtf_tex.decode(changed)
    assert mtf_tex.parse(changed) == tex and changed[:tex.data_offset] == original[:tex.data_offset]
    mip_rows = []
    for i, mip in enumerate(tex.mips):
        assert mtf_tex.replace_blocks(original,mtf_tex.linear_blocks(original,i),i) == original
        image = mtf_tex.decode(changed,i)
        assert image.size == (mip.width,mip.height)
        mip_rows.append({'level':i,'width':mip.width,'height':mip.height,'offset':mip.offset,'size':mip.size})
    args.out.mkdir(parents=True,exist_ok=True)
    decoded.save(args.out/'original.png')
    after.save(args.out/'roundtrip.png')
    preview = Image.new('RGB',(tex.width*2,tex.height+40),'#20232b')
    preview.paste(decoded,(0,40)); preview.paste(after,(tex.width,40))
    draw = ImageDraw.Draw(preview)
    draw.text((12,12),'Native BC7 decoded',fill='white')
    draw.text((tex.width+12,12),'CPU BC7 encode + TEX reswizzle + decode',fill='white')
    preview.save(args.out/'roundtrip-preview.png')
    (args.out/'roundtrip.tex').write_bytes(changed)
    report = {'archive':str(args.arc.resolve()),'archive_sha256':hashlib.sha256(source).hexdigest(),
        'entry':args.entry,'tex_sha256':hashlib.sha256(original).hexdigest(),
        'output_sha256':hashlib.sha256(changed).hexdigest(),'format':hex(tex.format),
        'header_unchanged':True,'bytes':len(changed),'mips':mip_rows,
        'pixel_mae':float(np.abs(np.asarray(decoded).astype(float)-np.asarray(after)).mean())}
    (args.out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
