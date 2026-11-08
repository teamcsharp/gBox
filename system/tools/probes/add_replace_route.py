"""Add the one route the replacement panel calls: `POST /api/decrypt-lab/replace`.

The four sidebar operations are one call with different arguments, so this route takes the donor either as a collection `.glb` or as
another pack's slot, and returns the `ReplaceReport`. `write=false` previews without touching a build.
"""
import pathlib

target = pathlib.Path("system/gbox/decrypt_lab.py")
source = target.read_text(encoding="utf-8")

model = '''
class ReplaceIn(BaseModel):
    """One replacement: a pack, a donor from the collection or from another pack, and how strong it should be.

    `blend` omitted means "choose it from the target's bands" (`switch_replace`/`auto_blend`), which is what keeps a small slot
    loadable. `write=false` computes and reports without writing a build, for a preview.
    """
    title: str
    pack: str
    donor_glb: str = ""
    donor_pack: str = ""
    donor_slot: int = 0
    blend: float | None = None
    bands: int = 6
    build: str = ""
    hide: list[int] = []
    write: bool = True
'''

route = '''
    @app.post("/api/decrypt-lab/replace", dependencies=[Depends(auth)])
    def decrypt_lab_replace(body: ReplaceIn):
        """Replace a pack's mesh with a donor's proportions (or a collection model's) and report what changed.

        This is the single call behind the panel's four operations: remove clothes (`hide` alone), swap clothes, swap the player with a
        Zombie (`pack=pl..`, `donor_pack=em..`), replace the Zombies with cast (`pack=em..`, `donor_glb=<collection model>`).
        """
        from . import switch_replace
        try:
            report = switch_replace.replace_pack(
                _CONFIG, _title_id(body.title), body.pack,
                donor_glb=body.donor_glb or None, donor_pack=body.donor_pack or None,
                donor_slot=body.donor_slot, blend=body.blend, bands=body.bands,
                build=body.build, hide=body.hide or None, write=body.write)
        except switch_replace.ReplaceError as exc:
            raise HTTPException(400, str(exc)[:300]) from exc
        lab_state.event(body.title, "replace", f"{body.pack} <- {report.donor}", report.as_dict())
        return {"v": FORMAT, "report": report.as_dict()}
'''

anchor = '    @app.post("/api/decrypt-lab/pack-edit", dependencies=[Depends(auth)])'
assert anchor in source, "no pack-edit route to anchor against"
first_class = source.index("class PackMaterialsIn")
source = source[:first_class] + model.strip() + "\n\n\n" + source[first_class:]
source = source.replace(anchor, route.strip("\n") + "\n\n" + anchor, 1)
target.write_text(source, encoding="utf-8")
print("replace route added")
