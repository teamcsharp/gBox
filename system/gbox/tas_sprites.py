"""Native Mesen tile packs for replay: graphics only, original executable and state untouched."""
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import zipfile
from urllib.parse import quote

import httpx
from PIL import Image

from . import tas
from .smb1_inventory import _player_rows

OPTIONS = [('', 'Original Mario'), ('sonic', 'Sonic'), ('mario2', 'Mario (Super Mario Bros. 2)'),
           ('mario3', 'Mario (Super Mario Bros. 3)'), ('smw', 'Mario (Super Mario World)')]


def fit(image, width, height):
    image = image.convert('RGBA')
    box = image.getchannel('A').getbbox()
    if not box:
        raise ValueError('Replacement sprite is empty')
    image = image.crop(box)
    factor = min(width/image.width, height/image.height)
    image = image.resize((max(1, round(image.width*factor)), max(1, round(image.height*factor))), Image.Resampling.NEAREST)
    out = Image.new('RGBA', (width, height))
    out.alpha_composite(image, ((width-image.width)//2, height-image.height))
    return out


def write_pack(rom, frames, folder, provenance):
    """One full-colour image per SMB animation row; conditions disambiguate reused tiles."""
    tas.smb_identity(rom)
    if len(frames) != 26:
        raise ValueError('Provide all 26 SMB player animation rows')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    scale = 2
    rows = _player_rows(rom[16:32784])
    atlas = Image.new('RGBA', (32, 26*64))
    lines = ['<ver>106', '<scale>2', '<img>player.png']
    for i, (tiles, image) in enumerate(zip(rows, frames)):
        small = 12 <= i <= 22
        fitted = fit(image, 32, 32 if small else 64)
        atlas.alpha_composite(fitted, (0, i*64+(32 if small else 0)))
        lines.append(f'<condition>row{i},memoryCheckConstant,06D5,==,{i*8:02X}')
        used = set()
        for slot, tile in enumerate(tiles):
            if tile == 0xFC or tile in used:
                continue
            used.add(tile)
            x, y = slot % 2 * 16, i*64+slot//2*16
            lines.append(f'[row{i}]<tile>0,{tile:X},FF162718,{x},{y},1,Y')
    atlas.save(folder/'player.png')
    (folder/'hires.txt').write_text('\n'.join(lines)+'\n', encoding='ascii')
    meta = {'format': 'mesen-native-hdpack-106', 'rom_sha256': hashlib.sha256(rom).hexdigest(),
            'image_sha256': tas.fingerprint(folder/'player.png'), 'source': provenance,
            'notes': 'Player graphics only; source art fitted to SMB1 sprite bounds. SMB1 physics and collision remain unchanged.'}
    (folder/'pack.json').write_text(json.dumps(meta, indent=2))
    return meta


def _json(ctx, path, params=None):
    r = httpx.get(ctx.server+path, params=params, headers=ctx.headers, timeout=30)
    r.raise_for_status(); return r.json()


def _asset(ctx, slug, rel):
    if not re.fullmatch('[a-zA-Z0-9_-]+', slug) or not isinstance(rel, str) or '..' in rel.split('/'):
        raise ValueError('Invalid character sprite path')
    url = ctx.server+'/api/characters/'+quote(slug, safe='')+'/file/'+quote(rel, safe='/')
    with httpx.stream('GET', url, headers=ctx.headers, timeout=30) as response:
        response.raise_for_status(); out = bytearray()
        for block in response.iter_bytes(65536):
            out += block
            if len(out) > 4*2**20:
                raise ValueError('Sprite asset exceeds 4 MiB')
    return bytes(out)


def gallery_frames(ctx, slug):
    meta = _json(ctx, '/api/characters/'+quote(slug, safe=''))
    if meta.get('kind') != 'sprites':
        raise ValueError('Replay player must be a sprite character')
    clips = {a.get('clip', a.get('name')): a for a in meta.get('animations', [])}
    cache, hashes = {}, {}
    def frame(names, n=0):
        clip = next((clips[name] for name in names if name in clips), None)
        if not clip:
            raise ValueError('Sprite entry needs standing/walking animation clips')
        key = (clip.get('clip', clip.get('name')), n)
        if key not in cache:
            index = json.loads(_asset(ctx, slug, clip['index']))
            frames = index['frames']
            item = frames[n % len(frames)]
            relative = str(Path(clip['index']).parent/item['file']).replace('\\', '/')
            raw = _asset(ctx, slug, relative)
            image = Image.open(io.BytesIO(raw))
            if image.width > 1024 or image.height > 1024:
                raise ValueError('Sprite frame exceeds 1024 pixels')
            cache[key] = image.convert('RGBA')
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        return cache[key]
    stand = frame(('idle', 'wait', 'stand', 'walk'))
    walk = [frame(('walk', 'run'), n) for n in range(3)]
    jump = frame(('jump', 'roll', 'walk'))
    skid = frame(('skid', 'brake', 'walk'))
    swim = [frame(('swim', 'walk'), n) for n in range(3)]
    climb = [frame(('climb', 'walk'), n) for n in range(2)]
    duck = frame(('duck', 'crouch', 'walk'))
    dead = frame(('death', 'hurt', 'jump', 'walk'))
    return (walk+[skid, jump]+swim+climb+[duck, stand]+walk+[skid, jump]+swim+climb+[dead, stand, stand, stand],
            {'slug': slug, 'name': meta.get('name'), 'assets': hashes})


def nes_frames(path, which):
    """Use the existing signature-validated owned-ROM readers, never download game artwork."""
    from . import smb2_inventory as two, smb3_inventory as three
    data, _ = three.read_source(path)
    header = three.parse_ines(data); prg, chr_ = three.split(data, header)
    if which == 'mario2':
        if not two.identify(prg+chr_).get('match'):
            raise ValueError('SMB2 donor revision is not verified')
        inv = two.player_inventory(chr_, two.locate_chr_bank_select(prg), two.locate_character_tiles(prg), two.locate_character_palette(prg))
        inv = {'Mario': inv['Mario']}
        w, h, rgba = two.render_sheet(chr_, inv)
        sheet = Image.frombytes('RGBA', (w, h), rgba)
        names = list(two.FRAME_NAMES)
        def get(name, small=False):
            n = names.index(name) if name in names else 0
            return sheet.crop((n*18, 34 if small else 0, n*18+16, (34 if small else 0)+32))
        walknames = [n for n in names if 'walk' in n or 'run' in n] or names[:3]
        def rows(small):
            walk = [get(walknames[n % len(walknames)], small) for n in range(3)]
            jump = get(next((n for n in names if 'jump' in n), names[0]), small)
            duck = get(next((n for n in names if 'duck' in n or 'crouch' in n), names[0]), small)
            return walk+[walk[0], jump]+walk+[walk[0], walk[1]]+[duck, walk[0]]
        big, small = rows(False), rows(True)
    else:
        identity = three.identify(prg+chr_)
        if not identity.get('match'):
            raise ValueError('SMB3 donor revision is not verified')
        inv = three.player_inventory(prg, chr_, three.locate_player_tables(prg))
        w, h, rgba = three.render_sheet(chr_, inv)
        sheet = Image.frombytes('RGBA', (w, h), rgba)
        # Frontal poses repeat the left pattern; Player_Draw flips the right sprite.
        # The inventory contact sheet deliberately omits that OAM attribute.
        for row, powerup in enumerate(inv['powerups'].values()):
            for fr in powerup['frames']:
                sprites = {s['slot']: s for s in fr['sprites']}
                for slot in (1, 4):
                    left, right = sprites.get(slot-1), sprites.get(slot)
                    if left and right and left['pattern'] == right['pattern']:
                        x, y = fr['frame']*26+(slot % 3-1)*8, row*34+slot//3*16
                        part = sheet.crop((x, y, x+8, y+16)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        sheet.paste(part, (x+8, y))
        def get(n, small=False):
            y = 0 if small else 34
            return sheet.crop((n*26, y, n*26+24, y+32))
        def rows(small):
            walk = [get(n, small) for n in (1, 2, 3)]
            # Only the complete basic poses are used for this adaptation. Other
            # table entries depend on shared pages/size-specific OAM adjustments;
            # importing those as standalone frames produces detached body parts.
            return walk+[get(0, small), get(0, small)]+[get(n, small) for n in (0, 1, 2)]+[get(0, small), get(1, small), get(0, small), get(0, small)]
        big, small = rows(False), rows(True)
    frames = big+small[:10]+[small[4], small[0], big[0], big[0]]
    return frames, {'kind': which, 'source_sha256': hashlib.sha256(data).hexdigest(),
                    'mapping': 'SMB1 animation poses adapted from the owned donor tile tables'}


def lz2(source):
    """Bounded LC_LZ2 decoder for the owned World's GFX32 stream."""
    out, pos = bytearray(), 0
    def take(n):
        nonlocal pos
        if pos+n > len(source):
            raise ValueError('Truncated World graphics')
        value = source[pos:pos+n]; pos += n; return value
    while True:
        head = take(1)[0]
        if head == 255:
            return bytes(out)
        command, count = head >> 5, (head & 31)+1
        if command == 7:
            command, count = (head >> 2) & 7, ((head & 3) << 8 | take(1)[0])+1
        if len(out)+count > 65536:
            raise ValueError('World graphics exceed decode budget')
        if command == 0:
            out += take(count)
        elif command == 1:
            out += take(1)*count
        elif command == 2:
            pair = take(2); out += (pair*((count+1)//2))[:count]
        elif command == 3:
            start = take(1)[0]; out += bytes((start+i)&255 for i in range(count))
        elif command == 4:
            offset = int.from_bytes(take(2), 'big')
            if offset >= len(out):
                raise ValueError('Invalid World graphics back reference')
            for i in range(count):
                out.append(out[offset+i])
        else:
            raise ValueError('Unsupported World compression command')


def world_frames(path):
    """SMW US LoROM: GFX32 at $08:8000, draw tables at $00:E00C/E0CC, native 4bpp tiles.

    Addresses/pose transfer follow IsoFrieze/SMWDisX bank_00.asm and bank_08-0B.asm.
    This reader is deliberately pinned to the owned US ROM hash rather than guessing on hacks.
    """
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            names = [i for i in z.infolist() if i.filename.lower().endswith(('.sfc', '.smc')) and i.file_size <= 2**20]
            if len(names) != 1:
                raise ValueError('Select the owned single-ROM World archive')
            raw = z.read(names[0])
    else:
        if path.stat().st_size > 2**20:
            raise ValueError('World donor exceeds reader limit')
        raw = path.read_bytes()
    if len(raw) % 32768 == 512:
        raw = raw[512:]
    sha = hashlib.sha256(raw).hexdigest()
    if sha != '0838e531fe22c077528febe14cb3ff7c492f1f5fa8de354192bdff7137c27f5b':
        raise ValueError('World donor differs from the verified US cartridge')
    gfx = lz2(raw[0x40000:])
    if len(gfx) != 23808:
        raise ValueError('World player graphics length differs')
    pointer = struct.unpack_from('<H', raw, 0x62A2)[0] & 0x7FFF
    colours = [0, 0x7FFF, 0, 0x001F, 0x7FFF, 0] + list(struct.unpack_from('<10H', raw, pointer))
    palette = [tuple(((c >> shift) & 31)*255//31 for shift in (0, 5, 10))+(255,) for c in colours]
    palette[0] = (0, 0, 0, 0)
    def part(value):
        offset = ((value & 0xF7) << 6)+(0x4000 if value & 8 else 0)
        image = Image.new('RGBA', (16, 16))
        for slot in range(4):
            base = offset+(slot % 2)*32+(slot//2)*512
            if base+32 > len(gfx):
                raise ValueError('World pose points outside its graphics')
            for y in range(8):
                for x in range(8):
                    pixel = sum(((gfx[base+(p//2)*16+y*2+p%2] >> (7-x)) & 1) << p for p in range(4))
                    image.putpixel((slot%2*8+x, slot//2*8+y), palette[pixel])
        return image
    def pose(n, small=False):
        index = n+(0 if small else 0x46)
        image = Image.new('RGBA', (16, 32))
        image.alpha_composite(part(raw[0x600C+index]), (0, 0))
        image.alpha_composite(part(raw[0x60CC+index]), (0, 16))
        return image
    def rows(small):
        walk = [pose(n, small) for n in (0, 1, 2)]
        return walk+[pose(13, small), pose(11, small)]+[pose(n, small) for n in (16, 17, 18)]+[pose(21, small), pose(22, small), pose(28, small), pose(0, small)]
    big, small = rows(False), rows(True)
    return big+small[:10]+[pose(62, True), small[0], big[0], big[0]], {'kind': 'smw', 'source_sha256': sha,
            'graphics_sha256': hashlib.sha256(gfx).hexdigest(), 'mapping': 'SMB1 pose adaptation; native World top/bottom tile tables'}


def prepare(ctx, sprite, rom, folder):
    from .tools import rom_path
    from .models import CatalogEntry
    if sprite.startswith('sprite:'):
        frames, source = gallery_frames(ctx, sprite[7:])
    elif sprite == 'sonic':
        frames, source = gallery_frames(ctx, 's3k_sonic')
    elif sprite in ('mario2', 'mario3'):
        gid = '768145c187bf6dd0' if sprite == 'mario2' else '213e4208929ec3e9'
        game = _json(ctx, '/api/catalog/'+gid)
        frames, source = nes_frames(rom_path(CatalogEntry.model_validate(game), ctx.config), sprite)
    elif sprite == 'smw':
        game = _json(ctx, '/api/catalog/a4a1e706115175dd')
        frames, source = world_frames(rom_path(CatalogEntry.model_validate(game), ctx.config))
    else:
        raise ValueError('Choose Sonic, Mario 2, Mario 3, World Mario or a sprite:gallery_slug')
    return write_pack(rom, frames, Path(folder)/'system/HdPacks/replay', source)
