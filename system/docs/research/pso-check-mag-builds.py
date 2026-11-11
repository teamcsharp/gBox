import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import equip_roulette as R

print("six random builds (one per archetype):")
for archetype in R.ARCHETYPES[:6]:
    build = R.random_build(archetype=archetype)
    total = build["def"] + build["pow"] + build["dex"] + build["mind"]
    print(f"  {build['archetype']:<10} def {build['def']:3d} pow {build['pow']:3d} dex {build['dex']:3d} "
          f"mind {build['mind']:3d} sum {total:3d} iq {build['iq']:3d} sync {build['synchro']:3d} "
          f"colour {build['color']:2d}")
    assert total <= 200, f"over budget: {total}"
    assert build["synchro"] <= 120 and build["color"] <= 18 and build["iq"] <= 200
print("all builds within mag_set caps")
