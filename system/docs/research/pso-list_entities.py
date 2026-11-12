"""List every entity the semantic profile sees, looking for a warp or teleporter to a real field.

`explore` fights what is near and otherwise walks to the nearest **door/gate** it has not visited. Pioneer 2 has neither, which is why the mission stops at step 1 - so the
character has to reach a field. The semantic profile reads PSO properly (`TObjPlayer`, `TObjNpcCloakroomBase`, rooms), so whatever warp exists should be visible here as an
object with a position the bot can walk to.
"""
import json

from pso_pad import Pad, call

if __name__ == "__main__":
    pad = Pad()
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST")
    entities = (state or {}).get("entities") or []
    print("session:", pad.sid)
    print("profile:", (state or {}).get("profile"), "| globals:", json.dumps((state or {}).get("globals"))[:160])
    print("entities:", len(entities))
    print()
    for entity in entities:
        print("  slot %2s room %3s (%8.1f,%8.1f) %-32s [%s]"
              % (entity.get("slot"), entity.get("room"), entity.get("x") or 0,
                 entity.get("z") or 0, entity.get("class"), entity.get("kind")))

    kinds = sorted({str(entity.get("kind")) for entity in entities})
    classes = sorted({str(entity.get("class")) for entity in entities})
    print("\nkinds:", kinds)
    print("classes:", classes)
    print("\nchecks:", json.dumps((state or {}).get("checks"))[:400])
