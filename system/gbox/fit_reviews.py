"""Operator mesh comparisons and durable feedback, without requiring a running emulator."""
import re
import time
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from . import build_feedback


class ReviewIn(BaseModel):
    model: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=1, max_length=4000)
    evidence: dict | None = None
    prefer_original: bool = True


def routes(app, store, config, auth, *, file_report):
    def job(jid):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", jid):
            raise HTTPException(404, "Job not found")
        row = store.get("job", jid)
        if not row:
            raise HTTPException(404, "Job not found")
        return row

    def mesh_file(jid, url):
        prefix = f"/api/jobs/{jid}/fitting/files/"
        if not isinstance(url, str) or not url.startswith(prefix):
            return None
        name = url[len(prefix):]
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,92}\.glb", name):
            return None
        path = Path(config.cache) / "fitting-jobs" / jid / name
        return path if (path.is_file() and path.resolve().parent == path.parent.resolve()
                        and path.stat().st_size <= 8 << 20) else None

    def pair_of(jid, model):
        pair = model.get("comparison") or {}
        if pair.get("data", {}).get("sampled") is not False:
            return None
        return pair if all(mesh_file(jid, pair.get(side)) for side in ("before", "after")) else None

    @app.get("/api/jobs/{jid}/fitting/review")
    def get_review(jid: str, actor=Depends(auth)):
        row = job(jid); fitting = row.get("fitting") or {}; models = fitting.get("models") or {}
        return {"job_id": jid, "state": row.get("state"), "models": [
            {"key": key, "label": model.get("label") or key, "donor": model.get("donor"),
             "game_id": model.get("game"), "slot": model.get("slot"), "comparison": pair_of(jid, model),
             "stages": {name: stage.get("data") for name, stage in model.get("stages", {}).items()}}
            for key in fitting.get("order", []) if (model := models.get(key))]}

    @app.post("/api/jobs/{jid}/fitting/review")
    def submit_review(jid: str, body: ReviewIn, actor=Depends(auth)):
        row = job(jid)
        model = ((row.get("fitting") or {}).get("models") or {}).get(body.model)
        if not model:
            raise HTTPException(404, "Fitted model not found")
        inp = row.get("input") or {}
        gid = model.get("game") or inp.get("target_game") or inp.get("game_id")
        if not re.fullmatch(r"[0-9a-f]{16}", str(gid or "")):
            raise HTTPException(422, "This fit has no target game ID; feedback cannot be assigned safely")
        note = body.note.strip()
        if not note:
            raise HTTPException(422, "Describe the mesh problem")
        attachments = []; marked = None
        if body.evidence is not None:
            from .build_report_images import evidence_images
            try:
                marked, attachments = evidence_images(body.evidence)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            for attachment in attachments:
                attachment["name"] = attachment["name"].replace("game-frame", "mesh-comparison")
        pair = pair_of(jid, model)
        retained = {}
        if pair:
            for side in ("before", "after"):
                path = mesh_file(jid, pair[side])
                ref = store.put_artifact(path.read_bytes(), f"mesh-{side}.glb", "model/gltf-binary",
                                         {"job": jid, "model": body.model, "stage": "decimation", "side": side})
                retained[side] = ref.sha256
                attachments.append({"sha256": ref.sha256, "name": f"mesh-{side}.glb", "type": "model/gltf-binary"})
        preference = "Preserve the original mesh wherever possible; report measured limits before reducing it." if body.prefer_original else "Review the reported reduction defects."
        detail = (f"Fit job {jid}; model {body.model}; donor {model.get('donor')}; target slot {model.get('slot')}.\n"
                  f"{preference}\nThese are mesh-stage views before game encoding, not verified gameplay.\n"
                  f"Comparison: {pair.get('data') if pair else 'No exact saved pair remains for this fit.'}\n"
                  f"Retained geometry artifacts: {retained}\nOperator note: {note}")
        output = row.get("output") or {}; result = output.get("result") or output
        name = result.get("mod") if isinstance(result, dict) else None
        name = str(name or f"fit-{jid}")
        issue = {"title": f"Mesh reduction review: {model.get('label') or body.model}",
                 "what": "Review mesh reduction", "detail": detail, "note": note, "save_state": False,
                 "attachments": attachments, "context": {"job_id": jid, "game_id": gid,
                 "mesh_review": True, "fit_model": body.model, "donor": model.get("donor"),
                 "slot": model.get("slot"), "prefer_original": body.prefer_original, "mesh_artifacts": retained}}
        if marked:
            issue["image_b64"] = marked
        report = file_report(issue, detail, actor)
        feedback = build_feedback.record(store, report, gid, name, note, "decimation", {
            "writer": row.get("tool"), "recipe": {"tool": row.get("tool"), "input": inp},
            "slots": [{"target": model.get("slot"), "donor": model.get("donor")}]})
        with store.lock:
            feedback = store.get(build_feedback.KIND, report["id"]) or feedback
            feedback["mesh_review"] = {"job_id": jid, "model": body.model, "prefer_original": body.prefer_original,
                                       "geometry_only": True, "artifacts": retained}
            store.put(build_feedback.KIND, report["id"], feedback)
        store.put("fit_review", report["id"], {"id": report["id"], "job_id": jid, "model": body.model,
                  "game_id": gid, "note": note, "mesh_artifacts": retained, "created": time.time()})
        return {"id": report["id"], "number": report.get("number"), "url": f"/api/requests/{report['id']}",
                "geometry_retained": retained}
