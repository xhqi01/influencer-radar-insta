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
| `RADAR_DB` | No | Database path (default `./radar.db`) |
| `HOST` / `PORT` | No | Bind address for shared deployment |

**The server holds no API tokens.** Each user pastes their own Apify token
(and optionally an Anthropic key) into the "API setup" dialog in the top-right
corner of the page. Tokens live only in that user's browser (localStorage) and
are sent per-request; the server never stores them. Search costs are billed to
each user's own Apify account — the operator only provides the service.
Serve over HTTPS when exposing beyond localhost, since tokens travel in request
headers.

```bash
pip install -r requirements.txt
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

Lists can live inside **folders** — e.g. a `2026 Q3 campaign` folder holding
`home workout women` and `protein men`. Create folders at the bottom left, and
move a list with the folder dropdown in the toolbar. Deleting a folder never
deletes its lists; they move back to Uncategorized.

**Database tab** — every account any search has ever fetched accumulates here
automatically, with the hashtags it appeared under, how many times it's been
seen, and a quality rating. Browsing and searching this tab costs **zero Apify
credit** — the tool builds your own influencer database as a side effect of
normal use. Click any account (here or in search results) for a detail panel:
follower trend chart built from your own observation history, quality red flags
(abnormally low ER, mass-following, follower spikes — heuristic signs of bought
followers, not proof), which lists they're in, and similar accounts from the
database ranked by shared hashtags and content overlap.

The search box above the folder tree looks across **every list at once**, by
account name or note, and shows which folder and list each person sits in. In
search results, anyone already saved shows a ✓ instead of a `+` — hover to see
which lists they're in, so you don't re-contact someone twice.

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
| Account type | Real data | Business / Creator / Personal |
| Verified | Real data | |
| Contact email | Real data | From the public email field or the bio |
| Sponsored posts | Real data | Official paid-partnership flag plus #PR / #ad tags |
| Avg Reel views | Real data | |
| Post count | Real data | |
| Follower growth | Real data | Built from this tool's own history — needs two searches on different days |
| Content | **Estimated** | Classified from captions and hashtags |
| Region | **Estimated** | Only when written in the bio |

**Not obtainable, by any method:** follower-side demographics — audience
geography, gender split, age range, interests, active rate. Instagram does not
publish these without the creator's own consent; commercial platforms get them
through paid partnerships with the platform or with creators. The filter panel
lists these explicitly as unavailable rather than showing dead inputs.

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

名单可以放进**文件夹**——比如一个「2026 Q3 活动」文件夹，里面放「居家健身女生」
和「蛋白粉男生」两个名单。左下角新建文件夹，用工具栏的下拉菜单把名单移进去。
删除文件夹不会删掉里面的名单，它们会回到未分类。

**数据库标签页** — 历次搜索抓到的每个账号都会自动积累在这里，带着它出现过的
话题标签、出现次数和质量评级。在这个页面浏览和搜索**不消耗任何 Apify 额度**——
正常使用的副产品就是一个越来越大的自有达人库。点任何账号（这里或搜索结果里）
会弹出详情面板：用自己观测历史画的粉丝趋势图、质量红旗（互动率异常低、大量关注、
粉丝暴涨——是买粉的启发式信号，不是证据）、所在名单、以及按共同标签和内容重合度
排序的类似账号。

文件夹树上方的搜索框是**跨所有名单**搜的，按账号名或备注找，会显示这个人在哪个
文件夹的哪个名单里。搜索结果里，已经存过的人显示 ✓ 而不是 `+`，鼠标悬停能看到
在哪几个名单里——避免重复联系同一个人。

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
| 账号类型 | 真实数据 | 企业号／创作者号／个人号 |
| 认证账号 | 真实数据 | |
| 联系邮箱 | 真实数据 | 取公开邮箱字段或简介里的邮箱 |
| 广告合作帖 | 真实数据 | 官方合作标记 + #PR／#ad 标签 |
| Reel 平均播放 | 真实数据 | |
| 发帖数 | 真实数据 | |
| 粉丝增长率 | 真实数据 | 由本工具自己积累的历史算出，需要隔天再搜一次才有 |
| 内容方向 | **推断** | 从文案和话题标签分类 |
| 地区 | **推断** | 只有写在简介里才有 |

**任何方法都拿不到的：** 粉丝侧画像——粉丝地区、男女比例、年龄层、兴趣、活跃率。
Instagram 不经创作者本人授权就不公开这些，商用平台是通过和平台或达人签约拿到的。
筛选面板里把这几项明确列成「拿不到」，而不是放几个点了没反应的输入框。

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

リストは**フォルダ**にまとめられる。例：「2026 Q3 キャンペーン」フォルダの中に
「宅トレ女子」「プロテイン男子」を入れる。フォルダは左下で作成し、ツールバーの
ドロップダウンでリストを移動する。フォルダを削除しても中のリストは消えず、
未分類に戻るだけ。

**データベースタブ** — 過去の検索で取得した全アカウントが自動でここに蓄積される。
出現したハッシュタグ、出現回数、品質評価つき。このタブの閲覧・検索は **Apify を
一切消費しない**。普段使いの副産物として、自前のインフルエンサーデータベースが
育っていく。アカウントをクリック（ここでも検索結果でも）すると詳細パネルが開く：
自前の観測履歴から描いたフォロワー推移グラフ、品質の危険信号（異常に低い ER・
大量フォロー・フォロワー急増——フォロワー買いの兆候を示すヒューリスティックで、
断定ではない）、入っているリスト、共通タグと内容の重なりで並べた類似アカウント。

フォルダツリー上部の検索欄は**全リスト横断**で、アカウント名やメモから探せる。
どのフォルダのどのリストに入っているかも表示される。検索結果では、すでに保存済みの
アカウントは `+` ではなく ✓ になり、ホバーでどのリストに入っているか確認できる。
同じ人に二重に連絡してしまうのを防げる。

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
| アカウントタイプ | 実データ | ビジネス／クリエイター／個人 |
| 認証アカウント | 実データ | |
| 連絡先メール | 実データ | 公開メール欄または bio 内のアドレス |
| PR・タイアップ投稿 | 実データ | 公式タイアップフラグ + #PR／#ad タグ |
| リール平均再生数 | 実データ | |
| 投稿数 | 実データ | |
| フォロワー成長率 | 実データ | 本ツール自身の履歴から算出。別日に2回検索して初めて出る |
| 投稿内容 | **推定** | キャプションとハッシュタグから分類 |
| 地域 | **推定** | bio に記載がある場合のみ |

**どんな方法でも取得できないもの：** フォロワー側の属性——地域構成・性別比・
年齢層・興味関心・アクティブ率。Instagram は本人の同意なしにこれらを公開しておらず、
商用プラットフォームはプラットフォームやクリエイターとの契約で入手している。
フィルター画面では、反応しない入力欄を並べるのではなく「取得できない項目」として
明示している。

推定項目には確度マーク（■ 高 / ▪ 中 / □ 低 / ⬚ 不明）が付く。
低・不明のものは必ず本人のアカウントを開いて確認すること。

年齢で絞り込むと記載の無いアカウントが全て除外され、候補が大幅に減る。
まず実データの項目で絞り、年齢・性別は参考列として目視で確認する運用を推奨。

### コスト

Apify は従量課金。1回の検索で「ハッシュタグ検索 1回 + ヒットしたアカウント数
ぶんのプロフィール取得」が発生する。無料枠は試用向け。
`ANTHROPIC_API_KEY` を設定していると条件に合った1アカウントにつき1回 API を
呼ぶため、抑えたい場合は「AI 推定を使う」のチェックを外す。
