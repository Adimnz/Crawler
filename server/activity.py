"""Public execution summaries and measured stage progress, never model reasoning."""
from __future__ import annotations

import os
import threading
import time

from .storage import now_ms


class JobInterrupted(RuntimeError):
    pass


class ResearchActivity:
    def __init__(self, service):
        self.s, self.db = service, service.db
        self.local = threading.local()
        self.budget_seconds = max(60, min(3600, int(os.getenv("CRAWLER_JOB_BUDGET_SECONDS", "900"))))

    def begin(self, job):
        payload = job.get("payload", {})
        task = self.db.get("researchTask", payload.get("taskId", "")) or {}
        record = {"id": job["id"], "kind": job["kind"], "boardId": payload.get("boardId", task.get("boardId")),
                  "topicId": payload.get("topicId"), "ownerId": payload.get("ownerId", task.get("ownerId")),
                  "status": "Running", "percent": 0, "stage": "Starting task", "attempt": job.get("attempts", 1),
                  "startedAt": now_ms(), "updatedAt": now_ms(), "events": []}
        self.local.record, self.local.started = record, time.monotonic()
        self.report("Starting task", 0, 1)

    def check(self):
        if not getattr(self.local, "record", None): return
        if self.s.stop_event.is_set(): raise JobInterrupted("Server stopping; task will retry")
        if time.monotonic() - self.local.started > self.budget_seconds:
            raise JobInterrupted("Task time budget reached; task will retry")
        # Yield the interpreter during archive/model loops so request handlers can run.
        time.sleep(0)

    def report(self, message, completed, total, *, detail="", completed_items=None, total_items=None):
        record = getattr(self.local, "record", None)
        if not record: return
        self.check()
        percent = min(99, max(0, int(100 * completed / max(1, total))))
        event = {"at": now_ms(), "message": str(message)[:250], "detail": str(detail)[:500], "percent": percent}
        if completed_items is not None:
            event.update(completedItems=completed_items, totalItems=total_items)
        record.update(stage=event["message"], percent=percent, updatedAt=event["at"], completedStages=completed,
                      totalStages=total, progressBasis="Completed planned stages; not a time estimate or confidence score")
        if not record["events"] or any(record["events"][-1].get(k) != event.get(k) for k in ("message", "detail", "percent")):
            record["events"] = (record["events"] + [event])[-40:]
        self.db.put("taskProgress", record["id"], record)

    def finish(self, error=None, waiting=None):
        record = getattr(self.local, "record", None)
        if not record: return
        if error:
            record.update(status="Retrying", stage="Task interrupted; queued retry", error="The worker could not complete this attempt. Retained evidence is preserved.")
            if isinstance(error, JobInterrupted): record["error"] = str(error)
        elif waiting:
            record.update(status=waiting if waiting in {"Paused", "Cancelled", "Failed"} else "Waiting", stage=str(waiting))
        else:
            record.update(status="Complete", percent=100, stage="Task completed", completedAt=now_ms())
        record["updatedAt"] = now_ms()
        record["events"] = (record["events"] + [{"at": now_ms(), "message": record["stage"], "percent": record["percent"]}])[-40:]
        self.db.put("taskProgress", record["id"], record)
        self.local.record = None

    def feed(self, owner, board_id):
        board = self.s.network_research._owned("researchBoard", board_id, owner)
        topics = [board["topicId"]] + board.get("branchTopics", [])[:30]
        branches = [t for t in self.db.matching("researchTask", "boardId", board_id, 60) if t.get("ownerId") == owner]
        topics += [t["childTopicId"] for t in branches if t.get("childTopicId")]
        tasks = self.db.activity_records(board_id, topics, limit=40)
        result = []
        for record in tasks:
            if record.get("ownerId") and record["ownerId"] != owner: continue
            record = dict(record)
            job = self.db.get_job(record["id"])
            if record["status"] == "Waiting" and job and job["state"] == "done": continue
            if job and job["state"] == "dead": record.update(status="Failed", stage="Task failed; review worker queue")
            elif record["status"] == "Running" and job and job["state"] == "queued":
                record.update(status="Queued", stage="Waiting for a worker to resume")
            record["events"] = record.get("events", [])[-12:]
            result.append(record)
        known = {r["id"] for r in result}
        for job in self.db.activity_jobs(board_id, topics, [t["id"] for t in branches]):
            if job["id"] in known or job["payload"].get("ownerId", owner) != owner: continue
            result.insert(0, {"id": job["id"], "kind": job["kind"], "status": "Queued", "stage": "Waiting for an available worker",
                              "percent": 0, "updatedAt": job["updated_at"], "events": []})
        return {"boardId": board_id, "tasks": result, "asOf": now_ms(),
                "organizationPolicy": self.s.organizer.policy(owner, board_id),
                "progressBasis": "Completed planned stages, not elapsed time or investment confidence"}
