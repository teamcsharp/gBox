"""Native-layout fixtures; these tests do not assert live bullet impacts."""
import math
import struct

import pytest

from gbox.mercs.titles import re4_garrador_aim as G

BASE, UNIT, PARTS, BOX = 0x3CA7C04000, 0x5D50000000, 0x5D51000000, 0x5D52000000


class Mem:
    def __init__(self):
        self.blocks = {}
        self.reads = 0
    def rd(self, at, size):
        self.reads += 1
        for address, raw in self.blocks.items():
            if address <= at and at+size <= address+len(raw):
                return bytes(raw[at-address:at-address+size])
        raise ValueError('unmapped')
    def put(self, at, fmt, *values):
        for address, raw in self.blocks.items():
            if address <= at and at+struct.calcsize(fmt) <= address+len(raw):
                struct.pack_into(fmt, raw, at-address, *values)
                return
        raise ValueError('unmapped')


def world(packed=True, native_type=10):
    m = Mem()
    m.blocks[UNIT] = bytearray(0x500)
    m.blocks[PARTS] = bytearray(G.PART_STRIDE*37)
    m.blocks[BOX] = bytearray(G.HIT_SIZE)
    m.put(UNIT, '<QI', BASE+G.ENEMY_CLASS, 1 | (0x2000 if packed else 0))
    m.put(UNIT+G.PARTS, '<Q', PARTS)
    m.put(UNIT+G.TYPE-1, '<BB', 0x1C, native_type)
    m.put(UNIT+G.HIT_ROOT+G.HIT_NEXT, '<Q', BOX)
    m.put(BOX, '<3f', 0, 50, 0)
    m.put(BOX+0x18, '<2f', 200, 0)
    m.put(BOX+0x24, '<Hh', 1, 37)
    for i in range(36):
        m.put(PARTS+i*G.PART_STRIDE+G.PART_NEXT, '<Q', PARTS+(i+1)*G.PART_STRIDE)
    part = PARTS+36*G.PART_STRIDE
    m.put(part+G.MATRIX, '<12f', 1, 0, 0, 1000, 0, 1, 0, 1200, 0, 0, 1, 1800)
    e = {'ptr':UNIT, 'pos':(1000, 0, 2000), 'rot':0., 'hp':2600, 'hp_max':2600}
    return m, e


@pytest.mark.parametrize('packed', [True, False])
@pytest.mark.parametrize('kind', [10, 13])
def test_exact_active_damage_sphere_uses_current_bone_matrix(packed, kind):
    m,e = world(packed, kind)
    w = G.read(m, BASE, e)
    assert w['point'] == pytest.approx((1000, 1250, 1800))
    assert w['radius_mm'] == 200 and w['part_no'] == 37
    assert w['native_type'] == kind
    assert G.native_type(m, BASE, e) == kind


def test_animated_rotated_scaled_sphere_not_generic_body_height():
    m,e=world()
    # Local Y becomes world -Z, local radius is doubled.
    m.put(PARTS+36*G.PART_STRIDE+G.MATRIX, '<12f', 2,0,0,1000, 0,0,2,400, 0,-2,0,1800)
    w=G.read(m,BASE,e)
    assert w['point'] == pytest.approx((1000,400,1700))
    assert w['radius_mm'] == 400


@pytest.mark.parametrize('at,fmt,values', [
    (UNIT,'<Q',(BASE+0x1234,)), (UNIT+8,'<I',(0,)), (UNIT+G.TYPE,'<B',(7,)),
    (BOX+0x24,'<H',(0,)), (BOX+0x24,'<H',(9,)), (BOX+0x26,'<h',(5,)),
    (BOX+0x18,'<f',(float('nan'),)), (BOX,'<f',(float('inf'),)),
    (BOX+G.HIT_NEXT,'<Q',(BOX,)), (UNIT+G.PARTS,'<Q',(0,)),
    (PARTS+36*G.PART_STRIDE+G.MATRIX,'<f',(float('nan'),)),
    (PARTS+36*G.PART_STRIDE+G.MATRIX+12,'<f',(1e9,)),
])
def test_unknown_disabled_cyclic_or_deformed_geometry_is_refused(at,fmt,values):
    m,e=world();m.put(at,fmt,*values)
    assert G.read(m,BASE,e) is None


def test_linked_part_cycle_is_refused_with_bounded_reads():
    m,e=world(False);m.put(PARTS+G.PART_NEXT,'<Q',PARTS)
    assert G.read(m,BASE,e) is None
    assert m.reads < 20


def test_identity_or_hit_list_change_during_read_is_refused():
    m,e=world();rd=m.rd
    def changing(at,size):
        raw=rd(at,size)
        if at == PARTS+36*G.PART_STRIDE+G.MATRIX:
            m.put(UNIT+G.HIT_ROOT+G.HIT_NEXT,'<Q',0)
        return raw
    m.rd=changing
    assert G.read(m,BASE,e) is None


def test_no_hp_only_weakpoint_and_no_infinite_laser_extension():
    m,e=world(); assert G.point(e) is None
    e['weakpoint']=G.read(m,BASE,e)
    assert G.point(e)==(1000,1250,1800)
    assert G.contact((1000,1250,0),(1000,1250,1500),e) is False
    assert G.contact((1000,1250,0),(1000,1250,1800),e) is True
    e['weakpoint']['owner']+=8
    assert G.point(e) is None


def test_rear_arc_uses_native_facing_and_rotates_with_enemy():
    _,e=world()
    assert G.rear_visible(e,(1000,1000,0)) is True
    assert G.rear_visible(e,(1000,1000,4000)) is False
    assert G.rear_goals(e)[0] == pytest.approx((1000,0,-1000))
    e['rot']=math.pi/2
    assert G.rear_goals(e)[0] == pytest.approx((-2000,0,2000))
