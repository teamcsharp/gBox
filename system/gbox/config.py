"""Configuration: one TOML file + env overrides. Secrets (API token) live in data_dir, never in the TOML."""
import os
import platform
import secrets
import tomllib
from pathlib import Path

from pydantic import BaseModel

HOST_OS = platform.system().lower()          # "windows" | "linux"


class EmulatorConfig(BaseModel):
    adapter: str = "retroarch"        # "retroarch" | "command" | "rocketlauncher"
    executable: str | None = None     # default for retroarch: the provisioned/apt retroarch
    core: str | None = None           # libretro core name ("flycast") or path to a .so/.dll
    args: list[str] = []              # extra args; "{rom}" is substituted for the command adapter
    stage_local: bool = False         # copy into the bounded cache before launch


class Library(BaseModel):
    """A game collection on the network. Paths are per-OS so Linux and Windows nodes resolve the same games."""
    id: str
    kind: str = "files"               # "attract" (HyperSpin/Attract-Mode tree) | "files" (plain ROM/ISO folders)
    paths: dict[str, str]             # os -> root path, e.g. {"linux": "/mnt/gbox/hyperspin/Arcade", "windows": "//nas/..."}
    mount: str | None = None          # linux: SMB source to mount at paths["linux"] during setup
    mount_root: str | None = None     # linux: mountpoint when paths["linux"] is a subdir of the share
    hash: bool = False                # content-hash files during scan (slow over SMB; on demand otherwise)
    platform: str | None = None       # known console for a plain ROM folder (disc containers have ambiguous extensions)
    recursive: bool = True
    exclude_dirs: list[str] = []      # relative folder globs, e.g. BIOS and emulator installations
    exclude_files: list[str] = []

    def root(self, os_: str = HOST_OS) -> Path | None:
        p = self.paths.get(os_)
        return Path(p) if p else None


class LLMEndpoint(BaseModel):
    name: str
    url: str                          # OpenAI-compatible base, e.g. http://127.0.0.1:11434/v1
    model: str
    api_key_env: str | None = None    # name of env var holding the key, never the key itself


class RewindConfig(BaseModel):
    """Select+L2 rewind where the emulator has no native rewind (gbox/rewind.py): a ring of periodic save states."""
    checkpoints: bool = True          # off: Select+L2 does nothing on those emulators (launch_game rewind= overrides per session)
    interval_s: float = 2.0           # seconds between checkpoints (one save state each)
    depth: int = 60                   # checkpoints kept per session (about two minutes at the default interval)
    max_mb: int = 2048                # disk cap per session's ring; the oldest checkpoints go first
    repeat_s: float = 0.6             # holding Select+L2: one older checkpoint per repeat


class Config(BaseModel):
    data_dir: Path = Path("gbox-data")
    libraries: list[Library] = []
    smb_credentials: str | None = None   # linux credentials file for SMB mounts (never stored in the TOML)
    steam_root: Path | None = None
    cache_dir: Path | None = None     # default: data_dir/cache
    cache_dirs: dict[str, str] = {}   # os -> fast local disk for staged titles (overrides cache_dir per node)
    cache_limit_gb: float = 20.0
    cache_limits_gb: dict[str, float] = {}   # os -> size cap for that node's cache
    runtime_dirs: dict[str, str] = {}        # os -> local disk for emulators/cores (never run binaries off a network share)
    stage_min_mb: int = 32            # stage library files larger than this (disc images) onto the local cache before launch
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    public_url: str | None = None     # how other machines (Blender add-on, clients) reach the control plane
    blender_path: str | None = None
    blender_search: list[str] = []    # dirs searched for the newest blender executable when blender_path is unset
    ghidra_home: str | None = None
    rea_env: dict[str, str] = {}      # explicit REA provider environment (GHIDRA_INSTALL_DIR, REA_IDA_MCP_CONFIG, etc.)
    retroarch_bios: dict[str, str] = {}   # os -> BIOS source dir (copied per core on demand)
    display: str = ":90"              # linux: Xvfb display used for headless emulator sessions
    llm_endpoints: list[LLMEndpoint] = []
    agent: dict = {"llm_url": "http://127.0.0.1:11434/v1", "model": "qwen3.6:35b", "searx_url": "http://127.0.0.1:8081",
                   "vision_model": "qwen2.5vl:7b", "voice_director": "http://127.0.0.1:8090", "tts_engine": "xtts",
                   "voice_library": "/home/ehm_eckx/pinevoice-stack/spark-agent/data/voices"}   # in-app chat agent (Spark-local Ollama + SearXNG)
    emulators: dict[str, EmulatorConfig] = {}   # platform -> backend override (defaults come from systems.py)
    examine_ready: bool = True        # Windows: local-window emulators start with RenderDoc inside (Examine 3D, gbox.scene_capture)
    rewind: RewindConfig = RewindConfig()   # [rewind] checkpoint rewind for emulators without a native one
    granted_permissions: list[str] = ["read", "execute", "stage", "network"]

    @property
    def cache(self) -> Path:
        if d := self.cache_dirs.get(HOST_OS):
            return Path(os.path.expandvars(d))
        return self.cache_dir or self.data_dir / "cache"

    @property
    def cache_limit(self) -> float:
        return self.cache_limits_gb.get(HOST_OS, self.cache_limit_gb)

    @property
    def runtime(self) -> Path:
        """Per-host installed runtimes (cores, BIOS copies, ghidra...). Separate per OS so a shared repo works."""
        if d := self.runtime_dirs.get(HOST_OS):
            return Path(os.path.expandvars(d))
        return self.data_dir / f"runtime-{HOST_OS}-{platform.machine().lower()}"

    def library(self, lib_id: str) -> Library:
        for lib in self.libraries:
            if lib.id == lib_id:
                return lib
        raise KeyError(f"library {lib_id} not configured")

    def token(self) -> str:
        if t := os.environ.get("GBOX_TOKEN"):
            return t
        p = self.data_dir / "api_token"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(secrets.token_urlsafe(32))
        return p.read_text().strip()


def local_overlay(path: Path) -> Path:
    """Per-machine settings written by the setup wizard (gBox.sh): gbox.local-<host>.toml next to gbox.toml."""
    return path.with_name(f"gbox.local-{platform.node().lower()}.toml")


def load(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("GBOX_CONFIG", "gbox.toml"))
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    over = local_overlay(path)
    if over.exists():                                      # wizard choices win; tables merge one level deep
        for k, v in tomllib.loads(over.read_text()).items():
            data[k] = data.get(k, {}) | v if isinstance(v, dict) and isinstance(data.get(k), dict) else v
    if not data:
        return Config()
    cfg = Config(**data)
    if not cfg.data_dir.is_absolute():
        cfg.data_dir = path.parent / cfg.data_dir
    return cfg


TEMPLATE = """\
# gBox configuration.
data_dir = "gbox-data"            # artifacts, DB, audit ledger, api_token, runtimes
api_host = "127.0.0.1"            # bind 0.0.0.0 only on a trusted LAN; token auth is always on
api_port = 8765
cache_limit_gb = 20
granted_permissions = ["read", "execute", "stage", "network"]   # add memory_write / file_mutation / binary_patch explicitly
# smb_credentials = "/etc/nas.cred"     # linux: username=/password= file used for SMB mounts
# blender_search = ["C:/Users/me/Desktop/Blender Builds/Builds"]

# [rewind]                        # Select+L2 rewind on emulators without a native one: periodic save states (docs/rewind.md)
# checkpoints = true              # false: those emulators get no rewind (RetroArch's own rewind is unaffected)
# interval_s = 2.0                # seconds between checkpoints
# depth = 60                      # checkpoints kept per session
# max_mb = 2048                   # disk cap per session

# [[libraries]]
# id = "roms"
# kind = "files"                  # or "attract" for a HyperSpin / Attract-Mode tree
# paths = { linux = "/mnt/gbox/roms", windows = "//nas/roms" }
# mount = "//nas/roms"            # linux: mounted read-only at paths.linux by `gbox setup`

# [[llm_endpoints]]
# name = "ollama"
# url = "http://127.0.0.1:11434/v1"
# model = "llama3.1"
"""
