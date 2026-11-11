"""Decide whether a raw model swap can work, from the structure of the two bodies.

Measured on `GPOE8P` (i9-NUC, 2026-11-10), by dropping a donor body over a HUmar's:

| donor | what happens |
|---|---|
| HUcast body | the mesh **renders**, bound wrong: the character-select viewport fills with polygons |
| HUnewearl body | the game **reads an invalid pointer at PC `0x8028f508`** and Dolphin reports a crash |

And the two bodies differ in a way that predicts exactly that:

===========================  ========  ==========  ============
body                        bones     vertices    texture buckets
===========================  ========  ==========  ============
HUmar (`plAbdy00.nj`)       64        269         5
HUcast (`plCbdy00.nj`)      64        311         5
HUnewearl (`plBbdy00.nj`)   64        356         **8**
===========================  ========  ==========  ============

Every class has the **same 64-bone skeleton** and the same parent chain, so bone count is not the discriminator -- which
is why a structural check at that level would have passed all three. What differs is the **texture/material table** the
mesh references (`nj.tris` keys): a donor with more texture buckets than the host has materials makes the renderer look up
a material that is not there, which is the crash. Fewer buckets but a different vertex count is the "renders, deformed"
case, because the mesh's proportions come from the file while its pose comes from the host skeleton.

So: `buckets` must match for a raw copy to be even plausible; `vertices` differing is a deform, not a crash.
"""
from __future__ import annotations

import math
import struct


def model_centres(nj) -> list[tuple]:
    """Every node model's bounding centre (the four floats at model+8), read straight out of the NJCM payload.

    This is the field the renderer reads at PC ``0x8028f508``: the instruction there is ``lfs f0,0x8(r4)``, loading the
    first float of a vec3 through a pointer chain (`[entry+0x18] -> [obj] -> [obj+4] -> +8`). CP7.1 named the enclosing
    function and read the chain; see ``docs/research/pso-gc-executable.md`` section 9. A null link in that chain is what
    Dolphin reported as the HUnewearl-donor crash.
    """
    from . import ninja
    nodes = ninja.tree_nodes(nj.d, 0, nj.e)
    out = []
    for nd in nodes:
        model = nd.get("model")
        if model:
            out.append(struct.unpack_from(nj.e + "4f", nj.d, model + 8))
    return out


def signature_nj(nj) -> dict:
    """The structural fingerprint of a body, from a parsed `ninja.NJ`.

    Besides bones/buckets/vertices it carries the model list the per-frame transform walk indexes (``models``) and
    whether every model's centre vector is finite (``centre_ok``) - the ``+0x8`` field CP7.1 traced to ``0x8028f508``.
    """
    centres = model_centres(nj)
    return {"bones": len(nj.bones),
            "buckets": sorted(int(t) for t in nj.tris),
            "vertices": len(nj.vbuf),
            "models": len(centres),
            "centre_ok": all(all(math.isfinite(v) for v in c) for c in centres)}


def compare(host: dict, donor: dict) -> dict:
    """Will a byte-level copy of ``donor`` over ``host`` be structurally valid?"""
    if not host.get("bones") or not donor.get("bones"):
        return {"safe": False, "why": "one of the bodies has no bones", "host": host, "donor": donor}
    # Only a bucket the host lacks is the crash case (round 35): a donor that uses a *subset* of the host's materials - which
    # is what a built GameCube swap emits, since the writer places the fitted mesh in one material - renders on the host's
    # own material set.
    missing = sorted(set(donor["buckets"]) - set(host["buckets"]))
    if missing:
        return {"safe": False,
                "why": (f"the donor references texture buckets the host does not have: {missing} "
                        f"(host {host['buckets']}, donor {donor['buckets']}) -- that is the crash case (round 35)"),
                "host": host, "donor": donor, "missing_buckets": missing}
    if host.get("centre_ok") is False or donor.get("centre_ok") is False:
        return {"safe": False,
                "why": ("a model's centre vector is not finite: the per-frame transform walk reads that field at +0x8 "
                        "(PC 0x8028f508) and a bad value there is the invalid-pointer crash"),
                "host": host, "donor": donor}
    if host.get("models") != donor.get("models"):
        return {"safe": False,
                "why": (f"the model list lengths differ: host {host.get('models')}, donor {donor.get('models')} - the "
                        f"transform walk indexes that list, so a different length changes what +0x8 points at"),
                "host": host, "donor": donor}
    if host["bones"] != donor["bones"]:
        return {"safe": False,
                "why": f"bone count differs: host {host['bones']}, donor {donor['bones']}",
                "host": host, "donor": donor}
    if host["vertices"] != donor["vertices"]:
        return {"safe": True,
                "why": (f"same bones and materials, but {donor['vertices']} vertices against the host's "
                        f"{host['vertices']}: a copy renders with the donor's proportions on the host's skeleton "
                        f"(the deformed case, round 35)"),
                "host": host, "donor": donor, "deforms": True,
                "subset": set(donor["buckets"]) != set(host["buckets"])}
    return {"safe": True, "why": "bones, materials and vertex count all match", "host": host, "donor": donor,
            "subset": set(donor["buckets"]) != set(host["buckets"])}


def report(host_sig: dict, donor_sig: dict, *, host_name: str = "host", donor_name: str = "donor") -> str:
    """A one-block summary for a lane doc or a build log."""
    c = compare(host_sig, donor_sig)
    verdict = "SAFE" if c["safe"] else "REFUSE"
    extra = " (will deform)" if c.get("deforms") else ""
    return (f"{verdict}{extra}: {donor_name} -> {host_name}\n"
            f"  host  {host_name}: {host_sig['bones']} bones, {host_sig['vertices']} vertices, "
            f"{len(host_sig['buckets'])} texture buckets\n"
            f"  donor {donor_name}: {donor_sig['bones']} bones, {donor_sig['vertices']} vertices, "
            f"{len(donor_sig['buckets'])} texture buckets\n"
            f"  {c['why']}")
