# Instagram Radar

Find Instagram influencers by hashtag, filter candidates on real account
data, save people to shared named lists organized into folders, and export
to CSV. Accounts and workgroups are built in, so a team can register,
create a shared workspace, and collaborate on the same lists. Every
account any search touches also accumulates in a free, browsable local
database over time. Flask + SQLite, with an English / 中文 / 日本語 UI.

[English](#english) · [中文](#中文) · [日本語](#日本語)

---

## What's new in this version ｜ 本次更新 ｜ 今回の更新

**EN** — Accounts & workgroups: username/password login (30-day sessions),
groups with one-click-copy invite codes, lists/folders strictly isolated per
group (search history and result exports too), the first group created adopts
pre-groups legacy data, and users in no group see and touch nothing. Search now
requires an active group. Multi-hashtag search (up to 5 tags) with union /
intersect modes, wired into the AI brief parser. Profile avatars in results,
database, and detail panel, with automatic letter fallback for expired image
URLs. CSV gains a matched-hashtags column. Fixed: a login bug where the session cookie's Secure flag, combined with
how Render's reverse proxy reports HTTPS, silently prevented the browser
from keeping the cookie — registering or logging in appeared to do nothing.
Also fixed: Apify SDK 3.x Run-object
compatibility, and pipeline diagnostics that name the exact filter that zeroed
out a search.

**中文** — 账号与工作小组：用户名/密码登录（会话保持30天）、小组邀请码一键复制、
名单/文件夹按组严格隔离（搜索历史和结果导出同样隔离）、第一个创建的小组自动接收
旧数据、未加入小组的用户什么都看不到也改不了。搜索现在要求先加入小组。多标签
搜索（最多5个）支持并集/交集两种模式，AI 自由文解析也会自动判断用哪种。搜索
结果、数据库、详情面板均显示头像，图片链接失效时自动退化为首字母占位。CSV 新增
"匹配标签"列。修复：登录 cookie 的 Secure 标记和 Render 反向代理上报 HTTPS 的方式
对不上，导致浏览器悄悄丢弃登录 cookie——表现为点注册或登录后像是没反应。
另外还修复了 Apify SDK 3.x 的 Run 对象兼容性、以及能精确指出是哪个筛选条件把结果清零的诊断日志。

**日本語** — アカウントとワークグループ：ユーザー名／パスワードによるログイン
（セッション30日保持）、ワンクリックでコピーできる招待コード、リスト／フォルダの
グループ単位での厳格な分離（検索履歴と結果エクスポートも同様）、最初に作られた
グループによる旧データの自動引き取り、グループ未所属ユーザーは何も見えず何も
触れない設計。検索はグループ所属が必須になった。複数ハッシュタグ検索（最大5個）
は和集合／積集合の2モードに対応し、AI 自由文解析でも自動判定される。検索結果・
データベース・詳細パネルにアバターを表示し、画像 URL の期限切れ時は頭文字の
プレースホルダに自動で切り替わる。CSV に「マッチしたハッシュタグ」列を追加。
修正：リバースプロキシ配下でのログイン Cookie 問題（ProxyFix + 明示的な資格情報
送信）、Apify SDK 3.x の Run オブジェクト互換性、どの絞り込み条件で結果がゼロに
なったかを特定できる診断ログ。

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

The server holds no Apify or Anthropic API tokens. Each user pastes their
own Apify token (required) and, optionally, an Anthropic key into the "API
setup" dialog in the top right. Tokens live only in that user's browser
(localStorage) and are sent per request; the server never stores them,
and search costs bill to each user's own Apify account. **Because tokens
travel in request headers, serve this over HTTPS in any deployment beyond
localhost.**

Login sessions are signed with a key stored in the database (or set
`SECRET_KEY` as an env var to pin it yourself). Registration is open to
anyone who can reach the URL — there's no invite-only signup gate — but a
new account starts in no workgroup and can't see anyone's data until
someone shares an invite code with them (see Workgroups below).

## Project layout

```
app.py            Flask routes, auth, search job handling, CSV export
radar_core.py     Apify fetching, attribute inference, quality signals, filtering
db.py             SQLite (users / groups / jobs / lists / folders / account index / follower history)
templates/
  index.html      Full UI (three languages, i18n included)
```

Everything lives in one `radar.db` file. Back it up by copying that file.
Search jobs older than 30 days are pruned automatically on startup; users,
groups, lists, folders, and follower history (which growth-rate figures
depend on) are never touched.

---

## English

### What it does

- **Hashtag search**, with up to 5 tags at once and a choice between
  **union** (anyone who posted under any of the tags) and **intersect**
  (only accounts with posts under every tag — narrower, more targeted).
  An AI box also converts a plain-language brief into the filter form,
  including picking union vs. intersect from phrasing like "posts about
  A and B" vs. "either A or B."
- **Direct account lookup** — paste up to 15 usernames to check specific
  people instead of discovering new ones; this mode ignores every other
  filter, since naming someone means you want to see them regardless of
  follower count or activity.
- **Filtering on real account data**: followers, following, engagement
  rate (computed from the account's own recent posts, not the ones
  sourced from the hashtag search, which skew high), last-active date,
  account type, verified status, contact email, sponsored-post history,
  average Reel views, and post count.
- **Estimated attributes** (gender, age, content category, region,
  narration) with a confidence mark and, optionally, AI-assisted
  inference — see the reliability table below for what's real vs. guessed.
- **Quality flag** — a heuristic pattern-match on public signals (see
  Disclaimer) shown as a colored dot per row, with the specific signals
  that tripped it visible in the account detail panel.
- **Avatars** — every result and database row shows the account's
  profile picture; expired or blocked image links fall back to a
  letter placeholder automatically.
- **Sortable results table** with an instant refine bar (filters the
  current results without spending another search) and bulk or
  single-row save.
- **Lists and folders** — save people to named lists, group lists into
  folders, move lists between folders, and search across every list at
  once by name or note. Each saved person gets a status (New / Contacted
  / In talks / Approved / Passed) and a note, both saving as you type.
  Anyone already saved shows a ✓ instead of `+` in search results, and
  an "exclude already-saved" toggle keeps repeat searches from
  resurfacing people you've already logged.
- **Accumulating account database** — every account any search has ever
  fetched, browsable and searchable for free (zero Apify cost). Each
  entry tracks how many hashtags it's been seen under, how many times,
  and a follower-trend chart built from your own observation history
  (needs at least two searches on different days to show anything).
  Clicking any account opens a detail panel with similar accounts ranked
  by shared hashtags and content overlap.
- **CSV export**, per search job or per list, with a matched-hashtags
  column when a multi-tag search was used.
- **Accounts and workgroups** — register with a username and password;
  create a workgroup or join one with an invite code. Lists and folders
  are scoped to the active workgroup and invisible to anyone outside it;
  the accumulated account database and follower history are shared by
  everyone (they're public Instagram data, not any one group's work
  product). A person can belong to multiple groups and switch between
  them from the top bar. The invite code lives in the group management
  dialog, copyable with one click. The first workgroup ever created on a
  given deployment automatically adopts any lists and folders that
  existed before workgroups were introduced, so upgrading an existing
  deployment doesn't strand old data.
- **Three-language UI** (English / 中文 / 日本語), switchable anytime
  from the top bar, including AI-generated content like inferred content
  categories.

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
- **There's no invite-only signup gate and no rate limiting on login.**
  Anyone who can reach the URL can create an account, though a fresh
  account can't see any group's data without an invite code. Treat the
  URL as semi-private, or put a reverse proxy in front, if that's not
  acceptable for your deployment.

### Cost

Apify bills by usage: one hashtag scrape plus one profile fetch per
account found. The free tier is for trying it out. With an Anthropic key
set, one API call fires per matching account for AI-assisted inference —
untick "Use AI inference" to skip that cost.

---

## 中文

### 这个工具做什么

- **话题标签搜索**，一次最多输入5个标签，可选**并集**（任一标签下发过帖就算）
  或**交集**（每个标签下都发过帖的人才算，范围更窄更精准）。AI 输入框能把大白话
  需求转换成筛选表单，包括根据"发过A和B"还是"A或B都行"这类措辞自动判断该用
  并集还是交集。
- **直接查指定账号** — 填最多15个用户名，直接查这些人而不是发现新账号；这个
  模式会忽略其他所有筛选条件，因为指名要看的人就该出现，不管粉丝数或活跃度。
- **基于真实账号数据筛选**：粉丝数、关注数、互动率（用账号自己最新的帖子算，
  不用话题标签抓到的帖子，那些数据偏高）、最后活跃时间、账号类型、认证状态、
  联系邮箱、广告合作历史、Reel 平均播放、发帖数。
- **推断属性**（性别、年龄、内容方向、地区、有无讲解），带可信度标记，可选
  AI 辅助推断——具体哪些是真实数据、哪些是推测，见下方可信度表格。
- **质量标记** — 基于公开信号的启发式模式匹配（见免责声明），每行显示成一个
  彩色圆点，具体触发了哪些信号可以在账号详情面板里看到。
- **头像** — 搜索结果和数据库里每一行都显示账号头像；图片链接过期或被拦截时
  自动切换成显示首字母的占位图。
- **可排序的结果表**，配合即时筛选栏（对当前结果生效，不用重新花钱搜索），
  支持批量或单条保存。
- **名单和文件夹** — 把人存进有名字的名单，名单可以归进文件夹，名单能在文件夹
  间移动，还能跨所有名单一次性按名字或备注搜索。每个存过的人有状态（待处理／
  已联系／洽谈中／已确定／已否决）和备注，输入即自动保存。搜索结果里已存过的
  人显示 ✓ 而不是 `+`；"排除已保存"开关能让重复搜索不再冒出已经记录过的人。
- **持续积累的账号数据库** — 历次搜索抓到的每个账号都会免费存下来（不消耗
  Apify 额度），可浏览可搜索。每条记录追踪它出现过几个标签、出现过几次，还有
  用自己观测历史画的粉丝趋势图（至少要隔天搜两次才会出数据）。点开任意账号会
  弹出详情面板，包含按共同标签和内容重合度排序的类似账号。
- **CSV 导出**，可按单次搜索或按名单导出，多标签搜索时会带一列"匹配到的标签"。
- **账号与工作小组** — 用用户名和密码注册；创建工作小组，或者用邀请码加入别人
  的小组。名单和文件夹按当前所在的小组隔离，组外的人完全看不到；但积累的账号
  数据库和粉丝历史是全体共享的（那是公开的 Instagram 数据，不是某个小组的
  工作成果）。一个人可以属于多个小组，在顶栏随时切换。邀请码在小组管理弹窗里，
  一键复制。**系统里第一个被创建的小组会自动接收小组功能上线之前就存在的
  名单和文件夹**，所以给已经在用的部署升级不会丢老数据。
- **三语界面**（English／中文／日本語），顶栏随时切换，包括 AI 生成的内容
  分类等推断结果也会跟着语言切换。

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
- **注册没有邀请码门槛，登录也没有防暴力破解限速。** 只要能访问到这个网址，
  任何人都能注册账号——不过新注册的账号在拿到邀请码之前看不到任何小组的
  数据。如果这个开放程度不符合你的部署场景，可以把网址当半私密处理，或者
  在前面加一层反向代理限制访问。

### 成本

Apify 按用量计费：一次话题标签抓取 + 找到的每个账号各一次主页抓取。免费额度
只够试用。配置了 Anthropic 密钥的话，AI 辅助推断每个匹配账号会调用一次 API，
想省这部分就取消勾选"启用 AI 推断"。

---

## 日本語

### このツールでできること

- **ハッシュタグ検索**、一度に最大5個のタグを指定でき、**和集合**（どれか1つの
  タグに投稿があれば対象）と**積集合**（全タグに投稿がある人だけ。より絞られて
  精度が高い）を切り替えられる。AI 入力欄は自由文の要望をそのままフィルター
  フォームに変換し、「AもBも投稿してる人」「AかBどちらでもいい」のような
  言い回しから和集合／積集合も自動で判定する。
- **特定アカウントの直接チェック** — 最大15件のユーザー名を入力して、新規発掘
  ではなく指名した人だけを直接取得する。このモードは他の全フィルタを無視する
  ——指名した人はフォロワー数や活動状況に関わらず必ず見たいはずだから。
- **実データによる絞り込み**：フォロワー数、フォロー数、エンゲージメント率
  （本人の最新投稿から算出。ハッシュタグ経由で拾った投稿は伸びた投稿に偏る
  ため使わない）、最終活動日、アカウントタイプ、認証状態、連絡先メール、
  PR・タイアップ投稿履歴、リール平均再生数、投稿数。
- **推定属性**（性別・年齢・投稿内容・地域・ナレーション有無）に確度マーク付き。
  AI による推定補正も任意で利用可能——どこまでが実データでどこからが推測かは
  下記の信頼度表を参照。
- **品質マーク** — 公開情報のパターン照合によるヒューリスティック（下記免責
  事項を参照）を色付きドットで各行に表示。具体的にどの信号が引っかかったかは
  アカウント詳細パネルで確認できる。
- **アバター** — 検索結果とデータベースの各行にプロフィール画像を表示。画像
  URL が期限切れ・ブロックされている場合は自動的に頭文字のプレースホルダに
  切り替わる。
- **並び替え可能な結果表**と即時絞り込みバー（現在の結果に即座に効き、検索を
  再実行しない＝再課金しない）、一括・個別保存に対応。
- **リストとフォルダ** — 名前付きリストに保存し、リストをフォルダにまとめ、
  フォルダ間で移動でき、全リストを横断して名前やメモで検索できる。保存した
  人にはステータス（未対応／連絡済／交渉中／採用／見送り）とメモが付けられ、
  入力すると自動保存。検索結果では保存済みの人が `+` ではなく ✓ になり、
  「保存済みを除外」を有効にすれば再検索で同じ人が何度も出てくるのを防げる。
- **蓄積型アカウントデータベース** — 過去の検索で取得した全アカウントが無料
  （Apify 消費ゼロ）で閲覧・検索できる形で自動蓄積される。各アカウントは何個
  のハッシュタグで何回見つかったかを記録し、自前の観測履歴から描いたフォロワー
  推移グラフも持つ（別日に2回以上検索して初めてグラフが出る）。任意のアカウント
  をクリックすると、共通タグと内容の重なりで並べた類似アカウントを含む詳細
  パネルが開く。
- **CSV エクスポート**、検索ジョブ単位・リスト単位のどちらも可能。複数タグで
  検索した場合は「マッチしたハッシュタグ」列も付く。
- **アカウントとワークグループ** — ユーザー名とパスワードで登録し、ワークグループ
  を作成するか招待コードで参加する。リストとフォルダはアクティブなグループに
  限定され、グループ外からは一切見えない。一方、蓄積されるアカウントデータベース
  とフォロワー履歴は全員で共有される（公開の Instagram データであり、特定
  グループの成果物ではないため）。1人が複数グループに所属し、トップバーから
  いつでも切り替え可能。招待コードはグループ管理ダイアログにあり、ワンクリック
  でコピーできる。**そのデプロイで最初に作られたワークグループは、グループ機能
  導入前から存在していたリストとフォルダを自動的に引き取る**ため、既存の
  デプロイをアップグレードしても古いデータが迷子にならない。
- **3言語 UI**（English／中文／日本語）、トップバーからいつでも切り替え可能。
  AI が生成する内容分類などの推定結果も切り替えた言語に追従する。

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
- **登録に招待コードのゲートは無く、ログインにもブルートフォース対策の
  レート制限は無い。** URL にアクセスできれば誰でもアカウントを作成できる
  （ただし新規アカウントは招待コードを受け取るまでどのグループのデータも
  見えない）。この開放度がデプロイ環境に合わない場合は、URL を半非公開として
  扱うか、手前にリバースプロキシでアクセス制限を掛けること。

### コスト

Apify は従量課金。1回の検索で「ハッシュタグ検索1回 + ヒットしたアカウント数
ぶんのプロフィール取得」が発生する。無料枠は試用向け。Anthropic キーを設定
していると、AI 推定で条件に合った1アカウントにつき1回 API を呼ぶ。抑えたい
場合は「AI 推定を使う」のチェックを外す。
