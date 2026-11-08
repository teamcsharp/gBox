"""Add the extraction-tab routes for the pack edits: list a pack's materials, then apply a hide, a scale or a donor morph.

The panel needs two things the routes did not have: what a pack's materials *are* (so a person can pick one), and a way to apply an
edit into a build. `gbox.re4hd_edit` already holds the operation and its report; this is the HTTP surface over it, added beside the
existing `pack-slots` / `pack-swap` routes so a page has one place to look.

Applied as a patch to `system/gbox/decrypt_lab.py` - the models, the two routes and the imports are inserted together, and the file is
syntax-checked afterwards.
"""
import pathlib

target = pathlib.Path("system/gbox/decrypt_lab.py")
source = target.read_text(encoding="utf-8")

models = '''
class PackMaterialsIn(BaseModel):
    """One pack and slot, for the material list a picker shows."""
    title: str
    pack: str
    slot: int = 0


class PackEditIn(BaseModel):
    """An in-place edit of one slot: hide materials, scale materials, or morph toward another pack's slot.

    Exactly one of `hide`, `scale` or `donor_pack` is used; the route refuses an ambiguous request rather than choosing. `build`
    names the LayeredFS overlay the result is written into, so the panel can keep one build per experiment.
    """
    title: str
    pack: str
    slot: int = 0
    hide: list[int] = []
    scale: list[int] = []
    factor: float = 1.0
    donor_pack: str = ""
    donor_slot: int = 0
    bands: int = 6
    build: str = "gbox-lab"
'''

routes = '''
    @app.get("/api/decrypt-lab/pack-materials", dependencies=[Depends(auth)])
    def decrypt_lab_pack_materials(title: str, pack: str, slot: int = 0):
        """The materials of one BIN slot, with the triangle span each owns - the list "remove clothes" is chosen from."""
        tid = _title_id(title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")
        path = root / "bio4" / "em" / pack
        if not path.is_file():
            raise HTTPException(404, f"{pack} is not in this title's bio4/em")
        from . import re4hd_edit as EDIT
        try:
            return {"v": FORMAT, "pack": pack, "slot": slot, "materials": EDIT.material_census(path.read_bytes(), slot)}
        except EDIT.EditError as exc:
            raise HTTPException(400, str(exc)[:200]) from exc

    @app.post("/api/decrypt-lab/pack-edit", dependencies=[Depends(auth)])
    def decrypt_lab_pack_edit(body: PackEditIn):
        """Apply one in-place edit to a pack slot and write the result into a LayeredFS build.

        The report says which materials, how many vertices, whether the triangle table moved and the sha256 before and after, so
        the page can show what went in rather than assert it.
        """
        tid = _title_id(title := body.title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")
        path = root / "bio4" / "em" / body.pack
        if not path.is_file():
            raise HTTPException(404, f"{body.pack} is not in this title's bio4/em")
        from . import re4hd_edit as EDIT
        from . import re4hd_models as MODELS
        donor = None
        if body.donor_pack:
            donor_path = root / "bio4" / "em" / body.donor_pack
            if not donor_path.is_file():
                raise HTTPException(404, f"the donor pack {body.donor_pack} is not in this title's bio4/em")
            from . import re4gc_inventory as INV
            slots = INV.bin_slots(donor_path.read_bytes(), endian="<")
            if not 0 <= body.donor_slot < len(slots):
                raise HTTPException(400, f"the donor pack holds {len(slots)} BIN slot(s)")
            entry = slots[body.donor_slot]
            data = donor_path.read_bytes()
            donor = data[entry["offset"]:entry["offset"] + entry["size"]]
        try:
            patched, report = EDIT.edit_pack(path.read_bytes(), body.slot,
                                             hide=body.hide or None,
                                             scale=(body.scale, body.factor) if body.scale else None,
                                             donor=donor, pack_name=body.pack)
        except EDIT.EditError as exc:
            raise HTTPException(400, str(exc)[:200]) from exc
        folder = _mod_build(title, body.build)
        target = Path(folder) / "romfs" / "bio4" / "em" / body.pack
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patched)
        lab_state.event(title, "pack-edit", f"{body.pack} slot {body.slot}: {report.operation}", report.as_dict())
        return {"v": FORMAT, "build": body.build, "written": str(target), "report": report.as_dict()}
'''

anchor = None
for candidate in ('    @app.post("/api/decrypt-lab/pack-swap", dependencies=[Depends(auth)])',):
    if candidate in source:
        anchor = candidate
        break
assert anchor is not None, "no pack-swap route to anchor against"

# models go before the first class definition that follows the models block
first_class = source.index("class PackSwapIn")
source = source[:first_class] + models.strip() + "\n\n\n" + source[first_class:]

# routes go immediately before the pack-swap route
source = source.replace(anchor, routes.strip("\n") + "\n\n" + anchor, 1)
target.write_text(source, encoding="utf-8")
print("decrypt_lab.py: 2 routes and 2 models added")
