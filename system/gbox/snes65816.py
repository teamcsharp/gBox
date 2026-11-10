
"""Minimal 65816 recursive-descent disassembler for HiROM SNES ROMs (analysis probe)."""
import struct
# mnemonic, mode
_T = {}
G=[('ORA',0x01),('AND',0x21),('EOR',0x41),('ADC',0x61),('STA',0x81),('LDA',0xA1),('CMP',0xC1),('SBC',0xE1)]
gm={0x01:'(dp,X)',0x03:'sr',0x05:'dp',0x07:'[dp]',0x09:'imm_m',0x0D:'abs',0x0F:'long',0x11:'(dp),Y',0x12:'(dp)',0x13:'(sr),Y',0x15:'dp,X',0x17:'[dp],Y',0x19:'abs,Y',0x1D:'abs,X',0x1F:'long,X'}
def S(op,n,m): _T[op]=(n,m)
for op,n,m in [(0x00,'BRK','imm8'),(0x02,'COP','imm8'),(0x04,'TSB','dp'),(0x06,'ASL','dp'),(0x08,'PHP','imp'),(0x0A,'ASL','A'),(0x0B,'PHD','imp'),(0x0C,'TSB','abs'),(0x0E,'ASL','abs'),(0x10,'BPL','rel'),(0x14,'TRB','dp'),(0x16,'ASL','dp,X'),(0x18,'CLC','imp'),(0x1A,'INC','A'),(0x1B,'TCS','imp'),(0x1C,'TRB','abs'),(0x1E,'ASL','abs,X'),(0x20,'JSR','abs'),(0x22,'JSL','long'),(0x24,'BIT','dp'),(0x26,'ROL','dp'),(0x28,'PLP','imp'),(0x2A,'ROL','A'),(0x2B,'PLD','imp'),(0x2C,'BIT','abs'),(0x2E,'ROL','abs'),(0x30,'BMI','rel'),(0x34,'BIT','dp,X'),(0x36,'ROL','dp,X'),(0x38,'SEC','imp'),(0x3A,'DEC','A'),(0x3B,'TSC','imp'),(0x3C,'BIT','abs,X'),(0x3E,'ROL','abs,X'),(0x40,'RTI','imp'),(0x42,'WDM','imm8'),(0x44,'MVP','blk'),(0x46,'LSR','dp'),(0x48,'PHA','imp'),(0x4A,'LSR','A'),(0x4B,'PHK','imp'),(0x4C,'JMP','abs'),(0x4E,'LSR','abs'),(0x50,'BVC','rel'),(0x54,'MVN','blk'),(0x56,'LSR','dp,X'),(0x58,'CLI','imp'),(0x5A,'PHY','imp'),(0x5B,'TCD','imp'),(0x5C,'JML','long'),(0x5E,'LSR','abs,X'),(0x60,'RTS','imp'),(0x62,'PER','rell'),(0x64,'STZ','dp'),(0x66,'ROR','dp'),(0x68,'PLA','imp'),(0x6A,'ROR','A'),(0x6B,'RTL','imp'),(0x6C,'JMP','(abs)'),(0x6E,'ROR','abs'),(0x70,'BVS','rel'),(0x74,'STZ','dp,X'),(0x76,'ROR','dp,X'),(0x78,'SEI','imp'),(0x7A,'PLY','imp'),(0x7B,'TDC','imp'),(0x7C,'JMP','(abs,X)'),(0x7E,'ROR','abs,X'),(0x80,'BRA','rel'),(0x82,'BRL','rell'),(0x84,'STY','dp'),(0x86,'STX','dp'),(0x88,'DEY','imp'),(0x8A,'TXA','imp'),(0x8B,'PHB','imp'),(0x8C,'STY','abs'),(0x8E,'STX','abs'),(0x90,'BCC','rel'),(0x94,'STY','dp,X'),(0x96,'STX','dp,Y'),(0x98,'TYA','imp'),(0x9A,'TXS','imp'),(0x9B,'TXY','imp'),(0x9C,'STZ','abs'),(0x9E,'STZ','abs,X'),(0xA0,'LDY','imm_x'),(0xA2,'LDX','imm_x'),(0xA4,'LDY','dp'),(0xA6,'LDX','dp'),(0xA8,'TAY','imp'),(0xAA,'TAX','imp'),(0xAB,'PLB','imp'),(0xAC,'LDY','abs'),(0xAE,'LDX','abs'),(0xB0,'BCS','rel'),(0xB4,'LDY','dp,X'),(0xB6,'LDX','dp,Y'),(0xB8,'CLV','imp'),(0xBA,'TSX','imp'),(0xBB,'TYX','imp'),(0xBC,'LDY','abs,X'),(0xBE,'LDX','abs,Y'),(0xC0,'CPY','imm_x'),(0xC2,'REP','imm8'),(0xC4,'CPY','dp'),(0xC6,'DEC','dp'),(0xC8,'INY','imp'),(0xCA,'DEX','imp'),(0xCB,'WAI','imp'),(0xCC,'CPY','abs'),(0xCE,'DEC','abs'),(0xD0,'BNE','rel'),(0xD4,'PEI','dp'),(0xD6,'DEC','dp,X'),(0xD8,'CLD','imp'),(0xDA,'PHX','imp'),(0xDB,'STP','imp'),(0xDC,'JML','[abs]'),(0xDE,'DEC','abs,X'),(0xE0,'CPX','imm_x'),(0xE2,'SEP','imm8'),(0xE4,'CPX','dp'),(0xE6,'INC','dp'),(0xE8,'INX','imp'),(0xEA,'NOP','imp'),(0xEB,'XBA','imp'),(0xEC,'CPX','abs'),(0xEE,'INC','abs'),(0xF0,'BEQ','rel'),(0xF4,'PEA','abs'),(0xF6,'INC','dp,X'),(0xF8,'SED','imp'),(0xFA,'PLX','imp'),(0xFB,'XCE','imp'),(0xFC,'JSR','(abs,X)'),(0xFE,'INC','abs,X')]:
    S(op,n,m)
S(0x89,'BIT','imm_m')
OPS=dict(_T)
for hi,(n,_) in enumerate(G):
    for low,m in gm.items():
        if n=='STA' and m=='imm_m': continue
        OPS[hi*0x20+low]=(n,m)
OPS[0x89]=('BIT','imm_m')
SZ={'imp':1,'A':1,'imm8':2,'dp':2,'dp,X':2,'dp,Y':2,'(dp)':2,'(dp,X)':2,'(dp),Y':2,'[dp]':2,'[dp],Y':2,'sr':2,'(sr),Y':2,'rel':2,'abs':3,'abs,X':3,'abs,Y':3,'(abs)':3,'(abs,X)':3,'[abs]':3,'rell':3,'blk':3,'long':4,'long,X':4}

def rom_off(bank, addr, size):
    """HiROM: banks C0-FF -> file offset (bank&0x3F)<<16|addr; 00-3F:8000+ mirrors C0-FF."""
    b = bank & 0x3F
    if (bank & 0xC0)==0xC0 or (bank<0x40 and addr>=0x8000) or (bank&0xC0)==0x40 or (0x80<=bank<0xC0 and addr>=0x8000):
        o=(b<<16)|addr
        return o if o<size else None
    return None

def disasm_one(rom, bank, pc, m16, x16):
    o=rom_off(bank,pc,len(rom))
    if o is None: return None
    op=rom[o]
    ent=OPS.get(op)
    if ent is None: return None
    n,mode=ent
    sz=SZ.get(mode)
    if mode=='imm_m': sz=3 if m16 else 2
    elif mode=='imm_x': sz=3 if x16 else 2
    if sz is None: return None
    arg=rom[o+1:o+sz]
    return dict(op=op,name=n,mode=mode,size=sz,arg=bytes(arg))


def trace(rom, bank, pc, m16=False, x16=False, seen=None):
    """Recursive-descent trace tracking REP/SEP width flags. Returns (seen, calls)."""
    seen = seen if seen is not None else {}
    work = [(bank, pc, m16, x16)]; calls = set()
    while work:
        b, pc, m16, x16 = work.pop()
        while (b, pc) not in seen:
            i = disasm_one(rom, b, pc, m16, x16)
            if not i: break
            seen[(b, pc)] = (i, m16, x16)
            n, a = i['name'], i['arg']; nxt = (pc + i['size']) & 0xffff
            if n == 'REP':
                m16 |= bool(a[0] & 0x20); x16 |= bool(a[0] & 0x10)
            elif n == 'SEP':
                m16 &= not (a[0] & 0x20); x16 &= not (a[0] & 0x10)
            if i['mode'] in ('rel', 'rell'):
                work.append((b, (nxt + int.from_bytes(a, 'little', signed=True)) & 0xffff, m16, x16))
                if n in ('BRA', 'BRL'): break
            elif n == 'JSR' and i['mode'] == 'abs':
                t = int.from_bytes(a, 'little'); calls.add((b, t)); work.append((b, t, m16, x16))
            elif n == 'JSL':
                t = (a[2], int.from_bytes(a[:2], 'little')); calls.add(t); work.append((t[0], t[1], m16, x16))
            elif n == 'JMP' and i['mode'] == 'abs':
                pc = int.from_bytes(a, 'little'); continue
            elif n == 'JML' and i['mode'] == 'long':
                b = a[2]; pc = int.from_bytes(a[:2], 'little'); continue
            elif n in ('RTS', 'RTL', 'RTI', 'JMP', 'JML', 'STP'): break
            pc = nxt
    return seen, calls


def reset_vector(rom):
    return int.from_bytes(rom[0xfffc:0xfffe], 'little')


CGRAM_DMA = ((0x83, 0xdbf2), (0x83, 0xdbf5))   # LDX #$20 entry / caller-supplied X; A=src in bank $C0, Y=CGRAM index


def palette_loads(rom):
    """Statically find JSL $83:DBF2/DBF5 palette DMA calls with immediate A/X/Y operands.

    Returns [{'site','src','cgram','bytes','raw_ok'}]; src is a ROM offset in bank $C0
    (the CGRAM DMA routine hard-codes DMA bank $C0) and raw_ok is True if all words are
    valid BGR555 (bit 15 clear).  Sites with non-immediate operands are skipped.
    """
    seen, _ = trace(rom, 0xc0, reset_vector(rom))
    from_nmi = int.from_bytes(rom[0xffea:0xffec], 'little')
    trace(rom, 0xc0, from_nmi, seen=seen)
    ks = sorted(seen); out = []
    for idx, k in enumerate(ks):
        i = seen[k][0]
        if i['name'] != 'JSL' or i['arg'][:3] not in (b'\xf2\xdb\x83', b'\xf5\xdb\x83'):
            continue
        regs = {}
        for kk in reversed(ks[max(0, idx - 8):idx]):
            ii = seen[kk][0]
            if kk[0] != k[0]: break
            if ii['name'] in ('LDA', 'LDX', 'LDY') and ii['mode'] in ('imm_m', 'imm_x'):
                regs.setdefault(ii['name'], int.from_bytes(ii['arg'], 'little'))
        n = 0x20 if i['arg'][0] == 0xf2 else regs.get('LDX')
        if 'LDA' in regs and 'LDY' in regs and n:
            src = regs['LDA']
            words = [int.from_bytes(rom[src + j:src + j + 2], 'little') for j in range(0, n, 2)]
            out.append(dict(site='%02x:%04x' % k, src=src, cgram=regs['LDY'], bytes=n,
                            raw_ok=all(w < 0x8000 for w in words)))
    return out


def spc_block_table(rom, base=0x40000, limit=64):
    """C4:0000 is an APU upload block table (24-bit ptrs), not graphics; decode leading entries."""
    return [int.from_bytes(rom[base + 3 * j:base + 3 * j + 3], 'little') for j in range(limit)]
