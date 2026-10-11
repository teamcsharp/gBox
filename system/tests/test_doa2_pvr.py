"""Documented PVR header fields and exact allocation-preserving conversion."""
import copy
import struct

import pytest

from gbox import doa2_materials as A
from gbox import doa2_pvr as H
from test_doa2_materials import fixture, primitive


def test_synthesis_requires_explicit_opt_in():
    archive, binary = fixture([(8,8,1,1)])
    tex = A.T.descriptors(A.texture_directory(archive),binary)[0]
    with pytest.raises(ValueError,match='opt-in'):
        H.build_header(archive['models'][0]['meshes'][0]['header'],tex)


@pytest.mark.parametrize('shape,fmt', [((8,8),1),((128,64),13),((64,64),3)])
def test_synthesized_translucent_flags_match_native_descriptor(shape,fmt):
    archive,binary = fixture([(*shape,2,fmt,0)])
    tex = A.T.descriptors(A.texture_directory(archive),binary)[0]
    template = archive['models'][0]['meshes'][0]['header']
    result = H.build_header(template,tex,alpha='graded',validated_opt_in=True)
    pcw,isp,tsp,tcw = struct.unpack_from('<4I',result)
    assert ((pcw>>24)&7)==2 and pcw&8 and isp&(1<<25)
    assert ((tsp>>29)&7, (tsp>>26)&7)==(4,5)
    assert not tsp&(1<<19)
    assert (8<<((tsp>>3)&7),8<<(tsp&7))==shape
    assert ((tsp>>6)&3)==1
    assert ((tcw>>27)&7)==2 and bool(tcw&(1<<30))==(fmt==3)
    assert not tcw&((1<<31)|(1<<26)|(1<<25)|0x1ffffff)
    assert result[16:32]==template[16:32] and result[36:]==template[36:]


def test_normalized_opaque_header_ignores_alpha_and_keeps_geometry_layout():
    archive,binary=fixture([(8,8,2,1)])
    tex=A.T.descriptors(A.texture_directory(archive),binary)[0]
    template=archive['models'][0]['meshes'][0]['header']
    result=H.build_header(template,tex,alpha='opaque',validated_opt_in=True)
    pcw,isp,tsp,tcw=struct.unpack_from('<4I',result)
    assert (pcw>>24)&7==0
    assert (tsp>>29)&7==1 and (tsp>>26)&7==0 and tsp&(1<<19)
    assert (pcw&~(7<<24))==(struct.unpack_from('<I',template)[0]&~(7<<24))
    assert result[36:]==template[36:]


def test_synthesis_repairs_existing_header_dimension_mismatch():
    archive,binary=fixture([(64,64,1,1)])
    h=bytearray(archive['models'][0]['meshes'][0]['header'])
    struct.pack_into('<I',h,8,0x20282452)  # Stored32², descriptor64².
    archive['models'][0]['meshes'][0]['header']=bytes(h)
    with pytest.raises(A.MaterialCapacityError):
        A.allocate(archive,binary,[primitive(shape=(64,64))])
    result=A.allocate(archive,binary,[primitive(shape=(64,64))],synthesize_headers=True)
    assert result['materials'][0]['synthetic_header']
    assert result['descriptor_bytes']==b''.join(struct.pack('<3I',*d) for d in archive['textures'])


def test_existing_rgb_allocation_converts_to_argb4444_with_single_descriptor_byte_change():
    archive,binary=fixture([(8,8,1,1),(8,8,1,1)])
    original=copy.deepcopy(archive)
    source=primitive(alpha=136)
    with pytest.raises(A.MaterialCapacityError):
        A.allocate(archive,binary,[source],synthesize_headers=True)
    result=A.allocate(archive,binary,[source],synthesize_headers=True,retype_argb4444=True)
    assert archive==original
    slot=result['materials'][0]['texture_id']
    old_desc=b''.join(struct.pack('<3I',*d) for d in archive['textures'])
    assert [i for i,(old,new) in enumerate(zip(old_desc,result['descriptor_bytes'])) if old!=new]==[slot*12+4]
    updated=A.T.descriptors(A.texture_directory({'textures':result['textures']}),result['bin_data'])
    assert updated[slot].size==A.T.descriptors(A.texture_directory(archive),binary)[slot].size
    assert A.T.decode(updated[slot],result['bin_data']).getpixel((0,0))[3]==136
    other=1-slot
    assert result['bin_data'][updated[other].offset:updated[other].offset+updated[other].size]==binary[updated[other].offset:updated[other].offset+updated[other].size]
    assert len(result['bin_data'])==len(binary)


def test_vq_argb_conversion_preserves_payload_capacity_and_transparency():
    archive,binary=fixture([(8,8,1,3)])
    result=A.allocate(archive,binary,[primitive(alpha=136)],synthesize_headers=True,retype_argb4444=True)
    tex=A.T.descriptors(A.texture_directory({'textures':result['textures']}),result['bin_data'])[0]
    assert tex.pixel==2 and tex.format==3 and tex.size==2064
    assert A.T.decode(tex,result['bin_data']).getpixel((0,0))[3]==136


def test_conversion_requires_header_synthesis_and_respects_retained_slot_protection():
    archive,binary=fixture([(8,8,1,1)])
    with pytest.raises(ValueError,match='header synthesis'):
        A.allocate(archive,binary,[primitive(alpha=136)],retype_argb4444=True)
    with pytest.raises(A.MaterialCapacityError):
        A.allocate(archive,binary,[primitive(alpha=136)],synthesize_headers=True,retype_argb4444=True,excluded_slots=[0])


def test_fixed_vram_template_and_impossible_pixel_quality_are_rejected():
    archive,binary=fixture([(8,8,1,1)])
    tex=A.T.descriptors(A.texture_directory(archive),binary)[0]
    template=bytearray(archive['models'][0]['meshes'][0]['header'])
    struct.pack_into('<I',template,12,(1<<27)|8)
    with pytest.raises(ValueError,match='fixed VRAM'):
        H.build_header(bytes(template),tex,validated_opt_in=True)
    with pytest.raises(ValueError,match='ARGB4444'):
        H.build_header(archive['models'][0]['meshes'][0]['header'],tex,alpha='graded',validated_opt_in=True)


def test_sampler_sets_both_axis_modes_and_preserves_other_material_fields():
    from gbox.doa2_pvr import sampler
    header=bytes(range(80))
    modified=sampler(header,(33071,33648))
    assert modified[:8]==header[:8] and modified[12:]==header[12:]
    mode=struct.unpack_from('<I',modified,8)[0]
    assert mode & (1<<16) and mode & (1<<17)
    assert not mode & ((1<<15)|(1<<18))
    repeat=sampler(modified)
    assert not struct.unpack_from('<I',repeat,8)[0] & sum(1<<b for b in (15,16,17,18))
