# ArtiControlNet Spec 5：个人作品库 + 多轮追问（参数澄清）

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：给工作台加两块能力——①**个人作品库**：每个登录用户上传的、以及 AI 服务返回的**全部图片**，按用户持久保存，可在前端「我的作品」面板浏览 / 查看大图 / 下载 / 删除；②**多轮追问**：主 Agent 在参数没说清时**先追问**（可先存着图片），用户补齐参数或回复"看你 / 随便 / 你定 / 拒绝"后，再带默认值或整理好的参数交付子 Agent 调 API。
> 本 Spec 是 **Spec.md / Spec2.md / Spec4.md 的增量补充**，不推翻原有架构。作品库复用 Spec2 的 SQLite（`artcn.db`）再扩展一张 `images` 表 + 一个持久目录 `Server/gallery/`；追问的挂起意图按作者拍板**只放内存**（见 §2 决策记录）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量。数据库例外沿用 Spec2：仅本地单文件 SQLite，放在项目文件夹里。

---

## 1. 功能目的

- **个人作品库**：部署方式为内网穿透（本机跑后端、外网可访问）。作品库按账号隔离——每个用户只能看到自己的图片。图片 = 用户上传的 + AI 生成/编辑返回的**全部**结果；**不存任何对话文字**（仅存可选的一条生成 prompt 元数据，见 §2 决策记录）。
- **多轮追问**：现在主 Agent 对"没说清"的请求会直接猜着生成（例如"把它上色"只有图没有方向）。升级为：参数缺失 → 主 Agent 先问清楚（图片先留存）→ 用户补全或说"看你 / 拒绝" → 再用完整参数或默认值交付子 Agent。让"生成前确认"成为设计师的自然工作流。
- **创作参数可选化**：文生图 / 图文生图增加可追问的创作参数 `style`（风格）与 `size`（画幅），通过 `ask_clarification` 主动确认，而不是全部走后端默认值。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 作品库存储 | **SQLite `artcn.db` 扩展 `images` 表 + 持久目录 `Server/gallery/`** | 复用 Spec2 已就位的持久库（已 gitignore、已持久化），文件与元数据分离：库管"谁的、哪来的、什么时候"，目录管字节 |
| 图片文件位置 | `Server/gallery/`（项目文件夹内） | 作者要求"持久数据库放项目文件夹下即可"；与临时 `storage/`（TTL 1h、启动清空）**完全分开**，重启不清、不受 TTL 影响 |
| 画廊是否带 prompt | **带**（AI 生成/编辑结果记一条生成描述；上传原图为空） | 方便回看、检索、日后"再来一版"。**不存任何对话/聊天正文**（"不用存文字"的范围） |
| 服务方式 | **鉴权接口** `GET /api/gallery/{id}/file`，校验归属 | "每个人有每个人的作品库"→ 必须按用户隔离，不能像 `/images` 那样公开按 UUID 可访问 |
| 追问粒度 | **必填 + 创作参数都追问** | 作者拍板：不满足于"缺主体才问"，风格 / 画幅没指明时也主动确认，更贴近设计师 |
| 创作参数落 API | `style` 合并进 prompt；`size` 直接透传给 TokenHub | hy-image-v3 无 `style` 字段；`size` 字段 provider 已支持（`generate_image` / `sketch_to_image` 已有 `size` 形参），无需改 provider |
| 挂起意图（pending）存储 | **内存**（按 thread_id，重启即丢） | 作者拍板。追问是秒级/分钟级的短期态；丢了大不了重说一次。图片本身已由作品库持久化，不丢 |
| 追问实现 | **新增第 4 个工具 `ask_clarification`**，走既有 LangGraph 工具机制 | 结构化工参，后端可稳定识别"要不要建挂起意图"；仍是**单跳、每轮一次 LLM 调用**，不违反 Spec.md"结果不再回送 Supervisor 总结" |

> 排除项：图片以 BLOB 存库（库会变大、备份难）；`/gallery` 公开静态挂载（无法做按用户隔离）；pending 存数据库（需清理过期残留，作者已选择内存）；视频/音频/多图、批量生成、inpainting（均 v2+ 再议）。

### 2.1 追问的"单跳"边界（明确不违反）

Spec.md 的单跳约束是"工具结果不再回送 Supervisor 二次总结"。追问流程中**每一轮仍然只调用一次 DeepSeek 路由**：
- 第一轮：参数不全 → 路由选择 `ask_clarification`（一个无副作用工具），其返回值（追问文案）**就是**最终响应，不回送 LLM；
- 第二轮（用户回复）：新一轮 `/api/chat` → 又一次单跳路由，主 Agent 依据"挂起上下文 + 用户本轮回复"直接选中真实工具执行。

因此不新增任何"第二次 LLM pass"，也没有工具串联（每轮最多一个工具）。

---

## 3. 需求边界

### 范围内

- 作品库：每个用户上传 + AI 返回的全部图片持久保存（`images` 表 + `gallery/` 目录），按用户隔离。
- 画廊接口：列出我的作品（可按来源筛选）/ 查看原图 / 下载 / 删除；越权访问他人作品返回 `404`（不泄露是否存在）。
- 画廊前端：「我的作品」面板（所有登录用户可见），网格展示 + 来源标签 + 查看大图 + 下载 + 删除。
- 入库链路：上传即入库（无论之后是否被对话用到）；文生图 / 图文生图**成功**结果入库（带 prompt）；图像 QA 只回文本、不产生作品记录。
- 多轮追问：参数不全 → 主 Agent 追问（含创作参数 `style` / `size`）；用户补全或表示"看你 / 随便 / 你定 / 拒绝" → 交付子 Agent。
- 删除用户：连带删除其作品记录与文件（同 Spec4 usage 级联的口径一致性）。

### 范围外（本 Spec 不做）

- 存对话正文、聊天记录落库（明确排除）。
- 作品分享 / 公开链接 / 转存他人作品；相册、标签、收藏、按时间分组。
- 作品级统计（多少张、多大）、配额/容量上限（磁盘膨胀为已知可接受成本，v2 加 per-user 上限再议）。
- pending 持久化（重启后追问不恢复，作者选择内存）。
- 批量出图（一次 n 张）、seed 控制、局部重绘（inpainting）——`seed` 可作为 v2 创作参数，本版不引入。
- 不修改 Spec.md / Spec2.md / Spec3.md / Spec4.md 已有接口形态（`/api/images`、`/api/chat` 等均不改；仅 `agents` 内部与 `prompts.py` 工具定义扩展）。

### 已知边界与风险（写进本文档，避免误读）

- **pending 重启即丢**：内网穿透部署下后端重启（如 `uvicorn --reload` 开发热重载），未完成的追问清空，用户需重发一次。
- **持图时效**：挂起意图持有的 `image_url` 是 `storage/` 的临时 URL（TTL 1h）。追问一般在分钟级内结束，足够；若用户在图片过期后才回复，子 Agent 报"图片不存在或已过期"，重传即可。作品库里的持久副本不受影响。
- **磁盘增长**：作品库持续累积不清理（设计如此）。上传单张 ≤10MB、单用户生成量有限，个人部署可接受。
- **画廊图片不提供公开 URL**：`<img>` 标签无法带 `Authorization` 头，前端需用带 token 的 axios 拉 blob → `objectURL` 渲染（见 §7）。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | 无新依赖 | 复用 `sqlite3`（Spec2）+ 既有 `PIL` / httpx；新增 `gallery.py` 模块 + `images` 表 |
| 前端 | 无新依赖 / 无新框架 | 新增 `GalleryPanel.vue`，复用现有紫色主题样式 |

---

## 5. 架构设计（增量）

### 5.1 分层

```
Vue 3 SPA（聊天页 + 用户管理 + 数据统计 + 我的作品）
   │ Authorization: Bearer <JWT>
FastAPI（统一鉴权中间件已就位）
   ├─ 作品库：/api/gallery（列出/查看/下载/删除，校验归属）
   │    写入：POST /api/images 上传即入库；文生图/图文生图成功后入库
   ├─ 追问：worker 内 pending_store（内存，按 thread_id）↔ Supervisor 工具 ask_clarification
SQLite Server/artcn.db（users + usage + images 表）
持久目录 Server/gallery/（图片字节，与 storage/ 无关）
```

### 5.2 关键数据流

**作品库——入库（两条链路）**

1. **上传即入库**：`POST /api/images` 成功 → 除原样落 `storage/` 返回 `/images/...` 外，**额外**持久化到 `gallery/` + `images` 表（`source='upload'`，`prompt=NULL`）。
2. **AI 结果入库**：文生图 / 图文生图子 Agent 成功拿到图片字节 → 先照旧落 `storage/` 供对话渲染，**额外**持久化到 `gallery/` + `images` 表（`source='generate'` / `'edit'`，`prompt` = 实际发给 API 的完整描述，含合并的风格）。图像 QA 无图片输出，不写。

**作品库——读取**

- `GET /api/gallery`（登录）→ 返回**本人**作品（`ORDER BY created_at DESC`，可按 `source` 筛选）。
- 前端逐张 `GET /api/gallery/{id}/file`（带 token）→ blob → `objectURL` 渲染；下载同理（`?download=1` → `Content-Disposition: attachment`）。
- 所有读取/删除先校验 `images.user_id == 当前用户`，否则 `40403`。

**追问——第一轮（参数不全）**

```
用户：传线稿 + "把它上色"（带 image_url）
  → worker handle_task：无 pending → run_supervisor
  → 路由：意图=edit_image，但缺风格/画幅 → 调用 ask_clarification(
        intent="edit_image", missing=["style","size"],
        question="想用什么风格？画幅多大？比如：赛博朋克风、16:9。")
  → tool_node 拦截 ask_clarification → 返回 {kind:"clarify", intent, question,
       image_url:<本轮带的图>}
  → handle_task：kind=="clarify" → pending_store.set(thread_id, {...})
       并把结果转成 {kind:"text", text:question} 返回
  → 前端把它当作一条普通助手文本渲染（无新 UI）
```

**追问——第二轮（用户回答 / 放手）**

```
用户回复（可不再带图）
  → handle_task：pending 存在 → request["pending"]=pending → run_supervisor
  → _build_messages 注入一段"挂起任务上下文"（意图 / 上一轮问题 / 待处理图片 URL / 用户回复）
  → 路由判定：
       a. 参数补齐        → 调真实工具（generate/edit/qa，参数从对话 + 本轮补全）
       b. 用户"看你/随便/你定/拒绝" → 调真实工具，缺失参数用默认值
       c. 用户开新话题    → 不调挂起工具，按新请求正常路由（纯文本 或 新工具）
  → handle_task：结果 kind 不是 clarify → pending_store.clear(thread_id)
```

> 关键点：**后端只在"结果为 clarify"时写 pending，其余一律清 pending**。用户的"开新话题"由 Supervisor 的判定自然表达为"不调挂起工具"，pending 随之清除，无需额外状态机。

### 5.3 数据表（images，追加到 artcn.db）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER 自增主键 | 作品 ID |
| user_id | INTEGER NOT NULL | 归属用户；删用户时级联删除 |
| source | TEXT NOT NULL | `upload` \| `generate` \| `edit` |
| file_name | TEXT NOT NULL | `gallery/` 下的持久文件名（uuid + ext） |
| ext | TEXT NOT NULL | `.jpg` \| `.png` \| `.webp` \| `.gif` |
| prompt | TEXT | 生成/编辑实际使用的完整描述（含合并的风格）；上传为 `NULL` |
| created_at | TEXT | ISO8601 |

索引：`(user_id, created_at DESC)`（画廊按用户 + 时间倒序）。

### 5.4 子 Agent 参数（扩展前 → 扩展后）

| 子 Agent | 工具（扩展前） | 扩展后参数 | 说明 |
|---|---|---|---|
| 文生图 | `generate_image(prompt)` | `prompt`（必填，≤256）· `style?` · `size?` | 新增创作参数 |
| 图文生图 | `edit_image(prompt, image_url)` | `prompt`（必填，≤200）· `image_url`（必填）· `style?` · `size?` | 新增创作参数 |
| 图文分析 | `qa_image(image_url, question)` | `image_url`（必填）· `question`（必填） | 不变 |
| 追问 | （无） | `ask_clarification(intent, missing, question)` | 新增工具 |

**创作参数语义与默认值**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `style` | string | 不指定（模型自由发挥） | 风格描述，子 Agent 合并进 prompt：`"{prompt}，风格：{style}"` |
| `size` | string | `HUNYUAN_IMAGE_SIZE`（1024x1024） | 画幅 `${w}x${h}`，宽高 ∈ [512,2048] 且面积 ≤1024×1024（TokenHub 限制）；非法值 → 任务失败 `61004` |
| `question`（QA 用） | string | 用户说"看你"时用 **"请详细描述这张图片的内容。"** | 追问后放手的兜底 |

> `size` 在 provider 层已支持透传（`providers/tokenhub.py` 的 `generate_image(prompt, size)` / `sketch_to_image(prompt, image_bytes, size)`），本 Spec 只把子 Agent 暴露的参数接上去，**不改 provider**。

### 5.5 挂起意图（pending，内存）

```python
PendingIntent = {
    "thread_id": str,
    "intent":    "generate_image" | "edit_image" | "qa_image",  # 计划调用的工具
    "image_url": str | None,   # 上一轮携带的图（用户补全参数时不必再传图）
    "question":  str,          # 上一轮追问文案（供 Supervisor 回忆）
    "created_at": float,
}
```

- **存储**：内存 dict `{thread_id: PendingIntent}` + `asyncio.Lock`（与现有 `ThreadStore` 同级，位于 `main.py`）。
- **生命周期**：交付真实工具 → 清；结果为非 clarify → 清；超过 `PENDING_INTENT_TTL_SECONDS`（默认 1800s）→ 访问时清，视为新会话。
- **多次追问**：用户只答了一部分 → 主 Agent 再 `ask_clarification` → 覆盖写 pending；新一轮若没带图，`image_url` **沿用旧的**（`result.get("image_url") or old_pending.image_url`）。
- **持图**：直接存用户消息里的 `/images` URL；作品库已把该上传持久化，源图不丢（见 §3 时效边界）。

---

## 6. 接口约定

### 6.1 新增端点

| 方法 & 路径 | 鉴权 | 请求 | 成功响应 `data` | 说明 |
|---|---|---|---|---|
| `GET /api/gallery` | 登录 | `?source=upload\|generate\|edit`（可选） | `{items:[{id, source, url, prompt, created_at}]}` | 本人作品，时间倒序 |
| `GET /api/gallery/{id}/file` | 登录·本人 | `?download=1`（可选） | 图片字节（`Content-Type` 按 ext） | `download=1` 附加 `Content-Disposition: attachment` |
| `DELETE /api/gallery/{id}` | 登录·本人 | 无 | `{id}` | 删除记录 + 持久文件 |

- `url` 为 `/api/gallery/{id}/file`（需带 token 访问，前端用 blob 拉取）。
- 未登录 → `40103`（既有中间件）；非本人 / 不存在 → `404`（`40403`，见 §9）。
- 业务响应仍走 `{code, message, data}` 包装。

### 6.2 任务结果新增形态

`ask_clarification` 触发的任务，轮询终态返回：

```json
{ "kind": "text", "text": "想用什么风格？画幅多大？比如：赛博朋克风、16:9。" }
```

> 前端**零改动**渲染——追问就是一条普通助手文本气泡，用户在输入框正常回复即可。后端据此建/续挂起意图。

### 6.3 既有接口

- `POST /api/images`、`POST /api/chat`、`GET /api/tasks/{id}` 等**契约不变**（`/api/images` 响应仍是 `{image_url}`，不新增字段）。
- `/api/chat` 内部行为变化（pending 注入）对前端透明。

---

## 7. 前端交互

- **我的作品**：登录后聊天页头部出现「**我的作品**」按钮（**所有登录用户**都可见，不像「用户管理 / 数据统计」仅管理员）。与后两者**互斥**：打开一个自动关闭另外两个；面板内「返回聊天」回到聊天页。
- **`GalleryPanel.vue`**（形态沿用 AdminPanel / StatsPanel）：
  - 提示行：`当前登录：<用户名> · 我的作品仅本人可见`。
  - 筛选 Tab：`全部 / 上传 / 文生图 / 图文生图`（对应 `source='' / upload / generate / edit`）。
  - 网格卡片：缩略图（axios 带 token 拉 `file` → blob → `objectURL`）、来源标签、时间（本地时区）；操作：**查看大图**（overlay 大图）、**下载**（blob → 触发浏览器保存）、**删除**（确认后 DELETE → 刷新）。
- **追问**：无需新 UI（见 §6.2）。
- `api/chatApi.js` 新增：`listGallery({source})` / `fetchGalleryFile(id, download=false)` / `deleteGalleryItem(id)`。

---

## 8. 文件改动清单

| 文件 | 改动 |
|---|---|
| `Server/config.py` | 新增 `GALLERY_DIR = BASE_DIR / "gallery"`、`PENDING_INTENT_TTL_SECONDS = 1800`；启动确保目录存在 |
| `Server/db.py` | 新增 `images` 建表 + `add_image_record` / `get_image_record` / `list_image_records(user_id, source)` / `delete_image_record` / `delete_user_image_records`；`delete_user` 级联 |
| `Server/gallery.py`（新建） | `save_gallery_image(bytes, user_id, source, prompt)`（写文件 + 落库）、`list_user_images`、`get_item`、`delete_item(item_id, user_id)`（校验归属 + 删文件 + 删记录）、`read_gallery_file` |
| `Server/main.py` | 上传成功额外入库；`handle_task` 挂起意图逻辑（PendingStore：get/set/clear，TTL 检查）；新增 `/api/gallery` 三个路由；`delete_user` 级联作品 |
| `Server/agents/prompts.py` | 工具定义扩展 `style`/`size` + 新增 `ask_clarification`；`SUPERVISOR_SYSTEM_PROMPT` 补追问规则 / 默认值 / pending 上下文处理说明 |
| `Server/agents/supervisor.py` | `tool_node` 拦截 `ask_clarification` → 返回 `{kind:"clarify",...}`（不透传 provider）；给真实子 Agent 注入 `user_id`；`_build_messages` 注入 pending 上下文 |
| `Server/agents/generation.py` | 读 `style`/`size`，合并风格进 prompt，透传 size，成功后落库（`source='generate'`，prompt=完整描述） |
| `Server/agents/editing.py` | 同上（`source='edit'`） |
| `Server/errors.py` | 新增 `GalleryItemNotFoundError`（`40403`） |
| `Server/.gitignore` | 追加 `Server/gallery/` |
| `frontend/src/api/chatApi.js` | 新增画廊三接口 |
| `frontend/src/views/GalleryPanel.vue`（新建） | 画廊面板（筛选 + 网格 + 大图 + 下载 + 删除） |
| `frontend/src/App.vue` | 「我的作品」入口（所有用户）+ 三面板互斥 |

> 无 `.env` 变更（无新密钥）；无 `requirements.txt` 变更；`providers/tokenhub.py` 不改。

---

## 9. 错误码新增（追加到 Spec.md §9 / Spec2 §9 之后）

| HTTP | code | 含义 | 触发示例 |
|---|---|---|---|
| 404 | 40403 | 作品不存在或不属于当前用户 | 访问/删除他人作品、ID 不存在 |

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON；新增事件：

- `gallery.saved`（入库，附 user_id / source / prompt 截断）
- `gallery.deleted`（删除，附 user_id / item_id）
- `clarify.asked`（发起追问，附 thread_id / intent / question）
- `clarify.resolved`（挂起意图交付或清除，附 thread_id / intent）

**禁止**：把对话正文、完整 prompt、图片内容写入日志；`prompt` 超长截断（如 200 字符）。

---

## 11. 实施顺序（里程碑）

1. **G1 数据层**：`config.GALLERY_DIR`；`db.py` 的 `images` 表与函数；`gallery.py`（落盘 + 落库 + 归属校验）。
2. **G2 入库链路**：`main.py` 上传即入库；`supervisor.tool_node` 注入 `user_id`；`generation.py` / `editing.py` 结果入库。
3. **G3 画廊 API**：`GET /api/gallery` · `GET /api/gallery/{id}/file` · `DELETE /api/gallery/{id}` + `40403` + 删除用户级联。
4. **G4 前端画廊**：`chatApi.js` + `GalleryPanel.vue` + `App.vue` 入口（三面板互斥）。
5. **C1 创作参数扩展**：`prompts.py` 工具定义加 `style`/`size`；`generation.py` / `editing.py` 合并风格 + 校验 size。
6. **C2 追问机制**：`prompts.py` 加 `ask_clarification` + 追问规则 + pending 上下文注入；`supervisor.py` 拦截；`main.py` `PendingStore` + `handle_task` 逻辑。
7. **C3 验收**：按 §12 端到端 Smoke。

---

## 12. 验收用例（端到端 Smoke）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 登录 → 上传一张图（不发消息） | 「我的作品」里出现该图，来源=上传，prompt 空 |
| 2 | 纯文本"做一张赛博朋克海报"（文生图成功） | 作品库新增 `generate` 记录，prompt=该描述 |
| 3 | 线稿 + "按这个上色"（图文生图成功） | 作品库新增 `edit` 记录，prompt 含完整描述 |
| 4 | 上传线稿 + "把它上色"（缺风格/画幅） | 任务完成，返回追问文案；服务端产生 pending |
| 5 | 接着回复"赛博朋克风，16:9"（不带图） | 图文生图成功（用了上轮那张图）；pending 清空；作品库新增 edit 记录，prompt 含"风格：赛博朋克" |
| 6 | 再次追问时回复"看你" | 直接用默认画幅（1024x1024）、不指定风格生成，不再追问 |
| 7 | 上传照片 + "这张图怎么样"（缺具体问题） | 追问"想了解这张图的什么？"；回复"看你" → 返回"请详细描述这张图片的内容。"的回答 |
| 8 | pending 存在时发新话题"帮我想几个标题" | 挂起清空，按纯文本对话正常回复 |
| 9 | 用户 A 直接调 `GET /api/gallery/{B的作品id}/file` | `404`（`40403`），不泄露存在性 |
| 10 | 删除一个作品 | 列表消失，`gallery/` 下文件同步删除 |
| 11 | 重启后端 | 作品库仍在（`artcn.db` + `gallery/` 持久）；进行中的追问丢失（内存） |
| 12 | 图像 QA 成功 | 作品库**无新增** |
| 13 | 未登录访问 `/api/gallery` | `401`（`40103`） |
| 14 | 子 Agent 收到非法 `size`（如 `9999x9999`） | 任务 `FAILED`，`error.code=61004` |
| 15 | 管理员删除一个有作品的用户 | 该用户作品记录与文件一并删除 |

> 验收时明确排除：对话落库、分享/公开链接、收藏分组、pending 持久化、批量出图、seed、inpainting。
