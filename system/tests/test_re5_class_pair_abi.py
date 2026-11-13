"""Execute the real wrapper through a caller-clobbering native ABI stub."""
import struct
import pytest
from gbox.mercs.native.re5_ebffdb22 import classes as C

@pytest.mark.parametrize('base', [0x10000000, 0x3CA7C04000])
@pytest.mark.parametrize('item,update', [(0x106,C.BOMB_UPDATE_OFF),(0x108,C.FLASH_UPDATE_OFF)])
def test_explosion_preserves_class_arguments_across_configure(base,item,update):
    U=pytest.importorskip('unicorn')
    from unicorn import arm64_const as A
    u=U.Uc(U.UC_ARCH_ARM64,U.UC_MODE_ARM)
    u.mem_map(base,0x2000000)
    unit,player,stack=base+0x2100000,base+0x2200000,base+0x2300000
    for addr in (unit,player,stack):u.mem_map(addr,0x10000)
    def put(addr,fmt,*vals):u.mem_write(addr,struct.pack(fmt,*vals))
    u.mem_write(base+0x118E9D0,C.EXPLODE_CLASS_BYTES)
    vt=base+C.FLASH_VT
    put(unit,'<Q',vt);put(unit+0x1A00,'<Q',12);put(unit+0x1A10,'<Q',player)
    put(player+0x1A00,'<Q',13);put(player+0x1EB8,'<h',1000)
    put(unit+0x1B88,'<B',1);put(unit+0x1FB8,'<Q',1);put(unit+0x1D38,'<Q',1);put(unit+0x1D5C,'<I',1)
    for k,v in enumerate((unit,12,player,13,vt,item,base+update)):
        u.reg_write(getattr(A,'UC_ARM64_REG_X'+str(k)),v)
    u.reg_write(A.UC_ARM64_REG_SP,stack+0x8000)
    u.reg_write(A.UC_ARM64_REG_LR,base+0x118EAC8)
    seen=[]
    def call(uc,addr,size,data):
        if addr==base+0x60D6D0:
            seen.append(('configure',*[uc.reg_read(getattr(A,'UC_ARM64_REG_X'+str(k))) for k in range(5)]))
            # Valid native callees may destroy all argument/scratch registers.
            for k in range(19):uc.reg_write(getattr(A,'UC_ARM64_REG_X'+str(k)),0xDEAD0000+k)
            uc.reg_write(A.UC_ARM64_REG_PC,uc.reg_read(A.UC_ARM64_REG_LR))
        elif addr==base+update:
            seen.append(('update',uc.reg_read(A.UC_ARM64_REG_X0)))
            uc.reg_write(A.UC_ARM64_REG_PC,uc.reg_read(A.UC_ARM64_REG_LR))
    u.hook_add(U.UC_HOOK_CODE,call)
    u.emu_start(base+0x118E9D0,base+0x118EAC8,count=200)
    assert seen==[('configure',unit,1,0,item,1),('update',unit)]
    assert u.reg_read(A.UC_ARM64_REG_X0)==1
    assert u.reg_read(A.UC_ARM64_REG_SP)==stack+0x8000
