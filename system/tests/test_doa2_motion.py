"""Independent synthetic format, sharing, and malformed-boundary regressions."""
import struct
import unittest

from gbox.doa2_motion import (CHANNELS, PAYLOAD_BYTES, MotionFormatError,
                         clip_offsets, inspect_mot, read_directory, read_track)


def scalar(codec=1, duration=9, base=-321, upper=0xa, final=123):
    payload = bytes(range(1, PAYLOAD_BYTES[codec] + 1))
    return (struct.pack('<Hh', (upper << 12) | (duration << 2) | codec, base)
            + payload + struct.pack('<Hh', 0, final))


def fixture(*, layout='indexed', tracks=None, tables=None, references=None,
            ids=None, gaps=None):
    """Lay out streams before native channel tables with independently set IDs."""
    tracks = tracks if tracks is not None else [scalar(codec=i % 4, base=-i)
                                               for i in range(CHANNELS)]
    tables = tables if tables is not None else [list(range(CHANNELS))]
    references = references if references is not None else list(range(len(tables)))
    ids = ids if ids is not None else [700 + i for i in range(len(references))]
    entry_bytes = 4 if layout == 'indexed' else 8
    directory_end = entry_bytes * (len(references) + 1)
    data = bytearray(directory_end)
    starts = []
    for i, track in enumerate(tracks):
        starts.append(len(data))
        data.extend(track)
        data.extend((gaps or {}).get(i, b''))
        if len(data) % 4:
            data.extend(b'\0\0')
    table_offsets = []
    for table in tables:
        if len(table) != CHANNELS:
            raise ValueError('The fixture requires 44 channel references')
        table_offsets.append(len(data))
        data.extend(struct.pack('<44I', *(starts[i] for i in table)))
    for i, reference in enumerate(references):
        if layout == 'indexed':
            struct.pack_into('<I', data, i * 4, table_offsets[reference])
        else:
            struct.pack_into('<II', data, i * 8, ids[i], table_offsets[reference])
    if layout == 'paired':
        struct.pack_into('<II', data, directory_end - 8, 0xffffffff, 0)
    return data, starts, table_offsets


class MotionRecords(unittest.TestCase):
    def test_all_codecs_preserve_unknown_payload_and_signed_values(self):
        for codec in range(4):
            with self.subTest(codec=codec):
                data = scalar(codec=codec)
                track = read_track(data, 0, len(data))
                record = track['records'][0]
                self.assertEqual(record['codec'], codec)
                self.assertEqual(record['duration'], 9)
                self.assertEqual(record['signed_base'], -321)
                self.assertEqual(record['upper_nibble'], 0xa)
                self.assertEqual(record['payload_hex'], bytes(range(1, PAYLOAD_BYTES[codec] + 1)).hex())
                self.assertEqual(track['final_value'], 123)
                self.assertEqual(track['duration'], 9)

    def test_multi_record_duration_and_terminal_header_retained(self):
        data = scalar(codec=0, duration=3)[:-4] + scalar(codec=3, duration=5)
        data = data[:-4] + struct.pack('<Hh', 0xb000, -123)
        track = read_track(data, 0, len(data))
        self.assertEqual(track['duration'], 8)
        self.assertEqual(track['final_value'], -123)
        self.assertEqual(track['terminator_header'], 0xb000)

    def test_constant_track_is_not_a_skeleton_bone(self):
        data = struct.pack('<Hh', 0, -50)
        track = read_track(data, 0, 4)
        self.assertEqual(track['duration'], 0)
        self.assertEqual(track['records'], [])
        self.assertEqual(track['final_value'], -50)

    def test_two_zero_alignment_bytes_are_allowed(self):
        data = scalar(codec=2) + b'\0\0'
        track = read_track(data, 0, len(data))
        self.assertEqual(track['padding'], 2)
        self.assertEqual(track['unreferenced_tail_bytes'], 0)

    def test_nonzero_tail_is_only_allowed_when_explicitly_requested(self):
        data = scalar() + b'opaque'
        with self.assertRaisesRegex(MotionFormatError, 'trailing'):
            read_track(data, 0, len(data))
        track = read_track(data, 0, len(data), allow_tail=True)
        self.assertEqual(track['end'], len(scalar()))
        self.assertEqual(track['unreferenced_tail_bytes'], 6)

    def test_invalid_bounds(self):
        for start, end in [(-2, 4), (1, 4), (0, 3), (4, 4), (0, 10)]:
            with self.subTest(bounds=(start, end)), self.assertRaises(MotionFormatError):
                read_track(bytes(8), start, end)

    def test_missing_terminal_record(self):
        data = scalar(codec=3)[:-4]
        with self.assertRaisesRegex(MotionFormatError, 'terminator'):
            read_track(data, 0, len(data))

    def test_truncated_polynomial_payload(self):
        data = struct.pack('<Hh', 4, 1) + b'\0\0'
        with self.assertRaisesRegex(MotionFormatError, 'Truncated'):
            read_track(data, 0, len(data))

    def test_nonterminal_zero_duration_rejected(self):
        for codec in (1, 2, 3):
            data = struct.pack('<Hh', codec, 1) + bytes(6)
            with self.subTest(codec=codec), self.assertRaisesRegex(MotionFormatError, 'zero-duration'):
                read_track(data, 0, len(data))


class MotionContainers(unittest.TestCase):
    def test_indexed_file_counts_channels_and_reports_limits(self):
        data, starts, tables = fixture()
        result = inspect_mot(data, include_clips=True, include_tracks=True)
        self.assertEqual(result['format'], 'doa2-indexed-mot-44')
        self.assertEqual(result['validated_tracks'], 44)
        self.assertEqual(result['unique_tracks'], 44)
        self.assertEqual(result['record_codecs'], {0: 11, 1: 11, 2: 11, 3: 11})
        self.assertEqual(result['clip_ids'], [0])
        self.assertEqual(result['clip_offsets'], tables)
        self.assertFalse(result['animation_interpolation_decoded'])
        self.assertEqual(len(result['tracks']), 44)
        self.assertEqual(result['unreferenced_bytes'], 0)
        self.assertEqual(result['first_clip_signed_bases'], [-i for i in range(44)])

    def test_paired_clip_ids_are_preserved(self):
        data, _, tables = fixture(layout='paired', references=[0, 0], ids=[701, 706])
        result = inspect_mot(data, include_clips=True)
        self.assertEqual(result['format'], 'doa2-paired-mot-44')
        self.assertEqual(result['clip_ids'], [701, 706])
        self.assertEqual(result['clip_offsets'], [tables[0], tables[0]])
        self.assertEqual(result['clips'], 2)
        self.assertEqual(result['unique_clips'], 1)
        self.assertEqual(read_directory(data, layout='paired')['end'], 24)

    def test_shared_indexed_clip_tables_are_not_redecoded(self):
        data, _, tables = fixture(references=[0, 0, 0])
        result = inspect_mot(data)
        self.assertEqual(result['clips'], 3)
        self.assertEqual(result['unique_clips'], 1)
        self.assertEqual(result['validated_tracks'], 44)
        self.assertEqual(clip_offsets(data), [tables[0]] * 3)

    def test_shared_and_reordered_channels(self):
        mapping = [i % 3 for i in reversed(range(44))]
        data, starts, _ = fixture(tracks=[scalar(base=-10), scalar(base=20), scalar(base=30)],
                                  tables=[mapping])
        result = inspect_mot(data, include_clips=True)
        self.assertEqual(result['unique_tracks'], 3)
        self.assertEqual(result['validated_tracks'], 44)
        self.assertEqual(result['first_clip_signed_bases'], [[-10, 20, 30][i] for i in mapping])
        self.assertEqual(result['clip_tables'][0]['channel_offsets'], [starts[i] for i in mapping])

    def test_unreferenced_bytes_remain_opaque(self):
        data, _, _ = fixture(gaps={1: b'opaque!!'})
        result = inspect_mot(data)
        self.assertEqual(result['unreferenced_bytes'], 8)
        self.assertEqual(len(result['unreferenced_ranges']), 1)
        self.assertEqual(result['unreferenced_ranges'][0]['bytes'], 8)

    def test_channel_pointer_outside_valid_regions(self):
        original, starts, tables = fixture()
        for pointer in [0, 2, starts[0] + 1, tables[0], len(original), len(original) + 4]:
            data = bytearray(original)
            struct.pack_into('<I', data, tables[0], pointer)
            with self.subTest(pointer=pointer), self.assertRaises(MotionFormatError):
                inspect_mot(data)

    def test_pointer_inside_another_stream_is_not_accepted(self):
        data, starts, tables = fixture()
        struct.pack_into('<I', data, tables[0] + 4, starts[0] + 4)
        with self.assertRaises(MotionFormatError):
            inspect_mot(data)

    def test_channels_must_agree_on_duration(self):
        tracks = [scalar(duration=9), scalar(duration=8)]
        data, _, _ = fixture(tracks=tracks, tables=[[0] * 43 + [1]])
        with self.assertRaisesRegex(MotionFormatError, 'disagree on duration'):
            inspect_mot(data)

    def test_clip_table_cannot_overlap_directory(self):
        data, _, _ = fixture()
        struct.pack_into('<I', data, 0, 4)
        with self.assertRaisesRegex(MotionFormatError, 'overlaps its directory'):
            inspect_mot(data, layout='indexed')

    def test_clip_tables_cannot_overlap_each_other(self):
        data, _, tables = fixture(tables=[list(range(44)), list(range(44))])
        struct.pack_into('<I', data, 4, tables[0] + 4)
        with self.assertRaisesRegex(MotionFormatError, 'Overlapping MOT clip tables'):
            inspect_mot(data, layout='indexed')

    def test_missing_directory_terminator_rejected(self):
        for data in [b'', struct.pack('<I', 0), b'\xff' * 16]:
            with self.subTest(data=data), self.assertRaises(MotionFormatError):
                inspect_mot(data)

    def test_duplicate_paired_ids_rejected(self):
        data, _, _ = fixture(layout='paired', references=[0, 0], ids=[700, 700])
        with self.assertRaisesRegex(MotionFormatError, 'Duplicate paired'):
            inspect_mot(data, layout='paired')

    def test_nonzero_paired_sentinel_rejected(self):
        data, _, _ = fixture(layout='paired')
        struct.pack_into('<I', data, 12, 4)
        with self.assertRaisesRegex(MotionFormatError, 'Nonzero paired'):
            inspect_mot(data, layout='paired')

    def test_wrong_explicit_layout_and_invalid_option_rejected(self):
        data, _, _ = fixture(layout='paired')
        with self.assertRaises(MotionFormatError):
            inspect_mot(data, layout='indexed')
        with self.assertRaisesRegex(ValueError, 'layout must'):
            inspect_mot(data, layout='guess')


if __name__ == '__main__':
    unittest.main()
