#!/usr/bin/env python3
"""Analyze PL00 child6 texture bulk structure (request #1856)."""
import struct

iso_path = '/home/ehm_eckx/.hermes/cache/scratch/dmc1/dmc1_usa.bin'

with open(iso_path, 'rb') as f:
    lba = 1043291
    size = 1547616
    f.seek(lba * 2048)
    data = f.read(size)
    
    # Child6 starts at offset 273440, size 1042640
    child6_start = 273440
    child6_data = data[child6_start:child6_start+128]
    
    print('Child6 (texture bulk) first 128 bytes:')
    for i in range(0, 128, 16):
        hex_str = ' '.join(f'{b:02x}' for b in child6_data[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in child6_data[i:i+16])
        print(f'  {i:04x}: {hex_str:<48} {ascii_str}')
    
    # Parse as u32 values
    vals = struct.unpack('<32I', child6_data[:128])
    print()
    print('First 32 u32 values:')
    for i in range(0, 32, 8):
        print(f'  {vals[i:i+8]}')
    
    # The checkpoint said child6 = texture bulk with GS TEXTMODE/TEXTURE packets
    # But child6 starts with d7 00 00 00, not 80 00 00 00 (0x80 packet header)
    print()
    print('Looking for 0x80 packet headers in child6:')
    for i in range(0, min(100000, len(child6_data) - 4), 4):
        v = struct.unpack_from('<I', child6_data, i)[0]
        if v == 0x80:
            print(f'  Found 0x80 at offset {i}')
            if i + 16 <= len(child6_data):
                print(f'  Next 16 bytes: {child6_data[i:i+16].hex()}')
            break
    else:
        print('  No 0x80 packet header found in first 100KB')
