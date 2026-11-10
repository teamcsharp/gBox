import struct,sys,capstone,json
from capstone.arm64 import *
import os
raw=open(os.environ.get('RE6_NSO','/home/ehm_eckx/gBox_alt/scratch/agent/re6sw/nso/main-061D2A06CD700785E987C42CE2D72231.nso'),'rb').read()
img=raw[0x100:]
lo,hi=int(sys.argv[1],16),int(sys.argv[2],16)
md=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_ARM);md.detail=True
reg={}
mem={}
M64=(1<<64)-1
def rn(r): return md.reg_name(r)
def key(n):
    if n in('xzr','wzr'):return 'z'
    return 'x'+n[1:] if n[0] in 'xw' else n
def get(n):
    if n in('xzr','wzr'):return 0
    v=reg.get(key(n))
    if v is None:return None
    return v&0xFFFFFFFF if n[0]=='w' else v
def put(n,v):
    k=key(n)
    if v is None: reg.pop(k,None)
    else: reg[k]=v&(M64 if n[0]=='x' else 0xFFFFFFFF)
for ins in md.disasm(img[lo:hi],lo):
    m=ins.mnemonic;ops=ins.operands
    try:
        if m=='adrp': put(rn(ops[0].reg),ops[1].imm)
        elif m in('add','sub') and len(ops)==3 and ops[2].type==ARM64_OP_IMM:
            a=get(rn(ops[1].reg));imm=ops[2].imm
            if ops[2].shift.type!=0: imm<<=ops[2].shift.value
            put(rn(ops[0].reg),None if a is None else (a+imm if m=='add' else a-imm))
        elif m=='mov' and ops[1].type==ARM64_OP_IMM: put(rn(ops[0].reg),ops[1].imm)
        elif m=='mov' and ops[1].type==ARM64_OP_REG: put(rn(ops[0].reg),get(rn(ops[1].reg)))
        elif m=='movk':
            a=get(rn(ops[0].reg));sh=ops[1].shift.value if ops[1].shift.type else 0
            put(rn(ops[0].reg),None if a is None else (a&~(0xFFFF<<sh))|(ops[1].imm<<sh))
        elif m=='stp':
            r1,r2,mo=ops[0],ops[1],ops[2]
            base=get(rn(mo.mem.base))
            if base is not None:
                d=base+mo.mem.disp; sz=8 if rn(r1.reg)[0]=='x' else 4
                mem[d]=get(rn(r1.reg)); mem[d+sz]=get(rn(r2.reg))
        elif m=='str':
            r1,mo=ops[0],ops[1]; base=get(rn(mo.mem.base))
            if base is not None: mem[base+mo.mem.disp]=get(rn(r1.reg))
        elif m in('cmp','tst','cbz','cbnz','b','bl','ret','tbz','tbnz','strb','strh','nop'): pass
        elif ops and ops[0].type==ARM64_OP_REG and rn(ops[0].reg)[0] in 'xw':
            put(rn(ops[0].reg),None)
            if m=='ldp' and len(ops)>1 and ops[1].type==ARM64_OP_REG: put(rn(ops[1].reg),None)
    except Exception as e: pass
json.dump({hex(k):(v if v is None else hex(v)) for k,v in mem.items()},open(sys.argv[3],'w'))
print(len(mem))
