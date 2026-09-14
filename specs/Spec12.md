# ArtiControlNet Spec 12：个人作品风格 Wiki（风格生成 Block + 手动编辑）

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：在「我的作品」页顶部新增一块**「个人作品风格」Block** —— 它展示该用户在 `wiki` 表里的**「个人作品风格」**（主，正文字号）与**「上次更新前的个人作品风格」**（次，小字号）；用户可点**「基于我的新作品更新风格」**按钮，把**尚未纳入过风格的生成/绘图作品的 prompt** 提取出来，连同**原有风格**一起送 DeepSeek 纯文本 API 做**风格合并**，产出新风格写回；也可在页面上**直接手动编辑**风格并提交，手动覆盖前的旧风格同样落到「上次更新前」。
> 本 Spec 是 **Spec.md / Spec2~11 的增量补充**，不推翻原有架构。数据库变化：**新增 `wiki` 表**（每用户一行，存当前风格 + 上次更新前风格）+ **`images` 表新增 `wiki_used` 列**（该作品是否已纳入过风格，Spec5 作品库的增量）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 Spec2 的本地单文件 SQLite `artcn.db` 外无其他数据库。LLM 复用**既有 DeepSeek 纯文本通道**（`providers.deepseek.chat_text`，模型 `MODEL_NAME` = `deepseek-v4-flash`，即 Supervisor 路由用的那个），**不新增 provider、不新增模型、不新增依赖**。

---

## 1. 功能目的

- **让"个人作品风格"成为一个可积累的资产**：用户每生成/绘制一批新图，作品库里堆的是离散的 prompt；Spec12 把这堆散落的文字**沉淀成一段连贯的风格自述**，存在 Wiki 表里，之后无论用户自己回顾、还是未来做风格化生成，都有一个稳定的文本锚点。
- **"上次更新前的风格"给用户一条回退视线**：风格是被 LLM 合并重写过的，用户会想知道"我改之前长什么样"。用小字号并排展示前一版，比放在历史记录里更直观——**它是次要信息，所以不抢占主视觉**。
- **只吃"新料"**：更新风格时**不重算全部作品**，只提取**从未参与过合并**的作品文字（`images.wiki_used = 0`）。这样反复点更新是**增量**的，不会把同一批旧 prompt 一遍遍重复灌进风格里；`wiki_used` 这个标记就是增量的账本。
- **上传作品不掺和**：个人上传（`source='upload'`）没有 prompt（Spec5 §5.3 规定上传的 `prompt` 为 NULL），提取时**直接跳过**，并**直接视为已考虑**——否则任何传过图的用户都会永远剩下几张"未用于更新"的图，导致警告形同虚设、且更新按钮再也无法正常触发。
- **手动编辑是逃生口**：LLM 合并出来的风格不一定合用户心意（用词、侧重、颗粒度都可能别扭）。用户能**就地改**，改完提交即生效，且**旧版同样落进「上次更新前」**——与按钮更新走同一套"新旧交替"的语义，不搞两套。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 「所有作品已全部考虑到」的判定口径 | **不存在"待考虑作品"时触发**。待考虑作品 = `source ∈ {generate, edit}` 且 `wiki_used = 0` | 作者原话是"如果没有'已用于更新'则警告"，按字面会让"一张都没用过"的用户被警告并在原地卡死（永远无法更新），与警告文案「所有作品已全部考虑到」的语义正好相反。按文案取义：**没有新东西可考虑**才警告 |
| 上传作品（`source='upload'`） | **跳过提取，且在更新时一并标记为「已用于更新」** | 作者拍板。上传作品 `prompt` 为 NULL，本就提不出文字；若让它永远挂着"未用于更新"，任何传过图的用户都再也不会看到"全部已考虑到"的提示，判定形同虚设 |
| 首次更新（`wiki.style` 为空） | **走独立的「首次生成」分支**：换一份系统提示词 + 用户提示词只给「新提取的作品风格参考文字：…」 | 作者拍板。把空串塞进「个人作品风格：」冒号后面会让模型输出元话语（如"原有风格为空，我为你归纳"）或直接返回空 |
| 调用方式 | **同步接口** `POST /api/wiki/style/refresh`，后端 `await deepseek.chat_text(...)` 后直接返回 | 作者拍板。这是"点一下等几秒"的轻量操作，与 `/api/admin/*` 那类同步端点同构；复用 `task_queue` 要多一套任务状态机 + 前端轮询，语义不匹配 |
| 「是否用于更新个人Wiki」的前端露出 | **完全不露出** | 作者拍板。`wiki_used` 纯粹是后端增量账本，页面上不加角标、不可切换；用户只需看到"风格变了"这个结果 |
| Wiki 表形态 | **每用户一行的宽表** `wiki(user_id PK, style, prev_style, …)`，不做 key-value | 全库既有风格都是"每实体一行"（`usage` / `images` / `posts`）；风格是**成对**出现的两个字段（当前 / 上次更新前），宽表比 `app_meta` 式键值表少一次拼接、少一次解析 |
| 表名 | `wiki`（端点前缀 `/api/wiki`） | 作者原话"数据库设计一个Wiki表"；表名与端点前缀一致，和 Spec11 的"以资源命名"口径相同 |
| 「上次更新前」的写入时机 | **仅在 LLM 成功返回后**，与写新风格同一事务：`prev_style ← 旧 style`，`style ← 新风格` | 避免"旧风格已被挪走、新风格没生成出来"的中间态把用户唯一的一份风格弄丢 |
| 被截断丢弃的作品是否标记为已用 | **不标记**，保持 `wiki_used = 0` | 只有**真正进了这次合并**的作品才算"被考虑过"。若把因超长被丢弃的也标记成已用，等于悄悄吞掉用户的作品、下次再也补不回来 |
| 手动编辑的确认强度 | `window.confirm` **一次**（与 Spec11 清零、Spec9 撤销分享同构） | 提交会**覆盖当前风格**且旧版只能通过"上次更新前"这一格找回（再存一次就没了），属于准不可逆操作；但不至于要输入关键字 |
| 手动编辑的长度限制 | **1 ~ `WIKI_STYLE_MAX`（默认 2000）字**，空串 / 纯空白 / 超长 → `WikiContentError`（`40014`） | 与 Spec9 建议箱、Spec9 帖子文字的白名单式校验同构；空风格提交会让"上次更新前"被一段空文本顶掉 |
| 该动作是否计入 usage 统计 | **不计入** | `record_call` 的四类（chat / generate / edit / qa，Spec4 §5.4）是"用户的 AI 创作调用"；维护 Wiki 是账号资料管理动作，混进去会污染人均调用口径 |
| 风格生成失败时的表现 | 上游异常按既有 `UpstreamApiError`（`61001`）/ `UpstreamTimeoutError`（`61002`）抛出，**Wiki 与 `wiki_used` 全部不变** | 与 Spec5/Spec9 上游失败的口径一致；失败不能留下半个状态 |
| LLM 返回为空 | 视为上游异常 `UpstreamApiError`（`61001`，附 `风格生成返回为空`） | 空风格写进库比报错更糟——用户会看到风格凭空消失 |
| 并发 | **不加锁**，后写覆盖先写 | 与 Spec11 §5.3 口径一致；同一用户极少在多标签页同时点更新，加锁的复杂度不值当 |

> **时间语义**：`style_updated_at` 存 **UTC ISO（`_now_iso()`，与全库时间格式一致）**，前端按本地时区格式化展示。「上次更新前的作品风格」**不单独记时间**——它只是"上一版长什么样"的文本留存，加时间戳属于本 Spec 范围外的信息增量。

---

## 3. 需求边界

### 范围内

- 新增 `wiki` 表（建表幂等），每用户一行；新增 `images.wiki_used` 列（对**已存在的 `artcn.db` 做列存在性检查后 `ALTER TABLE ADD COLUMN`**，幂等）。
- 「我的作品」页顶部新增**「个人作品风格」Block**：展示当前风格（主） + 上次更新前的风格（次，小字）；两者都为空时显示引导文案。
- Block 内**「基于我的新作品更新风格」**按钮：提取未纳入过的生成/绘图作品 prompt → 与原风格一起送 DeepSeek 纯文本 API 合并 → 写回 Wiki → 标记这些作品为「已用于更新」。
- 无待考虑作品时，弹出警告 **「所有作品已全部考虑到」**，不调用 LLM、不改任何数据。
- Block 内**手动编辑**：就地改风格 → 提交 → 覆盖 `style`（旧值自动进入 `prev_style`）。
- 删除用户时级联删除其 `wiki` 行。
- 删除单张作品**不影响** Wiki（风格文本与具体作品 id 无引用关系）。

### 范围外（本 Spec 不做）

- **`wiki_used` 的前端露出与手动翻转**：不加角标、不提供"把某张作品捞回来重算"的开关（作者拍板前端完全不露出）。
- **风格历史版本列表 / 多版本回退**：只保留"当前"与"上次更新前"两格；不建 `wiki_history` 事件表，不做 N 版回溯。
- **风格的自动更新**：不因"用户新生成了一张图"自动触发；只有用户点按钮或手动提交才写库。
- **风格参与生成**：不做"用个人风格自动润色 prompt / 影响出图"。本 Spec 只负责风格的**沉淀与展示**，风格如何被消费留给后续 Spec。
- **管理员查看 / 编辑他人 Wiki**：无任何管理端入口；`/api/wiki*` 一律只作用于 `request.state.user`。
- **作品来源 `upload` 的文字提取**：按定义跳过（其 `prompt` 为 NULL）。
- **多用户共享 / 公开个人风格页**：不做。
- **清空风格 / 重置 Wiki**：不提供（要清空就手动编辑成一段新文本；要彻底重置需删用户，走既有级联）。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | **无新依赖** | `db.py`（`wiki` 建表 + `images.wiki_used` 列迁移 + Wiki / 作品标记 CRUD）、`wiki.py`（**新文件**：风格合并编排，与 `gallery.py` / `community.py` / `shares.py` 同为"业务模块"）、`main.py`（3 条路由）、`prompts.py`（2 份风格提示词）、`errors.py`（1 个错误类）、`config.py`（3 个常量）、`errors` 无新增码段以外的改动 |
| 前端 | 无新依赖 / 无新框架 | `GalleryPanel.vue` 顶部新增风格 Block（含展示 / 编辑 / 按钮）；`chatApi.js` 新增 3 个函数 |

> 无新 pip / npm 依赖；无新环境变量（仅 3 个**带默认值**的可选常量）；`.gitignore` 不变（`artcn.db` 已在其中，新表同库自动建）。

---

## 5. 架构设计（增量）

### 5.1 数据变更

**（a）新增 `wiki` 表**（`init_db` 内建表，幂等）：

```sql
CREATE TABLE IF NOT EXISTS wiki (
    user_id          INTEGER PRIMARY KEY,
    style            TEXT NOT NULL DEFAULT '',   -- 当前「个人作品风格」（空串 = 尚未建立）
    prev_style       TEXT,                       -- 「上次更新前的个人作品风格」（NULL = 从未更新过）
    style_updated_at TEXT,                       -- 当前风格的产生时刻（UTC ISO；NULL = 尚未建立）
    updated_at       TEXT                        -- 本行最后修改时刻（UTC ISO）
)
```

**（b）`images` 表新增列**（对存量库做幂等迁移）：

```sql
-- init_db() 内：PRAGMA table_info(images) 查得无 wiki_used 列时才执行
ALTER TABLE images ADD COLUMN wiki_used INTEGER NOT NULL DEFAULT 0
```

- `wiki_used = 1` 表示该作品已被纳入过某次风格更新（或作为上传作品被"视为已考虑"）。
- 新建库时直接在建表语句里带上该列，迁移分支只服务存量 `artcn.db`。
- 需在 `_CREATE_IMAGES_TABLE` 里同步补上该列定义，使两条路径（新建 / 迁移）最终 schema 一致。

### 5.2 关键数据流

**（A）读取风格（页面加载）**

`GET /api/wiki` → `db.get_wiki(user_id)`：行不存在则返回全空默认值（`style=''`、`prev_style=NULL`、`style_updated_at=NULL`），**不建行**（读操作不写库）。前端据此渲染 Block。

**（B）基于新作品更新风格（按钮）**

```
点「基于我的新作品更新风格」
  → POST /api/wiki/style/refresh
  → db.list_pending_style_images(user_id)      # source ∈ {generate, edit} AND wiki_used = 0，时间倒序
  → 若为空：
        直接返回 {updated: false, reason: "nothing_new", ...当前风格}
        前端 window.alert('所有作品已全部考虑到')   ← 不调 LLM、不写库、不改标记
  → 若非空：
        1. 提取文字：逐条取 images.prompt，单条截断到 WIKI_PROMPT_ITEM_MAX（默认 500 字）
           按时间倒序（新 → 旧）累加，累加后总长 ≤ WIKI_PROMPT_TOTAL_MAX（默认 6000 字）；
           超出上限的作品本次**丢弃且不标记**
        2. 读 db.get_wiki(user_id) 拿当前 style
        3. 组提示词并 await deepseek.chat_text(messages)：
             style 非空  → 【合并】系统提示词 + 「个人作品风格：…」+「新提取的作品风格参考文字：…」
             style 为空  → 【首次】系统提示词 + 仅「新提取的作品风格参考文字：…」
        4. 清洗返回值（strip / 剥 ``` 包裹 / 再 strip）；为空 → UpstreamApiError(61001)
        5. 单事务写库：
             wiki.prev_style ← 旧 style（首次更新时旧 style 为空串 → prev_style 存 ''）
             wiki.style      ← 新风格
             wiki.style_updated_at ← now
             wiki.updated_at ← now          （UPSERT，行不存在则 INSERT）
             被纳入本次合并的作品 → images.wiki_used = 1
             该用户其余 source='upload' 且 wiki_used=0 的作品 → images.wiki_used = 1（"视为已考虑"）
        6. 返回 {updated: true, style, prev_style, style_updated_at, used_count, pending_count}
  → 前端更新 Block 文案 + 顶部提示
```

> **"全部提取"与"全部标记"的关系**：正常规模下（作品数不多、总长未触顶），待考虑作品就是全部被提取的作品，`used_count == pending_count_before`；只有触及 `WIKI_PROMPT_TOTAL_MAX` 的极端情况才会出现"部分提取"，此时未提取的保持 `wiki_used = 0`，下次点按钮继续算——**增量语义天然自洽**。

**（C）手动编辑风格**

```
Block 内编辑框改文本 → 点「保存」
  → window.confirm('确定用这段文字覆盖当前的个人作品风格？原风格会存入"上次更新前"。')
  → PUT /api/wiki/style  {"style": "<新文本>"}
  → 后端校验：strip 后长度 ∈ [1, WIKI_STYLE_MAX]（默认 1~2000）→ 否则 WikiContentError(40014)
  → 单事务写库：prev_style ← 旧 style；style ← 新文本；style_updated_at ← now；updated_at ← now
  → 返回与 GET /api/wiki 同构的 data
  → 前端刷新 Block（主文案换新、小字换旧）
```

> 手动编辑**不触碰 `images.wiki_used`**：手动改风格是"覆盖式"动作，不消费任何作品。此前未纳入的作品仍是"待考虑"，下次点按钮照样会把它们合并进来——这正是期望行为。

### 5.3 并发 / 一致性说明

- **不做锁**：同一用户并发的两次风格更新，后完成的覆盖先完成的（含 `prev_style`）。与 Spec11 §5.3 口径一致，接受该竞态。
- **失败即无痕**：`chat_text` 抛错时，第（B）步的事务尚未开始，`wiki` 与 `images.wiki_used` 均保持原样。**不存在"作品被标记但风格没更新"的中间态。**
- **事务边界**：`wiki` 的 UPSERT 与 `images.wiki_used` 的批量 UPDATE 放在**同一个 `sqlite3` 连接/事务**里提交（沿用 `db.py` 既有的 `_connect()` + 显式 `conn.commit()` 写法），避免半写。
- **与其它功能的交叉**：
  - 删除作品（Spec5）不影响 Wiki；
  - 删除用户（Spec5 §3 / Spec2）需**级联删除 `wiki` 行**（与删 `usage` / `images` 同一处 `delete_user` 内补一行）；
  - 分享（Spec9）只引用 `images.id`，与本 Spec 无交叉。

---

## 6. 接口约定

### 6.1 新增

| 端点 | 鉴权 | 请求体 | 响应 `data` | 说明 |
|---|---|---|---|---|
| `GET /api/wiki` | 登录用户 | 无 | `{style, prev_style, style_updated_at, updated_at}` | 读本人 Wiki。行不存在时返回 `{style: "", prev_style: null, style_updated_at: null, updated_at: null}`，**不建行** |
| `POST /api/wiki/style/refresh` | 登录用户 | 无 | 见下 | 基于未纳入过的作品更新风格（同步，等 LLM） |
| `PUT /api/wiki/style` | 登录用户 | `{"style": "..."}` | 同 `GET /api/wiki` 的 `data` | 手动覆盖风格；旧值进 `prev_style` |

**`POST /api/wiki/style/refresh` 响应 `data`（有更新）**：

```json
{
  "updated": true,
  "reason": null,
  "style": "……新风格……",
  "prev_style": "……更新前的风格……",
  "style_updated_at": "2026-09-14T06:12:33.123Z",
  "used_count": 7,
  "pending_count": 0
}
```

> `prev_style` 取值规则：**首次更新**（更新前 `wiki.style` 为空串）时写回空串 `""`；此后每轮写回上一版风格全文。`GET /api/wiki` 在**行不存在**时返回 `null`。前端两者一律按"非空才渲染"处理，故 `""` 与 `null` 表现一致。

**`POST /api/wiki/style/refresh` 响应 `data`（无新东西可考虑）**：

```json
{
  "updated": false,
  "reason": "nothing_new",
  "style": "……当前风格原样……",
  "prev_style": "……原样……",
  "style_updated_at": "……原样……",
  "used_count": 0,
  "pending_count": 0
}
```

> `used_count` = 本次**真正被提取并纳入合并**的作品数；`pending_count` = 本次更新完成后，该用户**仍处于"未用于更新"且属于待考虑范围**（`source ∈ {generate, edit}`）的作品数。正常情况为 0；触顶截断时大于 0。
> **「所有作品已全部考虑到」不是错误**：它是"点了但没有新料"的**正常业务状态**，走 `200 + updated:false`，不占用错误码、不进错误处理链路。

### 6.2 变更

| 端点 / 表 | 变更 |
|---|---|
| `images` 表 | 新增 `wiki_used INTEGER NOT NULL DEFAULT 0` 列（存量库迁移见 §5.1） |
| `DELETE /api/gallery/{item_id}` | **行为不变**（不清理任何 Wiki 状态） |
| `DELETE /api/admin/users/{user_id}` | 级联删除中**新增一行** `DELETE FROM wiki WHERE user_id = ?` |
| 其余全部接口 | **不变** |

### 6.3 鉴权约定

沿用 Spec2/Spec11：非 `/api/auth/login` 的全 `/api` 接口需 Bearer JWT（无 → `40103`）。`/api/wiki*` 均为**普通登录用户**端点，**不涉及管理员权限**；`request.state.user["id"]` 是唯一的数据作用域来源（**请求体里不接受任何 `user_id`**）。

---

## 7. 前端交互

### 7.1 `chatApi.js` 新增

```js
export async function getWiki() {
  const { data } = await http.get('/api/wiki')
  return data.data // { style, prev_style, style_updated_at, updated_at }
}

export async function refreshWikiStyle() {
  const { data } = await http.post('/api/wiki/style/refresh')
  return data.data // { updated, reason, style, prev_style, style_updated_at, used_count, pending_count }
}

export async function updateWikiStyle(style) {
  const { data } = await http.put('/api/wiki/style', { style })
  return data.data
}
```

### 7.2 `GalleryPanel.vue` 新增「个人作品风格」Block

**位置**：页面头部 `<p class="admin-tip">` 之下、`<div class="gallery-tabs">` 之上——风格是**整页的语境**，先于作品网格出现。

**结构**：

```
┌─ 个人作品风格 ────────────────────── 更新于 2026/09/14 14:12 ─┐
│  一段连贯的风格描述……                                          │
│  上次更新前：上一版的风格描述……（小字、低对比度、最多 2 行）    │
│                                                                │
│  [基于我的新作品更新风格]  [编辑]                              │
│  ── 编辑态（点「编辑」后展开）──                               │
│  ┌ textarea（预填当前风格）──────────────────────┐             │
│  │                                               │             │
│  └───────────────────────────────────────────────┘             │
│  [保存]  [取消]                    0 / 2000                    │
└────────────────────────────────────────────────────────────────┘
```

**关键行为**：

| 元素 | 行为 |
|---|---|
| 主文案 `.wiki-style` | `wiki.style` 非空 → 原样展示（`white-space: pre-wrap`）；为空 → 引导文案「还没有风格记录，点下面的按钮从你的作品里归纳一版。」 |
| 时间戳 | `wiki.style_updated_at` 非空 → 「更新于 {toLocaleString('zh-CN')}」；为空 → 不渲染 |
| 「上次更新前」 `.wiki-prev` | **仅当 `wiki.prev_style` 非空时渲染**；`font-size` 明显小于主文案（12px vs 14px）、`color: var(--text-muted)`、`-webkit-line-clamp: 2` 折叠 + `title` 属性给全文。**视觉上明确是次要信息，不与主风格抢注意力** |
| 「基于我的新作品更新风格」按钮 | `btn-mini` 样式。点击 → 置 `wikiBusy = true` 并 `disabled`（文案换「更新中…」，因为要等 LLM 几秒）→ `refreshWikiStyle()`：<br>· `updated === true` → 用返回字段刷新 Block，提示「已根据 N 张作品更新风格」（N = `used_count`），若 `pending_count > 0` 追加「，还有 M 张作品因篇幅限制未纳入」<br>· `updated === false` → `window.alert('所有作品已全部考虑到')`，Block 文案不变<br>· 抛错 → 走既有 `error.value` 错误条展示 `e.message` |
| 「编辑」按钮 | 展开编辑态：`textarea` 预填 `wiki.style`，显示字数计数 `{len} / 2000`（与后端 `WIKI_STYLE_MAX` 同值，前端写常量即可），超长时计数变警示色且「保存」置灰 |
| 「保存」按钮 | 文本 `trim()` 后为空 → 不提交、提示「风格内容不能为空」；否则 `window.confirm('确定用这段文字覆盖当前的个人作品风格？原风格会存入"上次更新前"。')` → `updateWikiStyle(text)` → 成功则收起编辑态、刷新 Block、提示「已保存」 |
| 「取消」按钮 | 丢弃草稿、收起编辑态，不请求后端 |

**`load()` 编排**：`onMounted` 时并发发起 `loadWiki()` 与既有 `load()`（风格与作品互不依赖，不必串行）；`loadWiki()` 失败只写 `wikiError`，**不阻断作品列表渲染**。

**切 Tab 不重拉 Wiki**：`switchTab()` 只重拉作品列表（风格与来源筛选无关）。

### 7.3 样式约定

- Block 用 `var(--bg-surface)` 底 + `var(--border-color)` 边 + `var(--radius-lg)`，与 `.gallery-card` 同族；**不留白底**（Spec10 已明确的主题口径），深紫主题下不得出现浅色面板。
- 主文案 `var(--text-primary)`，次要文案 `var(--text-muted)`，按钮一律 `btn-mini` / `btn-clear` 既有类，**不新增按钮样式**。
- `textarea` 复用全局输入框风格（`var(--bg-input)` / `var(--border-color)`），与 `SuggestionPanel` 的输入框形态保持一致。

---

## 8. 配置 / 环境变量 / .gitignore

`config.py` 新增 3 个**带默认值**的常量（`os.getenv` + 兜底，与既有常量写法一致）：

```python
WIKI_STYLE_MAX = int(os.getenv("WIKI_STYLE_MAX", "2000"))              # 手编 / 生成的风格文本上限（字）
WIKI_PROMPT_ITEM_MAX = int(os.getenv("WIKI_PROMPT_ITEM_MAX", "500"))   # 单条作品 prompt 提取上限（字）
WIKI_PROMPT_TOTAL_MAX = int(os.getenv("WIKI_PROMPT_TOTAL_MAX", "6000"))# 一次合并送入 LLM 的参考文字总上限（字）
```

- `.env` 无需改动（三者在 `config.py` 内均有兜底）。
- `.env.example` **可选**补上这三行注释版占位（便于部署时调参），非必需。
- **无强制新增环境变量**；`.gitignore`、`requirements.txt`、`package.json` 均不变。

---

## 9. 错误码

| 码 | 类 | 场景 |
|---|---|---|
| `40014` | **新增** `WikiContentError(BadRequestError)` | 手动编辑提交的风格 strip 后为空、或长度 > `WIKI_STYLE_MAX` |
| `40103` | 既有 `AuthTokenError` | 未带 / 无效 token |
| `61001` | 既有 `UpstreamApiError` | DeepSeek 调用失败；**或返回内容清洗后为空**（message 注明 `风格生成返回为空`） |
| `61002` | 既有 `UpstreamTimeoutError` | DeepSeek 超时 |

- **「所有作品已全部考虑到」不是错误码**（见 §6.1），不落进错误处理链路。
- 无权限问题：`/api/wiki*` 无管理员门槛，无 `40301` / `40302` 场景。

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON 与既有事件。新增两条：

- `wiki.style_updated` —— 风格被写入。附 `user_id`、`source`（`"refresh"` \| `"manual"`）、`used_count`（手动编辑时为 0）、`style_len`（新风格字数）。**不记录风格全文**（可含用户创作倾向，属个人数据）。
- `wiki.refresh_skipped` —— 点了更新但无新作品可考虑。附 `user_id`、`reason: "nothing_new"`。

**不新增** `images.wiki_used` 的逐条日志（批量标记，逐条刷屏无价值）。

---

## 11. 目录结构增量

```
Server/
  db.py        # 新增 wiki 建表 + images.wiki_used 列迁移（PRAGMA 检查）
               #   + get_wiki / upsert_wiki / mark_images_wiki_used / list_pending_style_images
               #   + delete_user 内追加 DELETE FROM wiki
  wiki.py      # 【新文件】风格合并编排：提取 prompt → 组提示词 → 调 deepseek.chat_text → 清洗 → 落库
  main.py      # GET /api/wiki、POST /api/wiki/style/refresh、PUT /api/wiki/style
  agents/prompts.py            # 新增 WIKI_MERGE_SYSTEM_PROMPT / WIKI_INIT_SYSTEM_PROMPT
  errors.py                    # 新增 WikiContentError(40014)
  config.py                    # 新增 WIKI_STYLE_MAX / WIKI_PROMPT_ITEM_MAX / WIKI_PROMPT_TOTAL_MAX
  .env.example                 # 【可选】补三行注释占位
frontend/src/
  api/chatApi.js          # 新增 getWiki() / refreshWikiStyle() / updateWikiStyle()
  views/GalleryPanel.vue  # 顶部新增「个人作品风格」Block（展示 + 上次更新前 + 按钮 + 就地编辑）
```

> `wiki.py` 与 `gallery.py` / `community.py` / `shares.py` 并列，均为"拿到 `user_id` 就干活"的业务模块；`main.py` 只做参数解析、调模块、套统一响应壳。

---

## 12. 实施顺序（里程碑）

1. **B1 数据层**：`db.py` 新增 `wiki` 建表 + `images.wiki_used` 幂等迁移 + Wiki 与作品标记的 CRUD + `delete_user` 级联补一行。
2. **B2 提示词与错误**：`agents/prompts.py` 两份风格提示词；`errors.py` 新增 `WikiContentError`；`config.py` 三个常量。
3. **B3 业务编排**：`wiki.py` —— 提取（截断 + 倒序累加 + 判定空）→ 组提示词（首次 / 合并两分支）→ `chat_text` → 清洗 → 单事务写库。
4. **B4 路由**：`main.py` 三条端点 + `wiki.style_updated` 日志。
5. **F1 前端**：`chatApi.js` 三个函数；`GalleryPanel.vue` 风格 Block（展示 / 上次更新前小字 / 更新按钮 + loading + alert / 就地编辑 + confirm）。
6. **A1 验收**：`npm run build` + 后端冒烟（§13 用例）。

---

## 13. 验收用例

| # | 操作 | 期望 |
|---|---|---|
| 1 | 新用户进「我的作品」 | 风格 Block 显示引导文案，无时间戳、无「上次更新前」行；不因读接口在 `wiki` 表建行 |
| 2 | 用户上传 3 张图 + 文生图 2 张，点「基于我的新作品更新风格」 | 走**首次生成**分支；风格为一整段中文（无前言/引号/```）；`used_count = 2`；上传的 3 张也被标记 |
| 3 | 紧接着再点一次更新 | 弹 `alert('所有作品已全部考虑到')`；不调 LLM、`updated:false`、风格与时间戳不变 |
| 4 | 再文生图 1 张，点更新 | 走**合并**分支；「上次更新前」出现**第 2 步那版**风格（小字）；主文案是合并后的新风格；时间戳刷新 |
| 5 | 点「编辑」→ 清空 textarea → 点保存 | 提示「风格内容不能为空」，不发请求、不改库 |
| 6 | 输入 2001 字 | 字数计数警示、保存置灰，无法提交 |
| 7 | 改成一段有效文字 → 保存 | 先弹 `confirm`；取消 → 无请求、库不变；确定 → 主文案更新，「上次更新前」变成**上一步那版**，时间戳刷新 |
| 8 | 手动编辑后再点「更新风格」（此时仍有未纳入作品） | 合并基准是**手编后的新风格**（读的是 `wiki.style` 当前值），不是更早的版本 |
| 9 | 作品 prompt 极多（合计超 6000 字） | 按时间倒序取用到触顶；响应 `pending_count > 0`，前端提示「还有 M 张作品因篇幅限制未纳入」；未纳入者 `wiki_used` 仍为 0，再点更新会继续纳入 |
| 10 | 断网 / DeepSeek 返回 5xx | 前端显示既有错误条；`wiki` 表与 `images.wiki_used` **均无任何变化**（重试后行为与首次一致） |
| 11 | DeepSeek 返回空字符串 | 报 `61001`（`风格生成返回为空`）；库不变 |
| 12 | 用户 A 调 `/api/wiki` | 只拿到 A 自己的风格；请求体里塞 `user_id` 不产生任何影响 |
| 13 | 未带 token 调 `/api/wiki` 或 `/api/wiki/style/refresh` | `401`（`40103`） |
| 14 | 管理员删除某用户 | 该用户 `wiki` 行随之删除；其他用户 Wiki 不受影响 |
| 15 | 删除某张已纳入过风格的作品 | Wiki 风格文本不变、不报错 |
| 16 | 连点两次「更新风格」（第一次未返回时） | 按钮 `disabled` 挡住第二次；服务端即使收到并发请求也只以"后完成者"为准，不产生半写状态 |
| 17 | 页面切 Tab（全部/上传/文生图/图文生图）| 只重拉作品列表；风格 Block 不闪烁、不重新请求 |
| 18 | 刷新页面 / 重启后端 | 风格、上次更新前、时间戳持久显示（来自 `artcn.db`） |
| 19 | 样式回归 | Block 为深紫主题下的一体化面板（**无白底**），主文案与「上次更新前」字号层级分明，与作品卡片视觉同族 |
| 20 | 调用统计页（Spec4 / Spec11） | 调用「更新风格」**不增加**四类计数中任何一类 |

> 验收时明确排除：`wiki_used` 的前端角标与手动翻转 / 风格历史版本列表 / 自动更新 / 风格参与出图 / 管理员查看他人 Wiki / 风格清空重置。
