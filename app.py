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
    "username", "url", "full_name", "followers", "engagement", "last_post",
    "posts_count", "narration", "narration_conf", "reel_ratio",
    "gender", "gender_conf", "age", "age_conf", "content", "content_conf",
    "bio", "verified", "hashtag",
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
        writer.writerow(r)
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
    return render_template("index.html", has_ai=bool(os.getenv("ANTHROPIC_API_KEY")))


# ---------------------------------------------------------------------------
# 自由文 → 条件
# ---------------------------------------------------------------------------
@app.route("/api/parse", methods=["POST"])
def api_parse():
    payload = request.get_json(silent=True) or {}
    brief = (payload.get("brief") or "").strip()
    if not brief:
        return jsonify({"error": "empty_brief"}), 400

    key = os.getenv("ANTHROPIC_API_KEY")
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
    payload.pop("user", None)

    if not (payload.get("hashtag") or "").strip():
        return jsonify({"error": "no_hashtag"}), 400
    if not os.getenv("APIFY_API_TOKEN"):
        return jsonify({"error": "no_apify_token"}), 400

    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, payload, created_by=who(request.get_json(silent=True)))

    def worker():
        try:
            db.update_job(job_id, status="running", stage="fetching_posts")
            out = radar_core.run_search(
                payload, use_llm=use_llm,
                progress=lambda stage: db.update_job(job_id, stage=stage),
            )
            db.save_results(job_id, out["results"])
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
    tag = (job["params"] or {}).get("hashtag", "search")
    stamp = datetime.now().strftime("%Y%m%d")
    return csv_response(job["results"], CSV_COLUMNS, f"{safe_filename(tag)}_{stamp}.csv")


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
    try:
        list_id = db.create_list(name, payload.get("description", ""), created_by=who(payload))
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
