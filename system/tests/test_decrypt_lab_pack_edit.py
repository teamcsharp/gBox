"""The extraction tab must expose the pack edits: a material list and a way to apply one.

These are registration tests with stand-in dependencies - the routes are what the page calls, so the thing worth pinning is that they
exist, sit beside the existing pack routes, and carry the models their bodies name. The behaviour of the edit itself is covered by
`test_re4hd_edit.py` against a real pack.
"""
import inspect

from fastapi import FastAPI

import gbox.decrypt_lab as D


class Dummy:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def registered_paths() -> list[str]:
    app = FastAPI()
    D.install(app, Dummy(), Dummy(), lambda: None)
    return sorted(route.path for route in app.routes if "/decrypt-lab/" in getattr(route, "path", ""))


def test_the_pack_edit_routes_are_registered_beside_the_existing_pack_routes():
    paths = registered_paths()
    for expected in ("/api/decrypt-lab/pack-edit", "/api/decrypt-lab/pack-materials",
                     "/api/decrypt-lab/pack-slots", "/api/decrypt-lab/pack-swap"):
        assert expected in paths, f"{expected} is missing from {paths}"


def test_the_request_models_describe_one_edit_at_a_time():
    edit = D.PackEditIn(title="re4", pack="em16.udas")
    assert edit.slot == 0 and edit.hide == [] and edit.scale == [] and not edit.donor_pack
    materials = D.PackMaterialsIn(title="re4", pack="pl00.udas", slot=1)
    assert materials.slot == 1


def test_the_edit_model_carries_every_input_the_operation_needs():
    fields = set(D.PackEditIn.model_fields)
    for needed in ("hide", "scale", "factor", "donor_pack", "donor_slot", "bands", "build"):
        assert needed in fields, f"{needed} is not on PackEditIn"
