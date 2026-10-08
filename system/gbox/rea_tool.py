"""Complete upstream REA tool contracts, exposed as native audited gBox jobs."""
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar

from jsonschema import validators
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import rea
from .models import Permission as P
from .registry import Tool, REGISTRY, tool

CATALOG = json.loads(gzip.decompress(Path(__file__).with_name("rea_catalog.json.gz").read_bytes()))


class ContractInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    contract: ClassVar[dict] = {}

    @model_validator(mode="before")
    @classmethod
    def validate_contract(cls, value):
        validator = validators.validator_for(cls.contract)
        try:
            validator(cls.contract).validate(value)
        except Exception as exc:
            from jsonschema import ValidationError
            if not isinstance(exc, ValidationError):
                raise
            raise ValueError(f"REA input {list(exc.absolute_path)}: {exc.message}") from exc
        return value

    @classmethod
    def model_json_schema(cls, **kwargs):
        return cls.contract


class Result(BaseModel):
    upstream_tool: str
    version: str
    worker_id: str
    result: dict
    evidence_sha256: str


def inline_result(result):
    """Keep full evidence in the artifact, never duplicate a graph in every poll."""
    if len(json.dumps(result, ensure_ascii=False).encode()) <= 32768:
        return result
    structured = result.get("structuredContent")
    candidate = {k: v for k, v in result.items() if k != "content"}
    if len(json.dumps(candidate, ensure_ascii=False).encode()) <= 32768:
        return candidate | {"_gbox_truncated": True, "_gbox_full_result": "rea-result.json"}

    def compact(value, depth=0):
        if isinstance(value, dict):
            if depth >= 5:
                return {"_gbox_omitted": True, "keys": list(value)[:10]}
            return {k: compact(v, depth + 1) for k, v in list(value.items())[:20]}
        if isinstance(value, list):
            return [compact(v, depth + 1) for v in value[:5]]
        if isinstance(value, str) and len(value) > 1000:
            return value[:1000] + " [gBox inline excerpt; complete value in artifact]"
        return value

    summary = {"structuredContent": compact(structured), "isError": bool(result.get("isError")),
               "_gbox_truncated": True, "_gbox_full_result": "rea-result.json"}
    if len(json.dumps(summary, ensure_ascii=False).encode()) > 32768:
        summary["structuredContent"] = {"_gbox_omitted": True, "keys": list(structured or {})[:20]}
    return summary


def validate_result(out, artifacts):
    data = artifacts.get("rea-result.json")
    if data is None or hashlib.sha256(data).hexdigest() != out.evidence_sha256:
        return ["REA result artifact missing or hash mismatch"]
    try:
        record = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return ["REA result artifact is not valid UTF-8 JSON"]
    if not isinstance(record, dict) or any(k not in record for k in ("upstream_tool", "version", "worker_id", "result")) or not isinstance(record["result"], dict):
        return ["REA result artifact lacks its typed operation/worker/result identity"]
    if any(record[k] != getattr(out, k) for k in ("upstream_tool", "version", "worker_id")) or inline_result(record["result"]) != out.result:
        return ["REA output differs from preserved result artifact"]
    if record["result"].get("isError"):
        return ["REA reported a tool error; inspect the preserved result artifact"]
    contract = next(t for t in CATALOG["tools"] if t["name"] == out.upstream_tool)
    structured = record["result"].get("structuredContent")
    if structured is None:
        return ["REA omitted its advertised structured output"]
    cls = validators.validator_for(contract["outputSchema"])
    errors = list(cls(contract["outputSchema"]).iter_errors(structured))
    return [f"REA output schema: {e.message}" for e in errors[:5]]


def invoke(name, inp, ctx):
    ctx.progress(1, f"REA {name} on {ctx.worker}")
    result = rea.session(ctx.config).request("tools/call", {"name": name, "arguments": inp.model_dump()}, timeout=900,
              progress=lambda: ctx.progress(1, f"REA {name} still running on {ctx.worker}"))
    record = {"upstream_tool": name, "version": rea.VERSION, "worker_id": ctx.worker, "result": result}
    data = json.dumps(record, ensure_ascii=False).encode()
    ctx.artifact("rea-result.json", data, "application/json", upstream="https://github.com/morluto/rea", version=rea.VERSION, tool=name)
    ctx.progress(100, f"REA {name} returned evidence")
    return record | {"result": inline_result(result), "evidence_sha256": hashlib.sha256(data).hexdigest()}


def permissions(contract):
    effects = contract["effects"]
    result = [P.READ, P.EXECUTE]  # every call owns a persistent REA subprocess
    if effects["accessesNetwork"]:
        result.append(P.NETWORK)
    if effects["writesFilesystem"]:
        result.append(P.FILE_MUTATION)
    if effects["mutatesTarget"]:
        result.append(P.MEMORY_WRITE)
    return result


for _contract in CATALOG["tools"]:
    _name = _contract["name"]
    _input = type("Rea_" + _name, (ContractInput,), {"contract": _contract["inputSchema"]})

    def _run(inp, ctx, name=_name):
        return invoke(name, inp, ctx)

    REGISTRY["rea_" + _name] = Tool(
        name="rea_" + _name, version=rea.VERSION, fn=_run, In=_input, Out=Result,
        description=_contract["description"] + " Keep subsequent calls on the same worker_id. Full evidence is in rea-result.json.",
        capabilities=["reverse-engineering", "rea", _contract["kind"]], platforms=["windows", "linux", "darwin"],
        permissions=permissions(_contract),
        side_effects=[k for k, value in _contract["effects"].items() if value and k != "idempotent"],
        artifacts=["rea-result.json"], timeout_s=1080, check=rea.unavailable,
        validate=validate_result, validation="upstream structured output schema + preserved result artifact hash and identity")


class DiscoverIn(BaseModel):
    query: str = ""
    name: str = ""       # exact upstream or gBox name returns complete contract


class DiscoverOut(BaseModel):
    version: str
    tools: list[dict]


@tool("rea_tools", rea.VERSION, DiscoverIn, DiscoverOut, capabilities=["rea", "discovery"], platforms=["windows", "linux", "darwin"])
def discover(inp, ctx):
    """Search all REA operations; exact name returns schemas, effects and examples without executing REA."""
    name = inp.name.removeprefix("rea_")
    items = [t for t in CATALOG["tools"] if (not name or t["name"] == name) and
             (not inp.query or inp.query.lower() in (t["name"] + " " + t["description"] + " " + t["kind"]).lower())]
    return {"version": rea.VERSION, "tools": [dict(t, gbox_name="rea_" + t["name"]) if name else
            {"name": "rea_" + t["name"], "description": t["description"], "kind": t["kind"]} for t in items]}


class ProtocolIn(BaseModel):
    method: str = Field(pattern=r"^(resources/(list|templates/list|read)|prompts/(list|get))$")
    params: dict = {}


class ProtocolOut(BaseModel):
    worker_id: str
    result: dict


@tool("rea_resources", rea.VERSION, ProtocolIn, ProtocolOut, capabilities=["rea", "evidence"],
      permissions=[P.READ, P.EXECUTE], platforms=["windows", "linux", "darwin"], check=rea.unavailable, timeout_s=1080)
def resources(inp, ctx):
    """Access REA MCP resources/templates and workflow prompts on the same analysis worker."""
    return {"worker_id": ctx.worker, "result": rea.session(ctx.config).request(inp.method, inp.params)}


class ReadResultIn(BaseModel):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pointer: str = ""                 # RFC 6901 JSON Pointer into the original result artifact
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class ReadResultOut(BaseModel):
    sha256: str
    pointer: str
    value: Any
    total: int | None
    next_offset: int | None
    truncated: bool


@tool("read_rea_result", rea.VERSION, ReadResultIn, ReadResultOut, capabilities=["rea", "evidence"],
      platforms=["windows", "linux", "darwin"], timeout_s=180)
def read_result(inp, ctx):
    """Read/paginate original REA evidence by JSON Pointer when inline output is truncated. Empty pointer lists root keys."""
    import httpx
    base = ctx.server or ctx.config.public_url or f"http://127.0.0.1:{ctx.config.api_port}"
    headers = ctx.headers or {"authorization": "Bearer " + ctx.config.token()}
    response = httpx.get(base + "/api/artifacts/" + inp.sha256, headers=headers, timeout=120)
    response.raise_for_status()
    data = response.content
    if hashlib.sha256(data).hexdigest() != inp.sha256:
        raise ValueError("REA evidence download does not match its content hash")
    value = json.loads(data)
    if inp.pointer and not inp.pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or start with /")
    for token in inp.pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdigit() or len(token) > 1 and token.startswith("0"):
                raise ValueError("JSON Pointer array index must be a non-negative decimal integer")
            value = value[int(token)]
        else:
            value = value[token]
    total, next_offset, truncated = None, None, False
    if isinstance(value, dict):
        # Navigation returns keys, so a large child never hides its siblings.
        keys = list(value)
        total = len(keys)
        value = {"keys": keys[inp.offset:inp.offset + inp.limit]}
    elif isinstance(value, list):
        total = len(value)
        page = []
        for index, item in enumerate(value[inp.offset:inp.offset + inp.limit], inp.offset):
            if len(json.dumps(item, ensure_ascii=False).encode()) > 20000:
                item = {"_gbox_omitted": True, "pointer": inp.pointer + "/" + str(index)}
                truncated = True
            if len(json.dumps(page + [item], ensure_ascii=False).encode()) > 24000:
                break
            page.append(item)
        value = page
    elif isinstance(value, str):
        total = len(value)
        value = value[inp.offset:inp.offset + 6000]
    if total is not None:
        consumed = len(value["keys"]) if isinstance(value, dict) else len(value)
        next_offset = inp.offset + consumed if inp.offset + consumed < total else None
        truncated |= next_offset is not None
    excerpt = inline_result({"structuredContent": {"value": value}})
    if excerpt.get("_gbox_truncated"):
        value = excerpt["structuredContent"].get("value", excerpt["structuredContent"])
        truncated = True
    return {"sha256": inp.sha256, "pointer": inp.pointer, "value": value, "total": total,
            "next_offset": next_offset, "truncated": truncated}
