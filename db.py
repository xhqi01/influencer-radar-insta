"""
db.py — SQLite 永続化レイヤー

複数人で使うため、ジョブ・検索結果・保存リストをすべてファイルに保存する。
プロセスを再起動しても消えない。WAL モードなので読み書きが並行しても壊れない。
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = os.getenv("RADAR_DB", os.path.join(os.path.dirname(__file__), "radar.db"))
_init_lock = threading.Lock()
_initialized = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    stage       TEXT,
    params      TEXT,
    stats       TEXT,
    error       TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_results (
    job_id   TEXT NOT NULL,
    position INTEGER NOT NULL,
    username TEXT NOT NULL,
    data     TEXT NOT NULL,
    PRIMARY KEY (job_id, username)
);

CREATE TABLE IF NOT EXISTS lists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS list_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id    INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    username   TEXT NOT NULL,
    data       TEXT NOT NULL,
    note       TEXT DEFAULT '',
    status     TEXT DEFAULT 'new',
    added_by   TEXT,
    added_at   TEXT NOT NULL,
    UNIQUE (list_id, username)
);

CREATE INDEX IF NOT EXISTS idx_items_list ON list_items(list_id);
CREATE INDEX IF NOT EXISTS idx_results_job ON job_results(job_id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    global _initialized
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _initialized:
        with _init_lock:
            if not _initialized:
                conn.executescript(SCHEMA)
                conn.commit()
                _initialized = True
    return conn


# ---------------------------------------------------------------------------
# ジョブ
# ---------------------------------------------------------------------------
def create_job(job_id, params, created_by=None):
    with connect() as c:
        c.execute(
            "INSERT INTO jobs (id,status,stage,params,created_by,created_at) VALUES (?,?,?,?,?,?)",
            (job_id, "queued", "queued", json.dumps(params, ensure_ascii=False), created_by, now()),
        )


def update_job(job_id, **fields):
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
    vals.append(job_id)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {','.join(cols)} WHERE id=?", vals)


def save_results(job_id, results):
    with connect() as c:
        c.execute("DELETE FROM job_results WHERE job_id=?", (job_id,))
        c.executemany(
            "INSERT OR REPLACE INTO job_results (job_id,position,username,data) VALUES (?,?,?,?)",
            [(job_id, i, r["username"], json.dumps(r, ensure_ascii=False)) for i, r in enumerate(results)],
        )


def get_job(job_id, with_results=False):
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job["params"] = json.loads(job["params"]) if job["params"] else {}
        job["stats"] = json.loads(job["stats"]) if job["stats"] else None
        if with_results:
            rows = c.execute(
                "SELECT data FROM job_results WHERE job_id=? ORDER BY position", (job_id,)
            ).fetchall()
            job["results"] = [json.loads(r["data"]) for r in rows]
        return job


def recent_jobs(limit=15):
    with connect() as c:
        rows = c.execute(
            "SELECT id,status,params,stats,created_at,created_by FROM jobs "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"]) if d["params"] else {}
        d["stats"] = json.loads(d["stats"]) if d["stats"] else None
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# リスト
# ---------------------------------------------------------------------------
def create_list(name, description="", created_by=None):
    with connect() as c:
        cur = c.execute(
            "INSERT INTO lists (name,description,created_by,created_at) VALUES (?,?,?,?)",
            (name.strip(), description, created_by, now()),
        )
        return cur.lastrowid


def all_lists():
    with connect() as c:
        rows = c.execute(
            "SELECT l.*, (SELECT COUNT(*) FROM list_items i WHERE i.list_id=l.id) AS count "
            "FROM lists l ORDER BY l.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def rename_list(list_id, name):
    with connect() as c:
        c.execute("UPDATE lists SET name=? WHERE id=?", (name.strip(), list_id))


def delete_list(list_id):
    with connect() as c:
        c.execute("DELETE FROM list_items WHERE list_id=?", (list_id,))
        c.execute("DELETE FROM lists WHERE id=?", (list_id,))


def add_item(list_id, influencer, added_by=None):
    """既に入っている場合はデータだけ更新する（重複追加でエラーにしない）。"""
    with connect() as c:
        c.execute(
            "INSERT INTO list_items (list_id,username,data,added_by,added_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(list_id,username) DO UPDATE SET data=excluded.data",
            (list_id, influencer["username"], json.dumps(influencer, ensure_ascii=False),
             added_by, now()),
        )


def list_items(list_id):
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM list_items WHERE list_id=? ORDER BY added_at DESC", (list_id,)
        ).fetchall()
    out = []
    for r in rows:
        item = json.loads(r["data"])
        item.update({
            "item_id": r["id"],
            "note": r["note"] or "",
            "item_status": r["status"] or "new",
            "added_by": r["added_by"] or "",
            "added_at": r["added_at"],
        })
        out.append(item)
    return out


def update_item(item_id, note=None, status=None):
    sets, vals = [], []
    if note is not None:
        sets.append("note=?"); vals.append(note)
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if not sets:
        return
    vals.append(item_id)
    with connect() as c:
        c.execute(f"UPDATE list_items SET {','.join(sets)} WHERE id=?", vals)


def delete_item(item_id):
    with connect() as c:
        c.execute("DELETE FROM list_items WHERE id=?", (item_id,))


def get_list(list_id):
    with connect() as c:
        row = c.execute("SELECT * FROM lists WHERE id=?", (list_id,)).fetchone()
    return dict(row) if row else None
