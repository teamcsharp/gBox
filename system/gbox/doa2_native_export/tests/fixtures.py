import struct

def synthetic_chain(style=1):
    data=bytearray(180)
    struct.pack_into('<4I',data,0,1,32,255,0)
    struct.pack_into('<4B',data,32,3,1,0,style)
    struct.pack_into('<14f',data,36,.25,.1,1,.3,1,2,3,0,0,-1,.5,0,1,.05)
    struct.pack_into('<I',data,32+0x44,140)
    struct.pack_into('<3H',data,140,7,7,8)
    return data

def synthetic_prop(kind=1,parent=5):
    data=bytearray(96);struct.pack_into('<4I',data,0,0,32,255,0)
    struct.pack_into('<4B',data,32,kind,parent,0,0)
    struct.pack_into('<3f',data,32+0x1c,1,2,3)
    struct.pack_into('<3hH',data,32+0x28,0,0,16384,7)
    return data
