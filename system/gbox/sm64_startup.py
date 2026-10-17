"""Keep native title/file-select startup on the verified PAL Mario 64 layout.

PAL forces Options whenever no save slot exists. New character builds therefore
repeatedly open it. Clear only that automatic flag assignment; manual Options,
language selection, title demos and EEPROM data remain native.
"""
import hashlib
import os
from pathlib import Path
import tempfile

GAME_IDS=('b7aecee966090bfa','66062703301f4969')
START=0x206A4C
SIGNATURE=bytes.fromhex(
    '3c01801a3c11801aa0226d8426316d9800008025'
    '0c09aa6702002025145200032610000110000006a2200000'
    '00107600000e86032a0100041420fff6a2320000')
PATCH=0x206A88


def apply(rom):
    if rom[:4]!=bytes.fromhex('80371240') or rom[0x3b:0x3f]!=b'NSMP':
        return rom,{'applied':False,'reason':'not the verified PAL layout'}
    actual=rom[START:START+len(SIGNATURE)]
    edited=bytearray(SIGNATURE);edited[PATCH-START:PATCH-START+4]=bytes.fromhex('a2200000')
    if actual==bytes(edited):return rom,{'applied':True,'already_applied':True}
    if actual!=SIGNATURE:
        raise ValueError('Mario 64 PAL menu fingerprint differs; refusing the startup patch')
    output=bytearray(rom);output[PATCH:PATCH+4]=bytes.fromhex('a2200000')
    return bytes(output),{'applied':True,'offset':PATCH,'bytes_changed':1,
        'effect':'disable automatic empty-save Options; manual Options remains available','saves_changed':False}


def prepare_launch(src,config):
    """Use a separate cached copy; preserve the basename for existing EEPROM saves."""
    from . import n64_rom
    original=n64_rom.read(src);rom,report=apply(original)
    if rom==original:return Path(src),report
    key=hashlib.sha256(rom).hexdigest();folder=config.cache/'startup-roms'/'sm64'/key
    folder.mkdir(parents=True,exist_ok=True)
    dest=folder/(Path(src).stem+'.z64')
    if not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest()!=key:
        fd,tmp=tempfile.mkstemp(dir=folder,suffix='.part')
        with os.fdopen(fd,'wb') as stream:stream.write(rom)
        os.replace(tmp,dest)
    return dest,report|{'source_sha256':hashlib.sha256(original).hexdigest(),'launch_sha256':key}
