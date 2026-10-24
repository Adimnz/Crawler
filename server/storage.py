"""Durable records, append-only source versions, a leased job queue, and raw objects."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid


def now_ms():
    return int(time.time() * 1000)


def identifier(prefix):
    return prefix + "-" + uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
 kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL, PRIMARY KEY(kind,id)
);
CREATE INDEX IF NOT EXISTS records_kind_updated ON records(kind,updated_at,id);
CREATE TABLE IF NOT EXISTS document_versions (
 document_id TEXT NOT NULL, version INTEGER NOT NULL, retrieved_at BIGINT NOT NULL,
 payload TEXT NOT NULL, object_key TEXT NOT NULL, PRIMARY KEY(document_id,version)
);
CREATE INDEX IF NOT EXISTS versions_replay ON document_versions(retrieved_at,document_id);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
 dedupe_key TEXT UNIQUE, attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
 available_at BIGINT NOT NULL, lease_until BIGINT, last_error TEXT, created_at BIGINT NOT NULL,
 updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state,available_at);
CREATE TABLE IF NOT EXISTS audit (
 id TEXT PRIMARY KEY, at BIGINT NOT NULL, action TEXT NOT NULL,
 subject TEXT NOT NULL, detail TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_time ON audit(at,id);
"""


class Database:
    def __init__(self, directory, dsn=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.dsn = dsn or ""
        self.postgres = self.dsn.startswith(("postgres://", "postgresql://"))
        if self.dsn and not self.postgres:
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        self.lock = threading.RLock()
        self.kind_revisions = {}
        with self.connection() as conn:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    self.execute(conn, statement)
            metric = "(payload::jsonb->>'metric')" if self.postgres else "json_extract(payload,'$.metric')"
            asset = "(payload::jsonb->>'assetId')" if self.postgres else "json_extract(payload,'$.assetId')"
            self.execute(conn,f"CREATE INDEX IF NOT EXISTS records_market_prices ON records({metric},{asset},updated_at DESC) WHERE kind='observation'")

    @contextlib.contextmanager
    def connection(self):
        if self.postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("PostgreSQL requires: pip install 'psycopg[binary]'") from exc
            conn = psycopg.connect(self.dsn, row_factory=dict_row)
        else:
            conn = sqlite3.connect(self.directory / "research.sqlite3", timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, conn, sql, args=()):
        return conn.execute(sql.replace("?", "%s") if self.postgres else sql, args)

    def get(self, kind, record_id):
        with self.connection() as conn:
            row = self.execute(conn, "SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
            return json.loads(row["payload"]) if row else None

    def put(self, kind, record_id, payload, at=None):
        at = at or now_ms()
        with self.lock, self.connection() as conn:
            if kind == "source":
                prior = self.execute(conn,"SELECT payload FROM records WHERE kind=? AND id=?",(kind,record_id)).fetchone()
                old = json.loads(prior["payload"]) if prior else {}
                fields = ("enabled","tier","kind","url","config","family","permissions","allowFullText")
                if not prior or any(old.get(k) != payload.get(k) for k in fields):
                    self.kind_revisions["sourceConfiguration"] = self.kind_revisions.get("sourceConfiguration",0)+1
            self.execute(conn, "INSERT INTO records(kind,id,payload,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (kind, record_id, dumps(payload), at, at))
            self.kind_revisions[kind] = self.kind_revisions.get(kind, 0) + 1
        return payload

    def scan(self, kind, page_size=500):
        """Keyset iteration: no silent latest-N truncation, bounded read batches."""
        cursor = ""
        while True:
            with self.connection() as conn:
                rows = self.execute(conn, "SELECT id,payload FROM records WHERE kind=? AND id>? ORDER BY id LIMIT ?", (kind, cursor, page_size)).fetchall()
            if not rows: return
            for row in rows: yield json.loads(row["payload"])
            cursor = rows[-1]["id"]

    def market_observations(self, asset_id=None, limit=2000):
        metric = "(payload::jsonb->>'metric')" if self.postgres else "json_extract(payload,'$.metric')"
        asset = "(payload::jsonb->>'assetId')" if self.postgres else "json_extract(payload,'$.assetId')"
        clause, args = (f" AND {asset}=?", [asset_id]) if asset_id else ("", [])
        with self.connection() as conn:
            rows=self.execute(conn,f"SELECT payload FROM records WHERE kind='observation' AND {metric} IN ('price','price_usd','close','adjusted_close')"+clause+" ORDER BY updated_at DESC,id LIMIT ?",(*args,limit)).fetchall()
            return [json.loads(r['payload']) for r in rows]

    def list(self, kind, limit=5000, after=0):
        with self.connection() as conn:
            rows = self.execute(conn, "SELECT payload FROM records WHERE kind=? AND updated_at>=? ORDER BY updated_at,id LIMIT ?", (kind, after, limit)).fetchall()
            return [json.loads(row["payload"]) for row in rows]

    def delete(self, kind, record_id):
        with self.lock, self.connection() as conn:
            self.execute(conn, "DELETE FROM records WHERE kind=? AND id=?", (kind, record_id))
            self.kind_revisions[kind] = self.kind_revisions.get(kind, 0) + 1
            if kind == "source": self.kind_revisions["sourceConfiguration"] = self.kind_revisions.get("sourceConfiguration",0)+1

    def count(self, kind):
        with self.connection() as conn:
            return self.execute(conn, "SELECT COUNT(*) AS n FROM records WHERE kind=?", (kind,)).fetchone()["n"]

    def latest(self, kind, limit=5000):
        with self.connection() as conn:
            rows = self.execute(conn, "SELECT payload FROM records WHERE kind=? ORDER BY updated_at DESC,id DESC LIMIT ?", (kind, limit)).fetchall()
            return [json.loads(row["payload"]) for row in rows]

    def page(self, kind, after=0, after_id="", limit=500):
        with self.connection() as conn:
            rows = self.execute(conn, "SELECT payload,updated_at,id FROM records WHERE kind=? AND (updated_at>? OR (updated_at=? AND id>?)) ORDER BY updated_at,id LIMIT ?", (kind, after, after, after_id, limit)).fetchall()
            return [{"payload": json.loads(row["payload"]), "updatedAt": row["updated_at"], "id": row["id"]} for row in rows]

    def get_job(self, job_id):
        with self.connection() as conn:
            row = self.execute(conn, "SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def version(self, doc, object_key):
        with self.lock, self.connection() as conn:
            self.execute(conn, "INSERT INTO document_versions(document_id,version,retrieved_at,payload,object_key) VALUES(?,?,?,?,?)", (doc["id"], doc["version"], doc["retrievedAt"], dumps(doc), object_key))
            self.execute(conn, "INSERT INTO records(kind,id,payload,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", ("document", doc["id"], dumps(doc), doc["updatedAt"], doc["updatedAt"]))

    def replay(self, as_of, limit=20000):
        with self.connection() as conn:
            rows = self.execute(conn, "SELECT v.payload FROM document_versions v JOIN (SELECT document_id,MAX(version) AS version FROM document_versions WHERE retrieved_at<=? GROUP BY document_id) x ON v.document_id=x.document_id AND v.version=x.version ORDER BY v.retrieved_at LIMIT ?", (as_of, limit)).fetchall()
            return [json.loads(row["payload"]) for row in rows]

    def versions(self, doc_id):
        with self.connection() as conn:
            return [json.loads(row["payload"]) for row in self.execute(conn, "SELECT payload FROM document_versions WHERE document_id=? ORDER BY version", (doc_id,)).fetchall()]

    def enqueue(self, kind, payload, dedupe_key=None, delay=0, max_attempts=5):
        at = now_ms()
        with self.lock, self.connection() as conn:
            if dedupe_key:
                existing = self.execute(conn, "SELECT id FROM jobs WHERE dedupe_key=?", (dedupe_key,)).fetchone()
                if existing:
                    return existing["id"]
            job_id = identifier("job")
            self.execute(conn, "INSERT INTO jobs(id,kind,payload,state,dedupe_key,attempts,max_attempts,available_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (job_id, kind, dumps(payload), "queued", dedupe_key, 0, max_attempts, at + int(delay * 1000), at, at))
            return job_id

    def claim_job(self, lease_seconds=180, kinds=None, exclude_kinds=None):
        at = now_ms()
        with self.lock, self.connection() as conn:
            self.execute(conn, "UPDATE jobs SET state='queued',lease_until=NULL WHERE state='running' AND lease_until<?", (at,))
            suffix = " FOR UPDATE SKIP LOCKED" if self.postgres else ""
            selection, args = "", [at]
            for values, operator in ((kinds, "IN"), (exclude_kinds, "NOT IN")):
                if values:
                    selection += " AND kind " + operator + " (" + ",".join("?" for _ in values) + ")"
                    args.extend(values)
            args.append(at - 120000)
            # Interactive research gets a short head start; aging prevents feed starvation.
            row = self.execute(conn, "SELECT * FROM jobs WHERE state='queued' AND available_at<=?" + selection + " ORDER BY CASE WHEN available_at<? THEN 0 WHEN kind IN ('topic-research','network-research','network-index') THEN 1 ELSE 2 END,available_at,created_at LIMIT 1" + suffix, tuple(args)).fetchone()
            if not row:
                return None
            updated = self.execute(conn, "UPDATE jobs SET state='running',attempts=attempts+1,lease_until=?,updated_at=? WHERE id=? AND state='queued'", (at + lease_seconds * 1000, at, row["id"]))
            if not updated.rowcount:
                return None
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["attempts"] += 1
            return result

    def finish_job(self, job_id):
        with self.lock, self.connection() as conn:
            self.execute(conn, "UPDATE jobs SET state='done',lease_until=NULL,updated_at=? WHERE id=?", (now_ms(), job_id))

    def renew_job(self, job_id, lease_seconds=180):
        """Keep a live research task leased while provider requests are in progress."""
        with self.lock, self.connection() as conn:
            updated = self.execute(conn, "UPDATE jobs SET lease_until=? WHERE id=? AND state='running'", (now_ms() + int(lease_seconds * 1000), job_id))
            return bool(updated.rowcount)

    def fail_job(self, job, error, retry_after=None):
        dead = job["attempts"] >= job["max_attempts"]
        delay = min(3600, max(2 ** job["attempts"] * 15, retry_after or 0))
        with self.lock, self.connection() as conn:
            self.execute(conn, "UPDATE jobs SET state=?,last_error=?,available_at=?,lease_until=NULL,updated_at=? WHERE id=?", ("dead" if dead else "queued", str(error)[:500], now_ms() + delay * 1000, now_ms(), job["id"]))

    def jobs(self, state=None, limit=100):
        with self.connection() as conn:
            rows = self.execute(conn, "SELECT * FROM jobs" + (" WHERE state=?" if state else "") + " ORDER BY updated_at DESC LIMIT ?", (state, limit) if state else (limit,)).fetchall()
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def retry_job(self, job_id):
        with self.lock, self.connection() as conn:
            changed = self.execute(conn, "UPDATE jobs SET state='queued',attempts=0,last_error=NULL,available_at=?,updated_at=? WHERE id=? AND state IN ('dead','done')", (now_ms(), now_ms(), job_id)).rowcount
            return bool(changed)

    def audit(self, action, subject, detail):
        with self.lock, self.connection() as conn:
            # Serialize chain appends across processes as well as threads.
            if self.postgres:
                self.execute(conn, "SELECT pg_advisory_xact_lock(817245)")
            else:
                self.execute(conn, "BEGIN IMMEDIATE")
            previous = self.execute(conn, "SELECT entry_hash FROM audit ORDER BY at DESC,id DESC LIMIT 1").fetchone()
            previous_hash = previous["entry_hash"] if previous else "0" * 64
            last = self.execute(conn, "SELECT MAX(at) AS at FROM audit").fetchone()["at"] or 0
            at = max(now_ms(), last + 1)
            item = {"id": identifier("audit"), "at": at, "action": action, "subject": subject, "detail": detail, "previous_hash": previous_hash}
            item["entry_hash"] = hashlib.sha256(dumps(item).encode()).hexdigest()
            self.execute(conn, "INSERT INTO audit(id,at,action,subject,detail,previous_hash,entry_hash) VALUES(?,?,?,?,?,?,?)", tuple(dumps(item[k]) if k == "detail" else item[k] for k in ("id", "at", "action", "subject", "detail", "previous_hash", "entry_hash")))
            return item

    def audit_entries(self, limit=500):
        with self.connection() as conn:
            result = [dict(row) for row in self.execute(conn, "SELECT * FROM audit ORDER BY at DESC LIMIT ?", (limit,)).fetchall()]
            for item in result:
                try:
                    item["detail"] = json.loads(item["detail"])
                except ValueError:
                    pass
            return result

    def verify_audit(self):
        previous = "0" * 64
        with self.connection() as conn:
            rows = self.execute(conn, "SELECT * FROM audit ORDER BY at,id").fetchall()
        for row in rows:
            item = dict(row)
            expected = item.pop("entry_hash")
            try:
                item["detail"] = json.loads(item["detail"])
            except ValueError:
                return {"valid": False, "failedAt": item["id"], "entries": len(rows)}
            if item["previous_hash"] != previous or hashlib.sha256(dumps(item).encode()).hexdigest() != expected:
                return {"valid": False, "failedAt": item["id"], "entries": len(rows)}
            previous = expected
        return {"valid": True, "entries": len(rows), "head": previous}


class ObjectStore:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket = os.getenv("S3_BUCKET", "")
        self.client = None
        if self.bucket:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("S3 object storage requires: pip install boto3") from exc
            self.client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None)

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest()
        key = digest[:2] + "/" + digest
        if self.client:
            self.client.put_object(Bucket=self.bucket, Key="raw/" + key, Body=data, ServerSideEncryption="AES256")
        else:
            target = self.root / key
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                temporary = target.with_suffix("." + uuid.uuid4().hex + ".tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
        return key

    def get(self, key):
        if not isinstance(key, str) or len(key) != 67 or key[2] != "/" or any(c not in "0123456789abcdef/" for c in key):
            raise ValueError("Invalid raw object reference")
        if self.client:
            return self.client.get_object(Bucket=self.bucket, Key="raw/" + key)["Body"].read()
        return (self.root / key).read_bytes()


