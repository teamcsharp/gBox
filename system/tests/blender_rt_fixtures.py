"""Synthetic glTF characters for the Blender round-trip tests (no Blender needed): a humanoid skeleton with any bone
names, a skinned body made of one box per bone, optional attachments (unskinned meshes under a joint, own texture),
and an unrigged variant (the same boxes, no skin)."""
import base64
import io
import json
import struct
from pathlib import Path

import numpy as np

# +Y up, facing +Z, the character's left on +X; a T-pose 1.8 units tall
POS = {"hip": [0, 1.0, 0], "chest": [0, 1.3, 0], "neck": [0, 1.5, 0], "head": [0, 1.6, 0],
       "l_clav": [0.05, 1.45, 0], "l_upper": [0.2, 1.45, 0], "l_fore": [0.5, 1.45, 0], "l_hand": [0.75, 1.45, 0],
       "r_clav": [-0.05, 1.45, 0], "r_upper": [-0.2, 1.45, 0], "r_fore": [-0.5, 1.45, 0], "r_hand": [-0.75, 1.45, 0],
       "l_thigh": [0.1, 0.95, 0], "l_shin": [0.1, 0.5, 0], "l_foot": [0.1, 0.08, 0],
       "r_thigh": [-0.1, 0.95, 0], "r_shin": [-0.1, 0.5, 0], "r_foot": [-0.1, 0.08, 0]}
PARENT = {"hip": None, "chest": "hip", "neck": "chest", "head": "neck", "l_clav": "chest", "l_upper": "l_clav",
          "l_fore": "l_upper", "l_hand": "l_fore", "r_clav": "chest", "r_upper": "r_clav", "r_fore": "r_upper",
          "r_hand": "r_fore", "l_thigh": "hip", "l_shin": "l_thigh", "l_foot": "l_shin", "r_thigh": "hip",
          "r_shin": "r_thigh", "r_foot": "r_shin"}
END = {"head": [0, 1.8, 0], "l_hand": [0.85, 1.45, 0], "r_hand": [-0.85, 1.45, 0], "l_foot": [0.1, 0.0, 0.12],
       "r_foot": [-0.1, 0.0, 0.12]}

MIXAMO = {"hip": "mixamorig:Hips", "chest": "mixamorig:Spine2", "neck": "mixamorig:Neck", "head": "mixamorig:Head",
          "l_clav": "mixamorig:LeftShoulder", "l_upper": "mixamorig:LeftArm", "l_fore": "mixamorig:LeftForeArm",
          "l_hand": "mixamorig:LeftHand", "r_clav": "mixamorig:RightShoulder", "r_upper": "mixamorig:RightArm",
          "r_fore": "mixamorig:RightForeArm", "r_hand": "mixamorig:RightHand", "l_thigh": "mixamorig:LeftUpLeg",
          "l_shin": "mixamorig:LeftLeg", "l_foot": "mixamorig:LeftFoot", "r_thigh": "mixamorig:RightUpLeg",
          "r_shin": "mixamorig:RightLeg", "r_foot": "mixamorig:RightFoot"}
RIGIFY = {"hip": "DEF-spine", "chest": "DEF-spine.003", "neck": "DEF-spine.004", "head": "DEF-spine.006",
          "l_clav": "DEF-shoulder.L", "l_upper": "DEF-upper_arm.L", "l_fore": "DEF-forearm.L", "l_hand": "DEF-hand.L",
          "r_clav": "DEF-shoulder.R", "r_upper": "DEF-upper_arm.R", "r_fore": "DEF-forearm.R", "r_hand": "DEF-hand.R",
          "l_thigh": "DEF-thigh.L", "l_shin": "DEF-shin.L", "l_foot": "DEF-foot.L", "r_thigh": "DEF-thigh.R",
          "r_shin": "DEF-shin.R", "r_foot": "DEF-foot.R"}
VRM = {"hip": "J_Bip_C_Hips", "chest": "J_Bip_C_UpperChest", "neck": "J_Bip_C_Neck", "head": "J_Bip_C_Head",
       "l_clav": "J_Bip_L_Shoulder", "l_upper": "J_Bip_L_UpperArm", "l_fore": "J_Bip_L_LowerArm", "l_hand": "J_Bip_L_Hand",
       "r_clav": "J_Bip_R_Shoulder", "r_upper": "J_Bip_R_UpperArm", "r_fore": "J_Bip_R_LowerArm", "r_hand": "J_Bip_R_Hand",
       "l_thigh": "J_Bip_L_UpperLeg", "l_shin": "J_Bip_L_LowerLeg", "l_foot": "J_Bip_L_Foot", "r_thigh": "J_Bip_R_UpperLeg",
       "r_shin": "J_Bip_R_LowerLeg", "r_foot": "J_Bip_R_Foot"}
UE = {"hip": "pelvis", "chest": "spine_03", "neck": "neck_01", "head": "head", "l_clav": "clavicle_l",
      "l_upper": "upperarm_l", "l_fore": "lowerarm_l", "l_hand": "hand_l", "r_clav": "clavicle_r", "r_upper": "upperarm_r",
      "r_fore": "lowerarm_r", "r_hand": "hand_r", "l_thigh": "thigh_l", "l_shin": "calf_l", "l_foot": "foot_l",
      "r_thigh": "thigh_r", "r_shin": "calf_r", "r_foot": "foot_r"}
BIPED = {"hip": "Bip01 Pelvis", "chest": "Bip01 Spine2", "neck": "Bip01 Neck", "head": "Bip01 Head",
         "l_clav": "Bip01 L Clavicle", "l_upper": "Bip01 L UpperArm", "l_fore": "Bip01 L Forearm", "l_hand": "Bip01 L Hand",
         "r_clav": "Bip01 R Clavicle", "r_upper": "Bip01 R UpperArm", "r_fore": "Bip01 R Forearm", "r_hand": "Bip01 R Hand",
         "l_thigh": "Bip01 L Thigh", "l_shin": "Bip01 L Calf", "l_foot": "Bip01 L Foot", "r_thigh": "Bip01 R Thigh",
         "r_shin": "Bip01 R Calf", "r_foot": "Bip01 R Foot"}
GENERIC = {r: f"bone_{i:02d}" for i, r in enumerate(POS)}
ROLE_NAMES = {r: r for r in POS}


def png(rgb=(200, 40, 40), size=4) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGBA", (size, size), (*rgb, 255)).save(b, "PNG")
    return b.getvalue()


def box(a, b, r=0.04):
    """8 vertices / 12 triangles around the segment a -> b."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    lo, hi = np.minimum(a, b) - r, np.maximum(a, b) + r
    P = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
    F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return P, F


class Writer:
    def __init__(self):
        self.gl = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                   "accessors": [], "bufferViews": [], "materials": [], "images": [], "textures": [], "skins": []}
        self.bin = bytearray()

    def view(self, raw: bytes) -> int:
        self.bin.extend(bytes(-len(self.bin) % 4))
        self.gl["bufferViews"].append({"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(raw)})
        self.bin.extend(raw)
        return len(self.gl["bufferViews"]) - 1

    def acc(self, arr, comp, typ, minmax=False) -> int:
        arr = np.ascontiguousarray(arr)
        a = {"bufferView": self.view(arr.tobytes()), "componentType": comp, "count": int(len(arr)), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        self.gl["accessors"].append(a)
        return len(self.gl["accessors"]) - 1

    def material(self, name, rgb) -> int:
        self.gl["images"].append({"bufferView": self.view(png(rgb)), "mimeType": "image/png"})
        self.gl["textures"].append({"source": len(self.gl["images"]) - 1})
        self.gl["materials"].append({"name": name, "pbrMetallicRoughness": {
            "baseColorTexture": {"index": len(self.gl["textures"]) - 1}}})
        return len(self.gl["materials"]) - 1

    def mesh(self, name, P, F, mat, J=None) -> int:
        attrs = {"POSITION": self.acc(P.astype(np.float32), 5126, "VEC3", True),
                 "NORMAL": self.acc(np.tile(np.float32([0, 0, 1]), (len(P), 1)), 5126, "VEC3"),
                 "TEXCOORD_0": self.acc(np.zeros((len(P), 2), np.float32), 5126, "VEC2")}
        if J is not None:
            Jv = np.zeros((len(P), 4), np.uint16)
            Jv[:, 0] = J
            Wv = np.zeros((len(P), 4), np.float32)
            Wv[:, 0] = 1
            attrs["JOINTS_0"] = self.acc(Jv, 5123, "VEC4")
            attrs["WEIGHTS_0"] = self.acc(Wv, 5126, "VEC4")
        self.gl["meshes"].append({"name": name, "primitives": [{"attributes": attrs, "material": mat,
                                                                 "indices": self.acc(F.reshape(-1).astype(np.uint32), 5125, "SCALAR")}]})
        return len(self.gl["meshes"]) - 1

    def node(self, nd, root=False) -> int:
        self.gl["nodes"].append(nd)
        i = len(self.gl["nodes"]) - 1
        if root:
            self.gl["scenes"][0]["nodes"].append(i)
        return i

    def save(self, path: Path) -> Path:
        gl = {k: v for k, v in self.gl.items() if v != []}
        self.bin.extend(bytes(-len(self.bin) % 4))
        gl["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(gl).encode()
        js += b" " * (-len(js) % 4)
        Path(path).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(self.bin))
                               + struct.pack("<II", len(js), 0x4E4F534A) + js
                               + struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin))
        return Path(path)


def _body(roles=POS):
    parts, owner = [], []
    for k, r in enumerate(roles):
        kids = [c for c, p in PARENT.items() if p == r and not c.endswith(("_clav", "_thigh"))]
        end = POS[kids[0]] if kids else END.get(r, POS[r])
        P, F = box(POS[r], end)
        parts.append((P, F))
        owner.append(k)
    return parts, owner


def humanoid(path: Path, names: dict = ROLE_NAMES, props: dict | None = None, vrm: str | None = None,
             extra_bone: str | None = None, armature_extras: dict | None = None) -> Path:
    """A skinned humanoid (one box per bone, rigidly weighted). props: {node name: (role it hangs on, colour)}:
    unskinned meshes, child nodes of that joint, with their own texture. vrm: '0' | '1' adds the VRM humanoid
    extension. extra_bone: one more joint under the head (a changed skeleton)."""
    w = Writer()
    roles = list(POS)
    arm = w.node({"name": "Armature", "children": [], **({"extras": armature_extras} if armature_extras else {})}, root=True)
    idx = {}
    for r in roles:
        p = PARENT[r]
        t = np.asarray(POS[r]) - (np.asarray(POS[p]) if p else 0)
        idx[r] = w.node({"name": names[r], "translation": [float(v) for v in t]})
    for r in roles:
        (w.gl["nodes"][idx[PARENT[r]]] if PARENT[r] else w.gl["nodes"][arm]).setdefault("children", []).append(idx[r])
    joints = [idx[r] for r in roles]
    if extra_bone:
        e = w.node({"name": extra_bone, "translation": [0, 0.1, 0]})
        w.gl["nodes"][idx["head"]].setdefault("children", []).append(e)
        joints.append(e)
    ibm = []
    for j in joints:
        m = np.eye(4, dtype=np.float32)
        pos = POS[next(r for r in roles if idx[r] == j)] if j in idx.values() else np.add(POS["head"], [0, 0.1, 0])
        m[:3, 3] = -np.asarray(pos)
        ibm.append(m.T.reshape(16))
    w.gl["skins"].append({"joints": joints, "inverseBindMatrices": w.acc(np.array(ibm, np.float32), 5126, "MAT4")})
    parts, owner = _body()
    P = np.concatenate([p for p, _ in parts])
    F = np.concatenate([f + 8 * k for k, (_, f) in enumerate(parts)])
    J = np.repeat(owner, 8)
    body = w.mesh("Body", P, F, w.material("skin", (220, 180, 150)), J)
    w.node({"name": "Body", "mesh": body, "skin": 0}, root=True)
    for name, (role, rgb) in (props or {}).items():
        Pp, Fp = box([-0.06, 0.18, -0.06], [0.06, 0.26, 0.06], 0.0)       # local to the joint: above the head joint
        m = w.mesh(name, Pp, Fp, w.material(name + "_mat", rgb))
        n = w.node({"name": name, "mesh": m})
        w.gl["nodes"][idx[role]].setdefault("children", []).append(n)
    if vrm == "0":
        w.gl["extensions"] = {"VRM": {"humanoid": {"humanBones": [
            {"bone": b, "node": idx[r]} for b, r in (("hips", "hip"), ("upperChest", "chest"), ("neck", "neck"),
                                                    ("head", "head"), ("leftShoulder", "l_clav"), ("leftUpperArm", "l_upper"),
                                                    ("leftLowerArm", "l_fore"), ("leftHand", "l_hand"),
                                                    ("rightShoulder", "r_clav"), ("rightUpperArm", "r_upper"),
                                                    ("rightLowerArm", "r_fore"), ("rightHand", "r_hand"),
                                                    ("leftUpperLeg", "l_thigh"), ("leftLowerLeg", "l_shin"),
                                                    ("leftFoot", "l_foot"), ("rightUpperLeg", "r_thigh"),
                                                    ("rightLowerLeg", "r_shin"), ("rightFoot", "r_foot"))]}}}
        w.gl["extensionsUsed"] = ["VRM"]
    return w.save(path)


def unrigged(path: Path, arms: str = "T") -> Path:
    """The same body as plain meshes (no skin, no joints): T-pose arms, or arms hanging down (arms='down')."""
    w = Writer()
    mat = w.material("clay", (120, 160, 200))
    parts = []
    for r in POS:
        kids = [c for c, p in PARENT.items() if p == r and not c.endswith(("_clav", "_thigh"))]
        a, b = POS[r], (POS[kids[0]] if kids else END.get(r, POS[r]))
        if arms == "down" and r[2:] in ("upper", "fore", "hand"):
            sg = 1 if r[0] == "l" else -1
            y = {"upper": (1.45, 1.15), "fore": (1.15, 0.9), "hand": (0.9, 0.8)}[r[2:]]
            a, b = [sg * 0.25, y[0], 0], [sg * 0.25, y[1], 0]
        parts.append(box(a, b))
    P = np.concatenate([p for p, _ in parts])
    F = np.concatenate([f + 8 * k for k, (_, f) in enumerate(parts)])
    w.node({"name": "Statue", "mesh": w.mesh("Statue", P, F, mat)}, root=True)
    return w.save(path)


def read(path: Path) -> dict:
    from gbox import attachments
    return attachments.read_gltf(path)[0]


def data_uri_gltf(src: Path, out: Path) -> Path:
    """The GLB as a .gltf with data: URIs (what some exporters write)."""
    from gbox import attachments
    gl, blob = attachments.read_gltf(src)
    gl["buffers"] = [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode()}]
    out.write_text(json.dumps(gl))
    return out
