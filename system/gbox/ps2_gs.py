"""A small model of the PS2 GS local memory: page / block / column swizzles for PSMCT32, PSMT8 and PSMT4, so texture
data that a game uploads as one format can be read back as another (MGS2 uploads its texture packs page-linearly as
PSMCT32 and samples them as PSMT8 / PSMT4 with CLUTs).

Addressing (GS User's Manual, "Memory arrangement"): a page is 8 KiB (PSMCT32 64 x 32, PSMT8 128 x 64, PSMT4
128 x 128), 32 blocks of 256 bytes; the block number of a pixel comes from a fixed block table and is added to the
buffer base pointer (BP, in blocks), the byte inside the block from a fixed column table. The PSMCT32 and PSMT4 tables
are the GS manual's (the same as PCSX2's GSTables); the PSMT8 in-page table is derived here from the PSMCT32 one through
the classic unswizzle8 relation (an 8-bit W x H texture uploaded as a W/2 x H/2 PSMCT32 image), and the test suite
checks it against the published table.
"""
from __future__ import annotations

import numpy as np

PAGE = 8192
BLOCK = 256

BT32 = np.array([[0, 1, 4, 5, 16, 17, 20, 21], [2, 3, 6, 7, 18, 19, 22, 23],
                 [8, 9, 12, 13, 24, 25, 28, 29], [10, 11, 14, 15, 26, 27, 30, 31]])
CT32 = np.array([[0, 1, 4, 5, 8, 9, 12, 13], [2, 3, 6, 7, 10, 11, 14, 15],
                 [16, 17, 20, 21, 24, 25, 28, 29], [18, 19, 22, 23, 26, 27, 30, 31],
                 [32, 33, 36, 37, 40, 41, 44, 45], [34, 35, 38, 39, 42, 43, 46, 47],
                 [48, 49, 52, 53, 56, 57, 60, 61], [50, 51, 54, 55, 58, 59, 62, 63]])
BT4 = np.array([[0, 2, 8, 10], [1, 3, 9, 11], [4, 6, 12, 14], [5, 7, 13, 15],
                [16, 18, 24, 26], [17, 19, 25, 27], [20, 22, 28, 30], [21, 23, 29, 31]])


# PSMT4 column table: nibble index inside a 32 x 16 block (GS manual / PCSX2 columnTable4)
CT4 = np.array([
    [0, 8, 32, 40, 64, 72, 96, 104, 2, 10, 34, 42, 66, 74, 98, 106, 4, 12, 36, 44, 68, 76, 100, 108, 6, 14, 38, 46, 70, 78, 102, 110],
    [16, 24, 48, 56, 80, 88, 112, 120, 18, 26, 50, 58, 82, 90, 114, 122, 20, 28, 52, 60, 84, 92, 116, 124, 22, 30, 54, 62, 86, 94, 118, 126],
    [65, 73, 97, 105, 1, 9, 33, 41, 67, 75, 99, 107, 3, 11, 35, 43, 69, 77, 101, 109, 5, 13, 37, 45, 71, 79, 103, 111, 7, 15, 39, 47],
    [81, 89, 113, 121, 17, 25, 49, 57, 83, 91, 115, 123, 19, 27, 51, 59, 85, 93, 117, 125, 21, 29, 53, 61, 87, 95, 119, 127, 23, 31, 55, 63],
    [192, 200, 224, 232, 128, 136, 160, 168, 194, 202, 226, 234, 130, 138, 162, 170, 196, 204, 228, 236, 132, 140, 164, 172, 198, 206, 230, 238, 134, 142, 166, 174],
    [208, 216, 240, 248, 144, 152, 176, 184, 210, 218, 242, 250, 146, 154, 178, 186, 212, 220, 244, 252, 148, 156, 180, 188, 214, 222, 246, 254, 150, 158, 182, 190],
    [129, 137, 161, 169, 193, 201, 225, 233, 131, 139, 163, 171, 195, 203, 227, 235, 133, 141, 165, 173, 197, 205, 229, 237, 135, 143, 167, 175, 199, 207, 231, 239],
    [145, 153, 177, 185, 209, 217, 241, 249, 147, 155, 179, 187, 211, 219, 243, 251, 149, 157, 181, 189, 213, 221, 245, 253, 151, 159, 183, 191, 215, 223, 247, 255],
    [256, 264, 288, 296, 320, 328, 352, 360, 258, 266, 290, 298, 322, 330, 354, 362, 260, 268, 292, 300, 324, 332, 356, 364, 262, 270, 294, 302, 326, 334, 358, 366],
    [272, 280, 304, 312, 336, 344, 368, 376, 274, 282, 306, 314, 338, 346, 370, 378, 276, 284, 308, 316, 340, 348, 372, 380, 278, 286, 310, 318, 342, 350, 374, 382],
    [321, 329, 353, 361, 257, 265, 289, 297, 323, 331, 355, 363, 259, 267, 291, 299, 325, 333, 357, 365, 261, 269, 293, 301, 327, 335, 359, 367, 263, 271, 295, 303],
    [337, 345, 369, 377, 273, 281, 305, 313, 339, 347, 371, 379, 275, 283, 307, 315, 341, 349, 373, 381, 277, 285, 309, 317, 343, 351, 375, 383, 279, 287, 311, 319],
    [448, 456, 480, 488, 384, 392, 416, 424, 450, 458, 482, 490, 386, 394, 418, 426, 452, 460, 484, 492, 388, 396, 420, 428, 454, 462, 486, 494, 390, 398, 422, 430],
    [464, 472, 496, 504, 400, 408, 432, 440, 466, 474, 498, 506, 402, 410, 434, 442, 468, 476, 500, 508, 404, 412, 436, 444, 470, 478, 502, 510, 406, 414, 438, 446],
    [385, 393, 417, 425, 449, 457, 481, 489, 387, 395, 419, 427, 451, 459, 483, 491, 389, 397, 421, 429, 453, 461, 485, 493, 391, 399, 423, 431, 455, 463, 487, 495],
    [401, 409, 433, 441, 465, 473, 497, 505, 403, 411, 435, 443, 467, 475, 499, 507, 405, 413, 437, 445, 469, 477, 501, 509, 407, 415, 439, 447, 471, 479, 503, 511]])



def _page32() -> np.ndarray:
    y, x = np.mgrid[0:32, 0:64]
    return BT32[y // 8, x // 8] * 64 + CT32[y % 8, x % 8]          # word index in the page


P32 = _page32()


def unswizzle8_index(w: int, h: int) -> np.ndarray:
    """Byte offset of each pixel of an 8-bit w x h texture inside the w/2 x h/2 PSMCT32 image it was uploaded as."""
    y, x = np.mgrid[0:h, 0:w]
    block_location = (y & ~0xF) * w + (x & ~0xF) * 2
    swap_selector = (((y + 2) >> 2) & 1) * 4
    pos_y = (((y & ~3) >> 1) + (y & 1)) & 7
    column_location = pos_y * w * 2 + ((x + swap_selector) & 7) * 4
    byte_num = ((y >> 1) & 1) + ((x >> 2) & 2)
    return block_location + column_location + byte_num


def _page8() -> np.ndarray:
    o = unswizzle8_index(128, 64)
    px, py, bt = (o // 4) % 64, (o // 4) // 64, o % 4
    return P32[py, px] * 4 + bt                                       # byte index in the page


P8 = _page8()


def _page4() -> np.ndarray:
    y, x = np.mgrid[0:128, 0:128]
    return BT4[y // 16, x // 32] * 512 + CT4[y % 16, x % 32]          # nibble index in the page


P4 = _page4()


class GSMemory:
    """Byte array standing for GS local memory (or one region of it: block addresses relative to its start)."""

    def __init__(self, size: int = 4 << 20):
        self.m = np.zeros(size, np.uint8)

    # -- address helpers
    def addr32(self, bp: int, bw: int, x, y):
        page = (y // 32) * max(bw, 1) + x // 64
        return (bp * BLOCK + page * PAGE + P32[y % 32, x % 64] * 4) % len(self.m)

    def addr8(self, bp: int, bw: int, x, y):
        page = (y // 64) * max(bw // 2, 1) + x // 128
        return (bp * BLOCK + page * PAGE + P8[y % 64, x % 128]) % len(self.m)

    def nib4(self, bp: int, bw: int, x, y):
        page = (y // 128) * max(bw // 2, 1) + x // 128
        return (bp * BLOCK * 2 + page * PAGE * 2 + P4[y % 128, x % 128]) % (2 * len(self.m))

    # -- transfers
    def write32(self, data: bytes, bp: int, bw: int, w: int, h: int):
        a = np.frombuffer(bytes(data), np.uint8)[:w * h * 4].reshape(h, w, 4)
        y, x = np.mgrid[0:h, 0:w]
        ad = self.addr32(bp, bw, x, y)
        for k in range(4):
            self.m[ad + k] = a[..., k]

    def read32(self, bp: int, bw: int, w: int, h: int) -> np.ndarray:
        y, x = np.mgrid[0:h, 0:w]
        ad = self.addr32(bp, bw, x, y)
        return np.stack([self.m[ad + k] for k in range(4)], -1)

    def write8(self, idx: np.ndarray, bp: int, bw: int):
        h, w = idx.shape
        y, x = np.mgrid[0:h, 0:w]
        self.m[self.addr8(bp, bw, x, y)] = idx

    def read8(self, bp: int, bw: int, w: int, h: int) -> np.ndarray:
        y, x = np.mgrid[0:h, 0:w]
        return self.m[self.addr8(bp, bw, x, y)]

    def read4(self, bp: int, bw: int, w: int, h: int) -> np.ndarray:
        y, x = np.mgrid[0:h, 0:w]
        n = self.nib4(bp, bw, x, y)
        v = self.m[n // 2]
        return np.where(n & 1, v >> 4, v & 15).astype(np.uint8)

    def write4(self, idx: np.ndarray, bp: int, bw: int):
        h, w = idx.shape
        y, x = np.mgrid[0:h, 0:w]
        n = self.nib4(bp, bw, x, y).reshape(-1)
        v = idx.reshape(-1).astype(np.uint8) & 15
        b = n // 2
        lo = (n & 1) == 0
        self.m[b[lo]] = (self.m[b[lo]] & 0xF0) | v[lo]
        self.m[b[~lo]] = (self.m[b[~lo]] & 0x0F) | (v[~lo] << 4)

    # -- page-linear PSMCT32 regions (how MGS2 packs upload: 64 pixels wide, page after page)
    def load_linear(self, data: bytes, bp: int = 0):
        n = len(data) // BLOCK
        self.write32(data[:n * BLOCK], bp, 1, 64, n)

    def dump_linear(self, bp: int, blocks: int) -> bytes:
        return self.read32(bp, 1, 64, blocks).tobytes()


def csm1(pal: np.ndarray) -> np.ndarray:
    """A 256-entry CSM1 CLUT as stored (entries 8-15 and 16-23 of every 32 swapped) <-> in index order."""
    k = np.arange(256)
    return pal[(k & ~0x18) | ((k & 0x08) << 1) | ((k & 0x10) >> 1)]


def alpha_to_8bit(pal: np.ndarray) -> np.ndarray:
    """GS alpha (0x80 = opaque) -> 0..255."""
    out = pal.copy()
    out[..., 3] = np.clip(pal[..., 3].astype(int) * 2, 0, 255).astype(np.uint8)
    return out


def alpha_to_gs(pal: np.ndarray) -> np.ndarray:
    out = pal.copy()
    out[..., 3] = ((pal[..., 3].astype(int) + 1) // 2).astype(np.uint8)
    return out
