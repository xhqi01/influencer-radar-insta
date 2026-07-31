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
import urllib.request
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
  "hashtag": "検索するハッシュタグ1つ。#は付けない",
  "min_followers": 数値,
  "max_followers": 数値,
  "active_days": 数値（既定90）,
  "gender": "female" | "male" | "any",
  "age_min": 数値 or null,
  "age_max": 数値 or null,
  "narration_only": true | false,
  "min_engagement": 数値（%。指定がなければ0）,
  "content_keywords": ["投稿内容の絞り込みキーワード"],
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
        "- hashtag が明示されていない場合は、要望文から最も検索効率が高いものを1つ選ぶ\n"
        "- 日本市場向けなら日本語ハッシュタグ（筋トレ、宅トレ 等）を優先する\n"
        "- 年齢の指定が無ければ age_min / age_max は null（推測で埋めない）\n"
        f"- notes は {lang} で書く\n\n"
        f"ユーザーの要望:\n{brief_text}"
    )
    data = parse_json_response(call_claude(prompt, api_key, max_tokens=700))
    return {
        "hashtag": str(data.get("hashtag") or "").lstrip("#").strip(),
        "min_followers": _as_int(data.get("min_followers"), 10000),
        "max_followers": _as_int(data.get("max_followers"), 70000),
        "active_days": _as_int(data.get("active_days"), 90),
        "gender": data.get("gender") if data.get("gender") in ("female", "male", "any") else "any",
        "age_min": _as_int(data.get("age_min")),
        "age_max": _as_int(data.get("age_max")),
        "narration_only": bool(data.get("narration_only")),
        "min_engagement": float(data.get("min_engagement") or 0),
        "content_keywords": [str(k) for k in (data.get("content_keywords") or [])],
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


def fetch_hashtag_posts(client, hashtag, limit):
    run = client.actor(HASHTAG_ACTOR).call(run_input={"hashtags": [hashtag], "resultsLimit": limit})
    return list(client.dataset(run["defaultDatasetId"]).iterate_items())


def fetch_profiles(client, usernames, progress=None):
    profiles = {}
    total = len(usernames)
    for i in range(0, total, PROFILE_BATCH_SIZE):
        batch = usernames[i:i + PROFILE_BATCH_SIZE]
        try:
            run = client.actor(PROFILE_ACTOR).call(run_input={"usernames": batch})
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
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

    token = apify_token or os.getenv("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN missing")
    client = ApifyClient(token)

    key = (anthropic_key or os.getenv("ANTHROPIC_API_KEY")) if use_llm else None

    hashtag = (params.get("hashtag") or "").strip()
    if not hashtag:
        raise ValueError("hashtag missing")

    report("fetching_posts")
    posts = fetch_hashtag_posts(client, hashtag, params.get("posts_limit", 200))
    if not posts:
        return {"results": [], "stats": {"posts": 0, "accounts": 0, "matched": 0}}

    posts_by_user = {}
    for p in posts:
        u = p.get("ownerUsername")
        if u:
            posts_by_user.setdefault(u, []).append(p)

    usernames = list(posts_by_user.keys())
    report(f"accounts_found:{len(usernames)}")

    profiles = fetch_profiles(client, usernames, progress=progress)

    report("filtering")
    cutoff = datetime.now(timezone.utc) - timedelta(days=params.get("active_days", 90))
    results = []

    for username, profile in profiles.items():
        if profile.get("private"):
            continue

        followers = profile.get("followersCount") or 0
        if not (params["min_followers"] <= followers <= params["max_followers"]):
            continue

        user_posts = dedupe_posts(posts_by_user.get(username, []) + (profile.get("latestPosts") or []))

        stamps = [t for t in (parse_ts(p.get("timestamp")) for p in user_posts) if t]
        if not stamps:
            continue
        last_post = max(stamps)
        if last_post < cutoff:
            continue

        # エンゲージメント率は可能なら本人の最新投稿だけで計算する。
        # ハッシュタグ検索で拾えた投稿は「伸びた投稿」に偏るため上振れする。
        er_source = profile.get("latestPosts") or user_posts
        likes = [p.get("likesCount", 0) for p in er_source if p.get("likesCount")]
        engagement = round(sum(likes) / len(likes) / followers * 100, 2) if likes and followers else 0.0
        if engagement < params.get("min_engagement", 0):
            continue

        narration = estimate_narration(user_posts)
        gender = estimate_gender(profile)
        age = estimate_age(profile)
        content = classify_content(user_posts, profile)

        if key:
            llm = llm_enrich(profile, user_posts, key)
            if llm:
                if llm.get("gender") in ("female", "male"):
                    gender = {"value": llm["gender"], "confidence": llm.get("gender_confidence", "medium")}
                if age["confidence"] in ("low", "unknown") and llm.get("age") not in (None, "unknown"):
                    age = {"value": str(llm["age"]), "confidence": llm.get("age_confidence", "low")}
                if llm.get("content"):
                    content = {**content, "value": llm["content"],
                               "confidence": llm.get("content_confidence", "medium")}

        if params.get("gender", "any") != "any" and gender["value"] != params["gender"]:
            continue

        if params.get("age_min") or params.get("age_max"):
            nums = re.findall(r"\d+", age["value"])
            if not nums:
                continue
            a = int(nums[0])
            if params.get("age_min") and a < params["age_min"]:
                continue
            if params.get("age_max") and a > params["age_max"]:
                continue

        if params.get("narration_only") and narration["value"] not in ("yes", "partial"):
            continue

        kws = [k.lower() for k in (params.get("content_keywords") or [])]
        if kws and not any(k in content["haystack"] for k in kws):
            continue

        results.append({
            "username": username,
            "url": f"https://www.instagram.com/{username}/",
            "full_name": profile.get("fullName") or "",
            "followers": followers,
            "engagement": engagement,
            "last_post": last_post.strftime("%Y-%m-%d"),
            "posts_count": profile.get("postsCount") or 0,
            "narration": narration["value"],
            "narration_conf": narration["confidence"],
            "reel_ratio": narration["reel_ratio"],
            "gender": gender["value"],
            "gender_conf": gender["confidence"],
            "age": age["value"],
            "age_conf": age["confidence"],
            "content": content["value"],
            "content_conf": content["confidence"],
            "bio": (profile.get("biography") or "").replace("\n", " ")[:160],
            "verified": bool(profile.get("verified")),
            "hashtag": hashtag,
        })

    results.sort(key=lambda r: r["followers"], reverse=True)
    return {
        "results": results,
        "stats": {"posts": len(posts), "accounts": len(usernames), "matched": len(results)},
    }
