# ArtiControlNet Spec 17：对话历史持久化 + 纯文字帖 + 评论

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：把聊天从「浏览器 localStorage 里的一段、图片 1 小时就死」升级成**按用户存进 `artcn.db` 的多段对话**（左侧常驻历史侧边栏 + 可继续聊 + 图片引用作品库持久化）；社区发帖**允许纯文字**（`posts.image_file` 改为可空，走一次重建表迁移）；帖子下方**内联展示评论区**（新表 `post_comments`，可增可删不可改）。
> 本 Spec 是 **Spec.md / Spec2~16 的增量补充**，不推翻原有架构。数据库变化：**新增 3 张表**（`conversations` / `chat_messages` / `post_comments`）+ **1 次重建表迁移**（`posts` 的 `image_file`/`ext` 去 `NOT NULL`）+ `app_meta` 新增 1 个键（`task_id_seq`）。**无新依赖、无新持久目录**；新增 2 个可选环境变量（均有默认值）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 Spec2 的本地单文件 SQLite `artcn.db` 外无其他数据库。**不新增 provider、不新增模型**——本次改动完全不调用任何外部 API（除既有聊天链路本身）。

---

## 1. 功能目的

### 1.1 对话历史持久化

- **聊天记录现在是「一次性的」**：`store/chat.js` 把整段会话塞进 `localStorage['artcn_chat_v2:<username>']`，**只有一段**、换浏览器就没了、清缓存就没了。用户想「回到上周那次海报的对话」在现有结构下**根本无法表达**——没有"多段对话"这个概念。
- **图比文字死得更快**：聊天里的图片地址是 `/images/{uuid}.png`，指向 `storage/`——**TTL 1 小时、后端启动即清空**（Spec §5.3）。用户开着页面超过一小时，之前生成的图就全裂了；刷新页面更是什么都不剩。这是既有缺陷，Spec17 必须一并修掉，否则"持久化对话"只是保存了一堆死链接。
- **「清空」是个语义含糊的按钮**：它既像"删掉这段"，又像"开一段新的"。用户点下去之后旧内容**永久消失且无法找回**。本 Spec 把它换成语义单一的**「新对话」**：当前这段留在侧边栏、开一段全新的。
- **复用既有资产**：用户上传的图和模型生成的图，**现在就已经**各自落了一份到 `Server/gallery/`（Spec5「上传即入库」+ Spec5/6 生成入库）。所以持久化**不需要复制任何字节**——聊天记录只要"指过去"就行。

### 1.2 纯文字帖

- **发帖被结构性地锁死了**：`POST /api/community` 强制"图片来源二选一"，`posts.image_file` 与 `ext` 都是 `NOT NULL`。用户想说一句心得、问一个问题、发一条公告，**必须先凑一张图**——这既别扭，也逼着用户往社区里灌无意义的图。
- **顺手清掉一句拦路的文案**：社区页顶部那行「当前登录：xxx · 社区对所有人可见 · 单图 + 文字」，在纯文字帖放开后前半段是冗余（用户名顶栏已有）、后半段是错的。整行删掉。

### 1.3 评论

- **社区只有"广播"没有"对话"**：Spec9 的社区是"发帖 + 点赞/点踩"，**没有任何回复通道**。前 16 个 Spec 攒下的全部表达方式，对一条帖子只能给一个 👍。这是社区功能最明显的缺口。
- **评论必须是"不能改"的**：帖子和评论的性质不同——帖子是作品展示（改文案是编辑行为），评论是对话（改口供会让上下文失去意义）。所以本 Spec **只做增、删、查，不做改**，并且这是全仓**唯一没有更新动词的资源**（决策记录 §2 会写明这是有意为之）。

---

## 2. 决策记录（为什么这么选）

### 2.1 对话历史

| 决策 | 选择 | 理由 |
|---|---|---|
| 聊天图片怎么持久化 | **引用作品库 `images.id`**，不复制字节 | 用户上传图与生成图**本来就已经**在 `gallery/` 里各存了一份（Spec5「上传即入库」、Spec5/6 生成入库）。再复制一份到独立目录是纯粹的磁盘浪费，而且要多维护一处删除级联。作者拍板 |
| 图片被删怎么办 | **接受裂图**，前端显示「图片已删除」占位 | 用户可以在「我的作品」里删掉那张图，聊天记录里的引用随之失效。这是"不复制字节"的必然代价，作者已知悉并接受 |
| 图片渲染地址 | **一律走 `/api/gallery/{id}/file`**（带 token 拉 blob → objectURL） | 若只在历史回看时切换、当轮仍用 `/images/`，同一张图在两种时机地址不同，`ChatBubble` 要分叉。统一后**顺带修掉**"页面停留超 1 小时旧图全裂"的既有缺陷 |
| `storage/` 还写不写 | **照旧写**，但前端渲染不再依赖它 | `storage/` 仍有真实用途：给 Supervisor 的路由上下文当"近期图片引用"（`_recent_images`）。改它风险大、收益小。语义收窄为"会话内的临时缓存"，不再是对用户可见的图片地址 |
| 新旧对话的形态 | **「新对话」完全取代「清空」**，头部不再有清空按钮 | 作者拍板。两个按钮并存会造成"清空到底删不删历史"的歧义；删掉某段对话的入口统一收进侧边栏的删除按钮 |
| 对话行何时创建 | **发出第一条消息时**才建 `conversations` 行 | 点了「新对话」但没说话，不该在侧边栏留下一个空条目。侧边栏里的每一条都对应一段真实存在过的对话 |
| 点历史对话 | **可继续聊**（共用同一个 `thread_id`） | 作者拍板。只读回看会让用户想接着问时无处下手。代价是路由上下文必须能从 DB 回填（见下一条） |
| 路由上下文跨重启 | `ThreadStore` 保留为内存缓存，新增 **`ensure_loaded` 从 `chat_messages` 回填最近 N 条** | `ThreadStore` 是纯内存的（`THREAD_HISTORY_LIMIT=20`），原设计重启即丢。对话持久化后"接着聊"必须跨重启有效，否则用户会看到"助手突然失忆"。不废掉 ThreadStore 是因为它还被失败路径复用（见 §5.3） |
| 侧边栏排序 vs 显示 | **按 `updated_at DESC` 排序，显示 `created_at`** | 接着聊旧对话会让它冒到顶上（与 ChatGPT/微信一致）；但标签如实地写"发起时间"，不随活跃度变化 |
| 时间粒度 | **一律精确到分**：`2026-09-15 14:30 的对话` | 作者拍板。精确到天会让同一天开的几段对话在侧边栏显示成一模一样的条目 |
| 谁能删对话 | **只能删自己的**，管理员也不能删他人的 | 作者拍板。聊天记录是私域数据，与作品库/社区（公开）性质不同；管理员越权看他人对话本身就不该开放，那么"能删不能看"也没有意义 |
| 删对话是否删图 | **不删** | `gallery/` 里的图是作品库的资产，删一段聊天记录不该连带删掉作品。侧边栏删除只清 `conversations` + `chat_messages` 两处 |
| 旧 localStorage 历史 | **不迁移、不主动清除** | 里面的图片地址**已全部失效**（`storage/` 早清空了），迁移过来是一堆裂图；格式也对不上（没有对话分段概念）。留着作为用户数据的最后退路，开发者工具里还能看到文本 |
| `GET /api/threads/{thread_id}/messages` | **删除**，连同前端死代码 `getThread()` | Spec17 之后它是 `GET /api/conversations/{id}/messages` 的**严格劣化版**：内容在内存、重启即丢、上限 20 条、还含「（任务失败：…）」这类内部记录。两个"取对话消息"的接口并存只会制造混淆。作者拍板 |
| **`task_id` 重启归零** | **持久化计数器**（`app_meta['task_id_seq']`） | **这是本 Spec 发现的一个真实数据缺陷**，详见 §3.4 |
| 对话列表上限 | `CONVERSATION_LIST_LIMIT`（默认 **50**），不分页 | 侧边栏是导航不是档案库；50 条足够覆盖任何真实使用。不引入分页状态 |

### 2.2 纯文字帖

| 决策 | 选择 | 理由 |
|---|---|---|
| 表怎么改 | **重建表迁移**（`CREATE new` → `INSERT SELECT` → `DROP old` → `RENAME`） | SQLite 不支持 `ALTER COLUMN` 去约束，`ADD COLUMN` 也改不了既有列的 `NOT NULL`。这是唯一正确的做法 |
| 迁移幂等判据 | `PRAGMA table_info(posts)` 里 `image_file` 的 **`notnull` 标志为 1** 才重建 | 与 Spec12/16 的补列迁移同思路（先查后改）。迁移后标志变 0，再启动不会重复重建 |
| 图片来源校验 | 从"必须二选一"改为「**不能同时给，但可以都不给**」 | 保持"一次最多一张图"的约束不变（多图仍不在范围内），只是把一个选项变成可选 |
| 错误码 | **沿用 `40011 PostContentError`**，只改提示文案 | "双来源"和"文字超长"仍是同一类错误（帖子内容非法），没有新增语义。不为它开新码 |
| 纯文字帖取图 | `GET /api/community/{post_id}/image` → **`40404`** | 帖子存在但没有图。在"取图片"这个语境下，"没有"就是"不存在"，复用 `PostNotFoundError` 语义自洽，不新增错误码 |
| 帖子上限是否放宽 | **否**，`text` 仍是 1~1000 字 | 纯文字帖没有被"解放"到需要更长文本的程度；放宽会牵动前端计数器与校验文案，收益不明 |

### 2.3 评论

| 决策 | 选择 | 理由 |
|---|---|---|
| 评论可否修改 | **不可**，只做增 / 删 / 查 | 作者拍板。评论是对话而非作品，改口供会让上下文失去意义。**这是全仓唯一没有 `PUT` 的资源**——有意为之，不是遗漏 |
| 表述方式 | 前端**不给"编辑"入口**，后端**不开 `PUT` 路由** | 两端一致地不提供，避免出现"接口能改但 UI 藏起来"的假象 |
| 删除权限 | **作者或管理员**（`40303`） | 作者拍板。与帖子/作品的删除口径一致（`40302` 的先例） |
| 展示形态 | **帖子下方内联固定高度滚动区**，自动加载 | 作者拍板。贴合"帖子下方自动展示评论、可上下滑动看全部"的原话 |
| 列表怎么返回 | `GET /api/community` 每项**内嵌 `comments: [...]`** | 作者选"全量不分页"。内嵌后前端**零额外请求**就能"自动展示"；若改成每帖单独拉，50 条帖子就是 50 个请求（N+1）。服务端用一次批量查询再分组实现，不是 N+1 |
| 排序 | 按 `id ASC`（时间正序） | 评论是从上往下读的对话，最新的在底部——与聊天一致，符合直觉 |
| 发/删后是否重拉列表 | **否**，本地 append / remove | 评论对象很小，重拉整页帖子列表纯属浪费，还会打断滚动位置 |
| 是否单独给一个 `GET /api/community/{post_id}/comments` | **给**（后端），**前端不调用** | 作者要求"评论有增删查"，而 `POST` / `DELETE` 挂在 `/comments` 下却没有 `GET`，会让资源形态残缺、也无法用 curl 单独验证某帖评论。成本是 `community.py` 里一个复用 `list_comments_for_posts([post_id])` 的函数 + 一条路由。**前端不调用**——评论已经内嵌在帖子列表里，再定义一个前端函数就是新的死代码（§7.2） |
| 点赞 / 楼中楼 / @ | **不做** | YAGNI。Spec9 已经给帖子做了点赞，评论点赞是另一个独立需求 |
| 字数上限 | `COMMENT_TEXT_MAX`（默认 **200**，可经 env 覆盖） | 作者拍板"评论内容不超 200 字" |
| 输入控件 | 单行 `input`，回车即发 | 200 字单行足够；textarea 会引入换行，而展示区是单行截断（§7.7） |

---

## 3. 需求边界

### 3.1 对话历史

**范围内**

- 每个用户**多段**对话；记录全部消息内容（用户的话 / 助手回复）+ 发起的日期时间，落到 `artcn.db`。
- 聊天界面的图片持久化：用户上传的参考图、模型生成/绘图的结果图，**跨重启、跨 TTL 存活**。
- 聊天视图左侧**常驻侧边栏**：顶部「新对话」，下方历史列表（显示 `<发起时间> 的对话`），可滚动。
- 点历史对话 → 载入该段全部消息，**可继续发消息**（共用 `thread_id`）。
- 删除对话（**仅本人**），`confirm` 一次。
- 「新对话」：结束当前段（保留在侧边栏）、开一段空对话。
- 刷新页面后回到上次所在的对话；失效则回到最近一条；没有对话则空对话。

**范围外（本 Spec 不做）**

- 对话重命名 / 搜索 / 置顶 / 收藏 / 导出 / 分享。
- 对话列表分页或无限滚动（一次最多 50 条）。
- 跨用户可见对话；管理员查看或删除他人对话。
- 旧 localStorage 历史的迁移导入。
- 消息级别的删除或编辑（只能删整段对话）。
- 消息的"已读/未读"、未读红点、新消息推送。

### 3.2 纯文字帖

**范围内**

- 发帖时可**不带图片**，只发文字（1~1000 字）。
- 列表与卡片：纯文字帖**不渲染图片区**，卡片自然变矮。
- 迁移存量帖子数据（全部有图，`image_file` 保持原值）。

**范围外（本 Spec 不做）**

- 多图帖（仍是一张图或零张图）。
- 帖子文字上限放宽 / 富文本 / 换行排版（仍是纯文本，前端按既有方式渲染）。
- 已发帖的编辑（Spec9 已定：发帖后不可改）。
- 发帖时的"图文必须匹配"之类的额外校验。

### 3.3 评论

**范围内**

- 任意登录用户可在**任意帖子**（含他人的）下发表评论，1~200 字。
- 帖子下方自动展示该帖全部评论（用户名 + 内容 + 时间），固定高度区域内上下滚动。
- 删除评论：**作者本人或管理员**，`confirm` 一次。
- 删帖 / 删用户时评论级联清理。

**范围外（本 Spec 不做）**

- 评论的编辑（**明确不做**，见 §2.3）。
- 楼中楼 / 回复某条评论 / @ 提及。
- 评论点赞、评论排序切换（热度/时间）、评论分页。
- 评论的敏感词过滤、审核、举报。
- 评论数徽章（评论区总是内联可见，不需要额外的数字入口）。

### 3.4 已知边界与风险（写入本文档，避免误读）

- **`task_id` 重启归零与持久化对话的冲突（本 Spec 发现，必须修）**：`task_queue.py` 用 `itertools.count(1)` 在内存里发号，**后端每次重启都从 1 重排**。Spec9 §3.5 当时明确接受了这个边界，理由是 task_id 只活在浏览器的 localStorage 气泡里、且反馈统计只看聚合类别——**"覆盖旧行对按类聚合无影响"**。
  **Spec17 打破了这个前提**：对话进了数据库、要长期存活，历史图片气泡上的 👍/👎 用的正是 `task_id`，而 `feedback` 表是 `UNIQUE(task_id)`。于是重启后给三个月前某张图点的 👍，其 `task_id` 会与一个**完全不相关的新任务**撞号 → 既把票记在了错误的对象上，又**静默覆盖别人的 `feedback` 行**，界面看不出任何异常；"对聚合计数无影响"也不再成立（覆盖是跨用户、跨类别的）。
  **修法**：`app_meta['task_id_seq']` 持久化当前值，`TaskQueue` 启动时从它接着数，每次 `submit` 后写回。`task_id` 变成**全局单调递增、永不重用**，`UNIQUE(task_id)` 永远成立。**URL 契约、`GET /api/tasks/{task_id}` 的行为都不变**。代价是每次提交多一次 SQLite 写入（WAL 模式，可忽略）。
- **`PendingStore`（追问挂起意图）仍是纯内存的**：Spec5 §5.5 定的 TTL 1800 秒、重启即丢。对话持久化后，重启会导致"上一轮刚追问完，这一轮接着说"的挂起意图丢失——用户需要重新说一遍。**接受**：这是 Spec5 既有设计，且 30 分钟 TTL 本来就不承诺跨重启。
- **失败的任务不入库**：`PENDING → PROCESSING → FAILED` 的任务**不写 `chat_messages`**。失败气泡是瞬时 UI 状态（带"重试"按钮），重试会产生新结果；落库只会让历史里堆满已无意义的错误。**后果**：刷新页面后，失败那一轮只剩用户自己的消息、没有回复——这是诚实的呈现。内存 `ThreadStore` 仍照旧追加「（任务失败：…）」，只影响当轮之后的路由上下文，不影响用户可见历史。
- **图片被删会裂图**：聊天记录只存 `images.id`，不存字节。用户在「我的作品」删掉那张图，聊天里对应位置显示「图片已删除」占位（前端按 404 处理）。**这是 §2.1 第 2 条决策的已知代价，不是缺陷。**
- **删除用户会连带删掉其全部对话**：与该用户的帖子/作品/建议同口径（Spec4/5/9 §3 的既有约定）。被删用户对话里的图片引用随之消失，但**图片本身若属于同一用户也一并删除**（`images` 行级联），不会留下悬挂引用。
- **`posts` 重建表迁移期间的数据安全**：迁移在 `init_db()` 里、单事务内完成（`executescript`）。若中途失败，SQLite 事务回滚，`posts` 表保持原样。**风险**：`DROP TABLE posts` 之后 `RENAME` 之前进程被杀会留下 `posts_new`。概率极低（本地单文件库、毫秒级），且**接受**——不做备份快照。
- **评论条数无上限**：`GET /api/community` 内嵌全量评论。理论上一条被灌爆的帖子会拖慢整个列表接口。**接受**：本系统是校园项目规模，且 `MAX_PENDING_TASKS=100` 之类的既有上限也说明了量级预期。若真出问题，改成分页是局部改动。
- **侧边栏只在聊天视图显示**：切到社区 / 我的作品 / 建议 / 用户管理 / 数据统计时整块隐藏。这些面板本来就是"全屏替换聊天区"的既有结构（`App.vue` 的互斥面板），不改为"面板嵌在聊天列里"。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | **无新依赖** | 复用 `sqlite3`（Spec2）+ 既有文件读写；新增 `chat_history.py` 模块；评论逻辑并入 `db.py` + `community.py` + `main.py` |
| 前端 | **无新依赖 / 无新框架** | 新增 `components/ConversationSidebar.vue`、`composables/useAuthedImage.js`；`store/chat.js` 重写；`App.vue` / `ChatBubble.vue` / `CommunityPanel.vue` / `api/chatApi.js` / `GalleryPanel.vue` 增量；`main.css` 追加样式 |

> 无需新 pip / npm 依赖。`.env` 仅新增两个**可选**变量（`COMMENT_TEXT_MAX`、`CONVERSATION_LIST_LIMIT`），不配也能跑。

---

## 5. 架构设计（增量）

### 5.1 数据变更

#### 5.1a 新增 `conversations`（一段对话一行）

```python
# 对话（Spec17 §5.1a）：按用户保存的聊天分段。
# id 沿用既有的 thread_id 形态（t_ + uuid4 前 8 位），前端/后端/日志三处同一个值。
_CREATE_CONVERSATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,          -- = thread_id（t_xxxxxxxx）
    user_id    INTEGER NOT NULL,          -- 归属用户（删用户级联）
    created_at TEXT NOT NULL,             -- 发起时间（侧边栏显示的就是它）
    updated_at TEXT NOT NULL              -- 最后一条消息时刻（列表排序用）
)
"""
_CREATE_CONVERSATIONS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_conversations_user "
    "ON conversations(user_id, updated_at DESC)"
)
```

**排序用 `updated_at`、显示用 `created_at`**（§2.1）。两者都在 `_now_iso()`（UTC ISO 8601 + `Z`）口径下，前端负责转本地时区显示。

#### 5.1b 新增 `chat_messages`（一条消息一行）

```python
# 对话消息（Spec17 §5.1b）：记录用户与助手双方的内容。
# image_id 引用 images.id（Spec5 作品库）——**不复制字节**；该图可能被用户在
# 「我的作品」里删掉，此时本行成为悬挂引用，前端渲染 404 → 「图片已删除」占位。
# task_id / tool 仅助手侧的工具结果有值（Spec9 反馈行用）。
_CREATE_CHAT_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id    TEXT    NOT NULL,          -- conversations.id
    user_id    INTEGER NOT NULL,          -- 归属用户（删用户级联）
    role       TEXT    NOT NULL,          -- 'user' | 'assistant'
    text       TEXT,                      -- 文本内容（纯图片消息为 NULL）
    image_id   INTEGER,                   -- images.id（无图为 NULL）
    task_id    INTEGER,                   -- 该结果的 task_id（仅工具结果；反馈用）
    tool       TEXT,                      -- 'generate_image'|'edit_image'|'qa_image'
    created_at TEXT    NOT NULL
)
"""
_CREATE_CHAT_MESSAGES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_conv "
    "ON chat_messages(conv_id, id)"
)
```

**一行 = 一条消息**，不是"一条消息的每个附件一行"——因为当前每个结果**恒为 1 张图**（`hy-image-v3` 每次返回一张，`result["images"]` 长度恒为 1）。若将来支持多图，`image_id` 改为 JSON 列或子表；本 Spec 不做。

`user_id` 是冗余列（可由 `conv_id` 推出），存在的唯一目的是让"删除用户"能用一条 `DELETE ... WHERE user_id = ?` 简单级联，与 `images`/`posts` 的既有写法一致。

#### 5.1c 重建迁移：`posts.image_file` / `ext` 去 `NOT NULL`

```python
def _migrate_posts_nullable_image(conn: sqlite3.Connection) -> None:
    """存量库把 posts.image_file / ext 改为可空（Spec17 §5.1c：纯文字帖）。

    SQLite 不支持 ALTER COLUMN，只能重建表。幂等判据：PRAGMA 查得 image_file
    的 notnull 标志为 1 才动手——重建后该标志变 0，再启动不会重复执行。
    新建库由 _CREATE_POSTS_TABLE 直接写成可空，本函数只服务已存在的 artcn.db，
    两条路径最终 schema 一致。

    DROP TABLE posts 会连带删掉 idx_posts_created，故重建后一并补回。
    """
    cols = {r["name"]: r["notnull"]
            for r in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if not cols.get("image_file"):
        return                                  # 已是可空 / 列不存在 → 无事可做
    conn.executescript("""
        CREATE TABLE posts_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            text       TEXT    NOT NULL,
            image_file TEXT,
            ext        TEXT,
            created_at TEXT    NOT NULL
        );
        INSERT INTO posts_new (id, user_id, text, image_file, ext, created_at)
            SELECT id, user_id, text, image_file, ext, created_at FROM posts;
        DROP TABLE posts;
        ALTER TABLE posts_new RENAME TO posts;
        CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
    """)
    logger.info("posts.image_file / ext 已改为可空", extra={"event": "db.migrate"})
```

`_CREATE_POSTS_TABLE` 同步改为可空（新建库路径）：

```python
_CREATE_POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,             -- 作者
    text       TEXT    NOT NULL,             -- 文字（1~1000 字，前后端校验）
    image_file TEXT,                         -- community/ 下持久文件名；纯文字帖为 NULL
    ext        TEXT,                         -- .jpg|.jpeg|.png|.webp|.gif；纯文字帖为 NULL
    created_at TEXT    NOT NULL
)
"""
```

`init_db()` 里在 `conn.execute(_CREATE_POSTS_INDEX)` **之后**调用迁移：

```python
        conn.execute(_CREATE_POSTS_TABLE)
        conn.execute(_CREATE_POSTS_INDEX)
        ...
        # Spec17 §5.1c：存量库把 posts.image_file / ext 改为可空（纯文字帖）
        _migrate_posts_nullable_image(conn)
```

#### 5.1d 新增 `post_comments`（一条评论一行）

```python
# 帖子评论（Spec17 §5.1d）：只增不删不改——**没有 updated_at 列**，
# 因为评论不可编辑（§2.3）。要改只能删了重发。
_CREATE_POST_COMMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS post_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,             -- 引用 posts.id
    user_id    INTEGER NOT NULL,             -- 评论者
    text       TEXT    NOT NULL,             -- 1~COMMENT_TEXT_MAX 字
    created_at TEXT    NOT NULL
)
"""
_CREATE_POST_COMMENTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_post_comments_post "
    "ON post_comments(post_id, id)"
)
```

#### 5.1e `app_meta` 新增键 `task_id_seq`（修 §3.4 的缺陷）

```python
# app_meta 键：值 = 已发出的最大 task_id（十进制字符串）。
# Spec17 §3.4：TaskQueue 是内存发号器，重启从 1 重排会让持久化对话里的
# 历史 👍/👎 与新任务撞号，覆盖他人 feedback 行。持久化后 task_id 全局单调、永不重用。
TASK_ID_SEQ_KEY = "task_id_seq"
```

新增一个公开写入口（现在只有内部的 `_upsert_meta`）：

```python
def set_meta(key: str, value: str) -> None:
    """写一条 app_meta（公开入口，Spec17 §5.1e 起供 TaskQueue 持久化 task_id 用）。"""
    with _connect() as conn:
        _upsert_meta(conn, key, value)
        conn.commit()
```

#### 5.1f 删除用户 / 删除帖子的级联

| 函数 | 追加的动作 |
|---|---|
| `db.delete_user(user_id)` | `DELETE FROM chat_messages WHERE user_id = ?`；`DELETE FROM conversations WHERE user_id = ?`；`DELETE FROM post_comments WHERE user_id = ?` |
| `db.delete_post_record(post_id)` | `DELETE FROM post_comments WHERE post_id = ?`（与既有 `post_votes` 同级联） |
| `db.delete_user_post_records(user_id)` | 删该用户帖子上的**全部**评论（`WHERE post_id IN (SELECT id FROM posts WHERE user_id = ?)`）+ 该用户发在**别人帖子**上的评论（`WHERE user_id = ?`） |

**注意顺序**：现有 `delete_user` 里 `DELETE FROM posts WHERE user_id = ?` 在最后附近。删除该用户帖子上的评论必须在 `DELETE FROM posts` **之前**执行（否则子查询取不到帖子 id 了）。实现时把评论清理放在帖子删除之前。

#### 5.1g `db.py` 新增的读写函数

```python
# ---------- 对话历史（Spec17 §5.1） ----------

def ensure_conversation(conv_id: str, user_id: int) -> dict:
    """取对话；不存在则建（created_at = updated_at = now）。返回记录 dict。"""

def get_conversation(conv_id: str) -> dict | None:
    """按 id 取对话；不存在返回 None。"""

def list_conversations(user_id: int, limit: int) -> list[dict]:
    """本人对话列表，updated_at 倒序。"""

def touch_conversation(conv_id: str) -> None:
    """把 updated_at 推到当前时刻（每次追加消息后调用）。"""

def add_chat_message(conv_id: str, user_id: int, role: str, *,
                     text: str | None, image_id: int | None,
                     task_id: int | None, tool: str | None) -> dict:
    """追加一条消息并 touch 对话（同一事务）。返回完整记录 dict。"""

def list_chat_messages(conv_id: str) -> list[dict]:
    """某段对话的全部消息，按 id 升序（= 时间正序）。"""

def list_recent_chat_messages(conv_id: str, limit: int) -> list[dict]:
    """某段对话最近 limit 条，**按 id 升序**返回（供 ThreadStore 回填路由上下文）。"""

def delete_conversation(conv_id: str) -> None:
    """删对话及其全部消息。**不触碰 images**（§2.1：删对话不删作品）。"""

def find_owned_conversation(conv_id: str, user_id: int) -> dict | None:
    """取本人对话；不存在或不属于本人一律返回 None（调用方转 40407，不泄露存在性）。"""

# ---------- 评论（Spec17 §5.1d） ----------

def create_comment(post_id: int, user_id: int, text: str) -> dict:
    """写一条评论，返回记录 dict。"""

def list_comments_for_posts(post_ids: list[int]) -> dict[int, list[dict]]:
    """批量取多帖的评论，按 post_id 分组，组内 id 升序。

    一次 JOIN users 查完（SELECT c.*, u.username, u.is_admin ... WHERE post_id IN (...)），
    避免列表接口变成 N+1。post_ids 为空时直接返回 {}。
    """

def get_comment(comment_id: int) -> dict | None:
    """按 id 取评论（含 author 字段）；不存在返回 None。"""

def delete_comment(comment_id: int) -> None:
    """删一条评论。"""
```

`list_comments_for_posts` 的 JOIN 形态（用户名与是否管理员随评论一起给出，前端才能渲染"用户名 + 内容"并决定是否显示删除按钮）：

```sql
SELECT c.id, c.post_id, c.user_id, c.text, c.created_at,
       u.username AS author, u.is_admin AS author_is_admin
  FROM post_comments c
  JOIN users u ON u.id = c.user_id
 WHERE c.post_id IN (…)
 ORDER BY c.id ASC
```

### 5.2 关键数据流

#### 5.2A 图片引用链（本次改动的核心）

现在聊天图片的地址是 `/images/{uuid}.png` → `storage/`（**TTL 1h、启动清空**）。Spec17 把"对用户可见的图片地址"整体换成**作品库**：

```
① 上传参考图
   POST /api/images
     ├─ media.save_upload(...)              → storage/{uuid}.png     （照旧，仍是临时缓存）
     ├─ gallery.save_gallery_image(...)     → gallery/{uuid}.png + images 行   （已存在，Spec5）
     └─ 返回 { image_url: "/images/…", image_id: 42 }        ← image_id 是本 Spec 新增

② 发消息
   POST /api/chat { message, image_id: 42, thread_id }
     ├─ 校验 image_id 归属（非本人 / 不存在 → 40403）
     ├─ 路由上下文用 "/api/gallery/42/file" 作为本轮参考图地址
     └─ chat_messages 落一行 { role:'user', text, image_id: 42 }

③ 生成结果
   generation/edit 子 Agent
     ├─ media.save_image(...)               → storage/{uuid}.png     （照旧）
     ├─ gallery.save_gallery_image(...)     → gallery/… + images 行   （已存在）
     └─ result 增加 image_ids: [id]          ← 本 Spec 新增

④ 落库 + 前端渲染
   chat_messages 落一行 { role:'assistant', image_id: id, task_id, tool }
   前端一律用 GET /api/gallery/{id}/file 拉图（带 token → blob → objectURL）
```

**为什么前端渲染非换不可**：历史对话重新载入时 `storage/` 里的文件早就没了。而且这顺带修掉一个既有缺陷——用户开着页面超过 1 小时，之前生成的图会全部裂掉（`storage/` TTL 到期）。

**`media.fetch_image_bytes` 新增一个与 `/images/` 对称的分支**，让子 Agent 能读作品库的图（否则回填的路由上下文里 `edit_image(image_url="/api/gallery/42/file")` 会读不到文件）：

```python
_GALLERY_REF = re.compile(r"^/api/gallery/(\d+)/file$")

def _read_gallery_ref(image_id: int) -> bytes:
    """按 images.id 读 gallery/ 原图（Spec17 §5.2A）。

    与 /images/ 分支对称。**不做归属校验**：调用方是子 Agent，id 来自当前
    用户自己的会话记录，越权无门可入；此函数只在服务端内部被调用，
    不对外暴露任何 HTTP 接口。
    """
    record = db.get_image_record(image_id)
    if record is None:
        raise ImageProcessError(f"图片不存在或已删除: gallery/{image_id}")
    fp = config.GALLERY_DIR / record["file_name"]
    if not fp.exists():
        raise ImageProcessError(f"图片文件缺失: gallery/{image_id}")
    return fp.read_bytes()
```

在 `fetch_image_bytes` 里，**排在 `/images/` 分支之前**（路径前缀不重叠，顺序只是可读性考虑）：

```python
    # 作品库引用（本站内部路径）
    m = _GALLERY_REF.match(image_url)
    if m:
        return _read_gallery_ref(int(m.group(1)))

    # 本站相对路径
    if image_url.startswith("/images/"):
        return _read_storage(image_url)

    parsed = urlparse(image_url)
    # 作品库引用（绝对 URL 形态，需与本站同源）
    if parsed.path and _GALLERY_REF.match(parsed.path):
        return _read_gallery_ref(int(_GALLERY_REF.match(parsed.path).group(1)))
    …
```

`media.py` 需新增 `import db`（顶层）。**无循环导入**：`db.py` 只依赖 `config` / `sqlite3` / `datetime` / `logging`，不反向依赖 `media`。

#### 5.2B 对话的创建、续接与路由上下文回填

```
POST /api/chat
  │
  ├─ 1. thread_id 解析
  │     有 → find_owned_conversation(id, me)；None → 40407
  │     无 → 生成新 id（t_ + uuid4[:8]），**此时还不落库**
  │
  ├─ 2. 参考图归属校验（image_id 非空时）→ 40403
  │
  ├─ 3. await store.ensure_loaded(thread_id, me)      ← 必须在写 user 消息之前
  │       内存里没有这段 → 从 chat_messages 回填最近 20 条
  │       （回填的图片引用用 /api/gallery/{id}/file）
  │
  ├─ 4. ensure_conversation(thread_id, me)            ← 这一步才真正创建 conversations 行
  │     add_chat_message(role='user', text, image_id)
  │
  ├─ 5. queue.submit(...)                             ← 异步，返回 { task_id, thread_id }
  └─ 6. store.append(thread_id, 本轮 user 消息)        ← 内存路由上下文
```

**第 3 步必须早于第 4 步**：否则 `ensure_loaded` 会把刚写进 DB 的这条 user 消息一并回填，第 6 步再 append 一次，同一句话在路由上下文里出现两遍。

`ensure_loaded` 用双检锁保证并发下只灌一次：

```python
async def ensure_loaded(self, thread_id: str, user_id: int) -> None:
    """内存 miss 时从 chat_messages 回填最近 N 条（Spec17 §5.2B）。

    对话持久化后，后端重启 / 换进程之后点历史对话"接着聊"不能失忆——
    原来只在内存里的路由上下文必须能从库里重建。
    """
    async with self._lock:
        if thread_id in self._threads:
            return
    rows = db.list_recent_chat_messages(thread_id, self._limit)
    if not rows:
        return
    entries = [_to_thread_entry(r) for r in rows]
    async with self._lock:
        if thread_id not in self._threads:        # 双检：并发请求只灌一次
            self._threads[thread_id] = deque(entries, maxlen=self._limit)
```

回填条目与 `POST /api/chat` 当场 append 的条目**同形**（Supervisor 的 `_recent_images` / `_build_messages` / `_history_text` 一行都不用改）：

```python
def _to_thread_entry(row: dict) -> dict:
    """chat_messages 行 → ThreadStore 条目（Spec17 §5.2B）。

    形态对齐 POST /api/chat 里 store.append 的写法：
      user      → {"role","text","image_url"}
      assistant → {"role","text","images":[...]}
    图片地址用作品库引用，fetch_image_bytes 认得它（§5.2A）。
    """
    entry = {"role": row["role"], "text": row["text"] or ""}
    if row["image_id"]:
        ref = f"/api/gallery/{row['image_id']}/file"
        if row["role"] == "user":
            entry["image_url"] = ref
        else:
            entry["images"] = [ref]
    return entry
```

#### 5.2C 助手消息落库

在 `_make_handler` 里，`run_supervisor` 返回之后。**成功路径**才落库：

| 结果形态 | 落库内容 |
|---|---|
| `kind == 'text'`（含 clarify 追问） | `role='assistant'`, `text=result.text`, 其余 NULL |
| `kind == 'images'` | `role='assistant'`, `image_id=(result.get("image_ids") or [None])[0]`, `tool=result.tool`, `task_id=task.id` |
| `raise AppError` / 其他异常 | **不落库**（§3.4） |

`image_ids` 可能为空（`generation` / `editing` 里 `gallery.save_gallery_image` 只在 `user_id is not None` 时调用），所以取首项要带 `or [None]` 兜底——避免 `IndexError` 让一个本已成功的任务在落库这一步翻车。

`task_id` 只在 `result.get("tool")` 非空时写入——`tool` 为空即纯文本对话，没有可反馈的对象，前端也不会渲染 👍/👎。

clarify 追问走的是 `kind == 'text'` 分支，**照常落库**（用户在历史里应该看到"助手当时追问了什么"）。

#### 5.2D 发帖（纯文字）

```
POST /api/community  (multipart)
  ├─ text 校验：strip 后 1~COMMUNITY_POST_TEXT_MAX，否则 40011
  ├─ has_gallery = gallery_id is not None
  ├─ has_file    = file is not None and file.filename
  ├─ has_gallery and has_file  → 40011「图片来源最多一张」（仍不允许同时给）
  ├─ 两者皆无                   → 纯文字帖，image_file=None, ext=None
  └─ community.create_post(...) → 写 community/ 文件（仅当有图）+ posts 行
```

`community.create_post` 的签名与分支调整：

```python
def create_post(user_id: int, text: str, *, gallery_id: int | None = None,
                image_bytes: bytes | None = None, ext: str | None = None) -> dict:
    """发帖（文字 + 可选单图），返回 posts 记录 dict。

    Spec17 起图片可选：三者皆空 = 纯文字帖（image_file/ext 落 NULL）。
    """
    if gallery_id is not None:
        record = db.get_image_record(gallery_id)
        if record is None or record["user_id"] != user_id:
            raise GalleryItemNotFoundError()
        image_bytes = _read_gallery_file(record["file_name"])
        ext = record["ext"]

    if image_bytes is None:                      # Spec17：纯文字帖
        return db.create_post_record(user_id, text, None, None)

    file_name = f"{uuid.uuid4().hex}{ext}"
    (config.COMMUNITY_DIR / file_name).write_bytes(image_bytes)
    post = db.create_post_record(user_id, text, file_name, ext)
    if gallery_id is None:
        gallery.save_gallery_image(image_bytes, user_id, "upload", None)
    return post
```

`list_posts` 的 `image_url` 改为可空：

```python
def list_posts(user_id: int, offset: int, limit: int) -> list[dict]:
    """社区帖子列表（最新在前）；图片可空，评论全量内嵌（Spec17 §5.2E）。"""
    posts = db.list_posts(user_id, offset, limit)
    # 一次批量取全部评论再分组，避免每帖一次查询（N+1）
    by_post = db.list_comments_for_posts([p["id"] for p in posts])
    items = []
    for p in posts:
        item = dict(p)
        item["image_url"] = (f"/api/community/{p['id']}/image"
                             if p["image_file"] else None)
        item["comments"] = [_comment_out(c) for c in by_post.get(p["id"], [])]
        items.append(item)
    return items
```

`read_post_image` / `_unlink_community_file` 需容忍 `image_file is None`：

```python
def read_post_image(post_id: int) -> tuple[dict, bytes]:
    post = db.get_post_record(post_id)
    if post is None or not post["image_file"]:      # Spec17：纯文字帖没有图
        raise PostNotFoundError()
    return post, _read_community_file(post["image_file"])


def _unlink_community_file(file_name: str | None) -> None:
    if not file_name:                               # Spec17：纯文字帖无文件
        return
    try:
        (config.COMMUNITY_DIR / file_name).unlink(missing_ok=True)
    except OSError:
        pass
```

`delete_post_record` / `delete_user_post_records` 返回的 `image_file` 可能为 `None`，调用方（`community.delete_post` / `delete_user_posts`）走的正是上面这个 `_unlink_community_file`，天然兼容。

#### 5.2E 评论

```
GET /api/community
  └─ community.list_posts(...)
       ├─ db.list_posts(...)                       一次查帖子
       └─ db.list_comments_for_posts([ids...])     一次查评论 + JOIN users
            └─ 按 post_id 分组挂到每项上            ← 前端零额外请求

POST /api/community/{post_id}/comments
  ├─ 校验帖子存在（40404）
  ├─ 校验文字 1~COMMENT_TEXT_MAX（40016）
  ├─ db.create_comment(...)  → 带 author / author_is_admin 返回
  └─ 前端本地 append 到该帖的 comments 数组（不重拉列表）

DELETE /api/community/{post_id}/comments/{comment_id}
  ├─ 评论不存在 / 不属于该帖 → 40408
  ├─ 非作者且非管理员 → 40303
  └─ db.delete_comment(id) → 前端本地 remove
```

评论输出的统一形态（列表内嵌与新增返回**同形**，前端可以无差别 append）：

```python
def _comment_out(record: dict) -> dict:
    return {
        "id": record["id"],
        "post_id": record["post_id"],
        "author": record["author"],
        "author_is_admin": bool(record["author_is_admin"]),
        "text": record["text"],
        "created_at": record["created_at"],
    }
```

### 5.3 一致性 / 失败语义

- **对话创建是"消息驱动"的**：`ensure_conversation` 用 `INSERT ... ON CONFLICT(id) DO NOTHING` 语义（先查后插或 upsert），保证并发两次提交同一 `thread_id` 不会撞主键。
- **消息追加 + `touch_conversation` 同一事务**：`add_chat_message` 内部一个 `with _connect() as conn:` 里完成 INSERT 与 UPDATE `conversations.updated_at`，避免出现"消息在但顺序不对"。
- **用户消息先落库、助手消息后落库**：助手任务可能失败、超时或被排队拒绝。用户消息已经落库（第 4 步，同步），助手消息只在成功回调里写——**失败时该轮就只有用户那一句**（§3.4）。
- **失败路径仍走内存 ThreadStore**：`handle_task` 里 `store.append({"role":"assistant","text":"（任务失败：…）"})` 保留不变。它只影响本轮之后的路由上下文，**不落库**、用户不可见。
- **删对话是幂等的**：`DELETE /api/conversations/{id}` 对不存在的 id → `40407`（而非静默成功），因为前端只会在自己的列表里拿到 id，触发即 bug。
- **图片悬挂引用的处理**：`chat_messages.image_id` 指向已删除的 `images` 行时，`GET /api/gallery/{id}/file` 返回 `40403` → 前端渲染「图片已删除」占位。**服务端不做额外补偿**（不删消息、不置 NULL）——保留用户"这里曾经有张图"的信息比抹掉它更有用。
- **评论删除后不重排**：`id` 是自增主键，删除中间某条不会影响其余的顺序或 id。前端本地 remove 即可，无需重拉。
- **`task_id` 单调性**：计数器只在 `submit` 成功取号后写回；`QueueFull` 时已取的号被烧掉（产生空洞）。**空洞无害**，`feedback` 只要求唯一不要求连续。

---

## 6. 接口约定

统一响应体 `{ "code": 200, "message": "ok", "data": ... }`（Spec §8）；除 `POST /api/auth/login` 外全部需要 `Authorization: Bearer <JWT>`。

### 6.1 变更：`POST /api/images`

**请求**：不变（multipart，`file`）。

**响应 `data`**：新增 `image_id`。

```json
{ "image_url": "/images/3f2a….png", "image_id": 42 }
```

```python
# schemas.py —— 替换 Spec §8 的 UploadOut
class UploadOut(BaseModel):
    """POST /api/images 返回。image_id 为作品库记录 id（Spec17 §6.1）。"""
    image_url: str
    image_id: int
```

路由改动（`image_id` 来自已经存在的那次入库调用，Spec5「上传即入库」，只是原先丢弃了返回值）：

```python
    url = media.save_upload(data, _public_base(request), ext)
    # 上传即入库：除临时 storage/ 外，额外持久化到个人作品库（Spec5 §5.2 链路 1）
    # Spec17：返回值不再丢弃——前端要把 image_id 带进 /api/chat
    record = gallery.save_gallery_image(data, request.state.user["id"], "upload", None)
    return _ok({"image_url": url, "image_id": record["id"]})
```

### 6.2 变更：`POST /api/chat`

**请求体**（`ChatRequest` 新增 `image_id`）：

```python
class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""
    message: str = Field(..., min_length=1, max_length=8000)
    image_url: Optional[str] = Field(None, description="参考图地址（本站路径或绝对 URL）")
    image_id: Optional[int] = Field(None, description="作品库图片 id（Spec17 §6.2；优先于 image_url）")
    thread_id: Optional[str] = Field(None, description="对话 id；复用则续接上下文")
```

| 字段 | 变化 |
|---|---|
| `thread_id` | **语义收紧**：必须是**本人的**对话 id。不属于本人或不存在 → `40407`（原先接受任意字符串） |
| `image_id` | **新增**，可选。给了就优先用它：校验归属（`40403`）→ 路由上下文用 `/api/gallery/{id}/file` → 落库记 `image_id` |
| `image_url` | **保留**，作为 `image_id` 缺席时的回退（外部 URL 等场景）。前端 Spec17 起只传 `image_id` |

**已知限制（只传 `image_url` 的调用方）**：此时 `chat_messages.image_id` 落 `NULL`，**该轮用户消息的配图不会被持久化**——路由上下文当轮仍能正常用到它（走 `storage/`），但刷新页面后用户气泡只剩文字。Spec17 之后前端一律传 `image_id`，这条只影响手工调 API / 外部集成方。不为此做兼容（要把 `image_url` 反查成 `images` 行需要"上传即入库"时回传文件名映射，为一个没有实际调用方的场景引入状态，不值得）。

**响应**：不变（`{ task_id, thread_id, status }`）。

### 6.3 新增：`GET /api/conversations`

本人对话列表，`updated_at` 倒序，最多 `CONVERSATION_LIST_LIMIT` 条。

```json
{ "items": [
    { "id": "t_9f3a2b1c", "created_at": "2026-09-15T06:30:12.345Z",
      "updated_at": "2026-09-15T06:41:55.001Z" }
] }
```

| 项 | 说明 |
|---|---|
| `id` | 对话 id（= `thread_id`），传给 `GET /api/conversations/{id}/messages` 或 `POST /api/chat` |
| `created_at` | **发起时间**，侧边栏显示它（前端转本地时区，格式化成 `2026-09-15 14:30 的对话`） |
| `updated_at` | 最后一条消息时刻，仅用于排序，前端不显示 |

不带 `message_count`、不返回首条消息摘要——**YAGNI**，侧边栏只显示时间。

**鉴权**：登录即可，只返回本人的（`WHERE user_id = ?`）。无管理员视角。

### 6.4 新增：`GET /api/conversations/{conv_id}/messages`

某段对话的全部消息，**按时间正序**（`id ASC`）。

```json
{
  "conversation": { "id": "t_9f3a2b1c", "created_at": "…", "updated_at": "…" },
  "messages": [
    { "id": 12, "role": "user", "text": "做一张新年海报",
      "image_id": null, "task_id": null, "tool": null, "created_at": "…" },
    { "id": 13, "role": "user", "text": "参考这张",
      "image_id": 42, "task_id": null, "tool": null, "created_at": "…" },
    { "id": 14, "role": "assistant", "text": null,
      "image_id": 43, "task_id": 107, "tool": "generate_image", "created_at": "…" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `id` | `chat_messages.id`（整数）。前端包成 `m_<id>` 作为列表 key，避免与临时的 `u_*` / `p_*` 字符串 id 冲突 |
| `role` | `'user'` \| `'assistant'` |
| `text` | 文本内容，可空（纯图片消息） |
| `image_id` | 作品库图片 id，可空。前端用 `GET /api/gallery/{id}/file` 渲染 |
| `task_id` / `tool` | 仅助手工具结果有值，前端据此渲染 👍/👎 反馈行（Spec9 §6.2 不变） |

**注意**：这里**不返回 `vote`**。用户在某条结果上点过 👍 还是 👎，Spec9 起就只存在前端气泡上（`feedback` 表按类聚合、不记"我选了什么"）。Spec17 **不改变这个口径**——重新载入的历史气泡上反馈按钮显示为未选，点击仍可正常投票/切换/取消。

**鉴权**：`find_owned_conversation` → 不存在或不属于本人 → `40407`。

### 6.5 新增：`DELETE /api/conversations/{conv_id}`

删除本人的某段对话及其全部消息。

```json
{ "id": "t_9f3a2b1c" }
```

- 不存在 / 不属于本人 → `40407`。
- **不删除任何图片**（§2.1、§5.2B）；已在「我的作品」里的图不受影响。
- 幂等性：重复删除第二次返回 `40407`（不是静默 200）。

### 6.6 删除：`GET /api/threads/{thread_id}/messages`

**移除该路由**，连同 `schemas.py` 的 `ThreadMessage` / `ThreadOut`、前端 `api/chatApi.js` 的 `getThread()`（死代码，从未被调用）。

替代品是 §6.4 的 `GET /api/conversations/{conv_id}/messages`（DB 支撑、重启不丢、无 20 条上限、不含内部失败记录）。

### 6.7 变更：`POST /api/community`

**请求**：不变（multipart：`text` 必填，`gallery_id` / `file` 可选）。

**校验变化**：

| 情形 | 现在 | Spec17 |
|---|---|---|
| 两者都给 | `40011`「图片来源需二选一」 | `40011`「图片来源最多一张」 |
| 两者都不给 | `40011`「图片来源需二选一」 | **合法 → 纯文字帖** |
| `text` 空 / 超 1000 字 | `40011` | 不变 |

**响应 `data.post`**：`image_url` 变为可空。

```json
{ "post": { "id": 7, "text": "今天试了新的配色思路…",
            "author": "fj", "author_is_admin": false,
            "image_url": null,
            "like_count": 0, "dislike_count": 0, "my_vote": null,
            "comments": [],
            "created_at": "…" } }
```

### 6.8 变更：`GET /api/community`

**响应 `data.items[]`** 每项新增 `comments` 数组，`image_url` 变为可空（§5.2D / §5.2E）：

```json
{ "items": [
    { "id": 7, "text": "…", "author": "fj", "author_is_admin": false,
      "image_url": null, "like_count": 2, "dislike_count": 0, "my_vote": "like",
      "comments": [
        { "id": 31, "post_id": 7, "author": "lisi", "author_is_admin": false,
          "text": "同感，构图也稳", "created_at": "…" }
      ],
      "created_at": "…" }
] }
```

分页参数（`offset` / `limit`）**不变**；`limit ≤ 100` 不变。**评论全量内嵌、不参与分页**（§2.3）。

### 6.9 变更：`GET /api/community/{post_id}/image`

纯文字帖（`image_file IS NULL`）→ `40404 PostNotFoundError`（§2.2）。

### 6.10 新增：评论三个接口

#### `POST /api/community/{post_id}/comments`

**请求**：`{ "text": "同感，构图也稳" }`

```python
class CommentCreateRequest(BaseModel):
    """POST /api/community/{post_id}/comments 请求体。长度校验在路由层（40016）。"""
    text: str
```

**响应**：`{ "comment": { …与列表内嵌的评论同形… } }`

| 错误 | 码 |
|---|---|
| 帖子不存在 | `40404` |
| `text` strip 后为空 / 超 `COMMENT_TEXT_MAX` | `40016` |

#### `GET /api/community/{post_id}/comments`

**响应**：`{ "items": [ … ] }`，按 `id ASC`（时间正序）。帖子不存在 → `40404`。

> 该接口与 `GET /api/community` 内嵌的 `comments` **内容完全一致**，返回项也同形。
> **前端不调用它**（评论已随帖子列表内嵌返回），保留的理由见 §2.3 决策记录：`POST` / `DELETE` 挂在 `/comments` 下而缺 `GET` 会让资源形态残缺，也无法用 curl 单独验证某帖的评论。

#### `DELETE /api/community/{post_id}/comments/{comment_id}`

**响应**：`{ "id": 31 }`

| 错误 | 码 |
|---|---|
| 评论不存在 / 不属于该 `post_id` | `40408` |
| 非作者且非管理员 | `40303` |

**路径里带 `post_id`**：与 `DELETE /api/community/{post_id}` 的既有形态保持嵌套一致，且能校验"这条评论确实挂在这个帖子上"，防止用 `post_id=A` + `comment_id=别人的B帖评论` 这种错配（否则权限判断会对着错误的帖子做）。

### 6.11 不变

- `GET /api/tasks/{task_id}`：契约与行为完全不变（`task_id` 只是变成单调递增，语义不变）。
- `POST /api/community/{post_id}/vote`、`POST /api/feedback`、`POST /api/shares`、建议箱全部接口、`/api/gallery/*`、`/api/wiki/*`、`/api/admin/*`：**一行不改**。
- `GET /api/gallery/{item_id}/file`：Spec17 起被聊天渲染复用，但其**契约、鉴权（40403）、下载参数都不变**——只是调用方多了一个。

---

## 7. 前端交互

### 7.1 `composables/useAuthedImage.js`（新增）

站内图片都要带 `Authorization` 头拉取（`<img src>` 无法带头），既有 `GalleryPanel.vue` / `CommunityPanel.vue` 各写了一份 objectURL 拉取 + 释放逻辑。Spec17 引入第三处（聊天气泡），**抽成一个共用 composable**，三处共用：

```js
// composables/useAuthedImage.js
//
// 站内图片渲染（Spec17 §7.1）：<img> 无法带 Authorization 头，
// 统一用带 token 的 axios 拉 blob → objectURL。
// 模块级缓存带引用计数：同一张图在多个位置出现时只拉一次，全部卸载后才 revoke。

/**
 * 单张响应式拉取。idSource 是 ref/getter，返回 image_id 或 null。
 * 返回 { src, missing, loading }：
 *   src     可用的 objectURL；未就绪 / 失败为空串
 *   missing true = 后端返回 404（图片已被用户在「我的作品」里删除）→ 渲染占位
 */
export function useAuthedImage(idSource) { … }

/**
 * 列表批量填充：给每个 item 按 getId 拉图，写入 item[key]（默认 'objectUrl'）。
 * 与单张共享同一个缓存与引用计数。
 */
export function attachObjectUrls(items, fetchFile, { getId, key = 'objectUrl' } = {}) { … }

/** 释放某个 item 的引用（列表刷新 / 组件卸载时调用）。 */
export function releaseObjectUrl(item, key = 'objectUrl') { … }
```

**缓存键**必须区分来源：聊天/作品库用 `gallery:<id>`，社区帖子用 `community:<postId>`——两者 id 空间不同，不能混用一个 Map。

`missing` 状态是聊天场景特有的（§3.4 图片悬挂引用）。`GalleryPanel` / `CommunityPanel` 迁移过来后忽略该字段即可。

**迁移范围**：`GalleryPanel.vue` 的 `objectUrl` 填充/释放、`CommunityPanel.vue` 的 `post.objectUrl` / `item.objectUrl` 填充/释放，改为调用本 composable；**行为不变**，只是不再各留一份。

### 7.2 `api/chatApi.js`

| 函数 | 变化 |
|---|---|
| `uploadImage(file)` | 返回值从 `image_url` 字符串改为 `{ imageUrl, imageId }` |
| `sendChat({ message, imageUrl, imageId, threadId })` | 请求体加 `image_id` |
| `getThread(threadId)` | **删除**（死代码 + 后端路由已移除） |
| `listConversations()` | 新增 → `GET /api/conversations` |
| `getConversation(convId)` | 新增 → `GET /api/conversations/{id}/messages` |
| `deleteConversation(convId)` | 新增 → `DELETE /api/conversations/{id}` |
| `createCommunityPost(...)` | 注释更新：图片可选 |
| `createComment(postId, text)` | 新增 → `POST /api/community/{postId}/comments` |
| `deleteComment(postId, commentId)` | 新增 → `DELETE /api/community/{postId}/comments/{commentId}` |

**不加 `listComments(postId)`**：评论随 `GET /api/community` 内嵌返回，前端没有单独拉取的时机。Spec17 刚因为"定义了从没被调用的 `getThread()`"而删掉一处死代码（§6.6），不该立刻补一个新的。（后端的 `GET /api/community/{post_id}/comments` 保留，理由见 §2.3。）

```js
export async function uploadImage(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/api/images', form)
  return { imageUrl: data.data.image_url, imageId: data.data.image_id }
}

export async function sendChat({ message, imageUrl, imageId, threadId }) {
  const { data } = await http.post('/api/chat', {
    message,
    image_url: imageUrl || null,
    image_id: imageId ?? null,
    thread_id: threadId || null
  })
  return data.data // { task_id, thread_id, status }
}
```

### 7.3 `store/chat.js`（重写）

**不再读写 localStorage 的聊天内容**。唯一的 localStorage 键是「上次所在的对话」：

```js
function currentConvKey(username) { return `artcn_current_conv:${username}` }
```

**state**

```js
{
  username: '',           // 当前历史归属用户；未登录为空串 → 不拉不写
  conversations: [],      // [{ id, created_at, updated_at }]，updated_at 倒序
  currentConvId: null,    // null = 尚未开始的空对话
  messages: [],           // 与后端 chat_messages 同形，见下表
  sending: false,
  loadingConv: false      // 切换对话时的加载态（防连点）
}
```

**前端消息形态**（与后端字段的对应关系）：

| 前端字段 | 来源 | 说明 |
|---|---|---|
| `id` | `m_<chat_messages.id>` | 历史消息；临时的用 `u_*`（用户）/ `p_*`（pending）/ `e_*`（错误） |
| `role` | `role` | `'user'` \| `'assistant'` |
| `kind` | 现算 | 助手：`image_id` 有值 → `'images'`，否则 `'text'`；另有临时的 `'pending'` / `'error'` |
| `text` | `text` | 可空 |
| `imageId` | `image_id` | 渲染走 `useAuthedImage` |
| `imageUrlPreview` | 本地 `URL.createObjectURL(file)` | **仅**用户刚选中、尚未上传成功时的本地预览 |
| `tool` / `taskId` / `vote` | `tool` / `task_id` / 本地 | 反馈行（Spec9 口径不变，`vote` 不来自后端） |
| `request` | 本地 | `{ text, imageId }`，供错误气泡"重试"复用 |

**actions**

| action | 行为 |
|---|---|
| `resetForUser(username)` | 清空全部状态；`username` 非空 → `refreshConversations()` + 载入上次的对话 |
| `refreshConversations()` | `GET /api/conversations` → 填 `conversations` |
| `newConversation()` | `currentConvId = null`、`messages = []`、清掉本地的 `artcn_current_conv`。**不调后端**（对话行在发出第一条消息时才创建） |
| `openConversation(id)` | `GET /api/conversations/{id}/messages` → 填 `messages`、`currentConvId = id`、写 localStorage |
| `deleteConversation(id)` | `confirm` → `DELETE` → 本地移除该条；若删的是当前对话 → `openConversation(列表首条)`，列表空则 `newConversation()` |
| `send(text, file)` | 结构不变，图片改为先 `uploadImage` 拿 `{imageUrl, imageId}` → 存 `imageId` |
| `submit(request, pendingId)` | `sendChat({ message, imageId, threadId: currentConvId })`；**首次发送成功后** `currentConvId = chat.thread_id` + `refreshConversations()`（新对话此时才出现在侧边栏） |
| `pollTask` / `replaceMessage` / `messageById` / `retry` / `toggleFeedback` | 逻辑不变，仅适配新的消息形态（`images[]` → `imageId`） |

**载入策略**（刷新页面后）：

```
读 localStorage 的 artcn_current_conv:<username>
  ├─ 有，且出现在 conversations 列表里 → openConversation(它)
  ├─ 有但不在列表里（已被删 / 换用户）→ 载入列表首条
  └─ 没有                            → 列表非空 ? 载入首条 : newConversation()
```

**登录切换**：`resetForUser` 由 `App.vue` 的 `watch([auth.loaded, auth.username])` 触发（Spec3 §5.2 既有机制，不改）。

### 7.4 `components/ConversationSidebar.vue`（新增）

```
┌───────────┐
│ + 新对话  │   ← 顶部固定，主按钮
│───────────│
│ 2026-09-15│   ← 可滚动列表，updated_at 倒序
│  14:30    │
│  的对话 ✕ │   ← hover 显示删除按钮
│───────────│
│ 2026-09-14│
│  09:05    │
│  的对话 ✕ │
└───────────┘
```

- **props / emits**：`props: { conversations, currentId }`；`emits: ['new', 'open', 'delete']`（纯展示组件，状态在 store 里）。
- **时间格式**：`created_at`（UTC ISO）→ `new Date(...)` → 本地时区 → `YYYY-MM-DD HH:mm 的对话`。**一律精确到分**，不做"今天/昨天"友好化（§2.1 作者拍板）。
  ```
  2026-09-15 14:30 的对话
  ```
  时间与「的对话」之间允许换行（窄侧边栏里 `display: block` 分两行更好读，见 §7.8 样式约定）。
- **当前对话高亮**：`currentId === conv.id` 时用 `--purple-600` 左标记 + 浅紫底。
- **删除**：`confirm('删除这段对话？聊天记录将被永久清除（作品库里的图片不受影响）')`。
- **空态**：没有任何对话时显示一行淡色提示「还没有对话，点「新对话」开始」。
- **新对话按钮**：`currentConvId === null` 时置灰禁用（已经在空对话里了）。

### 7.5 `App.vue`

**布局改为 flex row**，侧边栏只在聊天视图渲染：

```
<div class="app">
  <ConversationSidebar v-if="isChatView" … />
  <div class="main-col">
    <header class="app-header"> … </header>
    <GalleryPanel v-if="showGallery" … />     ← 以下五个面板互斥，保持原样
    <template v-else> <main class="chat-scroll"> … <ChatInput /></template>
  </div>
</div>
```

| 变化 | 说明 |
|---|---|
| `isChatView`（computed） | `!showGallery && !showAdmin && !showStats && !showCommunity && !showSuggestions` |
| **「清空」按钮删除** | 头部不再有它（`onClear` 一并删除） |
| 「新对话」 | 移到侧边栏顶部（`ConversationSidebar` 内部） |
| 侧边栏事件 | `@new="store.newConversation()"`、`@open="store.openConversation"`、`@delete="store.deleteConversation"` |
| 滚动到底 | `watch(() => store.messages, scrollToBottom, { deep: true })` 保留；**切换对话后**也要滚到底（`openConversation` 完成后调用一次） |

### 7.6 `components/ChatBubble.vue`

图片从 `message.images[]`（URL 数组）改为 `message.imageId`（单个 id），渲染改走 `useAuthedImage`：

| 位置 | 现在 | Spec17 |
|---|---|---|
| 用户消息配图 | `<img :src="message.imageUrl \|\| message.imageUrlPreview">` | 有 `imageId` → `useAuthedImage` 的 `src`；仅有 `imageUrlPreview`（上传中）→ 直接用本地预览 |
| 助手结果图 | `v-for="img in message.images"` → `<img :src="img">` | 单个 `message.imageId` → `useAuthedImage` 的 `src` |
| 图片缺失 | 无处理（裂图） | `missing === true` → 渲染「图片已删除」占位框（虚线边框 + 淡色文字），**不可点开大图** |

其余（pending / text / error / 反馈行）**不变**。

助手结果图外面那层 `<a :href="img" target="_blank">` 改为：`src` 就绪时点击用 `window.open(src)` 打开同一 objectURL（`href` 指向 blob URL 也行，保留 `<a :href="src">` 即可）。

### 7.7 `views/CommunityPanel.vue`

**发帖弹窗**：

- 图片来源从"二选一必选"改为**可选**。原 Tab（作品库选择 / 上传新图）保留，加一个「不配图」的清除入口（再点当前选中的 Tab = 取消选择，或加一个「×」）。
- 提示文案改为「文字 1~1000 字，配图可选」。
- 提交时：`galleryId` 与 `file` 都没有 → 不 append 任何图片字段。

**帖子卡片**：

- 图片区 `v-if="post.image_url"`，纯文字帖**不渲染该区域**（卡片自然变矮，文字也不做额外拉伸）。
- 反馈行右侧加 `💬 评论 N`（`N = post.comments.length`）——**只是计数展示，不承担展开/收起功能**（评论区总是内联可见）。

**评论区**（卡片底部，内联）：

```
├────────────────────────────────┤
│ 李四：同感，构图也稳      [删除] │
│ 王五：求 prompt！        [删除] │  ↕ 固定高 ~200px，
│ 赵六：这个配色好看       [删除] │     超出滚动
│ …（还没有评论时：淡色一行「还没有评论，来说两句」）
├────────────────────────────────┤
│ [写评论…（≤200字）]      [发表] │
└────────────────────────────────┘
```

- 每条显示 **`author` + 内容**，`created_at` 显示为 `MM-DD HH:mm`（评论密集，不显示年份；跨年帖子可接受的信息损失）。
- 删除按钮 `v-if="comment.author === auth.username || auth.is_admin"`（与纯前端隐藏一致——后端仍会独立校验并返回 `40303`）。
- 删除 → `confirm` → `deleteComment` → 本地 `splice` 移除。
- 输入：单行 `input`，`maxlength=200`，右侧实时计数 `N/200`；`Enter` 或点「发表」提交；空串不发。
- 发表成功 → 本地 `post.comments.push(comment)`，并同步 `💬 评论 N` 计数。

**顶部提示行删除**：删掉 `CommunityPanel.vue:11` 整个 `<p class="admin-tip">…</p>`（含 `当前登录：… · 社区对所有人可见 · 单图 + 文字`），以及只服务于它的样式规则。作者拍板「整行删掉，不要再加，保持干净」。

### 7.8 样式约定（`assets/styles/main.css`）

**必须复用 `:root` 里既有变量**（Spec §5.1 的紫色主题），不新增色值：

```css
/* Spec17：对话侧边栏（聊天视图左侧常驻） */
.conv-sidebar            /* 宽 260px，flex-shrink:0，右描边 1px var(--border)，
                            纵向 flex：顶部按钮区固定 + 列表区 overflow-y:auto */
.conv-sidebar-new        /* 主按钮：var(--purple-600) 底、白字、通宽 */
.conv-item               /* 列表项：纵向排列，时间与「的对话」分两行 */
.conv-item-time          /* 13px，var(--text-secondary) */
.conv-item-label         /* 13px，var(--text-muted) */
.conv-item.active        /* 浅紫底 + 左侧 3px var(--purple-600) 标记 */
.conv-item-del           /* 仅 hover 时显示，12px，var(--text-muted) */

/* Spec17：聊天图片缺失占位 */
.bubble-img-missing      /* 虚线边框 + 居中淡色文字「图片已删除」，与 .bubble-img 同尺寸约束 */

/* Spec17：帖子评论区（内联滚动区） */
.post-comments           /* max-height: 200px; overflow-y: auto; 上描边 1px var(--border) */
.comment-row             /* 单条：作者名 var(--purple-600) + 内容，两行截断 */
.comment-empty           /* 淡色空态一行 */
.comment-form            /* 输入行：input 撑满 + 右侧按钮 */
.comment-count           /* 实时字数，12px，var(--text-muted) */
```

`.app` 由纵向改为 `display: flex`；新增 `.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; }`（`min-width: 0` 必须有，否则聊天内容会把 flex 子项撑破）。

**响应式**：窄屏（≤768px）时侧边栏收成 `width: 0`（隐藏）——本 Spec **不实现移动端抽屉**，只在窄屏隐藏侧边栏，历史对话在窄屏下不可访问。这是明确的取舍（§3.1 范围外未列，但属已知限制）。

---

## 8. 配置 / 环境变量 / .gitignore

`Server/config.py` 新增两项（**均有默认值，不配可跑**）：

```python
# ===== 社区评论（Spec17）=====
COMMENT_TEXT_MAX = int(os.getenv("COMMENT_TEXT_MAX", "200"))   # 评论字数上限（前后端同值）
# 注意：前端 CommunityPanel.vue 的 COMMENT_TEXT_MAX 是同值副本，改这里必须同步改前端

# ===== 对话历史（Spec17）=====
CONVERSATION_LIST_LIMIT = int(os.getenv("CONVERSATION_LIST_LIMIT", "50"))  # 侧边栏一次返回的对话条数上限
```

`Server/.env.example` 追加同名占位（附注释说明单位与默认值）。

**`.gitignore` 无需改动**：本 Spec **不新增任何持久目录**（聊天图片复用既有的 `Server/gallery/`），`artcn.db` 已在忽略列表里。

---

## 9. 错误码

新增 4 个，追加到 Spec16 §9 的 `GalleryNoteError` 之后：

```python
# ---- 对话历史（Spec17 §9，追加到 Spec16 §9 之后）----

class ConversationNotFoundError(NotFoundError):
    """对话不存在或不属于当前用户（越权访问他人对话同样 404，不泄露存在性）。"""

    def __init__(self, message="对话不存在或不属于当前用户"):
        super().__init__(message, code=40407)


# ---- 帖子评论（Spec17 §9）----

class CommentContentError(BadRequestError):
    """评论内容非法（strip 后为空，或超过 COMMENT_TEXT_MAX）。"""

    def __init__(self, message="评论内容非法"):
        super().__init__(message, code=40016)


class CommentForbiddenError(AppError):
    """无权删除该评论（非作者且非管理员）。"""

    def __init__(self, message="无权删除该评论"):
        super().__init__(40303, message, status_code=403)


class CommentNotFoundError(NotFoundError):
    """评论不存在或不属于该帖子。"""

    def __init__(self, message="评论不存在"):
        super().__init__(message, code=40408)
```

**复用不新增**：

| 场景 | 复用 | 理由 |
|---|---|---|
| `POST /api/chat` 的 `image_id` 不属于本人 | `40403 GalleryItemNotFoundError` | 与 Spec5/16 的作品越权口径完全一致，不泄露存在性 |
| 纯文字帖取图 | `40404 PostNotFoundError` | "该帖没有图"在取图语境下就是"不存在"（§2.2） |
| 发帖双来源 / 文字超长 | `40011 PostContentError` | 同一类"帖子内容非法"（§2.2） |
| 评论所属帖子不存在 | `40404 PostNotFoundError` | 复用帖子口径，不为"给不存在的帖子评论"单独开码 |

**错误码全表（Spec17 后）**：

| 码 | 类 | HTTP | 场景 |
|---|---|---|---|
| 40011 | `PostContentError` | 400 | 帖子文字空/超长；图片来源同时给了两个 |
| 40015 | `GalleryNoteError` | 400 | 作品备注非法（Spec16） |
| **40016** | **`CommentContentError`** | **400** | **评论空/超长** |
| 40301 | `ForbiddenError` | 403 | 非管理员访问 `/api/admin/*` |
| 40302 | `PostForbiddenError` | 403 | 删他人帖子 |
| **40303** | **`CommentForbiddenError`** | **403** | **删他人评论** |
| 40403 | `GalleryItemNotFoundError` | 404 | 作品不存在/非本人（含 `image_id` 越权） |
| 40404 | `PostNotFoundError` | 404 | 帖子不存在；纯文字帖取图 |
| 40405 | `ShareNotFoundError` | 404 | 分享失效（Spec9） |
| 40406 | `SuggestionNotFoundError` | 404 | 建议不存在（Spec9） |
| **40407** | **`ConversationNotFoundError`** | **404** | **对话不存在/非本人** |
| **40408** | **`CommentNotFoundError`** | **404** | **评论不存在/不属于该帖** |

---

## 10. 日志约定

沿用 Spec §10 的单行 JSON，新增事件：

| event | 触发 | 附带字段 |
|---|---|---|
| `chat.conversation_started` | 首次为某 `thread_id` 创建 `conversations` 行 | `thread_id`, `user_id` |
| `chat.conversation_deleted` | 删除对话成功 | `thread_id`, `user_id`, `messages`（被删消息条数） |
| `community.commented` | 发表评论成功 | `post_id`, `comment_id`, `user_id` |
| `community.comment_deleted` | 删除评论成功 | `post_id`, `comment_id`, `actor_id`, `by_admin` |
| `db.migrate` | `posts` 重建表迁移执行 | （沿用 Spec12/16 的既有 event 名） |

**不新增**消息级日志（`chat.message_persisted` 之类）——每条消息都打会让日志被聊天内容淹没，而 `task.submitted` / `task.completed` 已经能追踪到每一轮。

**隐私**：评论正文**不入日志**（与 Spec16 §10 对作品备注的处理一致，用户私人文字只记 `post_id` / `comment_id`）。对话消息正文同样**不入日志**（现有 `chat.submitted` 只记 `thread_id` / `task_id`，保持不变）。

---

## 11. 目录结构增量

```
Server/
  chat_history.py                  # 新增：对话与消息的业务层（鉴权、落库编排、ThreadStore 回填）
  db.py                            # 增量：3 张建表 + 2 个索引 + posts 重建迁移
                                   #       + task_id_seq 键 + set_meta + 对话/消息/评论 CRUD
                                   #       + delete_user / delete_post_record 级联补评论与对话
  main.py                          # 增量：/api/conversations 三个路由、评论三个路由；
                                   #       改 POST /api/chat、POST /api/images、POST /api/community、GET /api/community；
                                   #       删 GET /api/threads/{thread_id}/messages；ThreadStore.ensure_loaded
  media.py                         # 增量：fetch_image_bytes 支持 /api/gallery/{id}/file 引用
  community.py                     # 增量：create_post 支持纯文字；评论业务层；_unlink 容忍 None
  config.py                        # 增量：COMMENT_TEXT_MAX、CONVERSATION_LIST_LIMIT
  errors.py                        # 增量：40407 / 40016 / 40303 / 40408
  schemas.py                       # 增量：ChatRequest.image_id、UploadOut.image_id、
                                   #       CommentCreateRequest；删 ThreadMessage / ThreadOut
  task_queue.py                    # 增量：task_id 计数器从 app_meta 续号并写回
  agents/generation.py             # 增量：result 增加 image_ids
  agents/editing.py                # 增量：result 增加 image_ids
  .env.example                     # 增量：2 个可选变量

frontend/src/
  components/ConversationSidebar.vue   # 新增
  composables/useAuthedImage.js        # 新增（三处共用）
  store/chat.js                        # 重写（去 localStorage，接管对话列表）
  App.vue                              # 增量：flex 布局 + 侧边栏；删「清空」
  components/ChatBubble.vue            # 增量：imageId + useAuthedImage + 缺失占位
  views/CommunityPanel.vue             # 增量：可无图发帖、纯文字卡片、评论区；删顶部提示行
  views/GalleryPanel.vue               # 增量：迁移到 useAuthedImage（行为不变）
  api/chatApi.js                       # 增量：对话 3 个 + 评论 3 个；改 uploadImage/sendChat；删 getThread
  assets/styles/main.css               # 增量：侧边栏 / 缺失占位 / 评论区样式

specs/Spec17.md                        # 本文件
```

**无新增持久目录**——这是本 Spec 的一个刻意结果（§2.1 第 1 条）。

---

## 12. 实施顺序（里程碑）

依赖关系决定顺序，**每一步都能独立跑起来**：

1. **M1 — 数据层地基**
   `db.py`：3 张建表 + 2 个索引 + `_migrate_posts_nullable_image` + `TASK_ID_SEQ_KEY` + `set_meta` + `delete_user` 级联补全。
   `task_queue.py`：计数器从 `app_meta` 续号 + 写回。
   验证：启动后 `sqlite3 Server/artcn.db ".schema posts"` 应无 `NOT NULL`；重启两次，`task_id` 连续不回头。

2. **M2 — 对话后端**
   `chat_history.py` + `main.py` 的 `/api/conversations` 三路由 + `POST /api/chat` 的 `thread_id` 归属校验 + `ThreadStore.ensure_loaded`，以及 `generation.py` / `editing.py` 返回 `image_ids` + 助手消息落库。
   验证（curl + 查库，前端还没改）：§13「对话历史」#2、#9~#12、#14。

3. **M3 — 图片引用链**
   `media.py` 的 gallery 引用分支；`POST /api/images` 返回 `image_id`；`ChatRequest.image_id` + 归属校验；`chat_messages.image_id` 落库。
   验证：§13「图片引用链」#15、#18、#19（后端可独立验）；#16、#17、#20、#21 待 M4。

4. **M4 — 对话前端**
   `useAuthedImage` + `api/chatApi.js` + `store/chat.js` 重写 + `ConversationSidebar.vue` + `App.vue` 布局 + `ChatBubble.vue`；`GalleryPanel.vue` 迁移到 composable。
   验证：§13「对话历史」#1、#3~#8、#13 + 「图片引用链」剩余项 + 「对话 UI」#22~#31。

5. **M5 — 纯文字帖**
   `community.create_post` 分支 + `main.py` 校验调整 + `_unlink_community_file` 容忍 None + `CommunityPanel.vue` 发帖弹窗与卡片。
   验证：§13「纯文字帖」#32~#39。

6. **M6 — 评论**
   `db` 评论 CRUD + `community.py` 评论业务层 + `main.py` 三路由 + `CommunityPanel.vue` 评论区。
   验证：§13「评论」#40~#54。

7. **M7 — 收尾**
   删 `GET /api/threads/{thread_id}/messages`、`schemas` 的 `ThreadMessage`/`ThreadOut`、前端 `getThread()`；删 `CommunityPanel.vue` 顶部提示行；`.env.example`；`CLAUDE.md` 同步（见下）。
   验证：§13「回归」#55~#60（确认三个既有面板、分享、建议箱、统计都没被这次改动碰坏）。

**`CLAUDE.md` 需要同步的段落**（Spec17 落地后）：

- 「Project Overview」的「no database」例外条款，从"登录认证引入 SQLite"扩写为"登录认证 + **对话历史/评论**"。
- 「Backend」小节补 `chat_history.py`、`db.py` 的 3 张新表、`task_queue.py` 的持久化计数器。
- 「Frontend」小节的 `localStorage (artcn_chat_v2)` 改为「仅存当前对话 id；聊天内容存后端」。
- 「Important notes / gotchas」补：图片引用作品库（删图会裂图）、评论不可改、`posts.image_file` 可空。

---

## 13. 验收用例（端到端 Smoke）

### 对话历史（M1~M4）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 全新登录 → 聊天页 | 左侧有侧边栏；显示「新对话」；列表为空并显示空态提示 |
| 2 | 发一条纯文本消息 | 助手回复；侧边栏**此时才出现**第一条「2026-09-15 14:30 的对话」（发起时间=刚才） |
| 3 | 刷新页面 | 仍停在这段对话，消息完整；发送时间不变 |
| 4 | 点「新对话」 | 聊天区清空；侧边栏**仍保留**刚才那段；当前对话高亮消失 |
| 5 | 再发一条消息 | 侧边栏出现**第二段**对话，排在最上面（updated_at 倒序） |
| 6 | 点回第一段对话 | 载入其全部消息，且**可以继续发消息**，回复正常（上下文连贯） |
| 7 | 点回第一段后刷新 | 停在第一段（`artcn_current_conv` 生效） |
| 8 | **重启后端** → 点历史对话 → 接着聊 | 助手能正确理解上下文（`ensure_loaded` 从 DB 回填成功），**不失忆** |
| 9 | 用户 B 登录 | 侧边栏只看到自己的对话，**看不到用户 A 的任何一条** |
| 10 | 用户 B 用抓包把 `thread_id` 改成 A 的 → `POST /api/chat` | `404`（`40407`），不泄露该对话是否存在 |
| 11 | 用户 B 直接 `GET /api/conversations/{A的id}/messages` | `404`（`40407`） |
| 12 | 用户 B 直接 `DELETE /api/conversations/{A的id}` | `404`（`40407`） |
| 13 | 点某段对话的删除按钮 | `confirm` → 该条消失；若删的是当前对话，自动切到列表首条（列表空则回到空对话） |
| 14 | 删除含生成图的对话 → 打开「我的作品」 | **图片仍在**（删对话不删作品）；后端重启后 `storage/` 被清空，该图在作品库里依然完好 |

### 图片引用链（M3~M4）

| # | 操作 | 期望 |
|---|---|---|
| 15 | 聊天里上传一张参考图并发送 | `POST /api/images` 返回 `image_id`；用户气泡显示该图 |
| 16 | 刷新页面 | 用户气泡的图**仍然显示**（走 `/api/gallery/{id}/file`，不再依赖 storage） |
| 17 | **重启后端 → 刷新** | 该图仍显示（storage 已清空，gallery 持久） |
| 18 | 文生图成功 | 结果图显示；`chat_messages` 有 `image_id` + `task_id` + `tool` |
| 19 | 回到这段对话 → 对结果图点 👍 | 投票成功，无 `UNIQUE` 冲突；`feedback` 表该行 `task_id` 与消息里的 `task_id` 一致 |
| 20 | 在「我的作品」删掉聊天里用过的那张图 → 回到那段对话 | 该位置显示**「图片已删除」占位**，不是裂图图标；其余消息不受影响 |
| 21 | 上传图后**未发送**就切换对话 | 无副作用；该图已在作品库里（Spec5「上传即入库」既有行为，未改变） |

### 对话 UI（M4）

| # | 操作 | 期望 |
|---|---|---|
| 22 | 查看头部按钮行 | **没有「清空」按钮** |
| 23 | 切到「社区」 | 侧边栏整块隐藏，聊天列占满宽度 |
| 24 | 从社区切回聊天 | 侧边栏恢复，仍高亮原对话 |
| 25 | 窄屏（≤768px） | 侧边栏隐藏，聊天区完整（历史对话在窄屏不可访问，已知限制） |
| 26 | 页面停留 >1 小时后查看早先生成的图 | **仍然显示**（修掉了 storage TTL 导致的既有裂图） |
| 27 | 在聊天 / 社区 / 作品库之间来回切换多次 | 每个面板的图片列表**不会重复拉取**已缓存的图（composable 的模块级缓存 + 引用计数生效）；切走的面板释放引用，不泄漏 objectURL |
| 28 | 连续快速点两段不同对话 | 不出现消息错乱（`loadingConv` 防连点） |
| 29 | 登录态失效（token 过期）后操作 | 与既有行为一致：回登录页（`artcn:unauthorized`） |
| 30 | 用户 A 登出 → 用户 B 登录 | 侧边栏换成 B 的对话；不残留 A 的任何内容 |
| 31 | 空对话时点「新对话」 | 按钮禁用，无副作用 |

### 纯文字帖（M5）

| # | 操作 | 期望 |
|---|---|---|
| 32 | 社区 → 发帖 → 不选图 → 只填文字 → 发布 | 成功；卡片**无图片区**、自然变矮；文字完整显示 |
| 33 | 刷新列表 | 纯文字帖仍无图片区（`image_url: null`） |
| 34 | 对纯文字帖调 `GET /api/community/{id}/image` | `404`（`40404`） |
| 35 | 作者删纯文字帖 | 成功；后端不因 `image_file is None` 报错 |
| 36 | 管理员删除一个有纯文字帖的用户 | 该帖及其评论一并删除，无异常 |
| 37 | 发帖时同时给 `gallery_id` 和 `file` | `400`（`40011`），提示"图片来源最多一张" |
| 38 | 用旧库（有图帖）启动新代码 | 迁移执行；**存量帖子的图全部完好**，`created_at` / `id` / 文字均未变；重启第二次迁移不再执行 |
| 39 | 社区页顶部 | **没有**「当前登录：… · 社区对所有人可见 · 单图 + 文字」那一行；页面以帖子列表开头 |

### 评论（M6）

| # | 操作 | 期望 |
|---|---|---|
| 40 | 任意帖子下方 | 内联显示评论区（含输入框）；0 条时显示淡色空态 |
| 41 | 用户 B 在用户 A 的帖子下评论 | 成功；评论立刻出现在该帖下方，`💬 评论` 计数 +1 |
| 42 | 刷新列表 | 评论仍在，用户名与内容正确 |
| 43 | 评论 200 字 | 成功（边界内） |
| 44 | 评论 201 字 / 空串 / 纯空格 | `400`（`40016`） |
| 45 | 尝试找编辑入口 | **前端没有任何编辑按钮**；后端也没有 `PUT` 路由 |
| 46 | 用户 B 删自己的评论 | 成功；该条消失，计数 −1 |
| 47 | 用户 B 删用户 A 的评论 | `403`（`40303`），且**前端不显示**该条的删除按钮 |
| 48 | 管理员删任意评论 | 成功 |
| 49 | 对不存在的帖子/评论发评论或删除 | `404`（`40404` / `40408`） |
| 50 | 用 `post_id=A` + `comment_id=<挂在B帖上的>` 删除 | `404`（`40408`），不会误删 B 帖的评论 |
| 51 | 删除一个有评论的帖子 | 该帖全部评论一并删除（`post_comments` 无残留行） |
| 52 | 管理员删除一个发过评论的用户 | 该用户发出的全部评论删除；**其帖子上的他人评论**也随帖子一并删除 |
| 53 | 一条帖子有 20 条评论 | 评论区固定高度内可上下滚动看到全部，不撑高卡片 |
| 54 | 帖子列表含评论 | 只发 **1 次** `GET /api/community`，不产生每帖一个评论请求 |

### 回归（Spec17 不应破坏的既有行为）

| # | 操作 | 期望 |
|---|---|---|
| 55 | 点赞 / 点踩 / 取消 | 与 Spec9 完全一致 |
| 56 | 三处 blob 图片渲染（聊天 / 作品库 / 社区） | 全部正常；`GalleryPanel` 迁移到 composable 后行为无变化 |
| 57 | 作品分享链接（`/share/{token}`） | 免登录访问正常（Spec9 未受影响） |
| 58 | 建议箱 / 用户管理 / 数据统计 | 全部正常（Spec10/11 未受影响） |
| 59 | `GET /api/threads/{thread_id}/messages` | **`404`**（路由已移除） |
| 60 | 后端重启后 `GET /api/tasks/{task_id}` 查旧任务 | `404`（`40401`，与 Spec17 前一致）；但**新任务的 `task_id` 从上次的最大值继续**，不回退到 1 |
