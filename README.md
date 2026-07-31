# Instagram Radar

Discover Instagram influencers by hashtag, filter them down, save candidates to
named lists, and export to CSV. Flask + SQLite, with a three-language UI.

[English](#english) · [中文](#中文) · [日本語](#日本語)

```
app.py            Flask routes, job handling, CSV export
radar_core.py     Apify fetching, inference, filtering
db.py             SQLite (jobs / results / lists)
templates/
  index.html      UI (English / 中文 / 日本語)
```

| Variable | Required | Purpose |
|---|---|---|
| `APIFY_API_TOKEN` | Yes | Fetching Instagram data |
| `ANTHROPIC_API_KEY` | No | AI brief box + better gender/content inference |
| `RADAR_DB` | No | Database path (default `./radar.db`) |

```bash
pip install -r requirements.txt
cp .env.example .env      # add your tokens
python app.py             # http://127.0.0.1:5000

# shared / multi-user
gunicorn -w 1 -k gthread -t 900 --threads 8 -b 0.0.0.0:8000 app:app
```

> **One worker only.** Search jobs run in a thread inside the process that
> started them, so with `-w 2+` a status poll can hit a worker that knows nothing
> about the job and the page spins forever.
>
> **No authentication.** Keep it behind a private network or VPN. The name field
> in the UI only records who added someone to a list.

---

## English

### Using it

1. **Search tab** — describe what you're looking for in plain language and press
   convert; the filters below fill in. Check and adjust, then run the search. You
   can also skip the AI box and fill the form directly.
2. **Results** — click any column header to sort. The refine bar filters the
   current results instantly without re-running the search (which costs money, so
   this matters). Save people with the `+` on a row, or tick several rows and use
   the bulk save button.
3. **Lists tab** — each saved person gets a status (New / Contacted / In talks /
   Approved / Passed) and a note. Both save as you type. CSV export is per list.

Everything lives in `radar.db` and survives a restart. To back up, copy that file.

### How much to trust each field

| Field | Type | Notes |
|---|---|---|
| Hashtag | Real | |
| Followers | Real | |
| Last post / active check | Real | |
| Engagement rate | Real | From the account's own recent posts |
| Narration | **Estimated** | Share of Reels using original audio; the audio itself isn't accessible |
| Gender | **Estimated** | From bio, display name, pronouns. Neutral bios → unknown |
| Age | **Estimated** | Only when stated in the bio — **most rows stay unknown** |
| Content | **Estimated** | Classified from captions and hashtags |

Estimated fields carry a confidence mark (■ high / ▪ medium / □ low / ⬚ unknown).
Anything low or unknown is a weak guess — open the account and check.

Filtering by age drops every account that doesn't state one, which cuts the pool
sharply. Filter on the real fields first; treat age and gender as reference
columns you verify by eye.

### Cost

Apify bills by usage: one hashtag scrape plus one profile fetch per account
found. The free tier is for trying it out. With `ANTHROPIC_API_KEY` set, one API
call fires per matching account — untick "Use AI inference" to avoid that.

---

## 中文

### 使用方式

1. **搜索标签页** — 用大白话写下要找什么，点转换，下面的条件表单自动填好。确认
   并修改后再执行搜索。也可以跳过 AI 输入框直接填表单。
2. **结果** — 点表头排序。上方筛选栏对当前结果即时生效，不重新跑搜索（跑一次要
   花钱，所以这点很实用）。点行尾 `+` 存单个人，或勾选多行批量保存。
3. **名单标签页** — 每个人可以标状态（待处理／已联系／洽谈中／已确定／已否决）
   和写备注，输入时自动保存。CSV 按名单导出。

所有数据存在 `radar.db` 里，重启不丢。备份就是复制这一个文件。

### 各字段的可信度

| 字段 | 类型 | 说明 |
|---|---|---|
| 话题标签 | 真实数据 | |
| 粉丝数 | 真实数据 | |
| 最后更新 / 活跃判断 | 真实数据 | |
| 互动率 | 真实数据 | 用博主主页的最新帖子计算 |
| 有无讲解 | **推断** | 看 Reel 使用原创音源的比例，拿不到音频本身 |
| 性别 | **推断** | 依据简介、昵称、代词。中性简介返回未知 |
| 年龄 | **推断** | 只有写在简介里才拿得到，**大部分是未知** |
| 内容方向 | **推断** | 从文案和话题标签分类 |

推断字段都带可信度标记（■ 高 / ▪ 中 / □ 低 / ⬚ 未知）。低和未知的是弱推断，
务必打开主页确认。

按年龄筛选会剔除所有没写年龄的账号，候选人会锐减。建议先用真实数据的字段筛，
年龄和性别当参考列人工过一遍。

### 成本

Apify 按用量计费：一次话题标签抓取 + 找到的每个账号各一次主页抓取。免费额度只
够试跑。配置了 `ANTHROPIC_API_KEY` 的话，每个符合条件的账号会调用一次 API，
想省这部分成本就取消勾选「启用 AI 推断」。

---

## 日本語

### 使い方

1. **検索タブ** — やりたいことを日本語で書いて「条件に変換」を押すと、下の
   フォームに条件が入る。確認・修正してから「検索する」。AI を使わず直接
   フォームに入力してもよい。
2. **結果** — 表のヘッダをクリックで並び替え。上の絞り込み欄はその場で効き、
   検索は再実行されない（1回の検索に費用がかかるので重要）。行の `+` か、
   チェックを入れて一括保存。
3. **リストタブ** — ステータス（未対応／連絡済／交渉中／採用／見送り）とメモを
   付けられる。入力すると自動保存。CSV 書き出しはリスト単位。

データはすべて `radar.db` に入り、再起動しても消えない。
バックアップはこのファイルをコピーするだけ。

### データの信頼度

| 項目 | 種別 | 備考 |
|---|---|---|
| ハッシュタグ | 実データ | |
| フォロワー数 | 実データ | |
| 最終投稿日 / アクティブ判定 | 実データ | |
| エンゲージメント率 | 実データ | 本人の最新投稿から算出 |
| ナレーション有無 | **推定** | Reel のオリジナル音源比率から判定。音声自体は取得できない |
| 性別 | **推定** | bio・表示名・代名詞から判定。中性的な bio は「不明」 |
| 年齢 | **推定** | bio に記載がある場合のみ。**大半は「不明」になる** |
| 投稿内容 | **推定** | キャプションとハッシュタグから分類 |

推定項目には確度マーク（■ 高 / ▪ 中 / □ 低 / ⬚ 不明）が付く。
低・不明のものは必ず本人のアカウントを開いて確認すること。

年齢で絞り込むと記載の無いアカウントが全て除外され、候補が大幅に減る。
まず実データの項目で絞り、年齢・性別は参考列として目視で確認する運用を推奨。

### コスト

Apify は従量課金。1回の検索で「ハッシュタグ検索 1回 + ヒットしたアカウント数
ぶんのプロフィール取得」が発生する。無料枠は試用向け。
`ANTHROPIC_API_KEY` を設定していると条件に合った1アカウントにつき1回 API を
呼ぶため、抑えたい場合は「AI 推定を使う」のチェックを外す。
