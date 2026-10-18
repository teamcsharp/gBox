"""Read-only evidence for RE5 PS3's single-technique standard-material BFX.

This maps material function bits to bounded Cg programs and records direct
instruction inputs. It does not emulate shaders, bind runtime vertex buffers,
repair UVs, or establish native rendering. See docs/re5ps3-shaders.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from .re5ps3_arc import Arc

MAX_BYTES = 64 * 1024 * 1024
MAX_PROGRAM_BYTES = 256 * 1024
MAX_REPORT_CODE = 1024 * 1024
MEMBER = r'system\xfshader\XfMaterialStandard'
TYPE_HASH = 0x50F9DB3E
TECHNIQUE = 0x8727E606
RPCS3_REVISION = 'cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3'
FUNCTIONS = ('FUNC_SKIN', 'FUNC_LIGHTING', 'FUNC_NORMALMAP', 'FUNC_SPECULAR',
             'FUNC_LIGHTMAP', 'FUNC_MULTITEXTURE')
SHIFTS = (28, 22, 18, 14, 10, 6)
WIDTHS = (4, 4, 4, 4, 4, 4)
LIMITS = ('Static encoded selection and direct instruction operands only; no runtime '
          'vertex-buffer binding, texture binding, execution/reachability, final pixel, '
          'NaN repair, full-cast export or gameplay acceptance.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extent(offset, size, limit, label):
    if offset < 0 or size < 0 or offset > limit or size > limit - offset:
        raise ValueError(label + ' outside source extent')


def disjoint(spans):
    ordered = sorted(spans)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('overlapping BFX tables or metadata headers')


class CgProgram:
    """The parameter-free BE revision-6 Cg layout present in this BFX."""

    def __init__(self, data, profile):
        self.data = bytes(data)
        if not 80 <= len(data) <= MAX_PROGRAM_BYTES:
            raise ValueError('invalid Cg extent')
        p, rev, size, count, params, program, ncode, code = struct.unpack_from('>8I', data)
        if p != profile or p not in (7003, 7004) or rev != 6:
            raise ValueError('unsupported Cg profile or revision')
        if size != len(data) or count or params or program != 32 or code != 64:
            raise ValueError('unsupported Cg envelope')
        if not ncode or ncode % 16 or ncode != size - code:
            raise ValueError('invalid Cg instruction extent')
        self.domain = struct.unpack_from('>6I', data, program)
        if self.domain[0] * 16 != ncode:
            raise ValueError('Cg instruction slot count disagrees with code extent')
        if p == 7003 and self.domain[1] != 0:
            raise ValueError('nonzero Cg vertex load slot is unsupported')
        self.profile, self.code = p, data[code:]
        self.input_mask = self.domain[3] if p == 7003 else self.domain[1]

    def inspect(self):
        rows = vertex_instructions(self.code) if self.profile == 7003 else fragment_instructions(self.code)
        return {'profile': self.profile, 'sha256': sha(self.data), 'bytes': len(self.data),
                'code_bytes': len(self.code), 'declared_16byte_slots': self.domain[0],
                'attribute_input_mask': self.input_mask,
                'domain_header_hex': self.data[32:56].hex(),
                'bfx_byte_offset': getattr(self, 'bfx_offset', None),
                'decoded_instructions': len(rows),
                'branch_instructions': [r for r in rows if r.get('branch_target') is not None],
                'direct_input_instructions': [r for r in rows if r['input_operands']],
                'texture_instructions': [r for r in rows if r.get('texture_unit') is not None]}


# Operand positions, not a shader evaluator. SFL/STR and unsupported/control-flow
# instructions are deliberately excluded rather than attributing unused operands.
# BRI is decoded only to a bounded immediate target, never executed or followed.
VEC = {0: (), 1: (0,), 2: (0, 1), 3: (0, 2), 4: (0, 1, 2),
       **{i: (0, 1) for i in (5, 6, 7, 8, 9, 10, 11, 12, 16, 18, 19, 20)},
       **{i: (0,) for i in (13, 14, 15, 22, 25)}}
SCALAR = {0: (), 9: (), **{i: (2,) for i in (1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 16)}}


def vertex_instructions(code):
    if not code or len(code) % 16:
        raise ValueError('invalid vertex instruction extent')
    rows = []
    for at in range(0, len(code), 16):
        d0, d1, d2, d3 = struct.unpack_from('>4I', code, at)
        vec, scalar = (d1 >> 22) & 31, d1 >> 27
        if vec not in VEC or scalar not in SCALAR:
            raise ValueError('unsupported vertex opcode/control flow')
        sources = ((d2 >> 23) | ((d1 & 255) << 9), (d2 >> 6) & 0x1ffff,
                   (d3 >> 21) | ((d2 & 63) << 11))
        used = sorted(set(VEC[vec] + SCALAR[scalar]))
        if any((sources[i] & 3) == 0 for i in used):
            raise ValueError('unsupported vertex source type')
        inputs = [i for i in used if sources[i] & 3 == 2]
        if inputs and d0 & (1 << 27):
            raise ValueError('indexed vertex inputs are not statically resolved')
        branch = (((d0 >> 23) & 1) << 9) | ((d2 & 63) << 3) | (d3 >> 29) if scalar == 9 else None
        if branch is not None and branch >= len(code) // 16:
            raise ValueError('vertex branch target outside instruction extent')
        if bool(d3 & 1) != (at + 16 == len(code)):
            raise ValueError('vertex end flag disagrees with code extent')
        rows.append({'instruction': at // 16, 'code_byte_offset': at,
                     'raw_hex': code[at:at + 16].hex(), 'vector_opcode': vec,
                     'scalar_opcode': scalar, 'input_operands': inputs,
                     'branch_target': branch,
                     'input_attribute': (d1 >> 8) & 15 if inputs else None,
                     'vector_operand_positions': list(VEC[vec]),
                     'scalar_operand_positions': list(SCALAR[scalar]),
                     'sources': [{'position': i, 'type': sources[i] & 3,
                                  'swizzle': ''.join('xyzw'[(sources[i] >> shift) & 3]
                                                     for shift in (14, 12, 10, 8)),
                                  'constant_index': (d1 >> 12) & 1023 if sources[i] & 3 == 3 else None,
                                  'constant_indexed': bool(d3 & 2) if sources[i] & 3 == 3 else False}
                                 for i in used],
                     'vector_result': bool(d0 & (1 << 30)), 'destination': (d3 >> 2) & 31,
                     'temporary_destination': (d0 >> 15) & 63,
                     'vector_write_mask': (d3 >> 13) & 15,
                     'scalar_write_mask': (d3 >> 17) & 15,
                     'condition_test': bool(d0 & (1 << 13)), 'condition_mask': (d0 >> 10) & 7,
                     'saturate': bool(d0 & (1 << 26)),
                     'texture_unit': (d2 >> 8) & 3 if vec == 25 else None})
    return rows


FRAGMENT_OPERANDS = {
    **{i: 0 for i in (0, 18, 61, 62)},
    **{i: 1 for i in (1, 23, 26, 27, 28, 29, 47, 57)},
    **{i: 2 for i in (2, 3, 5, 6, 8, 9, 10, 58, 59)},
    4: 3,
}


def fragment_instructions(code):
    if not code or len(code) % 16:
        raise ValueError('invalid fragment instruction extent')
    at, rows = 0, []
    while at < len(code):
        words = struct.unpack_from('>4I', code, at)
        dst, *sources = [((x << 16) | (x >> 16)) & 0xffffffff for x in words]
        opcode = ((dst >> 24) & 63) | ((sources[1] >> 31) << 6)
        if opcode not in FRAGMENT_OPERANDS:
            raise ValueError('unsupported fragment opcode/control flow')
        used = sources[:FRAGMENT_OPERANDS[opcode]]
        if any(s & 3 == 3 for s in used):
            raise ValueError('unsupported fragment source type')
        step = 32 if any(s & 3 == 2 for s in used) else 16
        extent(at, step, len(code), 'fragment embedded constant')
        if bool(dst & 1) != (at + step == len(code)):
            raise ValueError('fragment end flag disagrees with code extent')
        inputs = [i for i, s in enumerate(used) if s & 3 == 1]
        attribute = (dst >> 13) & 15 if inputs else None
        if attribute is not None and attribute > 14:
            raise ValueError('invalid fragment input attribute')
        rows.append({'instruction': len(rows), 'code_byte_offset': at,
                     'raw_hex': code[at:at + 16].hex(), 'opcode': opcode,
                     'input_operands': inputs, 'input_attribute': attribute,
                     'source_types': [s & 3 for s in used],
                     'condition_mask': (sources[0] >> 18) & 7,
                     'write_mask': (dst >> 9) & 15, 'destination': (dst >> 1) & 63,
                     'texture_unit': (dst >> 17) & 15 if opcode in (23, 47) else None,
                     'embedded_constant_hex': code[at + 16:at + step].hex()})
        at += step
    return rows


class StandardShader:
    def __init__(self, data):
        self.data = bytes(data)
        if not 100 <= len(data) <= MAX_BYTES:
            raise ValueError('invalid BFX extent')
        magic, version, techniques, parameters = struct.unpack_from('>4sHHI', data)
        if magic != b'\0XFB' or version != 0x2004 or techniques != 1 or parameters > 4096:
            raise ValueError('unsupported BFX envelope')
        record = 12 + parameters * 8
        extent(record, 28 + 60, len(data), 'BFX technique')
        technique, *fields = struct.unpack_from('>7I', data, record)
        sizes, opaque = fields[:5], fields[5]
        self.body = record + 28
        if technique != TECHNIQUE or sizes[3] or self.body + sum(sizes) != len(data):
            raise ValueError('unsupported standard-material technique layout')
        self.code_start = self.body + sizes[0] + sizes[2]
        self.code_size = sizes[1]
        extent(self.code_start, self.code_size, len(data), 'BFX Cg section')
        self.prefix = self.code_start - self.body
        extent(0, 60, self.prefix, 'BFX function header')
        header = self._words(0, 15)
        n, nf, n2, np, nv, funcs, selectors, vt, pt = header[:9]
        if n != n2 or not 1 <= n <= 1000000 or nf != 6 or not 1 <= nv <= 4096 or not 1 <= np <= 4096:
            raise ValueError('unsupported BFX selector counts')
        if header[12] != parameters:
            raise ValueError('BFX parameter counts disagree')
        self._span(funcs, 6 * 12); self._span(selectors, n * 4)
        self._span(vt, nv * 4); self._span(pt, np * 4)
        spans = [(0, 60), (funcs, funcs + 72), (selectors, selectors + n * 4),
                 (vt, vt + nv * 4), (pt, pt + np * 4)]
        self.functions, product = [], 1
        for i in range(6):
            name, packed, enums = self._words(funcs + i * 12, 3)
            multiplier, count = packed >> 8, packed & 255
            if multiplier != product or not 1 <= count <= 16 or self._string(name, selectors) != FUNCTIONS[i]:
                raise ValueError('invalid BFX function dimension')
            self._span(enums, count * 4)
            if enums < funcs + 72 or enums + count * 4 > selectors:
                raise ValueError('BFX enum table outside function region')
            spans.append((enums, enums + count * 4))
            names = [self._string(x, selectors) for x in self._words(enums, count)]
            self.functions.append({'name': FUNCTIONS[i], 'multiplier': multiplier, 'values': names})
            product *= count
        if product != n:
            raise ValueError('BFX dimensions disagree with selector count')
        self.selectors = self._words(selectors, n)
        if any(x != 0xffffffff and ((x & 0xffff) >= nv or (x >> 16) >= np) for x in self.selectors):
            raise ValueError('BFX selector program index out of range')
        self.vertex, self.fragment, cursor = [], [], 0
        for profile, table, count, target in ((7003, vt, nv, self.vertex), (7004, pt, np, self.fragment)):
            for relative in self._words(table, count):
                self._span(relative, 16)
                if relative < pt + np * 4:
                    raise ValueError('BFX program metadata precedes tables')
                spans.append((relative, relative + 16))
                values = self._words(relative, 4)
                off, a, b, c = values
                size = b if profile == 7003 else c
                if a or (profile == 7004 and b) or off != cursor:
                    raise ValueError('BFX code spans must be contiguous and nonoverlapping')
                extent(off, size, self.code_size, 'BFX compiled program')
                program = CgProgram(data[self.code_start + off:self.code_start + off + size], profile)
                program.bfx_offset = self.code_start + off
                if profile == 7003 and program.input_mask != c:
                    raise ValueError('BFX/Cg vertex input masks disagree')
                target.append(program)
                cursor += size
        if cursor != self.code_size:
            raise ValueError('BFX Cg section has unaccounted bytes')
        disjoint(spans)
        self.envelope = {'technique_hash': f'{technique:08x}', 'parameter_count': parameters,
                         'section_sizes_raw': sizes, 'technique_opaque_word': opaque,
                         'body_offset': self.body, 'code_offset': self.code_start,
                         'code_bytes': self.code_size, 'body_header_raw': header,
                         'vertex_programs': nv, 'fragment_programs': np, 'selectors': n,
                         'opaque_prefix_sha256': sha(data[self.body:self.code_start]),
                         'opaque_tail_sha256': sha(data[self.code_start + self.code_size:])}

    def _span(self, at, size):
        extent(at, size, self.prefix, 'BFX relative field')

    def _words(self, at, count):
        self._span(at, count * 4)
        return list(struct.unpack_from('>' + str(count) + 'I', self.data, self.body + at))

    def _string(self, at, limit):
        if at < 60 or at >= limit or limit > self.prefix:
            raise ValueError('BFX string outside function region')
        end = self.data.find(b'\0', self.body + at, self.body + min(limit, at + 256))
        if end < 0:
            raise ValueError('unterminated BFX function string')
        raw = self.data[self.body + at:end]
        if not raw or any(x < 32 or x > 126 for x in raw):
            raise ValueError('invalid BFX function string')
        return raw.decode('ascii')

    def selection(self, word):
        if type(word) is not int or not 0 <= word <= 0xffffffff:
            raise ValueError('material word must be uint32')
        values = [(word >> shift) & ((1 << width) - 1) for shift, width in zip(SHIFTS, WIDTHS)]
        if any(v >= len(f['values']) for v, f in zip(values, self.functions)):
            raise ValueError('material function value outside BFX dimension')
        index = sum(v * f['multiplier'] for v, f in zip(values, self.functions))
        selected = self.selectors[index]
        if selected == 0xffffffff:
            raise ValueError('material permutation is unsupported by this BFX')
        vi, fi = selected & 0xffff, selected >> 16
        return {'material_word': f'{word:08x}', 'function_values': values,
                'function_names': [f['values'][v] for v, f in zip(values, self.functions)],
                'selector_index': index, 'selector_word': f'{selected:08x}',
                'vertex_index': vi, 'fragment_index': fi}

    def inspect_material(self, word):
        result = self.selection(word)
        result['vertex'] = self.vertex[result['vertex_index']].inspect()
        result['fragment'] = self.fragment[result['fragment_index']].inspect()
        return result


def report(source, materials):
    if not materials or len(materials) > 64:
        raise ValueError('request between 1 and 64 material words')
    data = bytes(source)
    if len(data) > MAX_BYTES:
        raise ValueError('source exceeds shader evidence size limit')
    identity = {'sha256': sha(data), 'bytes': len(data)}
    if data[:4] == b'\0CRA':
        archive = Arc(data)
        try:
            member = archive.find(MEMBER, TYPE_HASH)
        except KeyError as exc:
            raise ValueError('standard-material shader member missing') from exc
        if member.size > MAX_BYTES:
            raise ValueError('shader member exceeds evidence size limit')
        data = archive.read(member)
        identity.update({'archive_member': MEMBER, 'type_hash': f'{TYPE_HASH:08x}',
                         'decoded_bytes': len(data), 'decoded_sha256': sha(data)})
    shader = StandardShader(data)
    selections = [shader.selection(word) for word in materials]
    if sum(len(shader.vertex[r['vertex_index']].code) + len(shader.fragment[r['fragment_index']].code)
           for r in selections) > MAX_REPORT_CODE:
        raise ValueError('selected shader code exceeds report budget')
    return {'schema': 1, 'source': identity, 'scope': LIMITS,
            'rpcs3_reference_commit': RPCS3_REVISION, 'envelope': shader.envelope,
            'functions': shader.functions,
            'materials': [shader.inspect_material(word) for word in materials]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='owned shader.arc or decoded XfMaterialStandard BFX')
    parser.add_argument('--material', action='append', required=True, type=lambda x: int(x, 16),
                        help='native material function word in hexadecimal (repeatable)')
    parser.add_argument('--out', required=True, type=Path, help='new evidence JSON; never overwrites')
    args = parser.parse_args(argv)
    with args.source.open('rb') as stream:
        source = stream.read(MAX_BYTES + 1)
    result = report(source, args.material)
    result['source']['path'] = str(args.source.resolve())
    encoded = json.dumps(result, indent=2, allow_nan=False) + '\n'
    with args.out.open('x', encoding='utf-8') as stream:
        stream.write(encoded)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
