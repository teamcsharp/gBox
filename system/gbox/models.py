"""Core contracts shared by the control plane and every worker (Linux and Windows)."""
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class Permission(StrEnum):
    READ = "read"
    EXECUTE = "execute"              # launch processes / games
    STAGE = "stage"                  # copy into cache/staging (never touches originals)
    NETWORK = "network"              # call external services (LLMs)
    INSTALL = "install"              # download/install runtimes, cores, packages (gbox setup)
    MEMORY_WRITE = "memory_write"
    FILE_MUTATION = "file_mutation"
    BINARY_PATCH = "binary_patch"


class ToolInfo(BaseModel):
    """Plan §19 tool schema."""
    name: str
    version: str
    description: str
    capabilities: list[str]
    input_schema: dict
    output_schema: dict
    platforms: list[str]             # host OSes the tool runs on: "windows", "linux"
    engines: list[str]               # game platforms/engines it applies to, ["*"] = any
    permissions: list[Permission]
    side_effects: list[str]
    artifacts: list[str]
    timeout_s: float
    retries: int
    validation: str


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"          # tool ran AND independent validation passed
    INVALID = "invalid"              # tool ran but validation failed
    FAILED = "failed"                # tool raised / unavailable
    REJECTED = "rejected"            # permission denied before running


class Job(BaseModel):
    parent_request_id: str | None = None
    id: str = Field(default_factory=new_id)
    tool: str
    input: dict[str, Any] = {}
    require_os: str | None = None    # pin to "windows"/"linux" only when necessary
    require_worker: str | None = None
    agent_use: bool = False       # agent is using a PC; keep its output unobtrusive
    state: JobState = JobState.QUEUED
    worker_id: str | None = None
    created: float = Field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    output: dict | None = None
    error: str | None = None
    receipt_id: str | None = None


class ArtifactRef(BaseModel):
    sha256: str
    name: str
    size: int
    media_type: str
    provenance: dict = {}


class Receipt(BaseModel):
    id: str = Field(default_factory=new_id)
    job_id: str
    tool: str
    tool_version: str
    worker_id: str
    input_sha256: str
    output_sha256: str | None
    artifacts: list[ArtifactRef]
    started: float | None
    finished: float
    validation_ok: bool
    validation_problems: list[str]
    audit_seq: int | None = None


class WorkerInfo(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    os: str
    tools: list[str]                 # tools this worker can actually run right now
    unavailable: dict[str, str] = {} # tool -> reason (shown in UI; never hidden)
    last_seen: float = Field(default_factory=time.time)
    idle_seconds: float | None = None  # time since local user input; unknown on headless workers
    active_jobs: int = 0
    features: list[str] = []


class CatalogEntry(BaseModel):
    """Plan §5 catalog fields."""
    game_id: str
    title: str
    alt_title: str | None = None     # e.g. internal disc-header name ("PHANTASY STAR ONLINE EPISODE I&II")
    platform: str
    platform_confidence: str = "extension"   # "header" | "extension" | "manifest"
    region: str | None = None
    serial: str | None = None
    source_paths: list[str]
    library: str | None = None       # library id; rel_path is resolved per-OS on whichever node runs it
    rel_path: str | None = None
    system: str | None = None        # source collection/system name (e.g. HyperSpin "Sega Dreamcast")
    collections: list[str] = []      # every collection/romlist that lists this game
    core: str | None = None          # default libretro core, None = Windows node only
    year: str | None = None
    manufacturer: str | None = None
    category: str | None = None
    clone_of: str | None = None
    players: str | None = None
    media: dict[str, list[str]] = {} # kind (boxart/snap/wheel/cartart) -> candidate library-relative stems
    hashes: dict[str, str] = {}
    size: int = 0
    format: str
    runtimes: dict[str, str] = {}    # adapter -> "configured" | "not_configured"
    playable: str = "untested"
    analysis: str = "none"
    asset_mapping: str = "none"
    autoplay: str = "none"
    modding: str = "none"
    launch: dict = {}                # launch recipe
    profile_id: str


class KnowledgeEdge(BaseModel):
    """Plan §20: every fact carries confidence + provenance; 'validated' requires evidence artifacts."""
    id: str = Field(default_factory=new_id)
    game_id: str
    src: str
    rel: str
    dst: str
    confidence: float = 0.5
    status: str = "hypothesis"       # hypothesis | validated | deprecated
    evidence: list[str] = []         # artifact sha256s
    source: str                      # who/what asserted it
    created: float = Field(default_factory=time.time)


class RunRecord(BaseModel):
    """Plan §21 experiment record."""
    id: str = Field(default_factory=new_id)
    game_id: str
    build_hash: str | None = None
    objective: str
    initial_state: str | None = None
    policy_version: str
    proposer: str
    observations: list[str] = []     # artifact sha256s
    outcome: str | None = None
    metrics: dict[str, float] = {}
    artifacts: list[str] = []
    cost_s: float | None = None
    evaluation: dict | None = None   # set only by a different actor than proposer
    knowledge_changes: list[str] = []
    retention: str = "keep"          # keep | summarize | delete
    created: float = Field(default_factory=time.time)
