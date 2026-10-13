"""Minimal reader for cooked Unreal Engine 4/5 packages (.uasset + .uexp): package summary, name map, import and
export tables. Enough to say which exports are SkeletalMesh / Skeleton / AnimSequence / Blueprint actor classes, how
big they are and which package holds them - the actor and animation inventory behind `ue_steam op=inventory`.

Cooked games are usually saved *unversioned* (FileVersionUE4 = 0): the object version then comes from the engine
version of the build, so callers pass `engine=(major, minor)` (ue_steam reads it from the executable).

Reference: Engine/Source/Runtime/CoreUObject/Private/UObject/PackageFileSummary.cpp, ObjectResource.cpp and
Engine/Source/Runtime/Core/Public/UObject/ObjectVersion.h.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ue_pak import PakError, Reader

PACKAGE_TAG = 0x9E2A83C1
PKG_UNVERSIONED_PROPERTIES = 0x00002000
PKG_FILTER_EDITOR_ONLY = 0x80000000

# EUnrealEngineObjectUE4Version per engine minor (cooked unversioned packages use the build's own version).
UE4_OBJECT_VERSION = {0: 342, 1: 352, 2: 363, 3: 382, 4: 385, 5: 401, 6: 413, 7: 434, 8: 451, 9: 482, 10: 482,
                      11: 498, 12: 504, 13: 505, 14: 508, 15: 510, 16: 513, 17: 513, 18: 514, 19: 516, 20: 516,
                      21: 517, 22: 517, 23: 517, 24: 518, 25: 518, 26: 519, 27: 522}
# EUnrealEngineObjectUE5Version per UE5 minor (best effort; UE5 games normally ship IoStore, not legacy packages).
UE5_OBJECT_VERSION = {0: 1004, 1: 1008, 2: 1009, 3: 1009, 4: 1012, 5: 1013}
UE5_SUPPORTED_MAX = 1013           # 1014+ (metadata offset, Verse cells, saved hash) change the summary layout

# Object version gates used below (ObjectVersion.h).
VER_WORLD_LEVEL_INFO = 224
VER_CHANGED_CHUNKID_TO_ARRAY = 326
VER_ENGINE_VERSION_OBJECT = 336
VER_LOAD_FOR_EDITOR_GAME = 365
VER_ADD_STRING_ASSET_REFERENCES_MAP = 384
VER_PACKAGE_SUMMARY_HAS_COMPATIBLE_ENGINE_VERSION = 444
VER_SERIALIZE_TEXT_IN_PACKAGES = 459
VER_COOKED_ASSETS_IN_EDITOR_SUPPORT = 485
VER_NAME_HASHES_SERIALIZED = 504
VER_PRELOAD_DEPENDENCIES_IN_COOKED_EXPORTS = 507
VER_TEMPLATE_INDEX_IN_COOKED_EXPORTS = 508
VER_ADDED_SEARCHABLE_NAMES = 510
VER_64BIT_EXPORTMAP_SERIALSIZES = 511
VER_ADDED_PACKAGE_SUMMARY_LOCALIZATION_ID = 516
VER_ADDED_PACKAGE_OWNER = 518
VER_NON_OUTER_PACKAGE_IMPORT = 520
UE5_NAMES_REFERENCED_FROM_EXPORT_DATA = 1001
UE5_PAYLOAD_TOC = 1002
UE5_OPTIONAL_RESOURCES = 1003
UE5_REMOVE_OBJECT_EXPORT_PACKAGE_GUID = 1005
UE5_TRACK_OBJECT_EXPORT_IS_INHERITED = 1006
UE5_ADD_SOFTOBJECTPATH_LIST = 1008
UE5_DATA_RESOURCES = 1009
UE5_SCRIPT_SERIALIZATION_OFFSET = 1010

# Classes the inventory groups (UClass names without the U prefix, as they appear in import tables).
MESH_CLASSES = {"SkeletalMesh"}
SKELETON_CLASSES = {"Skeleton"}
ANIM_CLASSES = {"AnimSequence", "AnimMontage", "AnimComposite", "BlendSpace", "BlendSpace1D", "AimOffsetBlendSpace",
                "AimOffsetBlendSpace1D", "PoseAsset", "AnimStreamable"}
ANIM_BP_CLASSES = {"AnimBlueprintGeneratedClass"}
PHYSICS_CLASSES = {"PhysicsAsset"}
BLUEPRINT_CLASSES = {"BlueprintGeneratedClass", "WidgetBlueprintGeneratedClass"}
PAWN_BASES = {"Character", "Pawn", "DefaultPawn", "SpectatorPawn", "WheeledVehicle", "WheeledVehiclePawn"}


class AssetError(PakError):
    """Package header could not be parsed (wrong magic, unsupported version, truncated)."""


@dataclass
class Import:
    class_package: str
    class_name: str
    outer: int
    name: str


@dataclass
class Export:
    class_index: int
    super_index: int
    outer: int
    name: str
    flags: int
    serial_size: int
    serial_offset: int
    is_asset: bool = False
    class_name: str = ""
    super_name: str = ""


@dataclass
class Package:
    summary: dict
    names: list[str]
    imports: list[Import] = field(default_factory=list)
    exports: list[Export] = field(default_factory=list)

    @property
    def ue4(self) -> int:
        return self.summary["ue4_version"]

    @property
    def ue5(self) -> int:
        return self.summary["ue5_version"]

    @property
    def unversioned_properties(self) -> bool:
        return bool(self.summary["package_flags"] & PKG_UNVERSIONED_PROPERTIES)

    def resolve(self, index: int) -> str:
        """FPackageIndex -> object name (imports negative, exports positive, 0 = null / UClass)."""
        if index < 0 and -index - 1 < len(self.imports):
            return self.imports[-index - 1].name
        if index > 0 and index - 1 < len(self.exports):
            return self.exports[index - 1].name
        return ""

    def path_of(self, index: int) -> str:
        """Full outer chain of an import (e.g. /Script/Engine.Character)."""
        parts, seen = [], 0
        while index and seen < 64:
            seen += 1
            if index < 0 and -index - 1 < len(self.imports):
                imp = self.imports[-index - 1]
                parts.append(imp.name)
                index = imp.outer
            elif index > 0 and index - 1 < len(self.exports):
                exp = self.exports[index - 1]
                parts.append(exp.name)
                index = exp.outer
            else:
                break
        parts.reverse()
        return parts[0] + ("." + ".".join(parts[1:]) if len(parts) > 1 else "") if parts else ""


def object_versions(engine: tuple[int, int] | None) -> tuple[int, int]:
    """(UE4 object version, UE5 object version) for an engine (major, minor); defaults to 4.27."""
    if not engine or engine[0] is None:
        return UE4_OBJECT_VERSION[27], 0
    major, minor = engine[0], engine[1] if engine[1] is not None else 99
    if major == 4:
        return UE4_OBJECT_VERSION.get(minor, UE4_OBJECT_VERSION[27] if minor > 27 else UE4_OBJECT_VERSION[0]), 0
    if major == 5:
        return 522, UE5_OBJECT_VERSION.get(minor, UE5_OBJECT_VERSION[max(UE5_OBJECT_VERSION)])
    raise AssetError(f"engine {major}.{minor} is not Unreal Engine 4 or 5")


def _fname(r: Reader, names: list[str]) -> str:
    idx, num = r.i32(), r.i32()
    if not 0 <= idx < len(names):
        raise AssetError(f"name index {idx} outside the {len(names)}-entry name map")
    return names[idx] if num == 0 else f"{names[idx]}_{num - 1}"


def _engine_version(r: Reader) -> str:
    major, minor, patch, changelist = r.u16(), r.u16(), r.u16(), r.u32()
    branch = r.fstring()
    return f"{major}.{minor}.{patch}-{changelist}" + (f"+{branch}" if branch else "")


def parse_summary(data: bytes, engine: tuple[int, int] | None = None) -> dict:
    """FPackageFileSummary. Raises AssetError for anything it does not understand."""
    r = Reader(data, what="package summary")
    if r.u32() != PACKAGE_TAG:
        raise AssetError("not an Unreal package (tag 0x9E2A83C1 missing)")
    legacy = r.i32()
    if not -8 <= legacy <= -4:
        raise AssetError(f"legacy file version {legacy} is outside UE4/UE5 (-4..-8)")
    if legacy != -4:
        r.i32()                                      # LegacyUE3Version
    ue4 = r.i32()
    ue5 = r.i32() if legacy <= -8 else 0
    licensee = r.i32()
    custom = []
    n = r.count(8, limit=4096)
    for _ in range(n):
        if legacy >= -5:                             # Guids format
            key = r.guid().hex()
            custom.append((key, r.i32()))
            r.fstring()
        else:                                        # Optimized format
            key = r.guid().hex()
            custom.append((key, r.i32()))
    unversioned = ue4 == 0 and ue5 == 0 and licensee == 0
    if unversioned:
        ue4, ue5 = object_versions(engine)
    if ue5 > UE5_SUPPORTED_MAX:
        raise AssetError(f"UE5 object version {ue5} is newer than this parser ({UE5_SUPPORTED_MAX})")
    s = {"legacy_version": legacy, "ue4_version": ue4, "ue5_version": ue5, "licensee_version": licensee,
         "unversioned": unversioned, "custom_versions": dict(custom)}
    s["total_header_size"] = r.i32()
    s["folder_name"] = r.fstring()
    flags = s["package_flags"] = r.u32()
    s["name_count"], s["name_offset"] = r.i32(), r.i32()
    if ue5 >= UE5_ADD_SOFTOBJECTPATH_LIST:
        r.i32(); r.i32()
    if not flags & PKG_FILTER_EDITOR_ONLY and ue4 >= VER_ADDED_PACKAGE_SUMMARY_LOCALIZATION_ID:
        r.fstring()
    if ue4 >= VER_SERIALIZE_TEXT_IN_PACKAGES:
        r.i32(); r.i32()
    s["export_count"], s["export_offset"] = r.i32(), r.i32()
    s["import_count"], s["import_offset"] = r.i32(), r.i32()
    s["depends_offset"] = r.i32()
    for k in ("name", "export", "import"):
        cnt, off = s[f"{k}_count"], s[f"{k}_offset"]
        if cnt < 0 or cnt > 1 << 22 or (cnt and not 0 < off < len(data)):
            raise AssetError(f"{k} table {cnt}@{off} lies outside the {len(data)}-byte header")
    # The rest of the summary is informational; a failure past this point keeps the tables usable.
    try:
        if ue4 >= VER_ADD_STRING_ASSET_REFERENCES_MAP:
            r.i32(); r.i32()
        if ue4 >= VER_ADDED_SEARCHABLE_NAMES:
            r.i32()
        r.i32()                                      # ThumbnailTableOffset
        r.guid()
        if not flags & PKG_FILTER_EDITOR_ONLY and ue4 >= VER_ADDED_PACKAGE_OWNER:
            r.guid()
            if ue4 < VER_NON_OUTER_PACKAGE_IMPORT:
                r.guid()
        for _ in range(r.count(8, limit=1 << 16)):
            r.i32(); r.i32()
        if ue4 >= VER_ENGINE_VERSION_OBJECT:
            s["saved_by"] = _engine_version(r)
        else:
            r.i32()
        if ue4 >= VER_PACKAGE_SUMMARY_HAS_COMPATIBLE_ENGINE_VERSION:
            s["compatible_with"] = _engine_version(r)
        r.u32()                                      # CompressionFlags
        if r.count(16, limit=1 << 16):
            raise AssetError("package-level compressed chunks are not supported")
        r.u32()                                      # PackageSource
        for _ in range(r.count(4, limit=1 << 16)):
            r.fstring()
        if legacy > -7:
            r.i32()                                  # NumTextureAllocations
        s["asset_registry_offset"] = r.i32()
        s["bulk_data_start_offset"] = r.i64()
    except AssetError:
        raise
    except PakError as e:
        s["summary_tail_error"] = str(e)
    return s


def parse_package(data: bytes, engine: tuple[int, int] | None = None) -> Package:
    """Summary, name map, imports and exports of a .uasset (header only; export bodies live in the .uexp)."""
    s = parse_summary(data, engine)
    ue4, ue5 = s["ue4_version"], s["ue5_version"]
    r = Reader(data, s["name_offset"], what="name map")
    names = []
    for _ in range(s["name_count"]):
        names.append(r.fstring())
        if ue4 >= VER_NAME_HASHES_SERIALIZED:
            r.u32()
    pkg = Package(s, names)
    editor = not s["package_flags"] & PKG_FILTER_EDITOR_ONLY
    r = Reader(data, s["import_offset"], what="import table")
    for _ in range(s["import_count"]):
        cp, cn, outer, name = _fname(r, names), _fname(r, names), r.i32(), _fname(r, names)
        if editor and ue4 >= VER_NON_OUTER_PACKAGE_IMPORT:
            _fname(r, names)
        if ue5 >= UE5_OPTIONAL_RESOURCES:
            r.bool32()
        pkg.imports.append(Import(cp, cn, outer, name))
    r = Reader(data, s["export_offset"], what="export table")
    for _ in range(s["export_count"]):
        cls, sup = r.i32(), r.i32()
        if ue4 >= VER_TEMPLATE_INDEX_IN_COOKED_EXPORTS:
            r.i32()
        outer, name, flags = r.i32(), _fname(r, names), r.u32()
        if ue4 >= VER_64BIT_EXPORTMAP_SERIALSIZES:
            size, off = r.i64(), r.i64()
        else:
            size, off = r.i32(), r.i32()
        r.bool32(); r.bool32(); r.bool32()          # forced export, not for client, not for server
        if ue5 < UE5_REMOVE_OBJECT_EXPORT_PACKAGE_GUID:
            r.guid()
        if ue5 >= UE5_TRACK_OBJECT_EXPORT_IS_INHERITED:
            r.bool32()
        r.u32()                                      # package flags
        if ue4 >= VER_LOAD_FOR_EDITOR_GAME:
            r.bool32()
        is_asset = r.bool32() if ue4 >= VER_COOKED_ASSETS_IN_EDITOR_SUPPORT else False
        if ue5 >= UE5_OPTIONAL_RESOURCES:
            r.bool32()
        if ue4 >= VER_PRELOAD_DEPENDENCIES_IN_COOKED_EXPORTS:
            r.take(20)
        if ue5 >= UE5_SCRIPT_SERIALIZATION_OFFSET:
            r.i64(); r.i64()
        if size < 0 or off < 0:
            raise AssetError(f"export {name}: negative serial size/offset")
        pkg.exports.append(Export(cls, sup, outer, name, flags, size, off, is_asset))
    for e in pkg.exports:
        e.class_name = pkg.resolve(e.class_index) or "Class"
        e.super_name = pkg.resolve(e.super_index)
    return pkg


def export_body(pkg: Package, e: Export, uasset: bytes, uexp: bytes | None) -> bytes:
    """An export's serialized bytes. Split packages keep them in the .uexp at serial_offset - total_header_size."""
    hdr = pkg.summary["total_header_size"]
    if e.serial_offset >= hdr and uexp is not None:
        start = e.serial_offset - hdr
        if start + e.serial_size > len(uexp):
            raise AssetError(f"export {e.name}: {start}+{e.serial_size} lies outside the {len(uexp)}-byte .uexp")
        return uexp[start:start + e.serial_size]
    if e.serial_offset + e.serial_size > len(uasset):
        raise AssetError(f"export {e.name}: body is not in the .uasset and no .uexp was given")
    return uasset[e.serial_offset:e.serial_offset + e.serial_size]


def classify(pkg: Package) -> list[dict]:
    """Inventory rows for the interesting exports of one package."""
    rows = []
    for i, e in enumerate(pkg.exports):
        c = e.class_name
        kind = ("skeletal_mesh" if c in MESH_CLASSES else "skeleton" if c in SKELETON_CLASSES
                else "animation" if c in ANIM_CLASSES else "anim_blueprint" if c in ANIM_BP_CLASSES
                else "physics_asset" if c in PHYSICS_CLASSES else "blueprint_class" if c in BLUEPRINT_CLASSES else None)
        if not kind:
            continue
        row = {"kind": kind, "export": e.name, "export_index": i + 1, "class": c, "serial_size": e.serial_size}
        if kind in ("blueprint_class", "anim_blueprint"):
            row["super"] = e.super_name
            row["super_path"] = pkg.path_of(e.super_index)
        rows.append(row)
    return rows
