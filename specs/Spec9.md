# ArtiControlNet Spec 9：社区分享 + AI 服务反馈 + 作品分享链接 + 建议箱

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：给工作台加四块能力——①**社区**：所有登录用户发帖分享作品与心得（单图 + 文字），帖子持久入库、点开弹窗可点赞/点踩/删除，作者可见；②**AI 服务反馈**：文生图 / 图文生图 / 图像QA 的成功结果气泡可 👍/👎（对话不显示），只统计到管理端「数据统计」展板，管理员可清空；③**作品分享链接**：我的作品可生成**公开免登录**的临时分享链接（配合已有公网域名外发），带有效期、可撤销；④**建议箱**：普通用户写信给管理员（发送前警告一次），管理员可标记状态 + 回复 + 删除，发送者能看到状态与回复。
> 本 Spec 是 **Spec.md / Spec2~8 的增量补充**，不推翻原有架构。四块都复用 Spec2 的 SQLite（`artcn.db`）新增数据表；社区图片、分享复用「文件与元数据分离」的既有模式。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量。数据库例外沿用 Spec2：仅本地单文件 SQLite，放在项目文件夹里。

---

## 1. 功能目的

- **社区**：内网穿透公网部署后，所有人能在一个页面分享自己的 AI 作品 + 一句心得，形成作品集氛围。帖子必须**恰好一张图 + 一段文字**（作者拍板）；图片可从「我的作品」选，也可当场新上传。帖子标注作者账号（管理员带角标）。**删除**：普通用户只能删自己的，管理员能删所有。
- **AI 服务反馈**：让管理员在「数据统计」展板（人均调用量那个界面）看到三类 AI 服务被用户认可/不认可的情况。反馈按钮只在**文生图 / 图文生图 / 图像QA** 的成功结果气泡上出现（**对话不显示**），同一结果只能二选一（可切换、可取消）。计数**只出现在管理端展板**，普通用户看不到。管理员可一键清空以便重新统计。
- **作品分享链接**：在「我的作品」里对自己的作品生成**临时、公开免登录**的分享链接。作者已有内网穿透的公网域名，链接直接外发；带有效期（默认 7 天），可撤销，删除作品自动失效。
- **建议箱**：普通用户在建议界面写信给管理员，**点击发送后先弹窗警告一次**确认；管理员在建议界面能**增删改查**所有普通用户建议——其中「改」= 标记状态（待处理/已读/已处理）+ 写回复；发送者能在「我的建议」里看到状态与回复。

---

## 2. 决策记录（为什么这么选）

### 2.1 社区

| 决策 | 选择 | 理由 |
|---|---|---|
| 帖子结构 | **单图 + 文字（必须配图）** | 作者拍板。每帖恰 1 张图 + 一段心得；数据与展示都最简洁 |
| 图片来源 | **作品库选择 + 新上传** | 作者拍板。从「我的作品」勾选最顺（分享已有作品）；新上传给没有库存的用户 |
| 帖子图片存储 | `Server/community/` 持久目录 + `posts` 表记录 | 与临时 `storage/`（TTL 1h）完全分开、不受清理影响；与 `gallery/` 独立，删作品库不影响已发帖 |
| 图片来源实现 | 发帖接口收 `gallery_id`（复制字节）或 `file`（新上传）两种 | 从作品库选 = 复制 gallery/ 字节到 community/；新上传 = 写 community/ + 照 Spec5「上传即入库」一并写 gallery/ |
| 点赞/点踩计数 | `post_votes` 表每帖每用户一行（UNIQUE(post_id, user_id)），计数用 COUNT 现算 | 不落冗余列，杜绝计数漂移；社区量级小，COUNT 足够 |
| 按钮位置 | 点赞/点踩/删除**只在点开帖子的弹窗里**显示；卡片只展示图 + 作者 + 文字摘要 | 作者要求「点进去才能看到」，社区列表保持干净 |
| 允许对自己帖子点赞 | **允许** | 个人小社区简化实现，不额外加错误码；作者同样需要正负反馈 |
| 帖子列表 | 每项带当前用户 `my_vote`（null/like/dislike） | 前端弹窗能高亮我的选择，无需额外详情接口 |
| 越权删除 | 作者或管理员才可删；他人删除 → `403`（`40302`） | 帖子对所有人可见，存在性公开，权限错误用 403 而非 404 |

### 2.2 AI 服务反馈

| 决策 | 选择 | 理由 |
|---|---|---|
| 识别"AI 服务结果" | 轮询结果 `result.tool ∈ {generate_image, edit_image, qa_image}` | Spec4 已给结果打 `tool` 标签、`task_queue.to_dict()` 原样返回（前端已可读），**无需改后端链路**。纯文本对话无 `tool` → 不显示按钮 |
| 反馈记录 | `feedback` 表一行 = 一次 AI 服务结果（UNIQUE(task_id)） | task_id 后端唯一，标识"哪一次结果"；QA 虽返回文本，但 `tool=qa_image`，同样计为 qa 类反馈 |
| 交互 | 同结果 👍/👎 只能选一个；再点当前选项 = 取消（`vote=null` 删行）；切换 = 更新同一行 | 满足「只能二选一点」，又允许反悔 |
| 统计归属 | 只在 `GET /api/admin/stats` 增加三类 like/dislike 聚合，**普通用户无任何计数可见** | 作者明确「数据只会统计在管理员的用户数据展板那里」 |
| 清空 | 新增管理端 `POST /api/admin/feedback/clear`（可 `?category=` 单选或全清） | 作者要求「清空点赞和不喜欢量（方便重新统计）」 |
| 投票身份键 | 用 `task_id`（服务端权威），前端把 `task_id`/`tool` 存进历史气泡 | 气泡的已选状态随 localStorage 历史持久；计数以后端为准 |
| 重启边界 | 接受 | 见 §3.5：后端重启后 task_id 从头计数，极端情况下旧行被新投票覆盖，对"按类聚合计数"无影响 |

### 2.3 作品分享链接

| 决策 | 选择 | 理由 |
|---|---|---|
| 开放方式 | **公开免登录** | 作者拍板。已有内网穿透公网域名，链接直接发外部的人 |
| 公开路由 | `/share/{token}` 与 `/share/{token}/image` 走**非 `/api` 路径** | 统一鉴权中间件只拦截 `/api/*`，非 `/api` 路径天然公开；免改中间件 |
| 分享页形态 | 后端生成的独立紫色主题 HTML 页（不依赖 SPA / 登录） | 免登录访问，无需前端构建；展示大图 + 作者 + 下载链接 |
| 链接基址 | 用 `PUBLIC_BASE_URL`（未配则按请求 Host 推导），复用 `main.py` 的 `_public_base` | 已存在的配置；内网穿透域名放这里，外发即得 |
| 有效期 | `expires_at = created + SHARE_TTL_SECONDS`（默认 7 天，`.env` 可配） | 「临时链接」的临时由后端强制：过期一律 `404`（`40405`） |
| 每作品一份 | **一个作品一条分享**；再次生成 = 覆盖旧 token/有效期 | 无需分享列表，画廊项内直接呈现「已分享·复制/撤销」 |
| 级联 | 删除作品 / 删除用户 → 其分享立即失效 | 与 gallery 删除一致性（同 Spec4/Spec5 口径） |
| 撤销 | `DELETE /api/shares/{share_id}`（本人）→ 删行即失效 | 随时可提前作废，不必等过期 |

> 排除项：分享页不登录/不统计访问量；分享链接不做密码保护、不做永久链接；分享对象只能是「我的作品」，社区帖子不走分享链接（社区本身所有登录用户可见）。

### 2.4 建议箱

| 决策 | 选择 | 理由 |
|---|---|---|
| 「改」语义 | 管理员可改 `status`（待处理/已读/已处理）与 `reply`（回复文字） | 作者拍板「状态 + 管理员回复」；不改用户原文 |
| 发送确认 | 前端点击发送 → **先 `confirm` 警告一次**再提交 | 作者明确要求「先警告一次确认是否发送」 |
| 回执 | 发送者在「我的建议」看到自己每条建议的 status 与 reply | 作者拍板，用户能知道处理结果 |
| 管理端「增」 | 不单独开"代发"接口：管理员也以自己身份走普通 `POST /api/suggestions` | 诚实落地「增删改查」里的「增」；删/改/查在管理 tab 完成 |
| 建议内容 | 纯文本，≤2000 字，允许任意登录用户（含管理员） | 保持简单，不做分类/附件/多轮会话 |
| 删除用户 | 级联删除其全部建议 | 与 usage/images 级联口径一致（Spec4/Spec5） |

---

## 3. 需求边界

### 3.1 社区

**范围内**

- 发帖：恰好一张图（作品库选择 `gallery_id` 或新上传 `file`）+ 一段文字（1~1000 字）。
- 列表：`GET /api/community` 最新在前，轻量分页（`?limit` 默认 50、`?offset`），每项含作者名、作者是否管理员、图片地址、like/dislike 计数、我的投票。
- 帖子弹窗：查看大图 + 全文 + 作者；点赞 / 点踩 / 删除（仅作者或管理员）。
- 删除帖子：连带删除 community/ 图片文件与该帖全部投票。
- 删除用户：级联删除其帖子、帖子图片、投票。

**范围外（本 Spec 不做）**

- 帖子评论 / 楼中楼 / 关注 / 收藏 / 标签 / 搜索 / 编辑已发帖。
- 多图帖、纯文字帖（结构拍板为单图 + 文字）；帖子文字落库后的修改。
- 帖子热度排序 / 置顶 / 管理员审核流（发帖即上墙）。

### 3.2 AI 服务反馈

**范围内**

- 三类 AI 服务（文生图 / 图文生图 / 图像QA）**成功结果**气泡出现 👍/👎；对话（纯文本、无工具）不出现。
- 同结果二选一，可切换、可取消；投票写入 `feedback` 表。
- 管理端「数据统计」展板新增三类 like/dislike 聚合；管理员可清空（全清或按类）。

**范围外（本 Spec 不做）**

- 反馈理由 / 备注 / 星级 / 导出。
- 成功之外（失败/超时）结果不可反馈；追问（`ask_clarification`）文本不可反馈。
- 普通用户可见任何计数；按用户维度的反馈明细（只做按类聚合）。

### 3.3 作品分享链接

**范围内**

- 我的作品每项可生成/覆盖临时分享链接；可撤销。
- `/share/{token}`（HTML 分享页）与 `/share/{token}/image`（图片本体，`?download=1` 下载）**公开免登录**。
- 有效期强制（默认 7 天，`SHARE_TTL_SECONDS` 可配）；过期/伪造/已撤销一律 `40405`。

**范围外（本 Spec 不做）**

- 分享访问量 / 埋点；分享页自定义文案 / 水印；一次多图分享；对他人作品 / 社区帖子生成分享。
- 永久链接 / 密码保护分享。

### 3.4 建议箱

**范围内**

- 任意登录用户写信（≤2000 字），前端发送前 `confirm` 警告一次。
- 发送者查看「我的建议」（含状态与回复）。
- 管理端查看全部建议（含发送者）、标记状态、写回复、删除。

**范围外（本 Spec 不做）**

- 建议分类 / 附件 / 图片；多条消息的来回会话（一条提交 = 一条建议）。
- 站内信通知 / 未读红点；自动回复。

### 3.5 已知边界与风险（写入本文档，避免误读）

- **社区帖子不可修改**：发帖后文字不能编辑（要改只能删了重发），设计如此。
- **`community/` 与 `gallery/` 各自独立**：从作品库发帖是**复制**字节到 community/，之后删除原作品不影响已发帖；新上传发帖会同时落 community/ 与 gallery/（上传即入库的不变量），磁盘略有重复，可接受。
- **反馈 `task_id` 重启边界**：任务引擎内存计数，后端重启后 task_id 从头排。若旧结果气泡在重启后又被投票，会覆盖旧 `feedback` 行——但统计只按类聚合，行数不受影响，可接受。
- **反馈已选状态存前端历史**：投票的"我选了什么"存在 localStorage 气泡上，计数以后端为准。管理员清空后，前端气泡仍显示旧选择（不影响后端计数），属可接受的对账偏差。
- **分享链接是临时的、公开的**：拿到链接的任何人可看、可下载；有效期与撤销是唯二控制手段。默认 7 天后自动失效。
- **分享图片字节**：分享直接读 `gallery/` 原图字节（不复制）；因此**删除该作品或该用户**必须级联删分享行，否则出现"token 有效但文件已删"的悬挂态——本 Spec 已要求级联（见 §5.3）。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | 无新依赖 | 复用 `sqlite3`（Spec2）+ 既有文件读写；新增 `community.py`、`shares.py` 模块；`feedback` 逻辑并入 `db.py` + `main.py` |
| 前端 | 无新依赖 / 无新框架 | 新增 `CommunityPanel.vue`、`SuggestionPanel.vue`；`GalleryPanel.vue` / `StatsPanel.vue` / `ChatBubble.vue` / `App.vue` / `chat.js` 增量 |

> 无需新 pip 依赖；`.env` 仅新增一个可选 `SHARE_TTL_SECONDS`。

---

## 5. 架构设计（增量）

### 5.1 分层

```
Vue 3 SPA（聊天页 + 社区 + 我的作品 + 用户管理 + 数据统计 + 建议）
   │ Authorization: Bearer <JWT>（社区/反馈/分享管理/建议均为登录接口）
FastAPI
   ├─ 社区：/api/community（发帖/列表/看图/投票/删除）
   ├─ 反馈：/api/feedback + 管理端 /api/admin/feedback/clear + /api/admin/stats 扩展
   ├─ 分享：/api/shares（登录）+ /share/{token}（公开，非 /api 路径，免鉴权）
   └─ 建议：/api/suggestions + /api/admin/suggestions
SQLite Server/artcn.db（users + usage + images + posts + post_votes + feedback + shares + suggestions）
持久目录 Server/gallery/（作品，已有）、Server/community/（帖子图片，新增）
```

### 5.2 数据表（追加到 artcn.db）

```sql
-- 社区帖子（单图 + 文字）
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,             -- 作者
    text       TEXT NOT NULL,                -- 心得文字（1~1000 字，前后端校验）
    image_file TEXT NOT NULL,                -- community/ 下持久文件名（uuid + ext）
    ext        TEXT NOT NULL,                -- .jpg|.jpeg|.png|.webp|.gif
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);

-- 帖子点赞/点踩（每帖每用户一行）
CREATE TABLE IF NOT EXISTS post_votes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    vote       TEXT NOT NULL,                -- 'like' | 'dislike'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(post_id, user_id)
);

-- AI 服务反馈（一行 = 一次 AI 服务结果）
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL UNIQUE,      -- 标识"哪一次结果"（重启边界见 §3.5）
    user_id    INTEGER NOT NULL,             -- 投票人（删用户级联）
    category   TEXT NOT NULL,                -- 'generate' | 'edit' | 'qa'
    vote       TEXT NOT NULL,                -- 'like' | 'dislike'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 临时分享链接
CREATE TABLE IF NOT EXISTS shares (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL UNIQUE,         -- secrets.token_urlsafe(16)
    image_id   INTEGER NOT NULL,             -- 引用 images.id（作品）
    user_id    INTEGER NOT NULL,             -- 创建者
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL                 -- created_at + SHARE_TTL_SECONDS
);

-- 建议箱
CREATE TABLE IF NOT EXISTS suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,             -- 发送者
    text       TEXT NOT NULL,                -- ≤2000 字
    status     TEXT NOT NULL DEFAULT 'pending', -- pending|read|resolved
    reply      TEXT,                         -- 管理员回复
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suggestions_user ON suggestions(user_id, created_at DESC);
```

索引说明：`post_votes` 的 UNIQUE(post_id, user_id) 已覆盖"查某帖我投过没"与"查某帖计数"；`feedback` 只做 `GROUP BY category, vote` 聚合（表小，不建索引）；`shares` 靠 UNIQUE(token) 查。

### 5.3 关键数据流

**社区——发帖（两条来源）**

1. **从作品库选**：前端传 `gallery_id` → 后端校验 `images.user_id == 当前用户`（否则 `40403`）→ 从 `gallery/` 读字节 → 复制写入 `community/` → 插 `posts` 行。
2. **新上传**：前端传 `file` → 后端校验图片格式/大小（复用 `media.validate_upload`）→ 写 `community/` 插 `posts` 行；**同时**照 Spec5「上传即入库」把同字节写入 `gallery/` + `images`（`source='upload'`），保持不变量。

**社区——读取与交互**

- `GET /api/community` → `posts JOIN users` 取作者名/is_admin，对每帖 `COUNT(post_votes)` 求 like/dislike、按当前用户取 `my_vote`，时间倒序。
- 帖子图片：`GET /api/community/{post_id}/image` 返回 community/ 文件字节（**任何登录用户**可看，不做归属校验——社区对所有人开放）。
- 点赞/点踩：`POST /api/community/{post_id}/vote` → `INSERT … ON CONFLICT(post_id, user_id) DO UPDATE SET vote=excluded.vote`；`vote=null` 时 `DELETE` 该行；随后现算该帖 like/dislike 返回。
- 删除：作者或管理员 → 删 community/ 文件 + `posts` 行 + 该帖全部 `post_votes`。删用户 → 同上对所有该用户帖子 + 其全部投票。

**AI 服务反馈——采集与展示**

- 前端轮询到 `COMPLETED` 且 `result.tool ∈ {generate_image, edit_image, qa_image}` → 在助手气泡写入 `tool`、`task_id`、`vote:null`（进 localStorage 历史）。
- 用户点 👍/👎 → `POST /api/feedback {task_id, category, vote}`；再点当前项 → `vote:null`（删行）。
- 管理端 `GET /api/admin/stats` 在原 data 上**新增** `feedback_totals`（三类 like/dislike 聚合）；`POST /api/admin/feedback/clear` 清空（可 `?category=`）。
- 删用户 → 级联删其 `feedback` 行。

**分享——生成 / 访问 / 失效**

- `POST /api/shares {image_id}`（校验本人作品，否则 `40403`）→ 覆盖写 `shares` 行（新 token + 新 expires_at）→ 返回 `{url, expires_at}`，url = `{PUBLIC_BASE_URL}/share/{token}`。
- `GET /share/{token}` → 校验 token + `expires_at`，否则 `40405` → 返回紫色主题 HTML 分享页（大图 `<img src="/share/{token}/image">` + 作者 + 下载链接）。
- `GET /share/{token}/image`（`?download=1` 触发下载）→ 校验同上 → 读 `gallery/` 原图字节返回。
- **级联**：`gallery.delete_item` / `delete_user_gallery`（删用户）时，先删引用该 image_id 的 `shares` 行；`DELETE /api/shares/{id}` 撤销即时生效。

**建议——写信与处理**

- 普通用户 `POST /api/suggestions {text}`（前端已 `confirm`）→ 插 `suggestions`（status=pending）→ `GET /api/suggestions/mine` 看自己的。
- 管理员 `GET /api/admin/suggestions`（含 username）→ `PUT /api/admin/suggestions/{id} {status?, reply?}`（改状态/回复，`updated_at` 刷新）→ `DELETE` 删除。
- 删用户 → 级联删其建议。

### 5.4 前端如何识别"AI 服务结果"（零后端链路改动）

`result.tool` 已在 Spec4 由 Supervisor 打标，`task_queue.to_dict()` 原样返回，轮询响应 `data.result.tool` 前端已可读：

| `result.tool` | 气泡类型 | 反馈按钮 | 类别（POST /api/feedback） |
|---|---|---|---|
| 无（纯文本对话） | text | 不显示 | — |
| `generate_image` | images | 👍/👎 | `generate` |
| `edit_image` | images | 👍/👎 | `edit` |
| `qa_image` | **text** | 👍/👎 | `qa` |
| （追问澄清，已转为普通文本） | text | 不显示 | — |

> 关键点：图像 QA 返回的是**文本气泡**，但 `tool=qa_image`，也要显示按钮并计为 `qa` 类；追问澄清在 `handle_task` 中被转成无 `tool` 的纯文本，天然不显示按钮。前端判断用 `tool` 而非气泡 `kind`。

---

## 6. 接口约定

### 6.1 新增端点

| 方法 & 路径 | 鉴权 | 请求 | 成功响应 `data` | 说明 |
|---|---|---|---|---|
| `POST /api/community` | 登录 | multipart：`text` +（`gallery_id` **或** `file`） | `{post}` | 发帖（单图 + 文字，二选一图片来源） |
| `GET /api/community` | 登录 | `?offset=0&limit=50`（limit≤100） | `{items:[post]}` | 帖子列表，最新在前；每项含 `my_vote` |
| `GET /api/community/{post_id}/image` | 登录 | 无 | 图片字节 | 帖子图片（任何登录用户可看） |
| `POST /api/community/{post_id}/vote` | 登录 | `{vote: 'like'\|'dislike'\|null}` | `{post_id, like_count, dislike_count, my_vote}` | 点赞/点踩/取消（UPSERT，`null` 删行） |
| `DELETE /api/community/{post_id}` | 登录·作者或管理员 | 无 | `{id}` | 删帖（文件 + 投票级联） |
| `POST /api/feedback` | 登录 | `{task_id, category, vote}`（vote: `'like'\|'dislike'\|null`） | `{task_id, category, vote}` | 记录/切换/取消某次 AI 结果反馈 |
| `POST /api/admin/feedback/clear` | 管理员 | `?category=`（可选） | `{cleared}` | 清空反馈统计（重统计用） |
| `POST /api/shares` | 登录 | `{image_id}` | `{id, url, expires_at}` | 生成/覆盖作品分享链接 |
| `DELETE /api/shares/{share_id}` | 登录·本人 | 无 | `{id}` | 撤销分享（立即失效） |
| `GET /share/{token}` | **公开**（非 /api） | 无 | HTML | 免登录分享页（紫色主题） |
| `GET /share/{token}/image` | **公开**（非 /api） | `?download=1` | 图片字节 | 分享图本体；`download=1` 触发下载 |
| `POST /api/suggestions` | 登录 | `{text}` | `{suggestion}` | 写信给管理员（前端先 confirm） |
| `GET /api/suggestions/mine` | 登录 | 无 | `{items:[suggestion]}` | 我的建议（含 status/reply） |
| `GET /api/admin/suggestions` | 管理员 | `?status=`（可选） | `{items:[{…, username}]}` | 全部建议，含发送者 |
| `PUT /api/admin/suggestions/{id}` | 管理员 | `{status?, reply?}` | `{id, status, reply}` | 标记状态 / 写回复 |
| `DELETE /api/admin/suggestions/{id}` | 管理员 | 无 | `{id}` | 删除建议 |

**post 对象形状**

```json
{
  "id": 12,
  "text": "赛博朋克新年海报第一版",
  "author": "designer01",
  "author_is_admin": false,
  "image_url": "/api/community/12/image",
  "like_count": 3,
  "dislike_count": 1,
  "my_vote": "like",
  "created_at": "2026-08-31T08:00:00.000Z"
}
```

**feedback 统计并入 `GET /api/admin/stats`（在现有 data 上新增字段，旧字段不动）**

```json
{
  "user_count": 12, "total_calls": 345,
  "totals": { "chat": 200, "generate": 80, "edit": 40, "qa": 25 },
  "per_user_avg": { "...": 0 },
  "shares": { "...": 0 },
  "feedback_totals": {
    "generate": { "like": 5,  "dislike": 1 },
    "edit":     { "like": 0,  "dislike": 2 },
    "qa":       { "like": 11, "dislike": 3 }
  }
}
```

**`GET /api/gallery` 每项新增 `share`（可空）**

```json
{ "id": 7, "source": "generate", "url": "/api/gallery/7/file",
  "prompt": "...", "created_at": "...",
  "share": { "id": 3, "url": "https://<公网域名>/share/abc123...", "expires_at": "..." } }
```

> 旧客户端只读旧字段，`share` 为新增可空字段，不破坏既有契约。

### 6.2 鉴权约定

- 除公开的 `/share/{token}`、`/share/{token}/image` 与既有 `POST /api/auth/login` 外，所有 `/api` 接口仍由统一中间件鉴权：未登录 `40103`，非管理员访问 `/api/admin/*` → `40301`。
- 分享路由是**非 `/api` 路径**，统一中间件（只拦 `/api/*`）天然放行；其自身的 token + 过期校验由 `shares.py` 完成（错误 `40405`）。
- 社区图片与帖子列表**任何登录用户**可读；删除限作者或管理员（他人 → `40302`）。
- 分享生成 / 撤销限本人作品（他人 → `40403` 不泄露存在性）；建议管理限管理员。
- 业务响应仍走 `{code, message, data}` 包装；`/share/*` 返回裸 HTML / 图片字节（不套 JSON）。

### 6.3 既有接口

- `POST /api/chat`、`GET /api/tasks/{id}`、`POST /api/images` 等**契约不变**（`result.tool` 早已存在，仅前端新增读取）。
- `GET /api/gallery` 响应**新增** `share` 字段（见 §6.1），为可空增量，不破坏既有字段。

---

## 7. 前端交互

- **头部按钮**（`App.vue`）：新增「**社区**」「**建议**」（所有登录用户）；与「我的作品 / 用户管理 / 数据统计」构成**五面板互斥**：打开一个自动关闭其余。`清空` 按钮仅在聊天视图（无任何面板打开）显示。401 回登录时全部面板关闭。「帮助」弹窗仍为顶层、任何视图可用（不与面板互斥）。
- **`CommunityPanel.vue`（新建）**：
  - 提示行：`当前登录：<用户名> · 社区对所有人可见`。
  - 顶部「发帖」按钮 → **发帖弹窗**（见下）；列表为**瀑布流网格**（`columns` 多列自适应，复用 `--purple-*` / `--bg-surface` / `--radius-lg` / `--shadow-md`），每卡片 = 图片缩略图（axios 带 token 拉 blob → objectURL）+ 作者行（用户名 + 管理员角标）+ 文字摘要（≤2 行截断）。点击卡片 → **帖子弹窗**。
  - **帖子弹窗**：大图 + 全文文字 + 作者 + 时间 + 操作行：👍 点赞（计数）、👎 不喜欢（计数）、**删除**（仅作者或管理员，`confirm` 后删）。点弹窗遮罩 / × / Esc 关闭。点赞/点踩后按钮态与计数即时刷新。
  - **发帖弹窗**：两个图片来源 Tab——「从作品库选」（复用 `listGallery` + blob 缩略图，点击选中一张，高亮）+「上传新图」（`<input type="file">`，本地 objectURL 预览）；下方文字 `<textarea>`（计数 ≤1000）+ 「发布」。发布 → multipart 提交 → 成功后关弹窗并刷新列表。
- **AI 反馈按钮（`ChatBubble.vue` + `store/chat.js`）**：
  - `chat.js` 在 `pollTask` 的 `COMPLETED` 分支，若 `result.tool` 属于三类 AI 服务 → 助手气泡追加 `{tool, task_id, vote:null}` 后再 `replaceMessage`（随 localStorage 历史持久）。
  - `ChatBubble.vue` 对 `message.tool` 属于三类 AI 服务的助手气泡（含**文本**的 qa 气泡与图片气泡）在气泡下方渲染一行 👍/👎（`btn-mini` 样式，已选态高亮紫色）。点击 → 更新 `message.vote` + `POST /api/feedback`；再点当前项 → 置 `null` 并提交。普通对话 / 追问 / 失败气泡**不渲染**。
- **`StatsPanel.vue` 扩展**：现有 4 类调用表下方新增「**服务反馈**」区：表格 `类型 | 点赞 | 不喜欢`（文生图 / 图文生图 / 图像QA 三行）+ 「**清空反馈统计**」按钮（`confirm` 后调 `POST /api/admin/feedback/clear`，成功后刷新）。保持只展示聚合、不含用户名。
- **`GalleryPanel.vue` 扩展**：每张卡片的操作行新增「**分享**」按钮——若无 `item.share` → 点「分享」生成链接（成功后该项出现 `item.share`）；若有 → 该按钮变为「**已分享**」，旁边出现「**复制链接**」（复制 `share.url`）与「**撤销分享**」（confirm 后 DELETE）。链接复制复用现有 `copyPrompt` 的剪贴板回退逻辑。
- **`SuggestionPanel.vue`（新建）**：
  - Tab1「**我的建议**」（所有用户）：textarea（≤2000）+「发送」→ **先 `confirm('确认发送这条建议吗？')`** → 提交成功清空输入、刷新列表；列表每条显示 `状态徽标（待处理/已读/已处理）+ 我的文字 + 管理员回复（若有）+ 时间`。
  - Tab2「**管理建议**」（仅管理员，`auth.isAdmin` 才显示）：全部建议表格（发送者、状态、文字、回复、时间）+ 每行的「改状态」下拉 /「写回复」输入 +「删除」。状态与回复变更走 `PUT`。
- `api/chatApi.js` 新增：`createCommunityPost` / `listCommunity` / `fetchCommunityImage`（blob）/ `votePost` / `deletePost` / `postFeedback` / `createShare` / `revokeShare` / `listMySuggestions` / `submitSuggestion` / `listAllSuggestions` / `updateSuggestion` / `deleteSuggestion` / `clearFeedback`。

---

## 8. 配置 / 环境变量 / .gitignore

| 变量 | 用途 | 说明 |
|---|---|---|
| `SHARE_TTL_SECONDS` | 分享链接有效期 | 默认 `604800`（7 天），`.env` 可选配置 |

- `config.py` 追加：`COMMUNITY_DIR = BASE_DIR / "community"`（启动确保存在）、`SHARE_TTL_SECONDS`；文本上限常量 `COMMUNITY_POST_TEXT_MAX = 1000`、`SUGGESTION_TEXT_MAX = 2000`（前后端同值）。
- `.gitignore` 追加：

```gitignore
# 社区帖子图片（持久，与 gallery/ 分开）
Server/community/
```

> `artcn.db` 已在 Spec2 忽略；无 `requirements.txt` 变更；`providers/` 不改。

---

## 9. 错误码新增（追加到 Spec.md §9 / Spec2 §9 / Spec5 §9 之后）

| HTTP | code | 含义 | 触发示例 |
|---|---|---|---|
| 400 | 40011 | 帖子内容非法 | 缺图片 / `gallery_id` 与 `file` 同时给出或都缺 / 文字为空或 >1000 字 |
| 400 | 40012 | 反馈参数非法 | `vote ∉ {like,dislike,null}` 或 `category ∉ {generate,edit,qa}` |
| 400 | 40013 | 建议内容非法 | 文字为空或 >2000 字 |
| 403 | 40302 | 无权操作该帖子 | 非作者且非管理员删除他人帖子 |
| 404 | 40404 | 帖子不存在 | 操作不存在的帖子 ID |
| 404 | 40405 | 分享链接不存在或已过期 | 伪造 token / 已撤销 / 过期 / 对应作品已删除 |
| 404 | 40406 | 建议不存在 | 管理端操作不存在的建议 ID |

> 投票 `vote=null` 用于取消（删行），不做成"不能投"。越权访问他人作品仍复用 `40403`。

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON；新增事件：

- `community.posted` / `community.deleted`（发帖/删帖，附 user_id / post_id；不记全文）
- `community.voted`（投票，附 post_id / user_id / vote；`null` 记 `cancel`）
- `feedback.voted`（反馈，附 task_id / user_id / category / vote）
- `feedback.cleared`（清空，附 operator / category）
- `share.created` / `share.revoked`（生成/撤销，附 user_id / image_id；**不记完整 token**，避免泄露）
- `suggestion.created` / `suggestion.updated` / `suggestion.deleted`（建议增改删，附 user_id / suggestion_id / status）

**禁止**：把帖子/建议/回复全文、完整分享 token 写入日志；长文本超 100 字符截断。

---

## 11. 目录结构增量

```
Server/
  db.py                 # 新增 posts/post_votes/feedback/shares/suggestions 建表与函数；delete_user 级联
  community.py（新建）   # 发帖（两种来源）、读图、投票、删帖（含文件与投票级联）
  shares.py（新建）      # 生成/覆盖/撤销分享；token+过期校验；渲染公开分享页 HTML
  main.py               # 追加四组路由 + /share/{token} 公开路由 + stats 扩展 + 删用户级联
  schemas.py            # 新增 vote/feedback/share/suggestion 请求模型
  errors.py             # 新增 40011/40012/40013/40302/40404/40405/40406 错误类
  config.py             # COMMUNITY_DIR / SHARE_TTL_SECONDS / 文本上限常量
  .gitignore            # 追加 Server/community/
  community/            # 运行时生成（帖子图片持久目录）
frontend/src/
  views/CommunityPanel.vue（新建）    # 社区面板 + 帖子弹窗 + 发帖弹窗
  views/SuggestionPanel.vue（新建）   # 我的建议 + 管理建议（admin）
  views/GalleryPanel.vue             # 分享 / 复制链接 / 撤销
  views/StatsPanel.vue               # 服务反馈区 + 清空按钮
  components/ChatBubble.vue          # AI 服务结果气泡渲染 👍/👎
  store/chat.js                      # 助手气泡存 tool / task_id / vote
  api/chatApi.js                     # 新增 14 个接口函数
  App.vue                            # 「社区」「建议」入口 + 五面板互斥
```

---

## 12. 实施顺序（里程碑）

1. **A1 数据层**：`config.py`（COMMUNITY_DIR / SHARE_TTL_SECONDS / 文本上限）；`db.py` 五张新表建表函数 + `delete_user` 级联。
2. **C1 社区后端**：`community.py`（发帖两来源 / 读图 / 投票 / 删帖级联）+ `/api/community*` 路由 + `40011 / 40302 / 40404`。
3. **C2 社区前端**：`chatApi.js` + `CommunityPanel.vue`（网格 + 帖子弹窗 + 发帖弹窗）+ `App.vue` 入口与五面板互斥。
4. **F1 反馈后端**：`db.py` 的 feedback 读写 / 聚合 / 清空；`POST /api/feedback` + `POST /api/admin/feedback/clear` + `GET /api/admin/stats` 扩展 + `40012`。
5. **F2 反馈前端**：`chat.js` 存 tool/task_id/vote；`ChatBubble.vue` 渲染 👍/👎；`StatsPanel.vue` 反馈区 + 清空按钮。
6. **S1 分享后端**：`shares.py`（生成/撤销/token 校验/分享页 HTML）+ `/api/shares` + `/share/{token}` 公开路由 + gallery 响应带 `share` + 删图/删用户级联 + `40405`。
7. **S2 分享前端**：`GalleryPanel.vue` 分享 / 复制 / 撤销。
8. **G1 建议后端**：`db.py` 建议读写；`/api/suggestions` + `/api/admin/suggestions` 四端点 + `40013 / 40406`。
9. **G2 建议前端**：`SuggestionPanel.vue`（我的建议 + 管理 tab）+ `App.vue` 入口。
10. **A3 验收**：按 §13 端到端 Smoke + `npm run build`。

---

## 13. 验收用例（端到端 Smoke）

### 社区

| # | 操作 | 期望 |
|---|---|---|
| 1 | 登录 → 社区 → 发帖（从作品库选一张图 + 文字） | 列表出现新帖；作者=本人；`image_url` 可看 |
| 2 | 发帖（新上传一张图 + 文字） | 成功；该图同时出现在「我的作品」（来源=上传） |
| 3 | 纯文字 / 空文字发帖 | `400`（`40011`） |
| 4 | 点开帖子 → 点 👍 | `like_count=1`，`my_vote=like`，按钮高亮 |
| 5 | 再点 👎 | 切换：`like_count=0`，`dislike_count=1`，`my_vote=dislike` |
| 6 | 再点当前项（取消） | 计数归 0，`my_vote=null` |
| 7 | 普通用户删他人帖子 | `403`（`40302`） |
| 8 | 作者删自己帖子 | 成功；community/ 文件与投票一并删除 |
| 9 | 管理员删任意帖子 | 成功 |
| 10 | 未登录访问 `/api/community` | `401`（`40103`） |
| 11 | 用户 B 打开用户 A 的帖子图片 | 可正常查看（登录即可，无需是作者） |
| 12 | 管理员删除一个有帖子的用户 | 其帖子、帖子图片、投票一并删除 |

### AI 服务反馈

| # | 操作 | 期望 |
|---|---|---|
| 13 | 文生图成功 | 图片气泡下方出现 👍/👎；纯文本对话气泡**无按钮** |
| 14 | 图文生图成功 | 图片气泡出现按钮 |
| 15 | 图像 QA 成功（返回文本） | **文本**气泡也出现按钮（`tool=qa_image`） |
| 16 | 追问澄清返回的文本 | 无按钮 |
| 17 | 同一结果先 👍 再 👎 | 后端该 `task_id` 行 `vote` 变为 dislike（不新增行） |
| 18 | 再点当前项（取消） | `vote=null`，`feedback` 行删除 |
| 19 | 管理员「数据统计」 | 新增「服务反馈」区：三类 like/dislike 计数与实测一致；普通用户看不到任何计数 |
| 20 | 普通用户访问 `/api/admin/stats` / `/api/admin/feedback/clear` | `403`（`40301`） |
| 21 | 管理员点「清空反馈统计」 | 计数归 0；再投票会重新累计 |
| 22 | 删除有反馈的用户 | 其 feedback 行删除，聚合计数随之减少 |
| 23 | 刷新页面 / 重启后端后打开历史气泡 | 气泡仍显示已选态（前端历史持久）；按钮可继续切换（重启边界见 §3.5，聚合不受影响） |

### 作品分享链接

| # | 操作 | 期望 |
|---|---|---|
| 24 | 我的作品 → 某张图点「分享」 | 返回 `{PUBLIC_BASE_URL}/share/<token>`，`expires_at`≈7 天后 |
| 25 | 无痕窗口打开该链接 | **免登录**显示紫色主题分享页 + 大图 + 作者 + 下载链接 |
| 26 | 分享页点下载（`?download=1`） | 浏览器下载原图 |
| 27 | 再对同一张图点「分享」 | 生成新 token，旧链接失效 |
| 28 | 点「撤销分享」 | 旧链接再打开 → `404`（`40405`） |
| 29 | 删除该作品 | 其分享自动失效（级联删行） |
| 30 | 伪造 token / 已过期链接 | `404`（`40405`） |
| 31 | 对他人作品点「分享」 | `404`（`40403`，不泄露存在性） |
| 32 | 未登录调 `POST /api/shares` / 直接访问 `/api/shares/*` | `401`（`40103`）；`/share/{token}` 公开路径不受影响 |

### 建议箱

| # | 操作 | 期望 |
|---|---|---|
| 33 | 普通用户写建议 → 点发送 | 先弹出 `confirm` 警告；确认后提交成功 |
| 34 | 「我的建议」 | 出现该条，状态=待处理，无回复 |
| 35 | 管理员「管理建议」tab | 看到该条（含发送者 username）；标记「已处理」并写回复 |
| 36 | 普通用户刷新「我的建议」 | 看到状态=已处理 + 管理员回复 |
| 37 | 管理员删除该建议 | 普通用户列表同步消失 |
| 38 | 空建议提交 | `400`（`40013`） |
| 39 | 普通用户访问 `/api/admin/suggestions` | `403`（`40301`） |

> 验收时明确排除：社区评论/多图/编辑帖子、反馈理由/导出、分享访问统计/密码保护、建议分类/附件/来回会话、以及 Spec2~8 未列出的其它能力。
