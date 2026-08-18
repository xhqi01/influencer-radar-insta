# Instagram Radar

Find Instagram influencers by hashtag, filter candidates on real account
data, save people to shared named lists organized into folders, and export
to CSV. Every account any search touches also accumulates in a free,
browsable local database over time. Flask + SQLite, with an English /
中文 / 日本語 UI.

[English](#english) · [中文](#中文) · [日本語](#日本語)

---

## Quick start

```bash
git clone <this repo>
cd influencer-radar-insta
pip install -r requirements.txt
python app.py                      # http://127.0.0.1:5000
```

For a shared deployment, run it behind gunicorn (needs a long-lived
process — serverless platforms like Vercel won't work, since search jobs
run in background threads and the database is a local SQLite file):

```bash
gunicorn -w 1 -k gthread -t 900 --threads 8 -b 0.0.0.0:$PORT app:app
```

> **`-w 1` is required.** Search jobs run in a thread inside the process
> that started them. With 2+ workers, a status poll can land on a worker
> that knows nothing about the job, and the page spins forever.

The server holds no API tokens. Each user pastes their own Apify token
(required) and, optionally, an Anthropic key into the "API setup" dialog
in the top right. Tokens live only in that user's browser (localStorage)
and are sent per request; the server never stores them, and search costs
bill to each user's own Apify account. **Because tokens travel in request
headers, serve this over HTTPS in any deployment beyond localhost.**

There's no built-in authentication — put it behind a VPN, private network,
or reverse-proxy auth if it shouldn't be publicly reachable.

## Project layout

```
app.py            Flask routes, search job handling, CSV export
radar_core.py     Apify fetching, attribute inference, quality signals, filtering
db.py             SQLite (jobs / lists / folders / account index / follower history)
templates/
  index.html      Full UI (three languages, i18n included)
```

Everything lives in one `radar.db` file. Back it up by copying that file.
Search jobs older than 30 days are pruned automatically on startup; lists,
folders, and follower history (which growth-rate figures depend on) are
never touched.

---

## English

### What it does

Search Instagram by hashtag, filter candidates on real account data
(followers, engagement, account type, contact info, sponsored-post
history, and more), save people to shared named lists organized into
folders, and export to CSV. Every account any search has ever fetched also
accumulates in a browsable database that costs nothing to query — normal
use builds an influencer index as a side effect.

### Using it

1. **Search tab** — describe what you want in plain language and press
   "Convert to filters"; the form below fills in (needs your own Anthropic
   key, set in API setup). You can also skip that and fill the form
   directly. Fill in a hashtag, or paste up to 15 usernames under "Check
   specific accounts" to look up named accounts directly — that mode
   ignores every other filter, since naming someone means you want to see
   them.
2. **Results** — click a column header to sort. The refine bar above the
   table filters the current results instantly, without spending another
   search. Save one person with the row's `+`, or tick several rows and use
   the bulk-save button. A dot next to each row shows a quality read —
   hover it, or open the account, for what tripped it.
3. **Lists tab** — lists can sit inside folders (e.g. a "Q3 campaign"
   folder holding "home workout women" and "protein men"). Deleting a
   folder never deletes what's inside — its lists move back to
   Uncategorized. The search box above the folder tree searches every list
   at once, by name or note. Each saved person gets a status (New /
   Contacted / In talks / Approved / Passed) and a note, both saving as you
   type. Anyone already saved shows a ✓ instead of `+` in search results,
   so you don't double up.
4. **Database tab** — every account ever fetched, browsable and searchable
   for free. Click any account (here or in results) for a detail panel: a
   follower-trend chart built from this tool's own observation history,
   quality flags, which lists they're in, and similar accounts ranked by
   shared hashtags and content overlap.

### Field reliability

| Field | Type | Notes |
|---|---|---|
| Hashtag, followers, following | Real | |
| Last post / active check | Real | |
| Engagement rate | Real | From the account's own recent posts, not the hashtag-sourced ones (those skew high) |
| Account type, verified, post count | Real | |
| Contact email | Real | Public email field or an address found in the bio |
| Sponsored posts | Real | Official paid-partnership flag plus #PR / #ad style tags |
| Avg Reel views | Real | |
| Follower growth | Real | Built from this tool's own history — needs two searches on different days before it shows anything |
| Narration | **Estimated** | Share of Reels using original audio; the audio itself isn't accessible |
| Gender | **Estimated** | From bio, display name, pronouns — neutral bios resolve to unknown |
| Age | **Estimated** | Only when stated in the bio — most rows stay unknown |
| Content category | **Estimated** | Classified from captions and hashtags |
| Region | **Estimated** | Only when written in the bio |
| Quality flag (ok/caution/check) | **Heuristic** | Pattern-matching on public signals — see disclaimer below |

Estimated fields carry a confidence mark (■ high / ▪ medium / □ low / ⬚
unknown). Filtering by age or gender drops everything unresolved, which
cuts the pool hard — filter on real fields first, treat estimated ones as
a column you verify by eye before you rely on them.

**Not obtainable, by any method:** audience-side demographics — follower
geography, gender split, age range, interests, active rate. Instagram does
not expose these without the creator's own consent to a partnered
platform; no amount of scraping recovers them. The filter panel lists this
explicitly instead of showing inputs that quietly do nothing.

### Disclaimer

- **The quality flag is a heuristic, not a finding.** It looks for public
  patterns associated with bought or inflated followers (engagement far
  below what the follower count would predict, unusually high following
  count, a thin follower-to-following ratio, very few posts for the
  follower count, a sudden spike in this tool's own growth history). None
  of these individually or together prove an account is fake, and a clean
  score doesn't prove it's genuine — audience-level data that would settle
  this isn't accessible to any outside tool. Treat it as "worth a closer
  look," not as a verdict.
- **Estimated fields (gender, age, content, region, narration) are
  inferences**, not facts reported by the account holder. They can be
  wrong, especially at low/unknown confidence. Don't use them as the sole
  basis for outreach decisions where getting it wrong has a real cost.
- **This tool scrapes public Instagram data via Apify.** Confirm this fits
  your own data-use policies and Instagram's terms of service before
  relying on it for business decisions; this project makes no
  representation about the legality or compliance of that use in your
  jurisdiction.
- **No warranty.** Provided as-is. Data accuracy depends entirely on what
  Instagram exposes and what Apify's actors return — verify anything
  before it goes into a contract, a brief, or a payment.
- **The server holds no tokens and takes no responsibility for usage
  costs.** Each user's Apify (and optional Anthropic) spend is billed to
  their own account under their own responsibility.

### Cost

Apify bills by usage: one hashtag scrape plus one profile fetch per
account found. The free tier is for trying it out. With an Anthropic key
set, one API call fires per matching account for AI-assisted inference —
untick "Use AI inference" to skip that cost.

---

## 中文

### 这个工具做什么

按话题标签搜索 Instagram，用真实账号数据筛选候选人（粉丝数、互动率、账号
类型、联系方式、广告合作历史等），把人存进按文件夹分组的共享名单，导出
CSV。历次搜索抓到的每个账号还会自动积累成一个可免费浏览的数据库——正常
使用的副产品就是越来越大的达人索引。

### 使用方式

1. **搜索标签页** — 用大白话描述需求，点"转换为条件"（需要在 API 设置里填
   自己的 Anthropic 密钥），下面表单自动填好；也可以跳过直接填表单。填话题
   标签搜索，或者在"直接查指定账号"里填最多15个用户名——这个模式会忽略所有
   其他筛选条件，因为指名要看的人就该出现在结果里。
2. **结果** — 点表头排序。上方筛选栏对当前结果即时生效，不重新花钱搜索。
   点行尾 `+` 存单人，或勾选多行批量保存。每行的小圆点是质量提示，鼠标悬停
   或点进账号详情看具体触发了什么。
3. **名单标签页** — 名单可以放进文件夹（比如"Q3 活动"文件夹装"居家健身
   女生"和"蛋白粉男生"）。删除文件夹不会删掉里面的名单，会回到未分类。
   文件夹树上方的搜索框跨所有名单搜，按名字或备注。每个存过的人有状态
   （待处理／已联系／洽谈中／已确定／已否决）和备注，输入即自动保存。搜索
   结果里已存过的人显示 ✓ 而不是 `+`，避免重复联系。
4. **数据库标签页** — 历次抓到的所有账号，免费浏览搜索。点任何账号（这里
   或搜索结果里）弹出详情：自己观测历史画的粉丝趋势图、质量信号、所在名单、
   按共同标签和内容重合度排的类似账号。

### 各字段可信度

| 字段 | 类型 | 说明 |
|---|---|---|
| 话题标签、粉丝数、关注数 | 真实数据 | |
| 最后更新 / 活跃判断 | 真实数据 | |
| 互动率 | 真实数据 | 用博主主页最新帖子算，不用话题标签抓到的帖子（那些偏高） |
| 账号类型、认证、发帖数 | 真实数据 | |
| 联系邮箱 | 真实数据 | 公开邮箱字段或简介里找到的地址 |
| 广告合作帖 | 真实数据 | 官方合作标记 + #PR／#ad 类标签 |
| Reel 平均播放 | 真实数据 | |
| 粉丝增长率 | 真实数据 | 靠本工具自己的历史算出，得隔天再搜一次才有 |
| 有无讲解 | **推断** | Reel 用原创音源的比例，拿不到音频本身 |
| 性别 | **推断** | 依据简介、昵称、代词，中性简介归未知 |
| 年龄 | **推断** | 只有简介写了才有，大部分是未知 |
| 内容方向 | **推断** | 从文案和话题标签分类 |
| 地区 | **推断** | 只有简介写了才有 |
| 质量标记（正常/注意/需核查） | **启发式** | 基于公开信号的模式匹配，见下方免责声明 |

推断字段带可信度标记（■高／▪中／□低／⬚未知）。按年龄或性别筛选会剔除所有
没判断出来的账号，候选人会锐减——建议先用真实数据字段筛，推断字段当参考列
人工核实。

**任何方法都拿不到的：** 粉丝侧画像——地区、性别比、年龄层、兴趣、活跃率。
Instagram 不经创作者本人授权、不对接入合作的平台开放这些数据，爬虫路线永远
拿不到。筛选面板明确列出这一点，而不是放几个点了没反应的输入框。

### 免责声明

- **质量标记是启发式判断，不是结论。** 它寻找的是公开数据里和买粉/刷量相关
  的常见模式（互动率远低于粉丝数该有的水平、关注数异常多、粉丝/关注比偏低、
  发帖极少但粉丝很多、本工具自己观测到的历史里出现过异常暴涨）。这些信号
  单独或加在一起都不能证明一个账号是假的，标记"正常"也不能证明它是真的——
  真正能一锤定音的粉丝级数据，任何外部工具都拿不到。把它当作"值得多看一眼"，
  不是"判决"。
- **推断字段（性别、年龄、内容方向、地区、有无讲解）是推测**，不是账号本人
  申报的事实，可信度低或未知时尤其可能出错。涉及实际成本的外联决策，不要
  只靠这些字段做判断。
- **这个工具通过 Apify 抓取 Instagram 公开数据。** 用它做商业决策之前，请自行
  确认这符合你自己的数据使用规范和 Instagram 的服务条款；本项目不对这种
  使用在你所在司法辖区的合法性或合规性做任何保证。
- **不提供任何担保。** 按现状提供。数据准确性完全取决于 Instagram 公开了
  什么、Apify 的抓取程序返回了什么——任何要写进合同、brief 或者涉及付款的
  信息，用之前请自行核实。
- **服务器不存任何 token，也不为使用产生的费用负责。** 每个人的 Apify（和可选
  的 Anthropic）花费记在各自账户下，由各自负责。

### 成本

Apify 按用量计费：一次话题标签抓取 + 找到的每个账号各一次主页抓取。免费额度
只够试用。配置了 Anthropic 密钥的话，AI 辅助推断每个匹配账号会调用一次 API，
想省这部分就取消勾选"启用 AI 推断"。

---

## 日本語

### このツールでできること

ハッシュタグで Instagram を検索し、実データ（フォロワー数、エンゲージメント率、
アカウントタイプ、連絡先、PR投稿履歴など）で絞り込み、フォルダ分けした共有
リストに保存し、CSV に書き出す。過去の検索で取得した全アカウントは無料で
閲覧・検索できるデータベースとして自動的に蓄積されていく——普段使いの
副産物としてインフルエンサー索引が育つ。

### 使い方

1. **検索タブ** — やりたいことをそのまま書いて「条件に変換」を押す（API設定
   で自分の Anthropic キーが必要）。下のフォームに自動で入る。使わず直接
   フォームに入力してもよい。ハッシュタグを入れるか、「特定アカウントを
   直接チェック」に最大15件のユーザー名を入れると、その人たちだけを直接
   取得する——このモードは他の全フィルタを無視する。指名した人は必ず見たい
   はずだから。
2. **結果** — 表のヘッダをクリックで並び替え。上の絞り込み欄はその場で効き、
   検索を再実行しない（1回ごとに費用がかかるので重要）。行の `+` で個別保存、
   チェックを入れて一括保存も可能。各行の丸印は品質の目安——ホバーするか
   アカウント詳細を開くと何が引っかかったか分かる。
3. **リストタブ** — リストはフォルダにまとめられる（例：「Q3 キャンペーン」
   フォルダに「宅トレ女子」「プロテイン男子」）。フォルダを削除しても中の
   リストは消えず、未分類に戻るだけ。フォルダツリー上の検索欄は全リスト
   横断で、名前やメモから探せる。保存した人にはステータス（未対応／連絡済／
   交渉中／採用／見送り）とメモが付けられ、入力すると自動保存。検索結果では
   保存済みの人が `+` ではなく ✓ になり、二重連絡を防げる。
4. **データベースタブ** — 過去に取得した全アカウントを無料で閲覧・検索。
   アカウントをクリック（ここでも検索結果でも）すると詳細パネルが開く：
   自前の観測履歴から描いたフォロワー推移グラフ、品質シグナル、入っている
   リスト、共通タグと内容の重なりで並べた類似アカウント。

### データの信頼度

| 項目 | 種別 | 備考 |
|---|---|---|
| ハッシュタグ、フォロワー数、フォロー数 | 実データ | |
| 最終投稿日 / アクティブ判定 | 実データ | |
| エンゲージメント率 | 実データ | 本人の最新投稿から算出（ハッシュタグ経由の投稿は使わない。伸びた投稿に偏るため） |
| アカウントタイプ、認証、投稿数 | 実データ | |
| 連絡先メール | 実データ | 公開メール欄または bio 内で見つけたアドレス |
| PR・タイアップ投稿 | 実データ | 公式タイアップフラグ + #PR／#ad 系タグ |
| リール平均再生数 | 実データ | |
| フォロワー成長率 | 実データ | 本ツール自身の履歴から算出。別日に2回検索して初めて値が出る |
| ナレーション有無 | **推定** | Reel のオリジナル音源比率から判定。音声自体は取得できない |
| 性別 | **推定** | bio・表示名・代名詞から判定。中性的な bio は「不明」 |
| 年齢 | **推定** | bio に記載がある場合のみ。大半は「不明」になる |
| 投稿内容 | **推定** | キャプションとハッシュタグから分類 |
| 地域 | **推定** | bio に記載がある場合のみ |
| 品質マーク（問題なし／注意／要確認） | **ヒューリスティック** | 公開情報のパターン照合。下の免責事項を参照 |

推定項目には確度マーク（■高／▪中／□低／⬚不明）が付く。年齢や性別で絞り込むと
未判定の全アカウントが除外され候補が大幅に減る——まず実データの項目で絞り、
推定項目は参考として目視確認する運用を推奨。

**どんな方法でも取得できないもの：** フォロワー側の属性——地域構成・性別比・
年齢層・興味関心・アクティブ率。Instagram は本人の同意なしにこれらを提携先
プラットフォームにすら公開しておらず、どんな取得方法でも復元できない。
フィルター画面では、反応しない入力欄を並べるのではなく明示的に「取得できない
項目」として示している。

### 免責事項

- **品質マークはヒューリスティック（経験則）であり、結論ではない。** 公開データ
  から読める、フォロワー買いや水増しと関連しやすいパターン（フォロワー数に
  対してエンゲージメント率が異常に低い、フォロー数が異常に多い、フォロワー／
  フォロー比が薄い、フォロワー数のわりに投稿が極端に少ない、本ツール自身の
  観測履歴で急なフォロワー急増が見られる）を探しているだけ。単独でも組み
  合わせでも、それがアカウントの不正を証明するものではなく、「問題なし」の
  表示もアカウントが健全であることの証明にはならない——それを確定させる
  フォロワー個人単位のデータは、どんな外部ツールにも取得できない。「一応
  確認する価値がある」程度の材料として扱い、結論として使わないこと。
- **推定項目（性別・年齢・投稿内容・地域・ナレーション有無）は推測であり**、
  本人が申告した事実ではない。確度が低い／不明のものは特に外れやすい。実際
  のコストが発生する外部への連絡判断を、これらの項目だけを根拠に行わないこと。
- **本ツールは Apify 経由で Instagram の公開データを取得している。** 業務判断に
  用いる前に、自身のデータ利用ポリシーおよび Instagram の利用規約に適合する
  ことを各自で確認すること。本プロジェクトは、利用者の所在地における当該
  利用の適法性・コンプライアンスについて一切保証しない。
- **無保証で提供される。** 現状有姿（as-is）で提供する。データの正確性は
  Instagram が公開している内容と Apify の取得結果に完全に依存する——契約・
  ブリーフ・支払いに関わる情報は、使用前に必ず自分で裏取りすること。
- **サーバーはトークンを一切保持せず、利用に伴う費用についても責任を負わない。**
  各利用者の Apify（および任意で使う Anthropic）の利用料は、各自のアカウントに
  それぞれの責任で課金される。

### コスト

Apify は従量課金。1回の検索で「ハッシュタグ検索1回 + ヒットしたアカウント数
ぶんのプロフィール取得」が発生する。無料枠は試用向け。Anthropic キーを設定
していると、AI 推定で条件に合った1アカウントにつき1回 API を呼ぶ。抑えたい
場合は「AI 推定を使う」のチェックを外す。
