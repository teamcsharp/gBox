"""Configuration: one TOML file + env overrides. Secrets (API token) live in data_dir, never in the TOML."""
import os
import platform
import secrets
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

HOST_OS = platform.system().lower()          # "windows" | "linux"


class EmulatorConfig(BaseModel):
    adapter: str = "retroarch"        # "retroarch" | "command" | "rocketlauncher" | "shadps4"
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
    max_duty: float = 0.05            # frame-rate budget: checkpoints slow down so saving takes at most 5% of play time
    two_state: bool = True            # the operator's cap (#2846): one session keeps at most two states — the oldest
                                      # (the moment you came from) and the newest; every checkpoint replaces the newest


class AudioCppConfig(BaseModel):
    """[audio_cpp] audio.cpp (audiocpp_server) as a gBox-managed local speech service (docs/audio_cpp.md, #816)."""
    enabled: bool = True
    binary: str | None = None         # audiocpp_server executable; unset = discovered (PATH, runtime/audio_cpp, C:/_tools, the user profile)
    search: list[str] = []            # extra folders searched for the binary (a build tree's bin folder)
    args: list[str] = []              # extra arguments placed before --config (e.g. ["--ui"])
    url: str | None = None            # an audio.cpp server gBox does not manage (another machine); start/stop then do nothing
    host: str = "127.0.0.1"
    port: int = 8790
    gpu: bool = True                  # true = cuda, false = cpu (backend= wins)
    backend: str = ""                 # explicit backend: cpu | cuda | vulkan | metal
    device: int = 0
    threads: int = 0                  # 0 = the server's default
    models_dir: str | None = None     # default <runtime>/audio_cpp/models (audiocpp_model_manager install <id> --models-dir ...)
    tts_family: str = "kokoro_tts"
    tts_model: str | None = None      # path; unset = the Kokoro GGUF found under models_dir
    tts_voice: str = "af_heart"       # the voice used when a request names none
    tts_language: str = ""            # "" = from the voice prefix (Kokoro: af_/am_ en-us, bf_/bm_ en-gb ...)
    stt_family: str = "qwen3_asr"
    stt_model: str | None = None      # path; unset = the Qwen3-ASR package found under models_dir
    stt_language: str = "en"
    models: list[dict] = []           # extra server.json model entries verbatim (any family audio.cpp supports)
    lazy_load: bool = True
    max_loaded_models: int = 0
    idle_unload_ms: int = 0
    busy_timeout_ms: int = 20000      # audio.cpp answers 503 instead of queueing longer; gBox then takes the other assistant
    autostart: bool = True            # start with the worker / control plane when the binary is on this machine
    start_timeout_s: int = 90


class VoiceConfig(BaseModel):
    """[voice] which speech assistant answers first and what happens when it is busy (docs/audio_cpp.md)."""
    default_assistant: Literal["director", "audio_cpp"] = "director"   # director = Pine Box Voice Director + Wyoming whisper
    fallback: bool = True                 # the other assistant takes a request when the default is busy or down
    director_slots: int = 1               # requests the Director serves at once; further ones go to audio.cpp in parallel
    down_cooldown_s: float = 20.0         # after a Director failure its requests go elsewhere for this long


class ShowcaseConfig(BaseModel):
    """[showcase] the Sonic showcase (gbox/sonic_showcase.py, docs/sonic_showcase.md): a background service on the
    control plane that builds `showcase_sonic_<title>` cast swaps (SA1 + SA2 cast) of the favorites and recently
    played titles, and queues readiness work for titles without a writer. The gBox Settings toggle overrides these."""
    roulette: bool = False  # hourly deterministic target/donor selection, recorded in the showcase receipt
    source_pool: list[str] = ['sonic','mario','sonic,mario']
    enabled: bool = False             # off until the operator turns it on (Settings card or PUT /api/showcase)
    paused: bool = False              # the pause switch: nothing new is planned, built or queued
    favorites: int = 25               # favorites considered per pass (starred titles first)
    recent: int = 10                  # then this many recently played titles
    budget_gb: float = 50.0           # disk cap for showcase builds; older showcase builds are evicted (LRU) to fit
    builds_per_hour: int = 3          # build jobs started per rolling hour
    whole_cast_max_slots: int = 16    # whole cast when it has at most this many slots, else player + main cast
    interval_s: float = 300.0         # seconds between passes (a settings change or POST /api/showcase/run wakes it)
    recheck_hours: float = 6.0        # an up-to-date title is planned again after this long (new donors, writer fixes)
    retry_failed_hours: float = 24.0  # a fresh random seed alone never bypasses failed-writer cooldown
    hdd_root: dict[str, str] = {"linux": "/home/ehm_eckx/samples"}   # os -> the external HDD mount; builds only there
    require_hdd: bool = True          # refuse to build when the mod cache is not on that mount (never fill the NVMe)
    min_free_gb: float = 50.0         # and when the HDD has less than this free
    dedupe: bool = True               # hard-link identical files of a new build to the game's base copy / other showcases
    dedupe_min_mb: int = 4            # files below this size are not compared
    pause_while_playing_anywhere: bool = False   # also wait while a game runs on a Windows PC (default: Spark only)


class GameAudioConfig(BaseModel):
    """[game_audio] where emulators send their sound on a Windows node, and what a slow sound device may cost a launch
    (gbox/game_audio.py). A sleeping or switching output (wireless headset) can hold an emulator's audio init for many
    seconds; RetroArch's main loop, and with it the launch, waits on it."""
    device: str = ""                  # output device name; "" = the default playback device when active, else the first active one
    retroarch_drivers: list[str] = ["xaudio", "wasapi", "null"]   # tried in order; the next one when audio init stalls
    init_grace_s: float = 3.0         # audio init this long without returning -> relaunch with the next driver
    stall_s: float = 6.0              # audio opened slowly, then the core's loop still not answering for this long -> next driver
    boot_wait_s: float = 30.0         # content running within this long (no audio trouble seen)
    extended_wait_s: float = 120.0    # content loaded and audio still opening: wait up to this long instead of failing
    warm_device: bool = True          # open a silent stream on the chosen device while the launch prepares (wakes it)
    remember_driver_h: float = 24.0   # a driver that took over from a stalled one starts first on that device for this long


class RecordingConfig(BaseModel):
    """Background gameplay ring recording (gbox/ring_record.py, #1084): the emulator window is recorded while the
    operator's pad or autoplay is active, so the last `seconds` can be clipped after the fact (PiP export icon)."""
    enabled: bool = True              # false: no background capture (the recording tool's op=enable switches it per session)
    seconds: int = 180                # three-minute PiP replay history
    audio: bool = True                # isolated emulator playback only; never microphone/system monitor
    encoder: str = "auto"             # auto (NVENC when ffmpeg has it, else libx264) | h264_nvenc | hevc_nvenc | libx264
    max_mb: int = 512                 # disk cap per session's ring; the oldest segments go first
    fps: int = 30                     # capture rate
    bitrate_kbps: int = 8000          # capture bitrate (the export re-encodes to the requested file size)
    idle_s: float = 20.0              # capture runs while pad activity was seen within this long; stops after it
    segment_s: int = 5                # length of one ring segment (export granularity is finer: the range is trimmed)
    capture: str = "auto"             # auto (Windows: gdigrab of the game window's screen area; Linux: x11grab of the session display) | gdigrab | ddagrab (Windows, GPU zero-copy, NVENC only) | x11grab
    priority: str = "low"             # low: ffmpeg below the emulator (Windows below-normal, Linux nice 10) | normal
    keep_ended: int = 1               # rings of ended sessions kept for a late export (newest first); older ones are deleted


class BroadcastConfig(BaseModel):
    """[broadcast] One gameplay feed for Pine Box and any media-source software (gbox/broadcast.py, docs/broadcast.md):
    the program (what is on air), one feed per PC and one per session, as MJPEG and H.264 (MPEG-TS, HLS)."""
    enabled: bool = True
    fps: int = 30                     # MJPEG frames a second, constant (?fps=1..60 per viewer); a quiet source is repeated
    ts_fps: int = 30                  # H.264 frame rate (MPEG-TS and HLS)
    size: str = "1280x720"            # H.264 canvas: every source is fitted inside it (letterbox/pillarbox)
    video_kbps: int = 2500            # H.264 bitrate (constant)
    encoder: str = "libx264"          # libx264 (ultrafast) | h264_nvenc; measured on the Spark: about the same CPU
    audio: str = "auto"               # auto: a Spark session's own PipeWire stream goes into the H.264 feeds | off
    audio_kbps: int = 128
    hls_segment_s: int = 1            # HLS segment length (latency is about three of them)
    hls_window_segments: int = Field(default=12, ge=6, le=60)
    hls_retained_segments: int = Field(default=12, ge=2, le=120)
    hold_s: float = 8.0               # a silent source keeps its last frame this long, then the slate (that frame dimmed)
    end_hold_s: float = 2.0           # an ended session's last frame stays this long before the program moves on
    watch_ttl_s: float = 900.0        # the operator's "watching" report counts this long after their app last said so
    linger_s: float = 20.0            # an H.264 encoder nobody reads stops after this (MJPEG costs nothing when unwatched)
    max_encoders: int = 3             # H.264 encoders at once (each ~25% of one Spark core at 720p30)
    auto_agents: bool = True          # auto may put an agent's or a bot's session on air when no operator game runs
    nice: int = 10                    # ffmpeg niceness (Linux)
    lan_url: str = ""                 # the URLs /api/broadcast/feeds hands out; default: public_url
    tailnet_url: str = ""             # e.g. "http://lilspark.tail1fec29.ts.net:8765" (the Spark's tailnet name)
    # Pine Box's names for the PCs (its gboxstream DEVICES) also name the per-PC feeds: /api/broadcast/pc/spark1.mjpg
    pc_aliases: dict[str, str] = {"spark1": "lilspark", "jaybuilt": "JAYBUILTFINALE", "i9nuc": "i9-NUC"}


class HermesLocalConfig(BaseModel):
    """[hermes.local] the Spark's GPU model as Hermes's last-resort route (docs/hermes-local-fallback.md).

    Hermes's route supervisor (hermes_feedback.adjust_routes) switches cron work to this route only when every paid
    route is cooling down or out of credit, or when the operator sets local only; it rotates back by itself as soon as
    a paid route recovers. Hermes reaches the model through gBox's proxy (gbox/llm_proxy.py), never Ollama directly."""
    enabled: bool = True
    provider: str = "spark-local"     # the Hermes custom provider name the supervisor registers
    model: str = "gpt-oss:20b"        # best tool caller on the GB10: MoE (3.6B active), native tool calls, 128k context
    upstream: str = "http://127.0.0.1:11434"   # Ollama on the Spark (native /api/chat: the only API that sets num_ctx)
    api_format: Literal['ollama', 'openai', 'anthropic'] = 'ollama'   # anthropic: Claude's Messages API (llm_proxy)
    host_name: str = 'lilspark'
    shared_with_games: bool = True   # false for an operator-designated dedicated inference machine
    max_parallel_jobs: int = Field(1, ge=1, le=32)
    allow_large_tasks: bool = False  # dedicated local models can work bounded milestones on any inbox task
    priority_only: bool = False      # a paid node takes only requests on the operator's priority list (pool dispatch)
    tool_budget_inbox: int = 0       # #2399: tool budget of an inbox-lane (operator) run when larger than tool_budget; 0 = same
    enable_thinking: bool | None = None   # anthropic: false sends thinking between_tools; else adaptive
    upstream_key_env: str = ''       # optional credential environment variable; never returned in status
    nodes: dict[str, dict] = {}       # named inference endpoints; operator switches live in local-nodes.json
    pool_max_parallel_jobs: int = Field(5, ge=1, le=64)
    proxy_url: str | None = None      # what Hermes calls; default http://127.0.0.1:<api_port>/api/llm/local/v1
    context_tokens: int = 65536       # num_ctx the proxy asks Ollama for; prompts are capped to fit (per-model: contexts)
    contexts: dict[str, int] = {}     # model -> its context limit, when a non-default model is chosen
    max_output_tokens: int = 8192     # reserved for the answer inside the context
    chars_per_token: float = 3.0      # conservative prompt-size estimate (no tokenizer in the control plane)
    keep_alive: str = "10m"           # Ollama unloads the model this long after the last call (frees GPU memory)
    reasoning_effort: str = "medium"  # gpt-oss think level when the call names none (low | medium | high)
    local_only: bool = False          # operator: Hermes uses only the local route (also POST /api/hermes/local)
    queue_limit: int = 8              # calls waiting for the single slot; more answer 503 at once
    queue_wait_s: float = 900.0       # a waiting call gives up with 503 after this long
    request_timeout_s: float = 1800.0 # one model call (prefill of a long prompt on the GPU can take minutes)
    retry_after_s: int = 120          # Retry-After on a 503 while the operator plays on the Spark
    tool_budget: int = 20             # tool calls a local run may make (paid runs: 45), the last 6 for handoff
    pr_label: str = "local model"     # label on draft PRs a local run publishes


class GruntConfig(BaseModel):
    """[hermes.grunt] the Spark helper: LLM-free chores for Hermes, one at a time at idle priority (gbox/spark_grunt.py)."""
    enabled: bool = True
    tick_s: float = 60.0              # how often the helper looks for a due chore
    start_delay_s: float = 180.0      # after the service starts, before the first chore
    disabled: list[str] = []          # chore names switched off (GET /api/grunt lists them)
    cooldowns: dict[str, float] = {}  # chore name -> seconds between runs (overrides the built-in cooldown)
    verify_nodes: list[str] = ["i9-NUC", "spark"]   # verification launches only here ("spark" = this control plane's node)
    never_nodes: list[str] = ["JAYBUILTFINALE"]     # never used for verification launches, whatever else says
    pr_test_timeout_s: float = 900.0  # one draft PR's focused tests
    manifest_budget_mb: int = 4096    # bytes hashed per built-mod manifest pass


class HermesConfig(BaseModel):
    local: HermesLocalConfig = HermesLocalConfig()
    grunt: GruntConfig = GruntConfig()


class Config(BaseModel):
    sync_mod_builds_on_startup: bool = False  # opt-in upload of local builds to this worker's control plane
    preferred_launch_workers: dict[str, str] = Field(default_factory=dict)  # platform -> worker name/ID for auto Play; no fallback
    gameplay_memory_enabled: bool = True  # operator gameplay journal and native capture on supported new launches
    gameplay_native_replay_enabled: bool = False  # experimental: BSV can change native load-state behavior
    data_dir: Path = Path(__file__).resolve().parents[1] / "gbox-data"   # never the working directory's (a script run
                                                                         # from the Spark's home made ~/gbox-data/cache)
    libraries: list[Library] = []
    smb_credentials: str | None = None   # linux credentials file for SMB mounts (never stored in the TOML)
    steam_root: Path | None = None
    cache_dir: Path | None = None     # default: data_dir/cache
    texture_comfy_url: str = "http://127.0.0.1:8188" # local experimental texture upscaler; no external image API
    texture_cpu_python: str = ""       # optional inference environment with torch, spandrel and Pillow
    texture_cpu_model: str = ""        # installed RGB upscaler; no automatic downloads
    cache_dirs: dict[str, str] = {}   # os -> fast local disk for staged titles (overrides cache_dir per node)
    cache_limit_gb: float = 20.0
    cache_limits_gb: dict[str, float] = {}   # os -> size cap for that node's cache
    # Two-tier cache (gbox/cache_tiers.py, docs/cache-tiers.md): cache_dirs is the fast hot tier, cold_cache_dirs a big
    # slow disk behind it. Least recently used per-game units move to the cold tier only while the node is idle and
    # leave a symlink, so <cache>/... paths keep working; access moves them back. Unset for an OS = one tier.
    cold_cache_dirs: dict[str, str] = {}      # os -> cold tier root (must exist: a missing mount is never created)
    hot_cache_limit_gb: dict[str, float] = {} # os -> size the idle demoter keeps the hot tier under (default: cache_limit)
    cache_tier_idle_minutes: float = 30.0     # no session / job / launch on this node for this long before demoting
    cache_tier_warm_fraction: float = 0.5     # after the migration, recently used cold units are promoted up to this share
    cache_tier_promote_wait_s: float = 60.0   # a launch waits for its unit's promotion only if it fits in this; else later
    runtime_dirs: dict[str, str] = {}        # os -> local disk for emulators/cores (never run binaries off a network share)
    stage_min_mb: int = 32            # stage library files larger than this (disc images) onto the local cache before launch
    stage_wait_s: float = 45.0        # a launch waits for a cache copy only if it will finish within this; else the game
                                      # plays from the share and the copy finishes in the background (#1506; 0 = always wait)
    stage_background_mb_s: float = 6.0   # background copy speed cap while a game plays on this PC (0 = no cap)
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    public_url: str | None = None     # how other machines (Blender add-on, clients) reach the control plane
    blender_path: str | None = None
    blender_search: list[str] = []    # dirs searched for the newest blender executable when blender_path is unset
    ghidra_home: str | None = None
    ida_home: str | None = None           # IDA Pro install folder (idat64.exe / idat.exe) for the `ida` tool
    native_decomp: dict = {}  # per-engine home and optional DecompPipeline ghidra_home/java_home/vcvars
    n64recomp_path: str | None = None     # N64Recomp executable or its folder for the `n64recomp` tool
    rpcs3_appimage: str | None = None     # linux PS3 sessions: an RPCS3 AppImage, its extracted AppRun or an rpcs3 binary
                                          # (unset: the official build for this CPU from GitHub, sha256-checked)
    decomp_me_enabled: bool = False       # opt-in: the `decomp_me` tool only talks to the network when true
    decomp_me_url: str = "https://decomp.me/api"
    ninja_ripper: dict = {}               # path, dll, launcher_args, hotkey, output_dir (docs/rip_and_decomp_tools.md)
    rea_env: dict[str, str] = {}      # explicit REA provider environment (GHIDRA_INSTALL_DIR, REA_IDA_MCP_CONFIG, etc.)
    retroarch_bios: dict[str, str] = {}   # os -> BIOS source dir (copied per core on demand)
    display: str = ":90"              # linux: Xvfb display used for headless emulator sessions
    llm_endpoints: list[LLMEndpoint] = []
    # [token_prices] USD per million tokens for the Detailed report's cost estimates, over request_story.DEFAULT_PRICES:
    # "provider/model" or "provider" = { in = 0.6, out = 2.2, cache_read = 0.11 }. Unknown providers get no cost.
    token_prices: dict[str, dict[str, float]] = {}
    agent: dict = {"llm_url": "http://127.0.0.1:11434/v1", "model": "qwen3.6:35b", "searx_url": "http://127.0.0.1:8081",
                   "vision_model": "qwen2.5vl:7b", "voice_director": "http://127.0.0.1:8090", "tts_engine": "xtts",
                   "voice_library": "/home/ehm_eckx/pinevoice-stack/spark-agent/data/voices"}   # in-app chat agent (Spark-local Ollama + SearXNG)
    emulators: dict[str, EmulatorConfig] = {}   # platform -> backend override (defaults come from systems.py)
    examine_ready: bool = False       # Windows: opt-in RenderDoc injection for Examine 3D. Off by default — injecting renderdoc.dll into every launch hung Dolphin's D3D12 renderer (Soul Calibur II froze ~70 s into attract mode with 0% GPU, #1973). Captures relaunch a dedicated Vulkan-layer session instead (gbox.scene_support.relay).
    examine_capture_worker: str = "JAYBUILTFINALE"   # Examine 3D capture sessions run here first (gbox/scene_relay.py)
    rewind: RewindConfig = RewindConfig()   # [rewind] checkpoint rewind for emulators without a native one
    audio_cpp: AudioCppConfig = AudioCppConfig()   # [audio_cpp] local audio.cpp speech service (docs/audio_cpp.md)
    voice: VoiceConfig = VoiceConfig()             # [voice] default speech assistant and busy fallback
    recording: RecordingConfig = RecordingConfig()   # [recording] background gameplay ring (#1084, docs/ring_recording.md)
    broadcast: BroadcastConfig = BroadcastConfig()   # [broadcast] the Pine Box / media-source feeds (docs/broadcast.md)
    hermes: HermesConfig = HermesConfig()           # [hermes.local] GPU fallback route, [hermes.grunt] Spark helper
    showcase: ShowcaseConfig = ShowcaseConfig()      # [showcase] Sonic showcase builds (docs/sonic_showcase.md)
    game_audio: GameAudioConfig = GameAudioConfig()  # [game_audio] emulator sound device + slow-device fallback (gbox/game_audio.py)
    granted_permissions: list[str] = ["read", "execute", "stage", "network"]

    @property
    def cache(self) -> Path:
        if d := self.cache_dirs.get(HOST_OS):
            from .side_dirs import moved
            return moved(Path(os.path.expandvars(d)))      # ~/gbox-cache is ~/gBox_alt/gbox-cache once moved
        return self.cache_dir or self.data_dir / "cache"

    @property
    def cache_limit(self) -> float:
        return self.cache_limits_gb.get(HOST_OS, self.cache_limit_gb)

    @property
    def cold_cache(self) -> Path | None:
        """The cold tier behind self.cache on this OS, or None (single-tier cache)."""
        d = self.cold_cache_dirs.get(HOST_OS)
        return Path(os.path.expandvars(d)) if d else None

    @property
    def hot_cache_limit(self) -> float:
        return self.hot_cache_limit_gb.get(HOST_OS, self.cache_limit)

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
sync_mod_builds_on_startup = false # local builds stay here; explicit build downloads/exports still work
# preferred_launch_workers = { ps4 = "i9-NUC" } # auto Play requires this PC online; explicit node choices override it
granted_permissions = ["read", "execute", "stage", "network"]   # add memory_write / file_mutation / binary_patch explicitly
# smb_credentials = "/etc/nas.cred"     # linux: username=/password= file used for SMB mounts
# blender_search = ["C:/Users/me/Desktop/Blender Builds/Builds"]

# [rewind]                        # Select+L2 rewind on emulators without a native one: periodic save states (docs/rewind.md)
# checkpoints = true              # false: those emulators get no rewind (RetroArch's own rewind is unaffected)
# interval_s = 2.0                # seconds between checkpoints
# depth = 60                      # checkpoints kept per session
# max_mb = 2048                   # disk cap per session
# max_duty = 0.05                 # frame-rate budget: a slow save state stretches the interval (1 s save -> every 20 s)
# two_state = true                # the operator's cap (#2846): one session keeps at most two states — oldest + newest

# [voice]                         # speech assistants (docs/audio_cpp.md)
# default_assistant = "audio_cpp" # "director" (Pine Box Voice Director + Wyoming whisper, the default) or "audio_cpp"
# fallback = true                 # the other assistant answers when the default is busy or down
# director_slots = 1              # Director requests served at once; more go to audio.cpp in parallel

# [audio_cpp]                     # audio.cpp (audiocpp_server) started and supervised by gBox on this machine
# binary = "C:/_tools/audio.cpp/build/windows-cuda-release/bin/audiocpp_server.exe"   # unset = discovered
# port = 8790
# gpu = true                      # cuda; backend = "vulkan" for a non-NVIDIA GPU, gpu = false for cpu
# models_dir = "D:/gBox/runtime/audio_cpp/models"
# tts_family = "kokoro_tts"       # tts_model / stt_model = explicit GGUF paths when discovery finds none
# tts_voice = "af_heart"
# stt_family = "qwen3_asr"
# [hermes.local]                  # the Spark's GPU model as Hermes's last-resort route (docs/hermes-local-fallback.md)
# model = "gpt-oss:20b"           # or "qwen3.8:27b-mtp-q4_K_M" (slower, dense); any Ollama model with tool calls
# context_tokens = 65536
# local_only = false              # true: Hermes uses only the local route
# [hermes.grunt]                  # Spark helper chores at idle priority (GET /api/grunt)
# disabled = []                   # e.g. ["verify_launch_fixes"]
# verify_nodes = ["i9-NUC", "spark"]
# [game_audio]                    # emulator sound on a Windows node (gbox/game_audio.py)
# device = ""                     # output device name; "" = default playback device if active, else the first active one
# retroarch_drivers = ["xaudio", "wasapi", "null"]   # next driver when audio init stalls past init_grace_s
# init_grace_s = 3.0
# extended_wait_s = 120.0         # content loaded, audio still opening: the launch waits this long instead of failing

# [recording]                     # background gameplay ring: right-click the record icon to clip the last minutes (docs/ring_recording.md)
# enabled = true                  # records only while the pad was used in the last idle_s seconds
# seconds = 120                   # how far back a clip can reach
# encoder = "auto"                # auto = h264_nvenc when it works on this node, else libx264 (reported in the status)
# max_mb = 512                    # disk cap per session ring

# [broadcast]                     # gameplay feeds for Pine Box / OBS / VLC (docs/broadcast.md)
# fps = 30                        # MJPEG frames a second (constant); H.264: ts_fps, size, video_kbps, encoder
# tailnet_url = "http://lilspark.tail1fec29.ts.net:8765"   # shown beside the LAN URLs in /api/broadcast/feeds

# [[libraries]]
# id = "roms"
# kind = "files"                  # or "attract" for a HyperSpin / Attract-Mode tree
# paths = { linux = "/mnt/gbox/roms", windows = "//nas/roms" }
# mount = "//nas/roms"            # linux: mounted read-only at paths.linux by `gbox setup`

# [[libraries]]                  # extracted PS4 games: <game>/eboot.bin + <game>/sce_sys/param.sfo
# id = "ps4"
# kind = "files"
# platform = "ps4"
# paths = { windows = "D:/Games/PS4", linux = "/mnt/games/PS4" }
# [emulators.ps4]                # standalone shadPS4 core executable, not QtLauncher
# adapter = "shadps4"
# executable = "D:/Emulators/shadPS4/shadPS4.exe"   # set per-node in gbox.local-<hostname>.toml
# stage_local = false            # eboot.bin needs the complete extracted game folder beside it

# [[llm_endpoints]]
# name = "ollama"
# url = "http://127.0.0.1:11434/v1"
# model = "llama3.1"
"""
