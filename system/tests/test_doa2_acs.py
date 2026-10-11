import struct
import unittest

from gbox.doa2_acs import EMPTY_DIRECTIVE, disable_acs, inspect_acs


class NativeAcsTermination(unittest.TestCase):
    def test_native_empty_padding_preserved(self):
        original = EMPTY_DIRECTIVE + bytes(2)
        patched, report = disable_acs(original)
        self.assertEqual(patched, original)
        self.assertEqual(report['changed_bytes'], 0)
        self.assertEqual(inspect_acs(patched)['directive_count'], 0)

    def test_directory_disabled_without_mutating_geometry_payload(self):
        original = (struct.pack('<II', 2, 24) + struct.pack('<II', 253, 28)
                    + EMPTY_DIRECTIVE + bytes(range(32)))
        patched, report = disable_acs(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched[8:], original[8:])
        self.assertEqual(patched[:8], EMPTY_DIRECTIVE)
        self.assertEqual(report['before']['directive_count'], 2)
        self.assertEqual(inspect_acs(patched)['directive_count'], 0)

    def test_native_low_byte_terminator(self):
        data = struct.pack('<II', 0x123400ff, 0xdeadbeef)
        self.assertEqual(inspect_acs(data)['directive_count'], 0)

    def test_uninterpreted_argument_is_reported_verbatim(self):
        data = struct.pack('<II', 254, 1) + EMPTY_DIRECTIVE
        self.assertEqual(inspect_acs(data)['directives'][0]['argument'], 1)

    def test_no_silent_unbounded_or_truncated_directory(self):
        for data in (bytes(7), struct.pack('<II', 2, 16),
                     struct.pack('<II', 2, 16) + b'\xff'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                disable_acs(data)


if __name__ == '__main__':
    unittest.main()
