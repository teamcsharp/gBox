"""Fix the scanner test's fake memory: short blocks must be readable past their end.

The test failed with zero entities, and the instrumented run showed why: the name string was stored as a 15-byte block, the scanner reads 32 bytes, and the
fake's rule - return a block only when `address + length <= start + len(data)` - rejected it and returned zeros. So the scanner correctly saw an empty
class name and skipped every actor.

Two fixes, both in the test:

  * names are stored padded to 64 bytes, which is how a real memory image behaves (the string sits in a larger allocation);
  * `read` returns whatever part of a block it can and zero-fills the rest, instead of refusing.

The scanner code is untouched - it was never wrong.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\test_scanners.py")
text = path.read_text(encoding="utf-8")

old_read = '''    def read(self, address, length):
        for start, data in self.blocks.items():
            if start <= address and address + length <= start + len(data):
                offset = address - start
                return data[offset:offset + length]
        return b"\\x00" * length'''

new_read = '''    def read(self, address, length):
        """Return the readable part of a block and zero-fill the rest, as a real memory image would."""
        for start, data in self.blocks.items():
            end = start + len(data)
            if start <= address < end:
                offset = address - start
                chunk = data[offset:offset + length]
                return chunk + b"\\x00" * (length - len(chunk))
        return b"\\x00" * length'''

if old_read in text:
    text = text.replace(old_read, new_read, 1)
    print("fake read now zero-fills instead of refusing")
else:
    print("read pattern not found")

old_name = '        memory.put(name_pointer, name.encode("ascii") + b"\\x00")'
new_name = '        memory.put(name_pointer, name.encode("ascii").ljust(64, b"\\x00"))   # a name lives in a larger allocation'
if old_name in text:
    text = text.replace(old_name, new_name, 1)
    print("names padded to 64 bytes")
else:
    print("name pattern not found")

path.write_text(text, encoding="utf-8")
