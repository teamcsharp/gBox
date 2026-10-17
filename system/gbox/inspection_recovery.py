"""Normalize one reviewed, unclaimed legacy inspection reservation without resubmitting."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sqlite3
import time

from . import inspection_builds as I
from . import build_feedback as B
from .store import append_audit


class ReadView:
    def __init__(self, db):
        self.db = db

    def get(self, kind, key):
        row = self.db.execute("SELECT body FROM docs WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind):
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM docs WHERE kind=?", (kind,))]


def normalize_reservation(db, job_id, *, expected_run, expected_digest, apply=False,
                          source_root=None, now=None, actor="operator-maintenance"):
    """Change only the legacy digest after independently deriving the reviewed recipe.

    This never creates a job, changes its input/worker, grants a review, launches
    a game, or bypasses normal admission. Default is read-only with full evidence.
    """
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError("Invalid observation time")
    if db.in_transaction:
        raise ValueError("Normalization requires its own transaction")
    db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
    try:
        view = ReadView(db)
        job = view.get("job", job_id)
        if (not job or job.get("id") != job_id or job.get("state") != "queued"
                or job.get("worker_id") is not None or job.get("started") is not None
                or job.get("finished") is not None or job.get("receipt_id") is not None
                or job.get("output") is not None or job.get("cancel")
                or job.get("tool") != "characters"
                or (job.get("origin") or {}).get("inspection_run") != expected_run):
            raise ValueError("Expected an unclaimed queued inspection job")
        row = db.execute("SELECT body FROM docs WHERE kind=? AND id=?", (I.RUN, expected_run)).fetchone()
        original = row[0] if row else None
        before = json.loads(original) if original else None
        if (not before or before.get("id") != expected_run or before.get("job_id") != job_id
                or before.get("input_digest") != expected_digest):
            raise ValueError("Expected reservation no longer matches")
        plan = view.get(I.PLAN, before["game_id"])
        policy = I.settings(view.get(I.POLICY, "default"))
        if (not policy["enabled"] or not plan or not plan.get("enabled")
                or not plan.get("reviewed", True) or plan.get("revision") != before.get("plan_revision")
                or I.missing_reviews(view, plan)):
            raise ValueError("Current recipe or operator feedback is not reviewed and enabled")
        feedback = B.rows(view, before["game_id"])
        plan_ack, job_ack = plan.get("feedback_ack") or {}, (job.get("input") or {}).get("feedback_ack") or {}
        if (not isinstance(plan_ack, dict) or not isinstance(job_ack, dict)
                or any(plan_ack.get(r["id"]) != r.get("revision", 1)
                       or job_ack.get(r["id"]) != r.get("revision", 1) for r in feedback)):
            raise ValueError("Current build feedback revisions need review")
        sources = I.dependencies(plan["dependencies"], root=source_root)
        if sources != before.get("sources"):
            raise ValueError("Writer sources changed since the reservation")
        if expected_run != I.digest({"plan": plan["revision"], "sources": sources}):
            raise ValueError("Reservation does not have the canonical recipe and source identity")
        worker = view.get("worker", job.get("require_worker")) or {}
        seen = worker.get("last_seen")
        if (worker.get("id") != job.get("require_worker") or worker.get("name") != policy["node"]
                or before.get("node") != policy["node"] or "characters" not in (worker.get("tools") or [])
                or type(seen) not in (int, float) or not math.isfinite(seen) or not -5 <= now-seen <= 30
                or any(worker.get("build_sources", {}).get(k) != v for k, v in sources.items())):
            raise ValueError("Pinned inspection worker needs fresh matching writer evidence")
        expected = I.build_input(plan, expected_run)
        sparse = I.build_input(plan, expected_run, normalized=False)
        target = I.digest(expected)
        if expected_digest == target:
            raise ValueError("Reservation is already normalized")
        if (expected_digest != I.digest(sparse) or not I.reservation_matches(plan, before, job)
                or job["input"].get("launch") is not False or job["input"].get("op") != "cast_swap"):
            raise ValueError("Job is not the full validated form of the exact reviewed legacy recipe")
        after = before | {"input_digest": target}
        evidence = {"before": before, "after": after, "job": job,
                    "plan_revision": plan["revision"], "worker": {k: worker.get(k) for k in ("id", "name", "last_seen")},
                    "observed_at": now, "reason": "Normalize only the digest of an equivalent reviewed legacy recipe"}
        result = {"applied": False, "audit_seq": None, **evidence}
        if apply:
            changed = db.execute("UPDATE docs SET body=? WHERE kind=? AND id=? AND body=?",
                                 (json.dumps(after), I.RUN, expected_run, original)).rowcount
            if changed != 1:
                raise ValueError("Reservation changed during normalization")
            result["audit_seq"] = append_audit(db, actor, "inspection.reservation_normalized", expected_run, evidence, ts=now)
            db.commit()
            result["applied"] = True
        else:
            db.rollback()
        return result
    except BaseException:
        db.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--expected-run", required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--source-root", type=Path, required=True, help="Installed system directory whose writer hashes workers report")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db = sqlite3.connect(args.database.resolve().as_uri() + ("?mode=rw" if args.apply else "?mode=ro"), uri=True, timeout=5)
    try:
        if not args.apply:
            db.execute("PRAGMA query_only=ON")
        result = normalize_reservation(db, args.job_id, expected_run=args.expected_run,
                                       expected_digest=args.expected_digest, source_root=args.source_root, apply=args.apply)
    finally:
        db.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
