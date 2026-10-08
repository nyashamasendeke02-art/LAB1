"""Authoritative lab state.

Three primitives, all append-only:

* **records** -- versioned, immutable documents (hypotheses, protocols, runs,
  results, ...). ``put`` never overwrites: a change creates version N+1 and
  must give a reason. Records may be *frozen* (e.g. a pre-registered
  protocol); a frozen record can only change through ``amend`` which is
  recorded as an amendment event.
* **events** -- a hash-chained ledger of everything the controller did. Any
  edit to a past event breaks :meth:`Store.verify_chain`.
* **artifacts** -- content-addressed files (sha256) for raw data, logs,
  diffs, reports. Stored read-only; identical content dedupes.

SQLite is the single source of truth. Agents never touch it directly.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StoreError(Exception):
    pass


class FrozenRecordError(StoreError):
    pass


class ChainError(StoreError):
    pass


@dataclass(frozen=True)
class Record:
    id: str
    version: int
    kind: str
    data: dict
    created_at: str
    author: str
    reason: str
    content_hash: str

    @property
    def frozen(self) -> bool:
        return bool(self.data.get("_frozen"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    reason TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    type TEXT NOT NULL,
    subject TEXT NOT NULL,
    data TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (prefix TEXT PRIMARY KEY, n INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
BEGIN SELECT RAISE(ABORT, 'records are append-only'); END;
CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
BEGIN SELECT RAISE(ABORT, 'records are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._depth = 0

    @classmethod
    def open_readonly(cls, db_path: str | Path) -> "Store":
        """Open another lab's ledger for reading only (SQLite ``mode=ro``): no schema
        creation, and any write raises ``sqlite3.OperationalError``."""
        path = Path(db_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"no ledger at {path}")
        self = cls.__new__(cls)
        self.path = path
        self._conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True,
                                     isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._depth = 0
        return self

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ tx
    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Nestable transaction. Outermost level commits or rolls back."""
        if self._depth == 0:
            self._conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._conn.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self._conn.execute("COMMIT")

    # ------------------------------------------------------------- counters
    def next_id(self, prefix: str, width: int = 4) -> str:
        with self.transaction():
            row = self._conn.execute(
                "SELECT n FROM counters WHERE prefix=?", (prefix,)
            ).fetchone()
            n = (row["n"] if row else 0) + 1
            self._conn.execute(
                "INSERT INTO counters(prefix,n) VALUES(?,?) "
                "ON CONFLICT(prefix) DO UPDATE SET n=excluded.n",
                (prefix, n),
            )
        return f"{prefix}-{n:0{width}d}"

    # -------------------------------------------------------------- records
    def _row_to_record(self, row: sqlite3.Row) -> Record:
        return Record(
            id=row["id"],
            version=row["version"],
            kind=row["kind"],
            data=json.loads(row["data"]),
            created_at=row["created_at"],
            author=row["author"],
            reason=row["reason"],
            content_hash=row["content_hash"],
        )

    def get(self, record_id: str, version: int | None = None) -> Record:
        if version is None:
            row = self._conn.execute(
                "SELECT * FROM records WHERE id=? ORDER BY version DESC LIMIT 1",
                (record_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM records WHERE id=? AND version=?",
                (record_id, version),
            ).fetchone()
        if row is None:
            raise KeyError(f"no record {record_id!r} (version={version})")
        return self._row_to_record(row)

    def exists(self, record_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM records WHERE id=? LIMIT 1", (record_id,)
            ).fetchone()
            is not None
        )

    def history(self, record_id: str) -> list[Record]:
        rows = self._conn.execute(
            "SELECT * FROM records WHERE id=? ORDER BY version", (record_id,)
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def query(self, kind: str, **filters: Any) -> list[Record]:
        """Latest version of every record of ``kind`` matching top-level filters."""
        rows = self._conn.execute(
            "SELECT r.* FROM records r JOIN (SELECT id, MAX(version) v FROM records "
            "WHERE kind=? GROUP BY id) m ON r.id=m.id AND r.version=m.v ORDER BY r.id",
            (kind,),
        ).fetchall()
        out = [self._row_to_record(r) for r in rows]
        for key, val in filters.items():
            out = [r for r in out if r.data.get(key) == val]
        return out

    def _insert(self, rec_id, version, kind, data, author, reason) -> Record:
        payload = canonical(data)
        chash = sha256_text(f"{rec_id}|{version}|{kind}|{payload}")
        ts = utcnow()
        self._conn.execute(
            "INSERT INTO records VALUES (?,?,?,?,?,?,?,?)",
            (rec_id, version, kind, payload, ts, author, reason, chash),
        )
        return Record(rec_id, version, kind, json.loads(payload), ts, author, reason, chash)

    def create(self, kind: str, data: dict, *, prefix: str | None = None,
               record_id: str | None = None, author: str = "controller",
               reason: str = "created") -> Record:
        with self.transaction():
            rid = record_id or self.next_id(prefix or kind.upper()[:4])
            if self.exists(rid):
                raise StoreError(f"record {rid} already exists")
            rec = self._insert(rid, 1, kind, data, author, reason)
            self.append_event(author, "record.created", rid,
                              {"kind": kind, "version": 1, "hash": rec.content_hash})
        return rec

    def update(self, record_id: str, changes: dict, *, author: str = "controller",
               reason: str) -> Record:
        """Create a new version with ``changes`` merged into the latest data."""
        if not reason or not reason.strip():
            raise StoreError("every record change needs a reason")
        with self.transaction():
            cur = self.get(record_id)
            if cur.frozen:
                raise FrozenRecordError(
                    f"{record_id} is frozen; use amend() to record an amendment"
                )
            data = {**cur.data, **changes}
            rec = self._insert(record_id, cur.version + 1, cur.kind, data, author, reason)
            self.append_event(author, "record.updated", record_id,
                              {"version": rec.version, "reason": reason,
                               "changed": sorted(changes), "hash": rec.content_hash})
        return rec

    def freeze(self, record_id: str, *, author: str, reason: str) -> Record:
        with self.transaction():
            cur = self.get(record_id)
            if cur.frozen:
                return cur
            body = {k: v for k, v in cur.data.items() if not k.startswith("_")}
            data = {**cur.data, "_frozen": True, "_freeze_hash": sha256_text(canonical(body))}
            rec = self._insert(record_id, cur.version + 1, cur.kind, data, author, reason)
            self.append_event(author, "record.frozen", record_id,
                              {"version": rec.version, "freeze_hash": data["_freeze_hash"]})
        return rec

    def amend(self, record_id: str, changes: dict, *, author: str, reason: str) -> Record:
        """Change a frozen record. The amendment is recorded, never silent.

        The new version is re-frozen with a new freeze hash and carries an
        ``_amendments`` list documenting every amendment so far.
        """
        if not reason or not reason.strip():
            raise StoreError("amendments need a justification")
        with self.transaction():
            cur = self.get(record_id)
            if not cur.frozen:
                raise StoreError(f"{record_id} is not frozen; use update()")
            amendments = list(cur.data.get("_amendments", []))
            amendments.append({"from_version": cur.version, "reason": reason,
                               "author": author, "changed": sorted(changes),
                               "previous_freeze_hash": cur.data.get("_freeze_hash"),
                               "ts": utcnow()})
            merged = {**cur.data, **changes}
            body = {k: v for k, v in merged.items() if not k.startswith("_")}
            merged["_amendments"] = amendments
            merged["_freeze_hash"] = sha256_text(canonical(body))
            rec = self._insert(record_id, cur.version + 1, cur.kind, merged, author, reason)
            self.append_event(author, "record.amended", record_id,
                              {"version": rec.version, "reason": reason,
                               "changed": sorted(changes),
                               "freeze_hash": merged["_freeze_hash"]})
        return rec

    # --------------------------------------------------------------- events
    def append_event(self, actor: str, etype: str, subject: str, data: dict | None = None) -> dict:
        with self.transaction():
            row = self._conn.execute(
                "SELECT hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev = row["hash"] if row else GENESIS
            ts = utcnow()
            body = canonical(data or {})
            h = sha256_text(canonical([prev, ts, actor, etype, subject, body]))
            cur = self._conn.execute(
                "INSERT INTO events(ts,actor,type,subject,data,prev_hash,hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (ts, actor, etype, subject, body, prev, h),
            )
        return {"seq": cur.lastrowid, "ts": ts, "actor": actor, "type": etype,
                "subject": subject, "data": data or {}, "hash": h}

    def events(self, subject: str | None = None, etype: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM events", []
        cond = []
        if subject:
            cond.append("subject=?")
            args.append(subject)
        if etype:
            cond.append("type=?")
            args.append(etype)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY seq"
        return [
            {"seq": r["seq"], "ts": r["ts"], "actor": r["actor"], "type": r["type"],
             "subject": r["subject"], "data": json.loads(r["data"]), "hash": r["hash"],
             "prev_hash": r["prev_hash"]}
            for r in self._conn.execute(sql, args).fetchall()
        ]

    def head(self) -> str:
        """Hash of the latest ledger event (GENESIS if empty)."""
        row = self._conn.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row["hash"] if row else GENESIS

    def has_event_hash(self, h: str) -> bool:
        return self._conn.execute("SELECT 1 FROM events WHERE hash=?", (h,)).fetchone() is not None

    def verify_chain(self) -> int:
        """Recompute the event hash chain. Returns event count or raises ChainError."""
        prev = GENESIS
        n = 0
        for r in self._conn.execute("SELECT * FROM events ORDER BY seq"):
            if r["prev_hash"] != prev:
                raise ChainError(f"event {r['seq']}: prev_hash mismatch")
            h = sha256_text(canonical([prev, r["ts"], r["actor"], r["type"],
                                       r["subject"], r["data"]]))
            if h != r["hash"]:
                raise ChainError(f"event {r['seq']}: hash mismatch (tampered)")
            prev = h
            n += 1
        # Records: recompute content hashes too.
        for r in self._conn.execute("SELECT * FROM records"):
            chash = sha256_text(f"{r['id']}|{r['version']}|{r['kind']}|{r['data']}")
            if chash != r["content_hash"]:
                raise ChainError(f"record {r['id']} v{r['version']}: content hash mismatch")
        return n


class ArtifactStore:
    """Content-addressed, read-only file store."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put_bytes(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        p = self._path(digest)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
            os.chmod(p, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        return digest

    def put_text(self, text: str) -> str:
        return self.put_bytes(text.encode("utf-8"))

    def put_file(self, path: str | Path) -> str:
        return self.put_bytes(Path(path).read_bytes())

    def get_bytes(self, digest: str) -> bytes:
        data = self._path(digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ChainError(f"artifact {digest} corrupted")
        return data

    def get_text(self, digest: str) -> str:
        return self.get_bytes(digest).decode("utf-8")

    def has(self, digest: str) -> bool:
        return self._path(digest).exists()

    def export(self, digest: str, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(digest), dest)
        return dest
