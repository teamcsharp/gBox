"""Copy cached report-moment evidence before dispatching worker capture jobs.

These sources are independently sampled, not an atomic emulator snapshot. Their own timestamps remain attached.
No memory reads, game input, new inspector, or state-slot operations are performed here.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import subprocess
import time

JSON_MAX = 5 * 1024 * 1024
JPEG_MAX = 8 * 1024 * 1024
SVG_MAX = 4 * 1024 * 1024
ROWS_MAX = 200


def _hex_values(value):
    if isinstance(value, dict):
        return {k: _hex_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_hex_values(v) for v in value]
    return hex(value) if isinstance(value, int) and not isinstance(value, bool) else value


def _json(value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > JSON_MAX:
        raise ValueError("cached source exceeds the 5 MiB report limit")
    return data


def cached(sid, live, tactical, telemetry, inspectors):
    """Server callback: copy available caches only; a busy inspector is reported rather than waited on."""
    out = {}
    lv = live.get(sid)
    if lv:
        with lv["cond"]:
            if lv.get("frame"):
                out["stream"] = {"data": bytes(lv["frame"]), "at": lv["ts"], "seq": lv["seq"]}
    if tactical is not None:
        with tactical.lock:
            row = tactical.frames.get(sid)
            if row:
                frame = copy.deepcopy(row["frame"])
                out["tactical"] = {"frame": frame, "stage": copy.deepcopy(tactical.stages.get(frame.get("stage"))),
                                   "at": row["at"], "seq": row["seq"]}
    tel = telemetry.get(sid)
    if tel:
        out["telemetry"] = {"data": copy.deepcopy(tel), "at": tel.get("at")}
    with inspectors._LOCK:
        inspector = inspectors._INSPECTORS.get(sid)
    if inspector is not None:
        if inspector.eval_lock.acquire(blocking=False):
            try:
                if inspector.last is not None:
                    rows = inspector.last.rows()
                    out["ram_fields"] = {"data": {"rows": copy.deepcopy(rows[:ROWS_MAX]),
                        "raw": copy.deepcopy(inspector.last.raw), "raw_hex": _hex_values(inspector.last.raw),
                        "errors": copy.deepcopy(inspector.last.errors),
                        "rows_omitted": max(0, len(rows) - ROWS_MAX)}, "at": inspector.last_at}
            except Exception as exc:
                out["ram_fields"] = {"error": f"cached RAM fields unavailable: {exc}"[:300]}
            finally:
                inspector.eval_lock.release()
        else:
            out["ram_fields"] = {"error": "RAM inspector is busy; no cached fields copied"}
    return out


def capture(provider, sid, received_at):
    """Freeze source bytes/JSON at receipt, before ticket creation or asynchronous capture submission."""
    out = {"session_id": sid, "report_received_at": received_at, "copied_at": time.time(), "sources": {}}
    try:
        sources = provider(sid) if provider else {}
    except Exception as exc:  # A failed optional cache must not lose the operator's report.
        out["capture_error"] = str(exc)[:300]
        sources = {}
    for name in ("stream", "tactical", "telemetry", "ram_fields"):
        source = sources.get(name)
        try:
            if not isinstance(source, dict):
                raise ValueError(f"no cached {name.replace('_', ' ')} for this session")
            source = copy.deepcopy(source)
            if source.get("error"):
                raise ValueError(source["error"])
            at = source.get("at")
            if not isinstance(at, (float, int)) or not math.isfinite(at) or at <= 0:
                raise ValueError("source timestamp unavailable")
            source["source_at"] = at
            source["age_s"] = round(received_at - at, 6)
            source["timestamp_basis"] = "server cache receipt / inspector read time"
            if name == "stream":
                data = source.get("data")
                if not isinstance(data, bytes) or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                    raise ValueError("cached stream is not a complete JPEG")
                if len(data) > JPEG_MAX:
                    raise ValueError("cached JPEG exceeds 8 MiB report limit")
            else:
                _json(source)
            out["sources"][name] = source
        except (TypeError, ValueError) as exc:
            out["sources"][name] = {"error": str(exc)[:300]}
    out["copied_at"] = time.time()
    return out


def render_map(frame, stage):
    """Use the same geometry/marks renderer as the tactical panel; never fetch a later frame."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "render_tactical_map.cjs"
    payload = _json({"frame": frame, "stage": stage, "width": 960, "height": 720})
    result = subprocess.run(["node", str(script)], input=payload, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=5, check=False)
    if result.returncode:
        raise ValueError("map renderer failed: " + result.stderr.decode("utf-8", "replace")[:200])
    if len(result.stdout) > SVG_MAX or b"<svg" not in result.stdout[:300]:
        raise ValueError("map renderer returned invalid or oversized SVG")
    return result.stdout


def prepare_map(packet):
    """Render outside the store lock, from the already frozen sources."""
    tactical = packet["sources"]["tactical"]
    if not tactical.get("error"):
        try:
            packet["_map"] = render_map(tactical["frame"], tactical.get("stage"))
        except Exception as exc:
            packet["_map_error"] = str(exc)[:300]


def attach(store, packet, note, rid, renderer=None):
    """Attach frozen evidence; source absence/failure remains visible independently of later worker jobs."""
    sources, evidence, attachments = packet["sources"], {}, []
    provenance = {"request": rid, "coach_note": note, "session_id": packet["session_id"],
                  "report_received_at": packet["report_received_at"]}

    def put(kind, data, suffix, media, source):
        try:
            ref = store.put_artifact(data, f"coach-{note}-{suffix}", media,
                                     provenance | {k: source[k] for k in ("source_at", "age_s") if k in source})
            attachments.append({"sha256": ref.sha256, "name": ref.name, "type": media, "size": ref.size})
            evidence[kind] = {"state": "done", "sha256": ref.sha256, "name": ref.name, "size": ref.size,
                              **{k: source[k] for k in ("source_at", "age_s", "seq") if k in source}}
            age = source.get("age_s")
            evidence[kind]["detail"] = (f"cached source age {age:.3f}s at report receipt" if age is not None
                                         else "report receipt and independently sampled source timestamps")
        except Exception as exc:
            evidence[kind] = {"state": "failed", "detail": f"attachment failed: {exc}"[:300]}

    for name, source in sources.items():
        if source.get("error"):
            evidence[name] = {"state": "skipped", "detail": source["error"]}
        elif name == "stream":
            put(name, source["data"], "report-frame.jpg", "image/jpeg", source)
        else:
            evidence[name] = {"state": "done", "source_at": source["source_at"], "age_s": source["age_s"],
                              "detail": "included in report-moment.json; cached, not a fresh RAM dump"}
    tactical = sources["tactical"]
    if tactical.get("error"):
        evidence["map"] = {"state": "skipped", "detail": tactical["error"]}
    else:
        try:
            if packet.get("_map_error"):
                raise ValueError(packet["_map_error"])
            svg = packet.get("_map") or (renderer or render_map)(tactical["frame"], tactical.get("stage"))
            put("map", svg, "report-map.svg", "image/svg+xml", tactical)
        except Exception as exc:
            evidence["map"] = {"state": "failed", "detail": f"map render failed: {exc}"[:300]}
    manifest = {k: v for k, v in packet.items() if k != "sources" and not k.startswith("_")}
    manifest |= {"schema": "gbox.coaching.moment/1", "sources": {
        k: {a: b for a, b in v.items() if not (k == "stream" and a == "data")} for k, v in sources.items()},
        "evidence": copy.deepcopy(evidence),
        "limits": ["Sources are sampled independently; source timestamps and ages identify skew or stale data.",
                   "Map includes only published objects and verified geometry; absent items/windows are unknown.",
                   "RAM fields are cached decoded values/raw integers and addresses, not the complete byte dump.",
                   "Capture jobs run asynchronously after receipt; any observation-time cache is identified by its own timing fields.",
                   "No video clip is captured by this report."]}
    try:
        put("moment", _json(manifest), "report-moment.json", "application/json", {})
    except (TypeError, ValueError) as exc:
        evidence["moment"] = {"state": "failed", "detail": str(exc)[:300]}
    if evidence["moment"]["state"] != "done":
        for name in ("tactical", "telemetry", "ram_fields"):
            if evidence[name]["state"] == "done":
                evidence[name] = {"state": "failed", "detail": "report-moment.json could not be attached"}
    return evidence, attachments
