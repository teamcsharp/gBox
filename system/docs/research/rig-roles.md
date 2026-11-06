rig_roles: joint roles from geometry, with the structural case that still needs handling

The ganado swap needs a roles map (hip, chest, neck, head, each upper arm / forearm / hand, each thigh / shin / foot) and Sonic's
glTF has no anatomical names, so the roles have to come from the rest pose. New module `gbox/rig_roles.py`, four tests passing:

* head = highest joint, its parent chain gives neck and chest
* hip = the ROOT of that chain, not the joint above it (rigs differ in spine count; the test skeleton has an extra one)
* limb roots = the pair of children that are not on the spine chain - arms by widest X span, legs by deepest drop
* `named()` maps indices to joint names for `characters.rig_from_gltf`

Measured on Sonic's own rig (66 nodes, all unnamed): it derives head/neck/chest/hip correctly and then **stops**, because his
shoulders do not hang off the head-to-root chain:

```
node000 (0.00, 0.00, 0.00)  root / hips
node001 (0.00, 5.00, 0.00)  spine        <- parent chain of the highest joint
node002 (0.00, 5.24, 0.00)  highest joint (read as head)
node003 (0.00, 5.09, 0.00)  the chain then DESCENDS ...
node005 (0.00, 4.62, 0.00)  ... to here, where the arms split
node006 (-0.28, 4.69)  node016 (0.32, 4.68)   the two shoulders
```

So the lateral pair is a child of a joint off the spine chain. The fix is a fallback: when the spine chain has no branching
joint, scan every joint for the best lateral pair (children of opposite X, arms) and the best downward pair (legs) and use
those as the limb roots. That is a small, testable addition to the same module, and it makes the derivation work on rigs whose
spine runs head-first, which this one does.