import math
import struct
import unittest

from gbox.doa2_motion import (MotionFormatError,inspect_mot,read_track,quantized_base,
                         scalar_polynomials,evaluate_scalar)
from gbox.doa2_motion_alternate import (LEGACY_TRIPLES,LEGACY_PAIRS,read_float_track)
from tests.test_doa2_motion import fixture,scalar


def header(base,duration,codec=0):
    bits=base&0xfffff
    return struct.pack('<HH',((bits>>16)<<12)|(duration<<2)|codec,bits&0xffff)


def legacy_fixture(duration=3):
    data=bytearray(8);starts=[]
    for i in range(26):
        starts.append(len(data))
        if i in LEGACY_TRIPLES or i in LEGACY_PAIRS:
            n=3 if i in LEGACY_TRIPLES else 2
            data.extend(struct.pack('<%dh'%(n*(duration+1)),*[i+v for v in range(n*(duration+1))]))
        else:
            data.extend(header(-10000,duration)+struct.pack('<2f',.125,-.25)+header(10000,0))
        if len(data)%4:data.extend(bytes(2))
    table=len(data);data.extend(struct.pack('<26I',*starts));struct.pack_into('<I',data,0,table)
    return data,starts,table


class NativeQuantization(unittest.TestCase):
    def test_signed_twenty_bit_base_uses_header_nibble(self):
        for value in (-524288,-131073,-10000,0,65536,524287):
            h,w=struct.unpack('<HH',header(value,4))
            self.assertEqual(quantized_base(h,w),value)
        self.assertEqual(quantized_base(0xf000,0),-65536)

    def test_native_linear_endpoint_and_midpoint(self):
        d=header(-10000,4,1)+header(10000,0)
        track=read_track(d,0,len(d))
        self.assertAlmostEqual(evaluate_scalar(track,0),-1,places=6)
        self.assertAlmostEqual(evaluate_scalar(track,2),0,places=6)
        self.assertAlmostEqual(evaluate_scalar(track,4),1,places=6)

    def test_native_quadratic_signed_coefficient(self):
        d=header(0,4,2)+struct.pack('<h',1024)+header(10000,0)
        p=scalar_polynomials(read_track(d,0,len(d)))[0]['coefficients']
        self.assertAlmostEqual(p[2],-.03125)
        self.assertAlmostEqual(p[1],.375,places=6)
        self.assertAlmostEqual(p[0]+p[1]*4+p[2]*16,1,places=6)

    def test_native_hermite16_endpoints_and_derivatives(self):
        d=header(0,4,3)+struct.pack('<2h',16384,-16384)+header(10000,0)
        p=scalar_polynomials(read_track(d,0,len(d)))[0]['coefficients']
        self.assertEqual(p[1],.125)
        self.assertAlmostEqual(p[0]+p[1]*4+p[2]*16+p[3]*64,1,places=6)
        self.assertAlmostEqual(p[1]+2*p[2]*4+3*p[3]*16,-.125)

    def test_native_hermite24_packed_byte_order_and_sign(self):
        a,b=250000,(-125000)&0xffffff
        payload=struct.pack('<3H',a&0xffff,((b>>16)<<8)|(a>>16),b&0xffff)
        d=header(0,4,0)+payload+header(10000,0)
        p=scalar_polynomials(read_track(d,0,len(d)))[0]['coefficients']
        self.assertAlmostEqual(p[1],.25,places=6)
        self.assertAlmostEqual(p[1]+2*p[2]*4+3*p[3]*16,-.125,places=6)

    def test_evaluation_rejects_out_of_range_and_raw_samples(self):
        track=read_track(header(10,0),0,4)
        with self.assertRaises(MotionFormatError):evaluate_scalar(track,-.1)
        with self.assertRaises(MotionFormatError):evaluate_scalar(track,.1)
        with self.assertRaises(MotionFormatError):scalar_polynomials({'encoding':'raw-i16x3'})


class AlternateContainers(unittest.TestCase):
    def test_shared_xyz_stream_count_is_independently_bounded(self):
        tracks=[scalar(duration=3) for _ in range(42)]
        tracks[3]=struct.pack('<12h',*range(12))
        mapping=[0,1,2,3,3,3]+list(range(4,42))
        data,_,_=fixture(tracks=tracks,tables=[mapping])
        result=inspect_mot(data,include_tracks=True,encoding='compact44')
        self.assertEqual(result['raw_vector_tracks'],1)
        raw=next(t for t in result['tracks'] if t['encoding']=='raw-i16x3')
        self.assertEqual(raw['first_sample'],[0,1,2])
        self.assertEqual(raw['samples'],4)
        self.assertFalse(raw['runtime_consumer_verified'])

    def test_legacy26_has_exact_zero_gap_44_component_partition(self):
        d,_,_=legacy_fixture()
        r=inspect_mot(d,include_tracks=True)
        self.assertEqual(r['format'],'doa2-indexed-mot-legacy26')
        self.assertEqual(r['stream_encodings'],{'raw-i16x3':7,'raw-i16x2':4,'legacy-float-coefficients':15})
        self.assertEqual(r['scalar_components_per_clip'],44)
        self.assertEqual(r['unreferenced_bytes'],0)
        self.assertEqual(r['unique_tracks'],26)
        self.assertFalse(r['runtime_consumer_verified'])

    def test_legacy_raw_alignment_is_exact_zero_padding(self):
        d,_,_=legacy_fixture(2)
        r=inspect_mot(d,include_tracks=True,encoding='legacy26')
        self.assertEqual(r['unreferenced_bytes'],0)
        self.assertEqual(sum(t['padding'] for t in r['tracks']),14)

    def test_legacy_shared_stream_kind_conflict_rejected(self):
        d,starts,t=legacy_fixture()
        struct.pack_into('<I',d,t+3*4,starts[0])
        with self.assertRaisesRegex(MotionFormatError,'different component count'):
            inspect_mot(d,encoding='legacy26')

    def test_legacy_nonfinite_coefficients_rejected(self):
        d,starts,_=legacy_fixture()
        struct.pack_into('<f',d,starts[3]+4,math.inf)
        with self.assertRaisesRegex(MotionFormatError,'Nonfinite'):
            inspect_mot(d,encoding='legacy26')

    def test_legacy_scalar_duration_mismatch_and_short_raw_rejected(self):
        d,starts,_=legacy_fixture()
        struct.pack_into('<H',d,starts[3],8)
        with self.assertRaisesRegex(MotionFormatError,'durations disagree'):
            inspect_mot(d,encoding='legacy26')
        d,starts,_=legacy_fixture()
        for i in range(26):
            if i not in LEGACY_TRIPLES+LEGACY_PAIRS:
                h=struct.unpack_from('<H',d,starts[i])[0]
                struct.pack_into('<H',d,starts[i],(h&0xf000)|16)
        with self.assertRaisesRegex(MotionFormatError,'Truncated legacy raw'):
            inspect_mot(d,encoding='legacy26')

    def test_legacy_float_bits_retained_without_claiming_runtime(self):
        d=header(-10000,3)+struct.pack('<2f',.125,-.25)+header(10000,0)
        t=read_float_track(d,0,len(d))
        self.assertEqual(t['records'][0]['payload_hex'],struct.pack('<2f',.125,-.25).hex())
        self.assertEqual(t['records'][0]['quantized_base'],-10000)
        self.assertFalse(t['runtime_consumer_verified'])


if __name__=='__main__':unittest.main()
