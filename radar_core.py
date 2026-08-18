"""
radar_core.py — Instagram インフルエンサー発掘のコアロジック

app.py（Web アプリ）から呼ばれる。UI 文言は持たない。

データの信頼度:
  実データ（API 直取得）: hashtag / followers / last_post / engagement
  推定（confidence 併記）: narration / gender / age / content
"""

import json
import os
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from apify_client import ApifyClient

HASHTAG_ACTOR = "apify/instagram-hashtag-scraper"
PROFILE_ACTOR = "apify/instagram-profile-scraper"
PROFILE_BATCH_SIZE = 50
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------
def call_claude(prompt, api_key, max_tokens=600):
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def parse_json_response(text):
    return json.loads(text.replace("```json", "").replace("```", "").strip())


# ---------------------------------------------------------------------------
# 自由文 → 検索条件
# ---------------------------------------------------------------------------
BRIEF_SCHEMA = """{
  "hashtags": ["検索するハッシュタグ（#は付けない）。複数可、最大5個"],
  "hashtag_mode": "union"（どれか1つでも投稿があれば対象） | "intersect"（指定した全タグに投稿がある人だけ）,
  "min_followers": 数値,
  "max_followers": 数値,
  "active_days": 数値（既定90）,
  "gender": "female" | "male" | "any",
  "age_min": 数値 or null,
  "age_max": 数値 or null,
  "narration_only": true | false,
  "min_engagement": 数値（%。指定がなければ0）,
  "content_keywords": ["投稿内容の絞り込みキーワード"],
  "profile_keyword": "プロフィール(bio)に含まれる語。指定が無ければ空文字",
  "caption_keyword": "キャプションに含まれる語。指定が無ければ空文字",
  "mention": "キャプション内で @メンションされているアカウント名。無ければ空文字",
  "account_type": "business" | "creator" | "personal" | "any",
  "has_contact": true | false（bio にメール等の連絡先がある人だけに絞るなら true）,
  "verified_only": true | false,
  "has_pr": "any" | "yes" | "no"（PR/タイアップ投稿の有無）,
  "min_reel_views": 数値 or null,
  "min_posts": 数値 or null,
  "region": "地域を表す語。無ければ空文字",
  "posts_limit": 数値（既定200）,
  "notes": "解釈できなかった条件や注意点を1文で"
}"""


def _as_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def brief_to_filters(brief_text, api_key, lang="ja"):
    prompt = (
        "あなたはインフルエンサー検索ツールのクエリ変換器です。\n"
        "ユーザーの要望文を、以下のスキーマの JSON に変換してください。\n"
        "JSON のみを返すこと。前置き・説明・コードブロックは禁止。\n\n"
        f"スキーマ:\n{BRIEF_SCHEMA}\n\n"
        "ルール:\n"
        "- hashtags が明示されていない場合は、要望文から最も検索効率が高いものを1〜2個選ぶ\n"
        "- 日本市場向けなら日本語ハッシュタグ（筋トレ、宅トレ 等）を優先する\n"
        "- 「AとBの両方」「両方に投稿してる人」のような条件なら hashtag_mode は intersect、"
        "「AかBのどちらか」「どちらでもいい」なら union\n"
        "- 年齢の指定が無ければ age_min / age_max は null（推測で埋めない）\n"
        f"- notes は {lang} で書く\n\n"
        f"ユーザーの要望:\n{brief_text}"
    )
    data = parse_json_response(call_claude(prompt, api_key, max_tokens=700))
    tags = [str(h).lstrip("#").strip() for h in (data.get("hashtags") or []) if str(h).strip()]
    return {
        "hashtags": tags[:5],
        "hashtag_mode": data.get("hashtag_mode") if data.get("hashtag_mode") in ("union", "intersect") else "union",
        "min_followers": _as_int(data.get("min_followers"), 10000),
        "max_followers": _as_int(data.get("max_followers"), 70000),
        "active_days": _as_int(data.get("active_days"), 90),
        "gender": data.get("gender") if data.get("gender") in ("female", "male", "any") else "any",
        "age_min": _as_int(data.get("age_min")),
        "age_max": _as_int(data.get("age_max")),
        "narration_only": bool(data.get("narration_only")),
        "min_engagement": float(data.get("min_engagement") or 0),
        "content_keywords": [str(k) for k in (data.get("content_keywords") or [])],
        "profile_keyword": str(data.get("profile_keyword") or "").strip(),
        "caption_keyword": str(data.get("caption_keyword") or "").strip(),
        "mention": str(data.get("mention") or "").lstrip("@").strip(),
        "account_type": data.get("account_type") if data.get("account_type") in
                        ("business", "creator", "personal", "any") else "any",
        "has_contact": bool(data.get("has_contact")),
        "verified_only": bool(data.get("verified_only")),
        "has_pr": data.get("has_pr") if data.get("has_pr") in ("yes", "no", "any") else "any",
        "min_reel_views": _as_int(data.get("min_reel_views")),
        "min_posts": _as_int(data.get("min_posts")),
        "region": str(data.get("region") or "").strip(),
        "posts_limit": _as_int(data.get("posts_limit"), 200),
        "notes": data.get("notes") or "",
    }


# ---------------------------------------------------------------------------
# 投稿の重複排除
# ---------------------------------------------------------------------------
def post_key(p):
    return p.get("shortCode") or p.get("shortcode") or p.get("id") or p.get("url") or id(p)


def dedupe_posts(posts):
    """同じ投稿が hashtag 側と profile 側の両方から来る。
    排除しないとエンゲージメント率の平均が歪む。"""
    seen, out = set(), []
    for p in posts:
        k = post_key(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# 推定: ナレーション
# ---------------------------------------------------------------------------
def estimate_narration(posts):
    """Reel のオリジナル音源比率から推定。音源情報が無い投稿は判定対象から外す
    （旧版は musicInfo が空の投稿を「オリジナル音源」と誤判定していた）。"""
    reels = [p for p in posts if p.get("productType") == "clips"]
    judged, original = 0, 0

    for p in reels:
        music = p.get("musicInfo")
        if not music:
            continue
        judged += 1
        if music.get("should_mute_audio"):
            continue
        song = (music.get("song_name") or "").lower()
        artist = (music.get("artist_name") or "").strip()
        if music.get("uses_original_audio") is True:
            original += 1
        elif "original audio" in song or "オリジナル音源" in song:
            original += 1
        elif not artist and not song:
            original += 1

    if judged == 0:
        return {"value": "unknown", "confidence": "unknown", "reel_ratio": 0.0, "sample": 0}

    ratio = original / judged
    conf = "medium" if judged >= 4 else "low"
    if ratio >= 0.6:
        return {"value": "yes", "confidence": conf, "reel_ratio": round(ratio, 2), "sample": judged}
    if ratio >= 0.3:
        return {"value": "partial", "confidence": "low", "reel_ratio": round(ratio, 2), "sample": judged}
    return {"value": "no", "confidence": conf, "reel_ratio": round(ratio, 2), "sample": judged}


# ---------------------------------------------------------------------------
# 推定: 性別
# ---------------------------------------------------------------------------
# ASCII の語は単語境界で照合する。部分一致だと "female" が "male" に、
# "woman" が "man" にヒットし、英語 bio の女性アカウントが判定不能になる。
FEMALE_HINTS = ["she/her", "her/she", "girl", "girls", "woman", "women", "female", "lady", "mom", "mama",
                "彼女", "女性", "女子", "女の子", "ママ", "主婦", "妻", "母", "レディース",
                "美ボディ", "くびれ", "美尻", "女性専用", "女性向け"]
MALE_HINTS = ["he/him", "him/he", "boy", "boys", "man", "men", "male", "guy", "dad", "papa",
              "男性", "男子", "パパ", "夫", "父", "メンズ", "筋肉男子", "漢", "男性向け"]

_ASCII = re.compile(r"^[a-z/\s.]+$")


def _count_hints(text, hints):
    total = 0
    for h in hints:
        h = h.lower()
        if _ASCII.match(h):
            pattern = r"(?<![a-z])" + re.escape(h) + r"(?![a-z])"
            total += len(re.findall(pattern, text))
        else:
            total += text.count(h)
    return total


def estimate_gender(profile):
    text = " ".join([
        profile.get("biography") or "",
        profile.get("fullName") or "",
        profile.get("businessCategoryName") or "",
    ]).lower()

    f = _count_hints(text, FEMALE_HINTS)
    m = _count_hints(text, MALE_HINTS)

    if f > m and f > 0:
        return {"value": "female", "confidence": "medium" if f >= 2 else "low"}
    if m > f and m > 0:
        return {"value": "male", "confidence": "medium" if m >= 2 else "low"}
    return {"value": "unknown", "confidence": "unknown"}


# ---------------------------------------------------------------------------
# 推定: 年齢
# ---------------------------------------------------------------------------
AGE_PATTERNS = [
    (re.compile(r"(\d{2})\s*[歳才]"), "direct"),
    (re.compile(r"\b(\d{2})\s*(?:yo|y\.o\.|years old)\b", re.I), "direct"),
    (re.compile(r"(19[7-9]\d|20[0-1]\d)\s*年生"), "birthyear"),
    (re.compile(r"(?<!\d)'(\d{2})(?!\d)"), "birthyear_short"),
]
AGE_BANDS = {
    "10代": (15, 19), "20代": (20, 29), "30代": (30, 39),
    "40代": (40, 49), "50代": (50, 59),
    "アラサー": (28, 32), "アラフォー": (38, 42),
}


def estimate_age(profile):
    bio = " ".join([profile.get("biography") or "", profile.get("fullName") or ""])
    now_year = datetime.now().year

    for pattern, kind in AGE_PATTERNS:
        m = pattern.search(bio)
        if not m:
            continue
        val = int(m.group(1))
        if kind == "direct" and 13 <= val <= 75:
            return {"value": str(val), "confidence": "high"}
        if kind == "birthyear":
            age = now_year - val
            if 13 <= age <= 75:
                return {"value": str(age), "confidence": "high"}
        if kind == "birthyear_short":
            year = 1900 + val if val > 30 else 2000 + val
            age = now_year - year
            if 13 <= age <= 75:
                return {"value": str(age), "confidence": "medium"}

    for band, (lo, hi) in AGE_BANDS.items():
        if band in bio:
            return {"value": f"{lo}-{hi}", "confidence": "low"}

    return {"value": "unknown", "confidence": "unknown"}


# ---------------------------------------------------------------------------
# 推定: 投稿内容
# ---------------------------------------------------------------------------
CONTENT_CATEGORIES = {
    "home_workout": ["宅トレ", "自宅", "home workout", "homeworkout", "マット"],
    "gym_weights": ["ジム", "gym", "ベンチプレス", "デッドリフト", "スクワット", "ウエイト", "bulking"],
    "diet": ["ダイエット", "減量", "痩せ", "diet", "fatloss", "体重"],
    "nutrition": ["プロテイン", "protein", "食事", "レシピ", "サプリ", "meal", "栄養"],
    "yoga_pilates": ["ヨガ", "yoga", "ピラティス", "pilates", "ストレッチ"],
    "running": ["ランニング", "running", "マラソン", "run"],
    "bodymake": ["ボディメイク", "くびれ", "美尻", "ヒップ", "腹筋", "abs"],
}


def classify_content(posts, profile):
    haystack = " ".join([
        profile.get("biography") or "",
        *[(p.get("caption") or "") for p in posts],
        *[" ".join(p.get("hashtags") or []) for p in posts],
    ]).lower()

    scores = {}
    for cat, keywords in CONTENT_CATEGORIES.items():
        hits = sum(haystack.count(k.lower()) for k in keywords)
        if hits:
            scores[cat] = hits

    if not scores:
        return {"value": "unknown", "keys": [], "confidence": "unknown", "haystack": haystack}

    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
    return {
        "value": " / ".join(c for c, _ in top),
        "keys": [c for c, _ in top],
        "confidence": "medium" if top[0][1] >= 3 else "low",
        "haystack": haystack,
    }


# ---------------------------------------------------------------------------
# プロフィール属性の抽出（すべて API の実データから）
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PR_TAGS = ["#pr", "#ad", "#sponsored", "#タイアップ", "#提供", "#広告",
           "#プロモーション", "paid partnership", "タイアップ投稿"]


def account_type(profile):
    """business / creator / personal を判定する。Apify のフラグをそのまま使う。"""
    if profile.get("isBusinessAccount"):
        return "business"
    # creator アカウントは業種カテゴリを持つが business フラグは立たない
    if profile.get("businessCategoryName") or profile.get("isProfessionalAccount"):
        return "creator"
    return "personal"


def contact_info(profile):
    """bio や公開連絡先からメールを拾う。営業先リストを作るとき効く。"""
    email = (profile.get("publicEmail") or "").strip()
    if not email:
        m = EMAIL_RE.search(profile.get("biography") or "")
        email = m.group(0) if m else ""
    phone = (profile.get("publicPhoneNumber") or "").strip()
    return {"email": email, "phone": phone, "has": bool(email or phone)}


def detect_pr(posts):
    """PR・タイアップ投稿の有無と本数。公式フラグとハッシュタグの両方を見る。"""
    n = 0
    for p in posts:
        if p.get("isSponsored") or p.get("isPaidPartnership") or p.get("sponsorUsers"):
            n += 1
            continue
        blob = ((p.get("caption") or "") + " " + " ".join(p.get("hashtags") or [])).lower()
        if any(tag in blob for tag in PR_TAGS):
            n += 1
    return n


def collect_mentions(posts):
    """キャプション内の @メンションを集める。競合や代理店の担当先を辿るのに使う。"""
    out = set()
    for p in posts:
        for m in (p.get("mentions") or []):
            out.add(str(m).lstrip("@").lower())
        for m in re.findall(r"@([A-Za-z0-9._]{2,30})", p.get("caption") or ""):
            out.add(m.lower())
    return out


def reel_views(posts):
    """Reel の平均再生回数。再生数を持つ投稿だけで平均する。"""
    vals = [p.get("videoPlayCount") or p.get("videoViewCount") or 0
            for p in posts if p.get("productType") == "clips"]
    vals = [v for v in vals if v]
    return round(sum(vals) / len(vals)) if vals else 0


REGION_HINTS = ["東京", "大阪", "名古屋", "福岡", "札幌", "京都", "神戸", "横浜", "仙台",
                "沖縄", "北海道", "関西", "関東", "九州", "tokyo", "osaka", "japan",
                "台北", "台湾", "香港", "上海", "北京", "seoul", "korea"]


def detect_region(profile):
    """bio・住所欄から地域語を拾う。書いていなければ空。"""
    text = " ".join([
        profile.get("biography") or "",
        profile.get("businessAddressJson") or "",
        profile.get("city") or "",
    ]).lower()
    for h in REGION_HINTS:
        if h.lower() in text:
            return h
    return ""


# ---------------------------------------------------------------------------
# 品質シグナル（フォロワー買い・不自然さの兆候）
# フォロワー個人のデータは取得できないため「断定」はできない。
# 公開データから読める危険信号を列挙し、判断材料として提示する。
# ---------------------------------------------------------------------------
# フォロワー帯ごとの ER 目安（%）。業界で一般に言われるレンジの下限。
ER_FLOOR = [(10_000, 1.2), (50_000, 0.8), (200_000, 0.5), (10**9, 0.3)]


def quality_signals(row, history=None):
    """row: 検索結果の1行。history: [{date, followers}] （あれば急増検知に使う）
    返り値: {"flags": [シグナルID...], "score": "ok"|"warn"|"risk"}"""
    flags = []
    followers = row.get("followers") or 0
    following = row.get("following") or 0
    er = row.get("engagement") or 0
    posts = row.get("posts_count") or 0

    floor = next(v for lim, v in ER_FLOOR if followers <= lim)
    if followers >= 5000 and 0 < er < floor:
        flags.append("low_er")           # フォロワー数に対して ER が異常に低い
    if following > 4000:
        flags.append("mass_following")   # 大量フォロー（フォロバ稼ぎの典型）
    if following > 0 and followers / following < 2 and followers > 10000:
        flags.append("weak_ratio")       # フォロワー/フォロー比が低い
    if posts and followers > 20000 and posts < 30:
        flags.append("few_posts")        # 投稿が少なすぎるのにフォロワーが多い

    if history and len(history) >= 2:
        for a, b in zip(history, history[1:]):
            try:
                d0 = datetime.fromisoformat(a["date"][:10])
                d1 = datetime.fromisoformat(b["date"][:10])
                days = max((d1 - d0).days, 1)
                if a["followers"] > 1000:
                    rate = (b["followers"] - a["followers"]) / a["followers"] / days
                    if rate > 0.05:      # 1日 +5% 超の急増
                        flags.append("growth_spike")
                        break
            except Exception:
                continue

    if len(flags) >= 3:
        score = "risk"
    elif flags:
        score = "warn"
    else:
        score = "ok"
    return {"flags": flags, "score": score}


def llm_enrich(profile, posts, api_key):
    payload = {
        "username": profile.get("username"),
        "full_name": profile.get("fullName"),
        "biography": profile.get("biography"),
        "captions": [(p.get("caption") or "")[:200] for p in posts[:6]],
    }
    prompt = (
        "以下は Instagram アカウントの公開プロフィールと投稿キャプションです。\n"
        "JSON のみを返してください（前置き・コードブロック禁止）。\n"
        'キー: gender("female"/"male"/"unknown"), gender_confidence("high"/"medium"/"low"/"unknown"), '
        'age(数値 or "20-29" 形式 or "unknown"), age_confidence, '
        "content(投稿内容を20文字以内の日本語で), content_confidence\n"
        "本文に根拠が無い項目は必ず unknown にすること。推測で埋めないこと。\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        return parse_json_response(call_claude(prompt, api_key, max_tokens=400))
    except Exception as e:
        print(f"[llm_enrich skipped] {profile.get('username')}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Apify 取得
# ---------------------------------------------------------------------------
def parse_ts(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except Exception:
            return None


def _dataset_id(run):
    """apify-client のバージョンによって call() の返り値が変わる：
    新しめ（3.x系）は Run オブジェクトで run.default_dataset_id、
    古い版は dict で run["defaultDatasetId"]。両対応にしておく。"""
    if hasattr(run, "default_dataset_id"):
        return run.default_dataset_id
    if isinstance(run, dict):
        return run.get("defaultDatasetId") or run.get("default_dataset_id")
    raise RuntimeError(f"Actor run から dataset ID を取得できません: {type(run)}")


def fetch_hashtag_posts(client, hashtags, limit_per_tag):
    """複数ハッシュタグを1回の Apify 呼び出しでまとめて取得する。
    hashtags: リスト（1つでも可）。各投稿に、どのタグから拾えたかを
    _source_hashtags として付けておく（積集合/和集合の判定に使う）。"""
    tags = [h.lstrip("#").strip() for h in hashtags if str(h).strip()]
    if not tags:
        return []
    run = client.actor(HASHTAG_ACTOR).call(
        run_input={"hashtags": tags, "resultsLimit": limit_per_tag})
    posts = list(client.dataset(_dataset_id(run)).iterate_items())

    # Apify の返り値には投稿がどのハッシュタグ由来かの明示フィールドが無い
    # ことが多いため、キャプション／hashtags 配列に含まれるタグ名を突き合わせる。
    for p in posts:
        blob = ((p.get("caption") or "") + " " + " ".join(p.get("hashtags") or [])).lower()
        p["_source_hashtags"] = [t for t in tags if t.lower() in blob] or tags[:1]
    return posts


def fetch_profiles(client, usernames, progress=None):
    profiles = {}
    total = len(usernames)
    for i in range(0, total, PROFILE_BATCH_SIZE):
        batch = usernames[i:i + PROFILE_BATCH_SIZE]
        try:
            run = client.actor(PROFILE_ACTOR).call(run_input={"usernames": batch})
            for item in client.dataset(_dataset_id(run)).iterate_items():
                if item.get("username"):
                    profiles[item["username"]] = item
        except Exception as e:
            print(f"[profile batch failed at {i}] {e}", file=sys.stderr)
        if progress:
            progress(f"profiles:{len(profiles)}/{total}")
    return profiles


# ---------------------------------------------------------------------------
# 検索パイプライン
# ---------------------------------------------------------------------------
def run_search(params, apify_token=None, anthropic_key=None, use_llm=True, progress=None):
    def report(stage):
        if progress:
            progress(stage)

    # トークンは呼び出し元（＝各利用者のブラウザ）から渡される。
    # サーバーの環境変数にはフォールバックしない：運営者のトークンを他人の検索に使わせない。
    token = apify_token
    if not token:
        raise RuntimeError("APIFY_API_TOKEN missing")
    client = ApifyClient(token)

    key = anthropic_key if use_llm else None

    # ハッシュタグは複数対応。旧パラメータ "hashtag"（単数）も後方互換で読む。
    hashtags = params.get("hashtags")
    if not hashtags:
        single = (params.get("hashtag") or "").strip()
        hashtags = [single] if single else []
    hashtags = [h.lstrip("#").strip() for h in hashtags if str(h).strip()]
    hashtag_mode = params.get("hashtag_mode", "union")  # "union"（和集合）| "intersect"（積集合）
    hashtag = hashtags[0] if hashtags else ""  # 表示用（結果行の hashtag 列など）

    direct = [u.lstrip("@").strip() for u in (params.get("usernames") or []) if str(u).strip()]

    posts_by_user = {}
    posts = []

    if direct:
        # 特定アカウントの直接チェック（ハッシュタグ検索を経由しない）
        report("fetching_profiles")
        usernames = direct[:15]
    else:
        if not hashtags:
            raise ValueError("hashtag missing")
        report("fetching_posts")
        posts = fetch_hashtag_posts(client, hashtags, params.get("posts_limit", 200))
        print(f"[diag] hashtags={hashtags} mode={hashtag_mode} raw posts fetched: {len(posts)}", file=sys.stderr)
        if posts:
            print(f"[diag] sample post keys: {sorted(posts[0].keys())}", file=sys.stderr)
        if not posts:
            return {"results": [], "stats": {"posts": 0, "accounts": 0, "matched": 0}}
        for p in posts:
            u = p.get("ownerUsername") or p.get("owner_username")
            if not u and isinstance(p.get("owner"), dict):
                u = p["owner"].get("username")
            if u:
                posts_by_user.setdefault(u, []).append(p)
            elif len(posts_by_user) == 0 and posts.index(p) < 2:
                print(f"[diag] post missing owner username, keys={sorted(p.keys())}", file=sys.stderr)

        # 積集合モード：投稿している全ハッシュタグの和が、指定したタグを
        # すべてカバーしているアカウントだけ残す（＝全部のタグに関連投稿がある人）。
        if hashtag_mode == "intersect" and len(hashtags) > 1:
            want = {h.lower() for h in hashtags}
            before = len(posts_by_user)
            posts_by_user = {
                u: ps for u, ps in posts_by_user.items()
                if want <= {t.lower() for p in ps for t in (p.get("_source_hashtags") or [])}
            }
            print(f"[diag] intersect mode: {before} -> {len(posts_by_user)} accounts "
                  f"cover all of {hashtags}", file=sys.stderr)

        usernames = list(posts_by_user.keys())
        print(f"[diag] unique usernames extracted from posts: {len(usernames)}", file=sys.stderr)
        report(f"accounts_found:{len(usernames)}")

    profiles = fetch_profiles(client, usernames, progress=progress)
    print(f"[diag] profiles fetched: {len(profiles)} / {len(usernames)} usernames requested", file=sys.stderr)
    if profiles:
        sample = next(iter(profiles.values()))
        print(f"[diag] sample profile keys: {sorted(sample.keys())}", file=sys.stderr)

    report("filtering")
    cutoff = datetime.now(timezone.utc) - timedelta(days=params.get("active_days", 90))
    results = []
    candidates = []   # LLM 補正待ち。key がある場合はここに積んで後で並列処理する
    drops = {}         # 診断用：どの条件で何件落ちたか
    def drop(reason):
        drops[reason] = drops.get(reason, 0) + 1

    for username, profile in profiles.items():
        if profile.get("private"):
            drop("private_account"); continue

        followers = profile.get("followersCount") or 0
        # 直接指定モードでは絞り込まない：ユーザー名を手で入れた＝この人を
        # 見たいという意図。フォームに残っている範囲設定で黙って消さない。
        if not direct and not (params.get("min_followers", 0) <= followers <= params.get("max_followers", 10**9)):
            drop("followers_range"); continue

        user_posts = dedupe_posts(posts_by_user.get(username, []) + (profile.get("latestPosts") or []))

        matched_tags = sorted({t for p in posts_by_user.get(username, [])
                                for t in (p.get("_source_hashtags") or [])}) or ([hashtag] if hashtag else [])

        stamps = [t for t in (parse_ts(p.get("timestamp")) for p in user_posts) if t]
        if stamps:
            last_post = max(stamps)
            # 活動期間の絞り込みはハッシュタグ検索のときだけ。ユーザー名を直接
            # 指定した場合は「この人を見たい」という意図なので落とさない。
            if not direct and last_post < cutoff:
                drop("active_days"); continue
            last_post_str = last_post.strftime("%Y-%m-%d")
        else:
            if not direct:
                drop("no_post_timestamps"); continue
            last_post_str = ""

        # エンゲージメント率は可能なら本人の最新投稿だけで計算する。
        # ハッシュタグ検索で拾えた投稿は「伸びた投稿」に偏るため上振れする。
        er_source = profile.get("latestPosts") or user_posts
        likes = [p.get("likesCount", 0) for p in er_source if p.get("likesCount")]
        engagement = round(sum(likes) / len(likes) / followers * 100, 2) if likes and followers else 0.0
        if not direct and engagement < params.get("min_engagement", 0):
            drop("min_engagement"); continue

        narration = estimate_narration(user_posts)
        gender = estimate_gender(profile)
        age = estimate_age(profile)
        content = classify_content(user_posts, profile)

        # --- 実データから取れる属性 ---
        atype = account_type(profile)
        contact = contact_info(profile)
        pr_count = detect_pr(user_posts)
        avg_reel = reel_views(user_posts)
        region = detect_region(profile)
        posts_count = profile.get("postsCount") or 0
        bio_raw = (profile.get("biography") or "")

        # --- 絞り込み（直接指定モードでは一切適用しない：指名した人は必ず表示） ---
        if not direct:
            if params.get("account_type", "any") != "any" and atype != params["account_type"]:
                drop("account_type"); continue
            if params.get("has_contact") and not contact["has"]:
                drop("has_contact"); continue
            if params.get("verified_only") and not profile.get("verified"):
                drop("verified_only"); continue
            if params.get("has_pr") == "yes" and pr_count == 0:
                drop("has_pr_yes"); continue
            if params.get("has_pr") == "no" and pr_count > 0:
                drop("has_pr_no"); continue
            if params.get("min_reel_views") and avg_reel < params["min_reel_views"]:
                drop("min_reel_views"); continue
            if params.get("min_posts") and posts_count < params["min_posts"]:
                drop("min_posts"); continue

            pk = (params.get("profile_keyword") or "").lower()
            if pk and pk not in bio_raw.lower() and pk not in (profile.get("fullName") or "").lower():
                drop("profile_keyword"); continue

            ck = (params.get("caption_keyword") or "").lower()
            if ck and not any(ck in (p.get("caption") or "").lower() for p in user_posts):
                drop("caption_keyword"); continue

            mention = (params.get("mention") or "").lstrip("@").lower()
            if mention and mention not in collect_mentions(user_posts):
                drop("mention"); continue

            rg = (params.get("region") or "").lower()
            if rg and rg not in (bio_raw + " " + region).lower():
                drop("region"); continue

            exclude = params.get("exclude_usernames") or []
            if exclude and username in exclude:
                drop("exclude_saved"); continue

            # 投稿内容キーワードは LLM に依存しない（haystack はルール抽出）ので先に判定
            kws = [k.lower() for k in (params.get("content_keywords") or [])]
            if kws and not any(k in content["haystack"] for k in kws):
                drop("content_keywords"); continue

        if key:
            candidates.append({
                "username": username, "profile": profile, "user_posts": user_posts,
                "followers": followers, "engagement": engagement,
                "last_post_str": last_post_str, "narration": narration,
                "gender": gender, "age": age, "content": content,
                "atype": atype, "contact": contact, "pr_count": pr_count,
                "avg_reel": avg_reel, "region": region,
                "posts_count": posts_count, "bio_raw": bio_raw,
                "matched_tags": matched_tags,
            })
            continue

        if not direct:
            if params.get("gender", "any") != "any" and gender["value"] != params["gender"]:
                drop("gender"); continue

            if params.get("age_min") or params.get("age_max"):
                nums = re.findall(r"\d+", age["value"])
                if not nums:
                    drop("age_unknown"); continue
                a = int(nums[0])
                if params.get("age_min") and a < params["age_min"]:
                    drop("age_min"); continue
                if params.get("age_max") and a > params["age_max"]:
                    drop("age_max"); continue

            if params.get("narration_only") and narration["value"] not in ("yes", "partial"):
                drop("narration_only"); continue

        results.append(_build_row(hashtag, {
            "username": username, "profile": profile,
            "followers": followers, "engagement": engagement,
            "last_post_str": last_post_str, "narration": narration,
            "gender": gender, "age": age, "content": content,
            "atype": atype, "contact": contact, "pr_count": pr_count,
            "avg_reel": avg_reel, "region": region,
            "posts_count": posts_count, "matched_tags": matched_tags,
        }))

    # --- LLM 補正フェーズ（並列） ---
    # 逐次だと 1 アカウント最大 60 秒 × 件数で実用に耐えないため、8 並列で回す。
    if key and candidates:
        report(f"llm:0/{len(candidates)}")
        done = [0]
        lock = threading.Lock()

        def enrich(c):
            llm = llm_enrich(c["profile"], c["user_posts"], key)
            with lock:
                done[0] += 1
                report(f"llm:{done[0]}/{len(candidates)}")
            return c, llm

        with ThreadPoolExecutor(max_workers=8) as pool:
            enriched = list(pool.map(enrich, candidates))

        for c, llm in enriched:
            gender, age, content = c["gender"], c["age"], c["content"]
            if llm:
                if llm.get("gender") in ("female", "male"):
                    gender = {"value": llm["gender"], "confidence": llm.get("gender_confidence", "medium")}
                if age["confidence"] in ("low", "unknown") and llm.get("age") not in (None, "unknown"):
                    age = {"value": str(llm["age"]), "confidence": llm.get("age_confidence", "low")}
                if llm.get("content"):
                    content = {**content, "value": llm["content"],
                               "confidence": llm.get("content_confidence", "medium")}
            c.update(gender=gender, age=age, content=content)

            if not direct:
                if params.get("gender", "any") != "any" and gender["value"] != params["gender"]:
                    drop("gender_llm"); continue
                if params.get("age_min") or params.get("age_max"):
                    nums = re.findall(r"\d+", age["value"])
                    if not nums:
                        drop("age_unknown_llm"); continue
                    a = int(nums[0])
                    if params.get("age_min") and a < params["age_min"]:
                        drop("age_min_llm"); continue
                    if params.get("age_max") and a > params["age_max"]:
                        drop("age_max_llm"); continue
                if params.get("narration_only") and c["narration"]["value"] not in ("yes", "partial"):
                    drop("narration_only_llm"); continue

            results.append(_build_row(hashtag, c))

    results.sort(key=lambda r: r["followers"], reverse=True)
    if not results:
        print(f"[diag] ZERO RESULTS. profiles_in={len(profiles)} drop_reasons={drops}", file=sys.stderr)
    return {
        "results": results,
        "stats": {"posts": len(posts), "accounts": len(usernames), "matched": len(results)},
    }


def _build_row(hashtag, c):
    profile = c["profile"]
    return {
        "username": c["username"],
        "url": f"https://www.instagram.com/{c['username']}/",
        "full_name": profile.get("fullName") or "",
        "avatar": profile.get("profilePicUrlHD") or profile.get("profilePicUrl") or "",
        "followers": c["followers"],
        "following": profile.get("followsCount") or 0,
        "engagement": c["engagement"],
        "last_post": c["last_post_str"],
        "posts_count": c["posts_count"],
        "account_type": c["atype"],
        "email": c["contact"]["email"],
        "has_contact": c["contact"]["has"],
        "pr_count": c["pr_count"],
        "avg_reel_views": c["avg_reel"],
        "region": c["region"],
        "narration": c["narration"]["value"],
        "narration_conf": c["narration"]["confidence"],
        "reel_ratio": c["narration"]["reel_ratio"],
        "gender": c["gender"]["value"],
        "gender_conf": c["gender"]["confidence"],
        "age": c["age"]["value"],
        "age_conf": c["age"]["confidence"],
        "content": c["content"]["value"],
        "content_conf": c["content"]["confidence"],
        "bio": (profile.get("biography") or "").replace("\n", " ")[:160],
        "verified": bool(profile.get("verified")),
        "hashtag": hashtag or "(direct)",
        "matched_hashtags": c.get("matched_tags") or ([hashtag] if hashtag else []),
    }
