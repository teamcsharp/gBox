"""Enumerate owned costume archives through verified native resource tables."""
from .complete import B


def owned_path(disc, filename, *, missing_ok=False):
    expected=('DOA2/'+filename).casefold()
    matches=[name for name in disc.files if name.casefold()==expected]
    if not matches and missing_ok:return None
    if len(matches)!=1:
        raise ValueError('Native resource '+filename+' does not resolve to one owned DOA2 file')
    return matches[0]


def native_acs(executable, binding):
    resolver=getattr(B,'accessory_filename',None)
    if resolver is None:
        raise ValueError('Native source export requires doa2_bindings.accessory_filename; update the binding module')
    return resolver(executable,binding['render_slot'],binding['costume'])


def costumes(disc, executable, *, include_unavailable=False):
    """Include every bound CHR, including costumes reusing another ACS filename."""
    names={entry['files']['geometry'] for slot in B.parse_render_scripts(executable)
           if slot['slot'] not in (19,20,21,22)
           for entry in slot['costumes'] if entry['sections']['primary']}
    records=[]
    for name in sorted(names):
        binding=B.resolve_archive_binding(executable,name)
        acs=native_acs(executable,binding)
        path=owned_path(disc,name,missing_ok=True)
        stem=(path or name.upper()).rsplit('/',1)[-1].rsplit('.',1)[0]
        acs_path=owned_path(disc,acs['filename'],missing_ok=path is None)
        if path is None and not include_unavailable:continue
        records.append({'stem':stem,'chr_path':path,'acs_path':acs_path,'available':path is not None,
                        'missing_sources':[] if path else [name],
                        'native_binding':binding,'native_acs_binding':acs})
    return records
