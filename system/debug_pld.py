#!/usr/bin/env python3
"""Debug script for PLD child table parsing (request #1856)."""
import struct
import binascii

iso_path = '/home/ehm_eckx/.hermes/cache/scratch/dmc1/dmc1_usa.bin'

with open(iso_path, 'rb') as f:
    lba = 1043291
    size = 1547616
    f.seek(lba * 2048)
    data = f.read(size)
    
    child_count = struct.unpack_from('<I', data, 0)[0]
    offsets = list(struct.unpack_from(f'<{child_count}I', data, 4))
    
    children = []
    for i, off in enumerate(offsets):
        next_off = offsets[i+1] if i+1 < len(offsets) else size
        children.append((off, next_off - off))
    
    print('PL00 children (offset, size):')
    for i, (off, sz) in enumerate(children):
        print(f'  child{i}: offset={off:7d}, size={sz:8d} B')
    
    # Child0 first 32 bytes
    print()
    child0_data = data[48:48+32]
    print(f'Child0 first 32 bytes: {child0_data.hex()}')
    
    # Parse as 8 u32 fields
    fields = struct.unpack('<8I', child0_data)
    print(f'8 u32 fields (LE): {fields}')
    
    # Check against checkpoint's hex values
    # Checkpoint: 13200301 e0780300 0100be00 40010000
    # These are u32 LE: 0x01032013, 0x000378e0, 0x00be0001, 0x00014040
    expected_bytes = bytes.fromhex('13200301 e0780300 0100be00 40010000')
    print(f'Checkpoint expected (first 16): {expected_bytes.hex()}')
    print(f'Match first 16: {child0_data[:16] == expected_bytes[:16]}')
    
    # Find the actual texture bulk (child6 = 1,042,640 B)
    # The checkpoint says child6 is the texture bulk
    # With 11 children, offsets[6] should be child6's start
    print()
    print('Texture bulk region (child6 at offset 271488):')
    # Actually, the checkpoint said child6 size is 1042640
    # Let's check which child has that size
    for i, (off, sz) in enumerate(children):
        if sz >= 1000000:
            print(f'  Found large child{i}: offset={off}, size={sz}')
            large_data = data[off:off+64]
            print(f'  First 64 bytes: {large_data.hex()}')
            break
    
    # Check the full data region
    print()
    print('Analyzing full PL00 data regions:')
    for i, (off, sz) in enumerate(children):
        print(f'  child{i}: off={off:7d}, sz={sz:8d}', end='')
        # Check for GS texture magic
        if sz > 32:
            chunk = data[off:off+16]
            print(f', magic={chunk[:8].hex()}')
        else:
            print()
