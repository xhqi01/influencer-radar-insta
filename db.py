"""
db.py — SQLite 永続化レイヤー

複数人で使うため、ジョブ・検索結果・保存リストをすべてファイルに保存する。
プロセスを再起動しても消えない。WAL モードなので読み書きが並行しても壊れない。
"""

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.getenv("RADAR_DB", os.path.join(os.path.dirname(__file__), "radar.db"))
_init_lock = threading.Lock()
_initialized = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id  INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);

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

CREATE TABLE IF NOT EXISTS folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    group_id   INTEGER REFERENCES groups(id),
    created_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id   INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    group_id    INTEGER REFERENCES groups(id),
    name        TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS accounts (
    username    TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    followers   INTEGER DEFAULT 0,
    engagement  REAL DEFAULT 0,
    content_keys TEXT DEFAULT '',
    hashtags    TEXT DEFAULT '',
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    times_seen  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS follower_history (
    username  TEXT NOT NULL,
    seen_on   TEXT NOT NULL,
    followers INTEGER NOT NULL,
    PRIMARY KEY (username, seen_on)
);

CREATE INDEX IF NOT EXISTS idx_items_list ON list_items(list_id);
CREATE INDEX IF NOT EXISTS idx_items_user ON list_items(username);
CREATE INDEX IF NOT EXISTS idx_results_job ON job_results(job_id);
"""

# インデックスはマイグレーション後に作る。folder_id を張る対象の列が
# 既存 DB にはまだ無いため、テーブル定義と同時に実行すると落ちる。
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_lists_folder ON lists(folder_id);
CREATE INDEX IF NOT EXISTS idx_lists_group ON lists(group_id);
CREATE INDEX IF NOT EXISTS idx_folders_group ON folders(group_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lists_name ON lists(COALESCE(group_id,0), name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_folders_name ON folders(COALESCE(group_id,0), name);
"""

# 既存 DB（folders / groups 導入前）を壊さずに更新するための追加カラム
MIGRATIONS = [
    ("lists", "folder_id", "ALTER TABLE lists ADD COLUMN folder_id INTEGER REFERENCES folders(id)"),
    ("lists", "group_id", "ALTER TABLE lists ADD COLUMN group_id INTEGER REFERENCES groups(id)"),
    ("folders", "group_id", "ALTER TABLE folders ADD COLUMN group_id INTEGER REFERENCES groups(id)"),
    ("jobs", "group_id", "ALTER TABLE jobs ADD COLUMN group_id INTEGER REFERENCES groups(id)"),
]


def _migrate(conn):
    for table, column, ddl in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(ddl)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# アプリ設定（セッション署名キーなど）
# ---------------------------------------------------------------------------
def get_or_create_secret():
    """Flask セッション署名用のキー。環境変数が無ければ生成して DB に保存する
    （再起動してもログインが切れないように、DB と同じ寿命で持つ）。"""
    env = os.getenv("SECRET_KEY")
    if env:
        return env
    with connect() as c:
        row = c.execute("SELECT value FROM app_meta WHERE key='secret_key'").fetchone()
        if row:
            return row["value"]
        secret = secrets.token_hex(32)
        c.execute("INSERT INTO app_meta (key,value) VALUES ('secret_key',?)", (secret,))
        return secret


# ---------------------------------------------------------------------------
# ユーザー認証
# ---------------------------------------------------------------------------
def create_user(username, password):
    username = username.strip()
    if not (2 <= len(username) <= 40):
        raise ValueError("bad_username")
    if len(password) < 8:
        raise ValueError("password_too_short")
    with connect() as c:
        try:
            cur = c.execute(
                "INSERT INTO users (username,password_hash,created_at) VALUES (?,?,?)",
                (username, generate_password_hash(password), now()))
        except sqlite3.IntegrityError:
            raise ValueError("username_taken")
        return cur.lastrowid


def verify_user(username, password):
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return {"id": row["id"], "username": row["username"]}
    return None


def get_user(user_id):
    with connect() as c:
        row = c.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# グループ（ワークスペース）
# ---------------------------------------------------------------------------
def create_group(name, user_id):
    """グループを作成し、作成者をメンバーに追加する。
    最初のグループが作られたとき、グループ導入前の既存リスト・フォルダを
    そのグループに引き取らせる（チームの既存データを迷子にしないため）。"""
    name = name.strip()
    if not name:
        raise ValueError("bad_name")
    code = secrets.token_urlsafe(6)
    with connect() as c:
        first = c.execute("SELECT COUNT(*) AS n FROM groups").fetchone()["n"] == 0
        cur = c.execute(
            "INSERT INTO groups (name,invite_code,created_by,created_at) VALUES (?,?,?,?)",
            (name, code, user_id, now()))
        gid = cur.lastrowid
        c.execute("INSERT INTO group_members (group_id,user_id,joined_at) VALUES (?,?,?)",
                  (gid, user_id, now()))
        if first:
            c.execute("UPDATE lists SET group_id=? WHERE group_id IS NULL", (gid,))
            c.execute("UPDATE folders SET group_id=? WHERE group_id IS NULL", (gid,))
    return {"id": gid, "name": name, "invite_code": code}


def join_group(code, user_id):
    with connect() as c:
        g = c.execute("SELECT * FROM groups WHERE invite_code=?", (code.strip(),)).fetchone()
        if not g:
            raise ValueError("bad_code")
        c.execute("INSERT OR IGNORE INTO group_members (group_id,user_id,joined_at) VALUES (?,?,?)",
                  (g["id"], user_id, now()))
        return {"id": g["id"], "name": g["name"], "invite_code": g["invite_code"]}


def leave_group(group_id, user_id):
    with connect() as c:
        c.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (group_id, user_id))


def user_groups(user_id):
    with connect() as c:
        rows = c.execute(
            "SELECT g.id, g.name, g.invite_code, "
            "(SELECT COUNT(*) FROM group_members m2 WHERE m2.group_id=g.id) AS member_count "
            "FROM groups g JOIN group_members m ON m.group_id=g.id "
            "WHERE m.user_id=? ORDER BY g.created_at", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def group_members(group_id):
    with connect() as c:
        rows = c.execute(
            "SELECT u.username, m.joined_at FROM group_members m "
            "JOIN users u ON u.id=m.user_id WHERE m.group_id=? ORDER BY m.joined_at",
            (group_id,)).fetchall()
    return [dict(r) for r in rows]


def is_member(group_id, user_id):
    with connect() as c:
        return c.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",
                         (group_id, user_id)).fetchone() is not None


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
                _migrate(conn)
                conn.executescript(INDEXES)
                # 30日より古い検索ジョブと結果を掃除する。
                # リスト・フォルダ・フォロワー履歴は消さない（履歴は成長率の元データ）。
                cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                old = [r["id"] for r in conn.execute(
                    "SELECT id FROM jobs WHERE created_at < ?", (cutoff,))]
                if old:
                    ph = ",".join("?" * len(old))
                    conn.execute(f"DELETE FROM job_results WHERE job_id IN ({ph})", old)
                    conn.execute(f"DELETE FROM jobs WHERE id IN ({ph})", old)
                conn.commit()
                _initialized = True
    return conn


# ---------------------------------------------------------------------------
# ジョブ
# ---------------------------------------------------------------------------
def create_job(job_id, params, created_by=None, group_id=None):
    with connect() as c:
        c.execute(
            "INSERT INTO jobs (id,status,stage,params,created_by,created_at,group_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (job_id, "queued", "queued", json.dumps(params, ensure_ascii=False),
             created_by, now(), group_id),
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


def recent_jobs(limit=15, group_id=None):
    with connect() as c:
        rows = c.execute(
            "SELECT id,status,params,stats,created_at,created_by FROM jobs "
            "WHERE group_id IS ? ORDER BY created_at DESC LIMIT ?", (group_id, limit)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"]) if d["params"] else {}
        d["stats"] = json.loads(d["stats"]) if d["stats"] else None
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# 蓄積型アカウントデータベース
# 検索のたびに取得した全アカウントをここに貯める。ここの閲覧・検索は
# Apify を消費しない。使うほど自前のデータベースが育つ。
# ---------------------------------------------------------------------------
def record_accounts(rows):
    day = now()
    with connect() as c:
        for r in rows:
            u = r.get("username")
            if not u:
                continue
            matched = r.get("matched_hashtags") or [r.get("hashtag", "")]
            tags = " ".join(sorted(set(matched) - {"", "(direct)"}))
            keys = r.get("content", "") if r.get("content") != "unknown" else ""
            old = c.execute("SELECT hashtags, content_keys, times_seen, first_seen "
                            "FROM accounts WHERE username=?", (u,)).fetchone()
            if old:
                merged_tags = " ".join(sorted(set(old["hashtags"].split()) | set(tags.split())))
                merged_keys = " ".join(sorted(set(old["content_keys"].split()) | set(keys.split())))
                c.execute(
                    "UPDATE accounts SET data=?, followers=?, engagement=?, hashtags=?, "
                    "content_keys=?, last_seen=?, times_seen=? WHERE username=?",
                    (json.dumps(r, ensure_ascii=False), r.get("followers") or 0,
                     r.get("engagement") or 0, merged_tags, merged_keys, day,
                     old["times_seen"] + 1, u))
            else:
                c.execute(
                    "INSERT INTO accounts (username,data,followers,engagement,hashtags,"
                    "content_keys,first_seen,last_seen) VALUES (?,?,?,?,?,?,?,?)",
                    (u, json.dumps(r, ensure_ascii=False), r.get("followers") or 0,
                     r.get("engagement") or 0, tags, keys, day, day))


def browse_accounts(query="", min_f=0, max_f=10**9, sort="followers", limit=200):
    order = {"followers": "followers DESC", "engagement": "engagement DESC",
             "last_seen": "last_seen DESC", "times_seen": "times_seen DESC"}.get(sort, "followers DESC")
    sql = "SELECT * FROM accounts WHERE followers BETWEEN ? AND ?"
    args = [min_f, max_f]
    if query:
        sql += " AND (username LIKE ? OR data LIKE ? OR hashtags LIKE ?)"
        args += [f"%{query}%"] * 3
    sql += f" ORDER BY {order} LIMIT ?"
    args.append(limit)
    with connect() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for r in rows:
        item = json.loads(r["data"])
        item.update({"first_seen": r["first_seen"][:10], "last_seen": r["last_seen"][:10],
                     "times_seen": r["times_seen"], "index_hashtags": r["hashtags"]})
        out.append(item)
    return out


def account_count():
    with connect() as c:
        return c.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]


def get_account(username):
    with connect() as c:
        r = c.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        if not r:
            return None
        item = json.loads(r["data"])
        item.update({"first_seen": r["first_seen"][:10], "last_seen": r["last_seen"][:10],
                     "times_seen": r["times_seen"], "index_hashtags": r["hashtags"]})
        hist = c.execute("SELECT seen_on, followers FROM follower_history "
                         "WHERE username=? ORDER BY seen_on", (username,)).fetchall()
        item["history"] = [{"date": h["seen_on"], "followers": h["followers"]} for h in hist]
        lists_in = c.execute(
            "SELECT l.name FROM list_items i JOIN lists l ON l.id=i.list_id WHERE i.username=?",
            (username,)).fetchall()
        item["in_lists"] = [x["name"] for x in lists_in]
        return item


def similar_accounts(username, limit=8):
    """同じハッシュタグ・同じ投稿内容カテゴリ・近いフォロワー帯で類似度を出す。
    自前のデータベース内での類似検索なので Apify を消費しない。"""
    with connect() as c:
        me = c.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        if not me:
            return []
        rows = c.execute("SELECT * FROM accounts WHERE username != ?", (username,)).fetchall()

    my_tags = set(me["hashtags"].split())
    my_keys = set(me["content_keys"].split())
    my_f = me["followers"] or 1

    scored = []
    for r in rows:
        tags = set(r["hashtags"].split())
        keys = set(r["content_keys"].split())
        score = len(my_tags & tags) * 3 + len(my_keys & keys) * 2
        ratio = (r["followers"] or 1) / my_f
        if 0.3 <= ratio <= 3:
            score += 1
        if score <= 0:
            continue
        item = json.loads(r["data"])
        item["similarity"] = score
        scored.append(item)
    scored.sort(key=lambda x: (-x["similarity"], -x.get("followers", 0)))
    return scored[:limit]


# ---------------------------------------------------------------------------
# フォロワー推移（成長率）
# ---------------------------------------------------------------------------
def record_followers(rows):
    """検索するたびにフォロワー数を1日1件記録する。
    成長率はこの履歴から出るので、最初の数回は『—』のままになる。"""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO follower_history (username,seen_on,followers) VALUES (?,?,?)",
            [(r["username"], day, int(r.get("followers") or 0)) for r in rows if r.get("username")],
        )


def growth_map(usernames):
    """{username: {"pct":成長率%, "days":観測期間, "from":当時のフォロワー}} を返す。
    履歴が1点しかないアカウントは含めない。"""
    if not usernames:
        return {}
    out = {}
    with connect() as c:
        q = ("SELECT username, seen_on, followers FROM follower_history "
             f"WHERE username IN ({','.join('?' * len(usernames))}) ORDER BY username, seen_on")
        rows = list(c.execute(q, list(usernames)))

    by_user = {}
    for r in rows:
        by_user.setdefault(r["username"], []).append(r)

    for u, hist in by_user.items():
        if len(hist) < 2:
            continue
        first, last = hist[0], hist[-1]
        if not first["followers"]:
            continue
        d0 = datetime.fromisoformat(first["seen_on"])
        d1 = datetime.fromisoformat(last["seen_on"])
        days = max((d1 - d0).days, 1)
        pct = (last["followers"] - first["followers"]) / first["followers"] * 100
        out[u] = {"pct": round(pct, 2), "days": days, "from": first["followers"]}
    return out


# ---------------------------------------------------------------------------
# フォルダ
# ---------------------------------------------------------------------------
def create_folder(name, created_by=None, group_id=None):
    with connect() as c:
        cur = c.execute(
            "INSERT INTO folders (name,created_by,created_at,group_id) VALUES (?,?,?,?)",
            (name.strip(), created_by, now(), group_id),
        )
        return cur.lastrowid


def all_folders(group_id=None):
    with connect() as c:
        rows = c.execute("SELECT * FROM folders WHERE group_id IS ? ORDER BY name",
                         (group_id,)).fetchall()
    return [dict(r) for r in rows]


def rename_folder(folder_id, name):
    with connect() as c:
        c.execute("UPDATE folders SET name=? WHERE id=?", (name.strip(), folder_id))


def delete_folder(folder_id):
    """フォルダだけ消す。中のリストは未分類に戻す（中身は消さない）。"""
    with connect() as c:
        c.execute("UPDATE lists SET folder_id=NULL WHERE folder_id=?", (folder_id,))
        c.execute("DELETE FROM folders WHERE id=?", (folder_id,))


def move_list(list_id, folder_id):
    with connect() as c:
        c.execute("UPDATE lists SET folder_id=? WHERE id=?", (folder_id, list_id))


def get_folder(folder_id):
    with connect() as c:
        row = c.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# リスト
# ---------------------------------------------------------------------------
def create_list(name, description="", created_by=None, folder_id=None, group_id=None):
    with connect() as c:
        cur = c.execute(
            "INSERT INTO lists (name,description,created_by,created_at,folder_id,group_id) "
            "VALUES (?,?,?,?,?,?)",
            (name.strip(), description, created_by, now(), folder_id, group_id),
        )
        return cur.lastrowid


def all_lists(group_id=None):
    with connect() as c:
        rows = c.execute(
            "SELECT l.*, (SELECT COUNT(*) FROM list_items i WHERE i.list_id=l.id) AS count "
            "FROM lists l WHERE l.group_id IS ? ORDER BY l.created_at DESC",
            (group_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def tree(group_id=None):
    """フォルダ + その中のリスト + 未分類リストを、UI がそのまま描ける形で返す。"""
    folders = all_folders(group_id)
    lists = all_lists(group_id)
    by_folder = {}
    for l in lists:
        by_folder.setdefault(l.get("folder_id"), []).append(l)

    out = []
    for f in folders:
        kids = by_folder.get(f["id"], [])
        out.append({**f, "lists": kids, "total": sum(k["count"] for k in kids)})
    loose = by_folder.get(None, [])
    return {"folders": out, "loose": loose,
            "total_lists": len(lists), "total_items": sum(l["count"] for l in lists)}


def find_saved(query="", usernames=None, group_id=None):
    """グループ内の全リスト横断で保存済みインフルエンサーを探す。
    query: ユーザー名・メモの部分一致。usernames: 完全一致で絞る。"""
    sql = ("SELECT i.*, l.id AS list_id, l.name AS list_name, f.name AS folder_name "
           "FROM list_items i "
           "JOIN lists l ON l.id = i.list_id "
           "LEFT JOIN folders f ON f.id = l.folder_id")
    where, args = ["l.group_id IS ?"], [group_id]
    if query:
        where.append("(i.username LIKE ? OR i.note LIKE ?)")
        args += [f"%{query}%", f"%{query}%"]
    if usernames:
        where.append(f"i.username IN ({','.join('?' * len(usernames))})")
        args += list(usernames)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY i.added_at DESC LIMIT 300"

    with connect() as c:
        rows = c.execute(sql, args).fetchall()

    out = []
    for r in rows:
        item = json.loads(r["data"])
        item.update({
            "item_id": r["id"], "note": r["note"] or "",
            "item_status": r["status"] or "new", "added_by": r["added_by"] or "",
            "added_at": r["added_at"], "list_id": r["list_id"],
            "list_name": r["list_name"], "folder_name": r["folder_name"] or "",
        })
        out.append(item)
    return out


def saved_usernames(group_id=None):
    """グループ内リストに入っている全ユーザー名。除外フィルタ用なので上限を掛けない
    （find_saved は表示用に 300 件で切っているため、除外には使えない）。"""
    with connect() as c:
        return [r["username"] for r in c.execute(
            "SELECT DISTINCT i.username FROM list_items i "
            "JOIN lists l ON l.id=i.list_id WHERE l.group_id IS ?", (group_id,))]


def saved_map(usernames, group_id=None):
    """{username: [リスト名, ...]} を返す。検索結果に『保存済み』を出すため。"""
    if not usernames:
        return {}
    out = {}
    with connect() as c:
        q = ("SELECT i.username, l.name FROM list_items i JOIN lists l ON l.id=i.list_id "
             f"WHERE l.group_id IS ? AND i.username IN ({','.join('?' * len(usernames))})")
        for r in c.execute(q, [group_id] + list(usernames)):
            out.setdefault(r["username"], []).append(r["name"])
    return out


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


def item_group(item_id):
    """アイテムが属するリストの group_id（所有権チェック用）。無ければ False を返す
    （None は『グループ無し』の正当な値なので、不存在と区別する）。"""
    with connect() as c:
        row = c.execute(
            "SELECT l.group_id FROM list_items i JOIN lists l ON l.id=i.list_id WHERE i.id=?",
            (item_id,)).fetchone()
    return row["group_id"] if row else False


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
