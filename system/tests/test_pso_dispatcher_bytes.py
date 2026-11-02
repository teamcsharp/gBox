"""Execute emitted PPC bytes in a deliberately small, strict offline interpreter."""
import struct
import pytest
from gbox import pso_gc_live as G


MASK=0xffffffff
def signed(value,bits=32):
    return value-(1<<bits) if value&(1<<(bits-1)) else value


class DispatcherMachine:
    def __init__(self,*,mode=1,hp=0,phase=14,survival=1,primary=True):
        self.memory={};self.writes=[];self.calls=[]
        self.r=[(0x10203040+i*0x10101)&MASK for i in range(32)]
        self.r[1]=0x817ff000
        self.actor=0x80da62a0;self.r[3]=self.actor
        self.original=list(self.r)
        self.fp=[0x3ff0010000000000+i*0x101010101 for i in range(32)]
        self.original_fp=list(self.fp)
        self.lr=0x81234560;self.original_lr=self.lr
        self.cr=0xa5c3693c;self.original_cr=self.cr;self.ctr=0
        self.put(self.actor,b'\0'*0x600)
        self.put(self.actor+0x324,struct.pack('>H',mode))
        self.put(self.actor+0x32c,struct.pack('>H',hp))
        self.put(G.QUEUE,b'\0'*(G.QMAX*G.QSZ))
        for addr,value in ((G.SURVIVAL,survival),(G.PHASE,phase),
                           (G.PLAYER,self.actor if primary else self.actor+0x3000),
                           (G.HEADER+8,G.ORIGINAL_UPDATE)):
            self.put(addr,struct.pack('>I',value))
        self.mode=mode

    def put(self,a,data):
        self.memory.update((a+i,b) for i,b in enumerate(data))
    def load(self,a,n):
        return int.from_bytes(bytes(self.memory[a+i] for i in range(n)),'big')
    def store(self,a,value,n):
        data=(value&((1<<(n*8))-1)).to_bytes(n,'big')
        self.writes.append((a,data));self.put(a,data)
    def cmp(self,a,b):
        nibble=8 if a<b else 4 if a>b else 2
        self.cr=(self.cr&0x0fffffff)|(nibble<<28)

    def queue(self,index,fn,args):
        self.put(G.QUEUE+index*G.QSZ,struct.pack('>9I',fn,*args))

    def native(self):
        args=tuple(self.r[3:11]);self.calls.append((self.ctr,args))
        if self.ctr==0x801b4340:
            assert args[0]==self.actor
            self.store(self.actor+0x32c,33,2)
            result=0
        else:
            result=(self.ctr^sum(args))&MASK
        # A conforming callee may destroy volatile state. The dispatcher must
        # still retain queue ownership and restore its original update context.
        for reg in (0,*range(3,13)):self.r[reg]=(0xd0000000+reg)&MASK
        for reg in range(1,14):self.fp[reg]=0x7ff0010000000000+reg
        self.cr=0x33333333;self.r[3]=result

    def run(self,code):
        pc=G.CAVE;steps=0
        while steps<3000:
            steps+=1
            assert G.CAVE<=pc<G.CAVE+len(code),'Escaped dispatcher'
            w=struct.unpack_from('>I',code,pc-G.CAVE)[0]
            op=w>>26;rt=(w>>21)&31;ra=(w>>16)&31;rb=(w>>11)&31
            imm=signed(w&0xffff,16);nxt=pc+4
            if op in (14,15):self.r[rt]=((self.r[ra] if ra else 0)+(imm<<(16 if op==15 else 0)))&MASK
            elif op==24:self.r[ra]=self.r[rt]|(w&0xffff)
            elif op in (32,40):self.r[rt]=self.load((self.r[ra]+imm)&MASK,4 if op==32 else 2)
            elif op in (36,37,44):
                address=(self.r[ra]+imm)&MASK
                self.store(address,self.r[rt],2 if op==44 else 4)
                if op==37:self.r[ra]=address
            elif op in (46,47):
                address=(self.r[ra]+imm)&MASK
                for reg in range(rt,32):
                    if op==47:self.store(address+(reg-rt)*4,self.r[reg],4)
                    else:self.r[reg]=self.load(address+(reg-rt)*4,4)
            elif op in (50,54):
                address=(self.r[ra]+imm)&MASK
                if op==54:self.store(address,self.fp[rt],8)
                else:self.fp[rt]=self.load(address,8)
            elif op==11:self.cmp(signed(self.r[ra]),imm)
            elif op==16:
                branch=w&0xffff0000
                assert branch in (0x40820000,0x41820000),'Only known bne/beq accepted'
                equal=bool(self.cr&0x20000000)
                if equal==(branch==0x41820000):nxt=pc+signed(w&0xfffc,16)
            elif w==0x7c001840:self.cmp(signed(self.r[0]),signed(self.r[3]))
            elif w==0x7c0802a6:self.r[0]=self.lr
            elif w==0x7c0803a6:self.lr=self.r[0]
            elif w==0x7c000026:self.r[0]=self.cr
            elif w==0x7c0ff120:self.cr=self.r[0]
            elif w==0x7d8903a6:self.ctr=self.r[12]
            elif w==0x4e800421:self.lr=nxt;self.native()
            elif w==0x4e800420:
                assert self.ctr==G.ORIGINAL_UPDATE
                self.steps=steps;return
            else:raise AssertionError(f'Unsupported PPC instruction {w:08X} at {pc:08X}')
            pc=nxt
        raise AssertionError('Dispatcher did not reach stock tail within its bounded queue')

    def assert_context(self):
        assert self.r[1:12]==self.original[1:12]
        assert self.r[13:32]==self.original[13:32]
        assert self.r[12]==G.ORIGINAL_UPDATE
        assert self.fp[1:14]==self.original_fp[1:14]
        assert self.lr==self.original_lr and self.cr==self.original_cr
        assert self.load(self.actor+0x324,2)==self.mode
        assert not any(a<self.actor+0x326 and a+len(b)>self.actor+0x324 for a,b in self.writes)


@pytest.mark.parametrize('mode',[1,2,3,6])
def test_actual_dispatcher_revive_preserves_actor_mode_and_tail_context(mode):
    machine=DispatcherMachine(mode=mode)
    machine.run(G.CODE)
    assert [(fn,args[0]) for fn,args in machine.calls]==[(0x801b4340,machine.actor)]
    machine.assert_context()


@pytest.mark.parametrize('guards',[{'hp':33},{'phase':15},{'survival':0},{'primary':False}])
def test_actual_dispatcher_guard_skips_revive_but_restores_context(guards):
    machine=DispatcherMachine(**guards);machine.run(G.CODE)
    assert machine.calls==[]
    machine.assert_context()


def test_actual_dispatcher_services_first_and_last_queue_after_revive_and_clobbers():
    machine=DispatcherMachine()
    expected=[]
    for index,fn in ((0,0x80100100),(G.QMAX-1,0x80100200)):
        args=tuple(0xa0000000+index*100+i for i in range(8))
        machine.queue(index,fn,args);expected.append((fn,args))
    machine.run(G.CODE)
    assert machine.calls[1:]==expected
    for index,(fn,args) in zip((0,G.QMAX-1),expected):
        assert machine.load(G.QUEUE+index*G.QSZ,4)==0
        assert machine.load(G.QUEUE+index*G.QSZ+36,4)==(fn^sum(args))&MASK
    machine.assert_context()
