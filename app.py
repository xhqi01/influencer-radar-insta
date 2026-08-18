#!/usr/bin/env python3
"""
app.py — Instagram Radar Web アプリ

    pip install -r requirements.txt
    python app.py                    # ローカル確認用
    gunicorn -w 1 -k gthread -t 900 --threads 8 -b 0.0.0.0:8000 app:app   # 共有時

環境変数（.env）:
    APIFY_API_TOKEN=...      必須
    ANTHROPIC_API_KEY=...    任意（AI 入力欄と推定精度の向上に使用）
    RADAR_DB=/path/radar.db  任意（既定はアプリと同じフォルダ）
    FLASK_DEBUG=1            任意（開発時のみ）

注意: gunicorn で使う場合はワーカー1本 + スレッドで動かすこと。
検索ジョブは起動したプロセス内のスレッドで走るため、ワーカーを複数にすると
別ワーカーに来たリクエストがジョブを進められない。
"""

import csv
import io
import os
import threading
import traceback
import uuid
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import db
import radar_core

app = Flask(__name__)

CSV_COLUMNS = [
    "username", "url", "full_name", "followers", "growth", "engagement", "last_post",
    "posts_count", "avg_reel_views", "account_type", "verified", "email", "pr_count",
    "region", "narration", "narration_conf", "reel_ratio",
    "gender", "gender_conf", "age", "age_conf", "content", "content_conf",
    "bio", "matched_hashtags", "hashtag",
]
LIST_CSV_EXTRA = ["item_status", "note", "added_by", "added_at"]


def who(payload=None):
    """簡易的な利用者名。認証ではなく『誰が追加したか』の記録用。"""
    name = (payload or {}).get("user") if isinstance(payload, dict) else None
    return (name or request.headers.get("X-Radar-User") or "").strip()[:40]


def csv_response(rows, columns, filename):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        row = dict(r)
        if isinstance(row.get("matched_hashtags"), list):
            row["matched_hashtags"] = " / ".join(row["matched_hashtags"])
        writer.writerow(row)
    return Response(
        "\ufeff" + buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def safe_filename(name):
    keep = "".join(ch for ch in name if ch.isalnum() or ch in " -_あ-んア-ン一-龥")
    return (keep.strip().replace(" ", "_") or "list")[:40]


@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# 自由文 → 条件
# ---------------------------------------------------------------------------
@app.route("/api/parse", methods=["POST"])
def api_parse():
    payload = request.get_json(silent=True) or {}
    brief = (payload.get("brief") or "").strip()
    if not brief:
        return jsonify({"error": "empty_brief"}), 400

    # 各利用者が自分の Anthropic キーをヘッダで送る。サーバーは保持しない。
    key = (request.headers.get("X-Anthropic-Key") or "").strip()
    if not key:
        return jsonify({"error": "no_api_key"}), 400

    try:
        return jsonify({"filters": radar_core.brief_to_filters(brief, key, lang=payload.get("lang", "ja"))})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "parse_failed", "detail": str(e)}), 500


# ---------------------------------------------------------------------------
# 検索
# ---------------------------------------------------------------------------
@app.route("/api/search", methods=["POST"])
def api_search():
    payload = request.get_json(silent=True) or {}
    use_llm = bool(payload.pop("use_llm", True))
    creator = who(payload)
    payload.pop("user", None)

    has_tags = bool(payload.get("hashtags")) or bool((payload.get("hashtag") or "").strip())
    if not has_tags and not payload.get("usernames"):
        return jsonify({"error": "no_hashtag"}), 400

    # 利用者ごとの自己申告トークン。サーバーには保存せず、この検索の間だけ使う。
    apify_token = (request.headers.get("X-Apify-Token") or "").strip()
    anthropic_key = (request.headers.get("X-Anthropic-Key") or "").strip()
    if not apify_token:
        return jsonify({"error": "no_apify_token"}), 400

    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, payload, created_by=creator)

    def worker():
        try:
            db.update_job(job_id, status="running", stage="fetching_posts")

            # 「キャンペーンリスト除外」: すでにリストに入っている人を候補から外す
            if payload.pop("exclude_saved", False):
                payload["exclude_usernames"] = db.saved_usernames()

            out = radar_core.run_search(
                payload,
                apify_token=apify_token,
                anthropic_key=anthropic_key or None,
                use_llm=use_llm and bool(anthropic_key),
                progress=lambda stage: db.update_job(job_id, stage=stage),
            )

            rows = out["results"]
            db.record_followers(rows)
            db.record_accounts(rows)
            growth = db.growth_map([r["username"] for r in rows])
            for r in rows:
                g = growth.get(r["username"])
                r["growth"] = g["pct"] if g else None
                r["growth_days"] = g["days"] if g else 0
                r["quality"] = radar_core.quality_signals(r)["score"]

            db.save_results(job_id, rows)
            db.update_job(job_id, status="done", stage="done", stats=out["stats"])
        except Exception as e:
            traceback.print_exc()
            db.update_job(job_id, status="error", stage="error", error=str(e))

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = db.get_job(job_id, with_results=True)
    if not job:
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        "status": job["status"],
        "stage": job["stage"],
        "error": job["error"],
        "stats": job["stats"],
        "results": job["results"] if job["status"] == "done" else None,
    })


@app.route("/api/jobs")
def api_jobs():
    return jsonify({"jobs": db.recent_jobs()})


@app.route("/api/export/job/<job_id>")
def api_export_job(job_id):
    job = db.get_job(job_id, with_results=True)
    if not job or not job.get("results"):
        return jsonify({"error": "no_results"}), 404
    p = job["params"] or {}
    tags = p.get("hashtags") or ([p["hashtag"]] if p.get("hashtag") else ["search"])
    tag = "+".join(tags[:3])
    stamp = datetime.now().strftime("%Y%m%d")
    return csv_response(job["results"], CSV_COLUMNS, f"{safe_filename(tag)}_{stamp}.csv")


# ---------------------------------------------------------------------------
# 蓄積データベース（閲覧は Apify を消費しない）
# ---------------------------------------------------------------------------
@app.route("/api/accounts")
def api_accounts():
    q = request.args.get("q", "").strip()
    min_f = int(request.args.get("min_f") or 0)
    max_f = int(request.args.get("max_f") or 10**9)
    sort = request.args.get("sort", "followers")
    rows = db.browse_accounts(q, min_f, max_f, sort)
    for r in rows:
        r["quality"] = radar_core.quality_signals(r)["score"]
    return jsonify({"accounts": rows, "total": db.account_count()})


@app.route("/api/accounts/<username>")
def api_account_detail(username):
    item = db.get_account(username)
    if not item:
        return jsonify({"error": "not_found"}), 404
    sig = radar_core.quality_signals(item, history=item.get("history"))
    item["quality"] = sig["score"]
    item["quality_flags"] = sig["flags"]
    item["similar"] = db.similar_accounts(username)
    return jsonify({"account": item})


# ---------------------------------------------------------------------------
# フォルダ
# ---------------------------------------------------------------------------
@app.route("/api/tree")
def api_tree():
    """フォルダ + リストの構造をまとめて返す（左ナビ用）。"""
    return jsonify(db.tree())


@app.route("/api/folders", methods=["POST"])
def api_create_folder():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "no_name"}), 400
    try:
        fid = db.create_folder(name, created_by=who(payload))
    except Exception:
        return jsonify({"error": "duplicate_name"}), 409
    return jsonify({"id": fid, "name": name})


@app.route("/api/folders/<int:folder_id>", methods=["PATCH", "DELETE"])
def api_folder(folder_id):
    if not db.get_folder(folder_id):
        return jsonify({"error": "not_found"}), 404

    if request.method == "DELETE":
        # フォルダのみ削除。中のリストは未分類に戻るだけで消えない。
        db.delete_folder(folder_id)
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "no_name"}), 400
    try:
        db.rename_folder(folder_id, name)
    except Exception:
        return jsonify({"error": "duplicate_name"}), 409
    return jsonify({"ok": True})


@app.route("/api/lists/<int:list_id>/move", methods=["POST"])
def api_move_list(list_id):
    if not db.get_list(list_id):
        return jsonify({"error": "not_found"}), 404
    payload = request.get_json(silent=True) or {}
    fid = payload.get("folder_id")
    db.move_list(list_id, int(fid) if fid else None)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 横断検索
# ---------------------------------------------------------------------------
@app.route("/api/saved")
def api_saved():
    """全リスト横断で保存済みの人を探す。?q= で絞り込み。"""
    return jsonify({"items": db.find_saved(request.args.get("q", "").strip())})


@app.route("/api/saved/map", methods=["POST"])
def api_saved_map():
    """検索結果に『保存済み』バッジを出すための {username: [リスト名]} を返す。"""
    payload = request.get_json(silent=True) or {}
    return jsonify({"map": db.saved_map(payload.get("usernames") or [])})


# ---------------------------------------------------------------------------
# リスト
# ---------------------------------------------------------------------------
@app.route("/api/lists", methods=["GET", "POST"])
def api_lists():
    if request.method == "GET":
        return jsonify({"lists": db.all_lists()})

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "no_name"}), 400
    fid = payload.get("folder_id")
    try:
        list_id = db.create_list(name, payload.get("description", ""),
                                 created_by=who(payload),
                                 folder_id=int(fid) if fid else None)
    except Exception:
        return jsonify({"error": "duplicate_name"}), 409
    return jsonify({"id": list_id, "name": name})


@app.route("/api/lists/<int:list_id>", methods=["GET", "PATCH", "DELETE"])
def api_list_detail(list_id):
    meta = db.get_list(list_id)
    if not meta:
        return jsonify({"error": "not_found"}), 404

    if request.method == "GET":
        return jsonify({"list": meta, "items": db.list_items(list_id)})

    if request.method == "PATCH":
        payload = request.get_json(silent=True) or {}
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"error": "no_name"}), 400
        try:
            db.rename_list(list_id, name)
        except Exception:
            return jsonify({"error": "duplicate_name"}), 409
        return jsonify({"ok": True})

    db.delete_list(list_id)
    return jsonify({"ok": True})


@app.route("/api/lists/<int:list_id>/items", methods=["POST"])
def api_add_items(list_id):
    if not db.get_list(list_id):
        return jsonify({"error": "not_found"}), 404
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or ([payload["item"]] if payload.get("item") else [])
    if not items:
        return jsonify({"error": "no_items"}), 400

    user = who(payload)
    for it in items:
        if it.get("username"):
            db.add_item(list_id, it, added_by=user)
    return jsonify({"ok": True, "added": len(items), "count": len(db.list_items(list_id))})


@app.route("/api/items/<int:item_id>", methods=["PATCH", "DELETE"])
def api_item(item_id):
    if request.method == "DELETE":
        db.delete_item(item_id)
        return jsonify({"ok": True})
    payload = request.get_json(silent=True) or {}
    db.update_item(item_id, note=payload.get("note"), status=payload.get("status"))
    return jsonify({"ok": True})


@app.route("/api/export/list/<int:list_id>")
def api_export_list(list_id):
    meta = db.get_list(list_id)
    if not meta:
        return jsonify({"error": "not_found"}), 404
    items = db.list_items(list_id)
    if not items:
        return jsonify({"error": "empty_list"}), 404
    stamp = datetime.now().strftime("%Y%m%d")
    return csv_response(items, CSV_COLUMNS + LIST_CSV_EXTRA,
                        f"{safe_filename(meta['name'])}_{stamp}.csv")


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG") == "1"
    app.run(debug=debug, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", 5000)))
