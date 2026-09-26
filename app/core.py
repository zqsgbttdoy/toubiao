"""配置、事务存储、乐观锁及不可变修订历史。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port: int = 8000
    parse_timeout: float = 25.0
    max_upload: int = 20 * 1024 * 1024
    max_pdf_pages: int = 300

    def __post_init__(self):
        directory = Path(self.data_dir).resolve()
        if directory == (ROOT / "app" / "static").resolve() or (ROOT / "app" / "static").resolve() in directory.parents:
            raise ValueError("数据目录不能放入公开静态资源目录")
        if not 1024 <= self.port <= 65535:
            raise ValueError("BID_PORT必须在1024至65535之间")
        object.__setattr__(self, "data_dir", directory)

    @classmethod
    def from_env(cls):
        port = int(os.environ.get("BID_PORT", "8000"))
        if not 1024 <= port <= 65535:
            raise ValueError("BID_PORT必须在1024至65535之间")
        return cls(Path(os.environ.get("BID_DATA_DIR", str(ROOT / "data"))).resolve(), port)


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(exist_ok=True)
        self.path = self.root / "database.sqlite3"
        self.lock = threading.RLock()
        self.initialize()

    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def initialize(self):
        with self.lock, self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise DomainError("SCHEMA_VERSION", "数据版本较新，请使用对应版本软件", 503)
            c.executescript("""
                CREATE TABLE IF NOT EXISTS entities (
                    kind TEXT NOT NULL, id TEXT NOT NULL, project_id TEXT,
                    version INTEGER NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(kind,id)
                );
                CREATE INDEX IF NOT EXISTS entity_project ON entities(kind,project_id);
                CREATE TABLE IF NOT EXISTS revisions (
                    kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(kind,id,version)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                    action TEXT NOT NULL, entity_id TEXT NOT NULL, project_id TEXT
                );
                PRAGMA user_version=1;
            """)

    @contextmanager
    def transaction(self):
        with self.lock:
            c = self.connect()
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise
            finally:
                c.close()

    def get(self, c, kind, entity_id, required=True):
        row = c.execute("SELECT data FROM entities WHERE kind=? AND id=?", (kind, entity_id)).fetchone()
        if row is None:
            if required:
                raise DomainError("NOT_FOUND", "记录不存在", 404)
            return None
        return json.loads(row["data"])

    def all(self, c, kind, project_id=None):
        if project_id is None:
            rows = c.execute("SELECT data FROM entities WHERE kind=? ORDER BY rowid DESC", (kind,))
        else:
            rows = c.execute("SELECT data FROM entities WHERE kind=? AND project_id=? ORDER BY rowid", (kind, project_id))
        return [json.loads(r["data"]) for r in rows]

    def save(self, c, kind, obj, action="save"):
        obj = dict(obj)
        old = self.get(c, kind, obj["id"], False)
        obj["version"] = (old["version"] if old else 0) + 1
        obj["created_at"] = old["created_at"] if old else now()
        obj["updated_at"] = now()
        text = dumps(obj)
        c.execute("INSERT INTO entities(kind,id,project_id,version,data) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(kind,id) DO UPDATE SET project_id=excluded.project_id,version=excluded.version,data=excluded.data",
                  (kind, obj["id"], obj.get("project_id"), obj["version"], text))
        c.execute("INSERT INTO revisions(kind,id,version,data) VALUES(?,?,?,?)", (kind, obj["id"], obj["version"], text))
        c.execute("INSERT INTO events(at,action,entity_id,project_id) VALUES(?,?,?,?)",
                  (now(), f"{kind}.{action}", obj["id"], obj.get("project_id")))
        return obj

    def history(self, c, kind, entity_id):
        return [json.loads(r[0]) for r in c.execute(
            "SELECT data FROM revisions WHERE kind=? AND id=? ORDER BY version DESC", (kind, entity_id))]

    def delete(self, c, kind, entity_id):
        obj = self.get(c, kind, entity_id)
        obj["deleted"] = True
        self.save(c, kind, obj, "delete")
        c.execute("DELETE FROM entities WHERE kind=? AND id=?", (kind, entity_id))

    @staticmethod
    def expect(obj, version):
        if obj["version"] != version:
            raise DomainError("VERSION_CONFLICT", "内容已变更，请刷新后重新操作", 409)

    def project(self, c, project_id, expected=None, writable=False):
        p = self.get(c, "project", project_id)
        if expected is not None:
            self.expect(p, expected)
        if writable and p.get("archived"):
            raise DomainError("PROJECT_ARCHIVED", "请先取消归档后再编辑", 409)
        return p

    def child(self, c, kind, entity_id, project_id):
        obj = self.get(c, kind, entity_id)
        if obj.get("project_id") != project_id:
            raise DomainError("NOT_FOUND", "记录不属于当前项目", 404)
        return obj

    def touch(self, c, p, reason):
        p["review_status"] = "pending"
        p["review_invalidated_reason"] = reason
        p["current_review_id"] = None
        return self.save(c, "project", p, "content_changed")

    def invalidate_resource(self, c, kind, entity_id):
        for p in self.all(c, "project"):
            key = {"material": "selected_material_ids", "template": "selected_template_ids", "snippet": "selected_snippet_ids"}[kind]
            referenced = any(s.get("draft_id") == p.get("current_draft_id") and
                any(r["kind"] == kind and r["id"] == entity_id for r in s.get("references", []))
                for s in self.all(c, "section", p["id"]))
            if entity_id in p.get(key, []) or referenced:
                self.touch(c, p, "引用资料或模板版本已变更，需重新核对与复核")
