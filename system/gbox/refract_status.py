"""Bounded, read-only Refract installation evidence for the supported RE4 VR package.

Receipts and file metadata establish setup prerequisites, not freshly verified contents,
rendering, native state access, or an autoplay driver. Never calls setup or starts a process.
The time budget is cooperative between local filesystem calls; redirected paths are refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import refract as R
from .models import Permission as P
from .registry import tool
from .storage_policy import SystemDriveRefused

PACKAGE = "com.Armature.VR4"
VERSION = 203
MAX_JSON_BYTES = 64 * 1024
MAX_OPERATIONS, MAX_ENTRIES, MAX_MEMBERS, MAX_SECONDS = 256, 256, 128, 3.
# APK census: docs/evidence/quest-refract/libcxx-rebind-re4vr-v203.txt. The last
# three are copied by vendor/refract/install_apk.py, not inferred game libraries.
APP_LIBRARIES = ("libbink2androidarm64.so", "libbinkpluginandroidarm64.so", "libc++_shared.so", "libovraudio64.so",
                 "libovrplatformloader.so", "libOVRPlugin.so", "libplaycore.so", "libUE4.so", "libvrapi.so",
                 "libopenxr_runtime.so", "librefract_driver.so", "librefract_ovrplatform.so")


class _Probe:
    def __init__(self, clock):
        self.clock, self.deadline = clock, clock() + MAX_SECONDS
        self.operations = self.bytes_read = 0
        self.exhausted = self.any = False
        self.issues = []
        self.entries = {}

    def take(self):
        if self.operations >= MAX_OPERATIONS or self.clock() >= self.deadline:
            self.exhausted = True
            return False
        self.operations += 1
        return True

    def safe_entry(self, path):
        """Inspect each ancestor without following it; cache within this one bounded snapshot."""
        chain = [*reversed(path.parents), path]
        if len(chain) > 32:
            self.issues.append("filesystem:path_depth")
            return None
        for part in chain:
            if part not in self.entries:
                if not self.take():
                    return None
                try:
                    found = part.lstat()
                    if self.redirected(found):
                        self.issues.append("filesystem:redirected")
                        found = None
                except OSError:
                    found = None
                self.entries[part] = found
            if self.entries[part] is None:
                return None
        return self.entries[path]

    @staticmethod
    def redirected(found):
        return stat.S_ISLNK(found.st_mode) or bool(getattr(found, "st_file_attributes", 0) & 0x400)

    def entry(self, path, directory=False):
        found = self.safe_entry(path)
        if found is not None:
            valid = stat.S_ISDIR(found.st_mode) if directory else stat.S_ISREG(found.st_mode)
            if valid:
                self.any = True
                return found.st_size
        return None

    def read(self, path, label):
        size = self.entry(path)
        if size is None:
            return None
        if size > MAX_JSON_BYTES:
            self.issues.append(label + ":oversize")
            return None
        if not self.take():
            return None
        try:
            with path.open("rb") as src:
                data = src.read(MAX_JSON_BYTES + 1)
            self.bytes_read += len(data)
            if len(data) > MAX_JSON_BYTES:
                self.issues.append(label + ":oversize")
                return None
            return data
        except OSError:
            self.issues.append(label + ":unreadable")
            return None

    def json(self, path, label):
        data = self.read(path, label)
        if data is not None:
            try:
                value = json.loads(data)
                if isinstance(value, dict):
                    return value
            except (ValueError, RecursionError):
                pass
            self.issues.append(label + ":invalid")
        return {}

    def libraries(self, directory):
        if self.entry(directory, directory=True) is None or not self.take():
            return False
        found = 0
        try:
            with os.scandir(directory) as entries:
                for count, entry in enumerate(entries):
                    if count >= MAX_ENTRIES or not self.take():
                        self.exhausted = True
                        return False
                    if entry.name.endswith(".so"):
                        observed = entry.stat(follow_symlinks=False)
                        if self.redirected(observed):
                            self.issues.append("filesystem:redirected")
                            return False
                        if stat.S_ISREG(observed.st_mode):
                            found += 1
                            if found >= 50:         # the same minimum as refract.sysroot_ok
                                return True
        except OSError:
            pass
        return False


def _same_path(value, expected):
    return isinstance(value, str) and os.path.normcase(os.path.normpath(value)) == os.path.normcase(str(expected))


def _network_path(path):
    if str(path).startswith(("\\\\", "//")):
        return True
    # A drive letter can also map to a share. GetDriveType examines its mount type,
    # without statting any remote path or opening a network connection.
    if R.HOST_OS == "windows":
        return R.ctypes.windll.kernel32.GetDriveTypeW(R.ctypes.c_wchar_p(str(path.anchor))) == 4
    return False


def _members(receipt):
    identity = receipt.get("identity")
    rows = identity.get("members") if isinstance(identity, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_MEMBERS:
        return None
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            return None
        name, size, crc = row
        if not isinstance(name, str) or not 1 <= len(name) <= 512 or "\\" in name \
                or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts \
                or type(size) is not int or not 0 < size <= 64 * 1024**3 \
                or type(crc) is not int or not 0 <= crc <= 0xFFFFFFFF:
            return None
    return rows


def status(config, package=PACKAGE, version_code=VERSION, *, clock=time.monotonic):
    if package != PACKAGE or type(version_code) is not int or version_code != VERSION:
        raise ValueError("Readiness currently supports com.Armature.VR4 v203 only")
    out = {"schema": "gbox.refract.readiness/1", "package": package, "version_code": version_code,
           "host": R.platform.node(), "state": "unsupported", "setup_ready": False,
           "verification": "receipts_and_file_metadata", "content_hashes_verified": False,
           "rendering_verified": False, "gameplay_verified": False,
           "memory_read_supported": "read_memory" in R.RefractAdapter.supported, "autoplay_supported": False,
           "checks": {}, "missing": [], "issues": [], "budget_exhausted": False}
    try:
        root = R.root(config)
        # No network paths: this diagnostic is only for the configured private local copy.
        if not root.is_absolute() or _network_path(root):
            out["issues"] = ["root:not_local_absolute"]
            return out
        root = R.check_node(config)
    except (R.ToolUnavailable, SystemDriveRefused, OSError, ValueError):
        out["issues"] = ["node:not_supported_by_quest_configuration"]
        return out
    out["root"] = str(root)
    probe, lay = _Probe(clock), R.Layout(root)
    if R.declaration(config, package):
        owner = {"owned": True, "via": "declaration"}
    else:
        path = R.meta_library_path()
        meta = probe.json(path, "ownership") if path is not None and path.is_absolute() and not _network_path(path) else {}
        games = meta.get("games")
        owned = isinstance(games, list) and any(isinstance(g, dict) and g.get("package") == package
                    and g.get("source") == "meta" and g.get("owned") is True for g in games[:256])
        owner = {"owned": bool(owned), **({"via": "meta"} if owned else {})}
    # Ownership metadata alone does not mean any private runtime files are present.
    probe.any = False
    out["ownership"] = owner
    checks = out["checks"]
    checks["ownership"] = owner["owned"]
    release = probe.json(lay.release / R.RELEASE_RECEIPT, "release_receipt")
    checks["release_receipt"] = all(release.get(k) == R.REFRACT[k] for k in ("version", "tag", "commit", "sha256"))
    release_files = [probe.entry(lay.release / name) for name in R.RELEASE_FILES]
    checks["release_files"] = all(size is not None and size > 0 for size in release_files)
    checks["aapt2"] = (probe.entry(lay.aapt2) or 0) > 0
    checks["system_image"] = (probe.entry(lay.system_img) or 0) > 0
    markers = [probe.entry(lay.sysroot / name) for name in ("refract_symlinks.txt", "system/bin/linker64")]
    apex = [probe.entry(lay.sysroot / "apex" / name, directory=True)
            for name in ("com.android.runtime", "com.android.art")]
    libraries = probe.libraries(lay.sysroot / "system/lib64")
    checks["sysroot"] = all(v is not None for v in markers + apex) and libraries

    dest = lay.packages / package / str(version_code)
    apk = dest / f"{package}.apk"
    receipt = probe.json(dest / R.PACKAGE_RECEIPT, "package_receipt")
    members = _members(receipt)
    try:
        info = R.select_members(members, package) if members else None
    except ValueError:
        info = None
        probe.issues.append("package_receipt:invalid")
    recorded = receipt.get("package")
    expected_obbs = {f"{kind}.{version_code}.{package}.obb" for kind in ("main", "patch")}
    valid = isinstance(recorded, dict) and info is not None and recorded.get("package") == package \
        and recorded.get("version_code") == version_code and info["version_code"] == version_code \
        and _same_path(recorded.get("apk"), apk) and recorded.get("apk_size") == info["apk_size"] \
        and recorded.get("apk_crc") == info["apk_crc"] \
        and {PurePosixPath(name).name for name in info["obb"]} == expected_obbs
    checks["package_receipt"] = bool(valid)
    sizes = {PurePosixPath(name).name: size for name, size, crc in (members or [])}
    actual_apk = probe.entry(apk)
    obbs = {name: probe.entry(dest / "obb" / name) for name in sorted(expected_obbs)}
    checks["package_files"] = bool(valid and actual_apk == info["apk_size"]
                                  and all(obbs[name] == sizes.get(name) for name in expected_obbs))
    app = lay.apps / package
    installed = probe.json(app / R.INSTALL_RECEIPT, "app_receipt")
    app_files = [probe.entry(app / name) for name in ("app.properties", "classes.jar")]
    checks["app_files"] = all(size is not None and size > 0 for size in app_files)
    properties = probe.read(app / "app.properties", "app_properties")
    props = {}
    if properties is not None:
        try:
            props = dict(line.split("=", 1) for line in properties.decode("utf-8").splitlines() if "=" in line)
        except (ValueError, UnicodeError):
            probe.issues.append("app_properties:invalid")
    checks["app_identity"] = props.get("package") == package and props.get("versionCode") == str(version_code) \
        and bool(props.get("activity")) and _same_path(props.get("apk"), apk)
    native_files = [probe.entry(app / "lib/arm64" / name) for name in APP_LIBRARIES]
    checks["app_native_libraries"] = all(size is not None and size > 0 for size in native_files)
    any_installation = probe.any
    digest = hashlib.sha256()
    sources = [probe.read(R.VENDOR / name, "installer_source") for name in ("install_apk.py", "private_libcxx.py")]
    for source in sources:
        if source is not None:
            digest.update(source)
    want = installed.get("want")
    app_apk = want.get("apk") if isinstance(want, dict) else None
    checks["app_current"] = bool(valid and isinstance(app_apk, list) and len(app_apk) == 3
        and _same_path(app_apk[0], apk) and app_apk[1:] == [info["apk_size"], info["apk_crc"]]
        and all(source is not None for source in sources) and want.get("installer") == digest.hexdigest()[:16]
        and want.get("refract") == R.REFRACT["version"])
    probe.take()                                     # account for time spent in the final read as well
    out.update(budget_exhausted=probe.exhausted, issues=probe.issues,
               operations=probe.operations, bytes_read=probe.bytes_read,
               missing=[name for name, good in checks.items() if not good])
    out["setup_ready"] = all(checks.values()) and not probe.exhausted
    out["state"] = "incomplete" if probe.exhausted else "ready" if out["setup_ready"] else "partial" if any_installation else "missing"
    return out


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: Literal["com.Armature.VR4"] = PACKAGE
    version_code: Literal[203] = VERSION


class StatusOut(BaseModel):
    worker_id: str
    result: dict


@tool("refract_status", "1.0", StatusIn, StatusOut, capabilities=["runtime"], permissions=[P.READ], timeout_s=10)
def refract_status(inp: StatusIn, ctx):
    """Read bounded local Refract/RE4 VR v203 setup evidence on this worker; no install, launch, input, or network."""
    return {"worker_id": ctx.worker, "result": status(ctx.config, inp.package, inp.version_code)}
