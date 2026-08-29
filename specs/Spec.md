# ArtiControlNet 重构 Spec

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）。本文件描述**做什么、删什么、留什么、怎么跑、接口长什么样**，不含具体实现代码。
>
> 一句话：为设计师打造一个**多智能体 AIGC 对话工作台**。用户以自然语言（可带参考图）提出需求，主 Agent 做一次意图分发，子 Agent 全部通过**外部云端模型 API**完成「文生图 / 线稿生图 / 图像问答」，结果**直接返回给用户**。
>
> 硬约束：**不做任何本地推理、不用数据库、只有前后端两层**。前端可静态部署（GitHub Pages），后端为无状态 API 编排服务。API 手册来源：`API's Usage/` 目录（保留为参考）。

---

## 1. 功能目的

- **多智能体编排（单跳分发）**：一个主 Agent（Supervisor）仅负责**一次意图识别与工具选择**，把请求分发给对应子 Agent；子 Agent 执行完，结果**直接回给用户**，不再经 Supervisor 二次总结。
- **三类能力，全部走外部 API**：
  - **文生图**：纯文字 → 返回纯图片（TokenHub `hy-image-v3` 文生图）。
  - **线稿生图（图像编辑）**：黑白线稿 + 文字 → 返回完整绘制图（TokenHub `hy-image-v3` 图生图，`images` 传线稿）——即"按这张线稿生成赛博朋克插画"这类场景，作为图像编辑的 v1 实现。
  - **图像问答**：图片 + 问题 → 返回文本（DeepSeek `deepseek-v4-flash-vision-exp`）。
  - 纯文本对话：Supervisor 直接用 DeepSeek 纯文本模型回复，不进入子 Agent。
- **对话式工作台**：简洁对话界面，对话流中可上传图片、多轮追问；前端本地保存历史。
- **轻量可部署**：后端无状态、无数据库；前端纯静态，为搬到 GitHub.io 铺路。

## 2. 需求场景（按能力划分）

| # | 场景 | 用户输入 | 路由 | 子 Agent | 外部 API | 返回 |
|---|---|---|---|---|---|---|
| A | **文生图** | 纯文字："做一张新年海报，标题『2026 龙年』" | Supervisor → 生成 | Generation | TokenHub `hy-image-v3` | **纯图片** |
| B | **线稿生图（图像编辑）** | 上传黑白线稿 + "按这个上色成赛博朋克风插画" | Supervisor → 线稿生图 | Edit | TokenHub `hy-image-v3`（传 `images`） | 图片 |
| C | **图像问答** | 上传照片 + "这张图里有什么？构图如何？" | Supervisor → QA | QA | DeepSeek vision | 文本 |
| D | **纯文本对话** | "帮我想三个海报标题"（无图像需求） | Supervisor 直接回复 | 无 | DeepSeek `deepseek-v4-flash` | 文本 |
| E | **多轮追问** | 上轮结果图 + "再亮一点 / 换个角度重来" | Supervisor 依据会话上下文再次分发 | 对应子 Agent | 同上 | 对应结果 |

> 说明：场景 B 的"线稿生图"即用户所说的图像编辑。v1 用 TokenHub **`hy-image-v3`**（图生图，`images` 传线稿 base64）承载"黑白线稿 + 文字描述 → 完整绘制图"（对线稿做色彩填充与细节描绘）。它仅接受线稿类输入，不做照片级/局部擦除重绘——这是 v1 边界。

## 3. 需求边界

### 数据流（本版定稿：单跳，不二次过 Supervisor）

```
用户
 │ ① 消息（可带图）
 ▼
Supervisor（一次 LLM 路由：选中 0~1 个子 Agent）
 │ ② 命中子 Agent → 调用其外部 API
 ▼
子 Agent（生成 / 线稿生图 / QA）
 │ ③ 结果（图片 或 文本）直接作为最终响应
 ▼
用户
```

- 子 Agent 结果**不送回 Supervisor 总结**（省一次 LLM 调用）。
- 纯文本场景：Supervisor 在 ② 发现不需要任何子 Agent，则直接返回文本。
- **复合任务（单轮内依次调用多个能力，如"先分析再生成"）不在 v1 支持**：走多轮对话（用户逐条指令）；v2 再让 Supervisor 支持多工具串联。

### 范围内（v1）
- 对话式多轮会话（thread_id 维护上下文，前端 localStorage 持久化历史）。
- 对话中**单图**上传（jpg/png/webp/gif，≤10MB，QA 模型 ≤32MiB）。
- 三类能力 + 纯文本聊天，全部走外部 API。
- 异步任务：提交即返回 `task_id`，前端轮询；任务与短期会话仅存**内存**，重启即丢（可接受）。
- 前端可静态构建（GitHub Pages），后端可部署公网服务器。

### 范围外（非目标，v2+ 再议）
- 本地推理、ControlNet、GPU、本地模型。
- 数据库 / 长期持久化 / 跨重启恢复 / 任务重跑。
- 用户体系 / 权限 / 计费 / 多租户。
- WebSocket / SSE 流式输出（预留升级点）。
- 视频 / 音频 / 3D / 批处理 / 多图同时处理。
- 局部精细编辑（inpainting / 蒙版重绘）、多工具单轮串联。
- **前端承载任何 API Key**——所有密钥只出现在后端环境变量。

---

## 4. 技术栈（无数据库，仅前后端）

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | **Python 3.10+ · FastAPI · Uvicorn** | 编排层：路由 + 主 Agent + 任务引擎 |
| | httpx | 异步调用外部 API（DeepSeek / TokenHub 统一生图） |
| | LangGraph + langchain-openai | 主 Agent 单跳路由 |
| | pydantic · python-multipart | 请求校验 / 文件上传 |
| | **无数据库** | 内存任务注册表 + asyncio.Queue |
| 前端 | **Vue 3 + Vite + Pinia + Axios**（**移除 vue-router**） | 对话式 SPA |
| | 紫色主题 `:root` 配色保留 | 视觉延续现状 |

> Python 版本无兼容负担（无 torch/ControlNet），直接用 Python 3.10+ 与最新 LangGraph。

---

## 5. 架构设计

### 5.1 分层

```
┌─ 前端层  Vue3 SPA（纯静态，GitHub Pages 托管）
│    · 对话流渲染、图片上传/预览、任务轮询、localStorage 历史
│    · 通信：REST/JSON，请求带 X-Request-Id
│
├─ 编排层  FastAPI 后端（公网服务器，无状态）
│    · 路由：/api/chat  /api/images  /api/tasks/{id}  /api/threads/{id}/messages  /healthz
│    · 主 Agent（单跳）：LangGraph 一次路由，选中 0~1 个子 Agent，结果直接返回
│    · 任务引擎：asyncio.Queue + Worker + 内存任务注册表
│        ├─ GenerationAgent ──▶ TokenHub hy-image-v3 文生图
│        ├─ EditAgent      ──▶ TokenHub hy-image-v3 图生图
│        └─ QAAgent        ──▶ DeepSeek deepseek-v4-flash-vision-exp
│    · 图片落盘 storage/ 并由 /images 静态服务（临时，非持久化）
│
└─ 模型提供层  外部云端 API
     DeepSeek（纯文本路由 + 视觉 QA）· TokenHub（统一生图：文生图 + 线稿生图）
```

### 5.2 通信约定

- **前端 → 后端**：HTTP/JSON。`POST /api/chat` 立即返回 `{task_id, thread_id}`（异步），`GET /api/tasks/{task_id}` 每 1~2s 轮询至终态。统一响应 `{code, message, data}`。
- **后端 → 外部 API**：
  - DeepSeek：OpenAI 兼容（`base_url=https://api.deepseek.com`），无状态，多轮上下文由后端拼接后整体发送。
  - TokenHub：`POST {TOKENHUB_API_URL}`，`Authorization: Bearer <TOKENHUB_API_KEY>`，OpenAI 风格 JSON（`model/prompt/size/images`）。
- **跨域**：后端 CORS 白名单由 `CORS_ALLOW_ORIGINS` 控制（GitHub Pages 部署后填前端域名）。
- **关联追踪**：前端发 `X-Request-Id`，后端全程写入日志（§10）。

### 5.3 部署

- **前端（GitHub Pages）**：`npm run build` → `dist/`；子路径部署设 Vite `base`；API 基址用 `VITE_API_BASE`；开发模式经 Vite 代理到本地后端。
- **后端（公网服务器）**：FastAPI + Uvicorn 部署到任意可公网访问的主机；所有密钥经环境变量注入；无状态。
- **本地演示**：后端也可直接托管前端 `dist/`（一个端口跑完）。

---

## 6. 主 Agent 与子 Agent

**主 Agent（Supervisor，`agents/supervisor.py`）**
- **单跳实现**：LangGraph StateGraph `START → router → (tool?) → END`。router 用 DeepSeek `deepseek-v4-flash`（支持 Tool Calls）做一次选择：
  - 选中工具 → 工具（= 子 Agent）执行，**工具返回值就是最终响应**，不再回送 LLM；
  - 未选中工具 → router 的文本输出就是最终响应（纯文本对话）。
- 具名工具：`generate_image(...)`、`edit_image(...)`、`qa_image(...)`，对应三个子 Agent。
- 系统提示词（`agents/prompts.py`）：给出三种工具的适用条件与参数格式；要求"带参考图 + 生成类需求 → edit_image；无参考图 + 生成类需求 → generate_image；图片理解/分析 → qa_image；其余 → 直接文本回答"。

**子 Agent 契约**

| 子 Agent | 输入 | 输出 | 外部 API（详见 §7） |
|---|---|---|---|
| **Generation 文生图** | `prompt`（文字描述） | **图片 URL 列表**（纯图片，无文本包裹） | TokenHub `hy-image-v3` |
| **Edit 线稿生图（图像编辑）** | `prompt` + `image_url`（黑白线稿，base64 或已传图 URL） | **图片 URL 列表** | TokenHub `hy-image-v3`（图生图） |
| **QA 图像问答** | `image_url`（base64） + `question` | **文本回答** | DeepSeek `deepseek-v4-flash-vision-exp` |

- 子 Agent 数量设计依据：设计师闭环 = 提需求 → 得图 → 问/改图 → 再得图，v1 至少需要**生成、线稿生图、问答**三个子 Agent + 纯文本兜底；提示词优化、超分、多工具串联等列为 v2 可插拔项。

**多轮上下文**：后端按 `thread_id` 在内存保留最近约 20 条消息；Supervisor 路由时拼接"最近几轮文本 + 本轮图片（base64）"作为 LLM 上下文。历史仅用于路由，不持久化。

---

## 7. 外部 API 记录（密钥配置 + 调用方式）

> 手册原文见 `API's Usage/`。所有 Key 只经后端环境变量注入，不写进仓库。

### 7.1 DeepSeek（Supervisor 路由 + 图像 QA）— OpenAI 兼容

| 项 | 值 |
|---|---|
| base_url | `https://api.deepseek.com` |
| 认证 | `Authorization: Bearer <DEEPSEEK_API_KEY>` |
| 协议 | OpenAI Chat Completions 兼容（也支持 Responses / Anthropic 端点） |
| 路由模型 | `deepseek-v4-flash`（纯文本，支持 Tool Calls / JSON Output） |
| QA 模型 | `deepseek-v4-flash-vision-exp`（额外支持图片输入） |
| 无状态 | 服务端不存上下文，后端需自行拼接多轮 messages |

**纯文本（路由 / 对话）调用**：
```python
from openai import OpenAI
client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "把这张图做成赛博朋克海报"}],  # 可附 tool 定义
)
print(resp.choices[0].message.content)
```

**图像 QA 调用**（`content` 必须是块数组；图片只在 user 消息里）：
```python
import base64
b64 = base64.b64encode(open("image.jpg","rb").read()).decode()
resp = client.chat.completions.create(
    model="deepseek-v4-flash-vision-exp",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "这张图片里有什么？"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]}],
)
print(resp.choices[0].message.content)
```
- 图片格式：JPEG / PNG / GIF / WebP（按实际内容识别）。
- 限制：内联请求体 ≤48MiB，单图 base64/URL ≤32MiB；`detail` 可选 low（省 token）/ high / original / auto。

### 7.2 TokenHub · 统一生图 `hy-image-v3`（文生图 + 线稿生图）

文生图与线稿生图走**同一个** OpenAI 风格同步接口（原腾讯云 TC3 接口已废弃，不再使用）：

| 项 | 值 |
|---|---|
| 端点 | `POST https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v3-generation` |
| 认证 | `Authorization: Bearer <TOKENHUB_API_KEY>` |
| 请求 | `{model, prompt, size, images?, seed?, footnote?, revise?}` |
| `model` | `hy-image-v3`（Hy-Image-3.0，最新混元生图模型） |
| `prompt` | 文本描述，≤8192 字符，推荐中文 |
| `size` | `${w}x${h}`，宽高各 ∈ [512,2048]，面积 ≤1024×1024；默认 `1024x1024` |
| `images` | 图生图专用：0~3 张参考图，**URL 或 `data:image/...;base64,...`**，png/jpeg/jpg，每张 ≤10MB |
| 输出 | 同步返回 `data[0].url`（生成图，**有效期 12 小时**）+ `request_id` + `usage.total_tokens` |
| 计费 | 按 token 计费（10 元/百万 tokens） |
| 前置 | 需在控制台 https://console.cloud.tencent.com/tokenhub/inference 开启后付费 |

**通用注意事项**：
1. 返回的生成图 URL 12 小时后失效 → 后端拿到 url 后**立即下载转存**到本服务 `storage/`，再返回本站 `/images/{file}` URL。
2. Prompt 限长且推荐中文 → 文生图子 Agent 截断 ≤256、线稿生图子 Agent 截断 ≤200 字符。
3. 图生图输入的线稿，转 base64 前先缩放/压缩至单边 ≤2000px、base64 ≤6MB（沿用 `media.enforce_sketch_input`）。

### 7.4 密钥与环境变量

| 环境变量 | 用途 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 路由 + QA | 真实值见 §7.5 |
| `OPENAI_BASE_URL` | DeepSeek 端点 | 默认 `https://api.deepseek.com` |
| `MODEL_NAME` | Supervisor 文本模型 | 默认 `deepseek-v4-flash` |
| `VLM_MODEL` | QA 视觉模型 | 默认 `deepseek-v4-flash-vision-exp` |
| `TOKENHUB_API_KEY` | TokenHub 统一生图 | 真实值见 §7.5 |
| `TOKENHUB_API_URL` | TokenHub 生图端点 | 默认 `https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v3-generation` |
| `HUNYUAN_IMAGE_MODEL` | 生图模型 ID | 默认 `hy-image-v3` |
| `HUNYUAN_IMAGE_SIZE` | 默认生成尺寸 | 默认 `1024x1024` |
| `CORS_ALLOW_ORIGINS` | 跨域白名单 | 逗号分隔 |
| `MAIN_SERVER_HOST` / `MAIN_SERVER_PORT` | 后端监听 | 默认 `0.0.0.0:8000` |

### 7.5 密钥登记（真实值只放 `Server/.env`，仓库内为占位符）

> ⚠️ **安全约定**：仓库内**不存放任何真实密钥**。真实值只存在于被 gitignore 的 `Server/.env` 与本地 `API's Usage/`。
> 1. 提交前用 `git status` / `grep` 确认无真实密钥入库（尤其本节）；
> 2. 若密钥曾提交到任何远程仓库，立即到控制台**吊销并更换**。

| 变量 | 值 |
|---|---|
| `DEEPSEEK_API_KEY` | （真实值只放 `Server/.env`） |
| `TOKENHUB_API_KEY` | （真实值只放 `Server/.env`） |

### 7.6 `.gitignore`（缺失，需新建）

仓库当前**没有 `.gitignore`**，真实密钥直接躺在 `API's Usage/` 下。Spec Coding 第一步应创建 `.gitignore`，至少包含：

```gitignore
node_modules/
dist/
.env
Server/storage/
tmp_images/
API's Usage/
```

---

## 8. 接口约定

### 8.1 统一响应包装

```json
{ "code": 200, "message": "ok", "data": { ... } }
```

- HTTP 状态与业务 `code` 语义一致（见 §9）；任务结果/失败通过轮询响应体返回，不占用提交时的 HTTP 状态。
- 请求携带 `X-Request-Id`，后端透传到日志。

### 8.2 端点

| 方法 & 路径 | 请求 | 成功响应 `data` | 说明 |
|---|---|---|---|
| `GET /healthz` | - | `{ status: "ok" }` | 健康检查 |
| `POST /api/chat` | JSON `{ message, image_url?, thread_id? }` | `{ task_id, thread_id }` | 异步提交，立即返回 |
| `POST /api/images` | multipart `file` | `{ image_url }` | 先传图再发消息 |
| `GET /api/tasks/{task_id}` | - | `{ task_id, status, error?, result? }` | 轮询；终态含 `result` |
| `GET /api/threads/{thread_id}/messages` | - | `{ messages: [...] }` | 内存近期会话（可选） |

### 8.3 任务模型（内存）

```python
Task = {
  "id": int, "thread_id": str, "kind": "chat|generate|edit|qa",
  "status": "PENDING|PROCESSING|COMPLETED|FAILED",
  "request": {...}, "result": {...} | None, "error": {...} | None,
  "created_at": "...", "started_at": "...", "finished_at": "..."
}
# result = { "kind": "text|images", "text"?, "images": [本站url,...]? }
#   文生图/线稿生图 → kind=images（纯图片）；QA/纯文本 → kind=text
# error  = { "code": 61001, "message": "..." }
```

- 任务注册表：内存字典 + `asyncio.Lock`；终态任务保留约 1 小时或最近 N 条后淘汰。
- 图片：上传/外部返回统一落 `storage/` 并经 `GET /images/{file}` 服务；**启动时清空 `storage/`，运行中文件 TTL 1 小时**（防磁盘膨胀，非持久化）。

### 8.4 前端交互契约

- `POST /api/chat` 得 `task_id` → 气泡进入"生成中" → 每 1~2s `GET /api/tasks/{id}` → `COMPLETED` 按 `result.kind` 渲染文本/图；`FAILED` 渲染 `error.message` 并提供重试。
- 多轮：复用 `thread_id`；历史存 localStorage，刷新恢复（后端内存历史仅当次运行有效）。
- 返回的 `image_url` 为**浏览器可直接访问的绝对地址**（后端把 `/images/{file}` 拼上自身公网基址再返回）；开发模式经 Vite 代理或后端基址补全。
- v1 前端为**纯对话**，不设生图参数面板；文生图尺寸等走后端 env 默认值（如 `HUNYUAN_IMAGE_SIZE`）。

---

## 9. 错误码

### 9.1 HTTP 层

| HTTP | code | 含义 | 触发示例 |
|---|---|---|---|
| 200 | 200 | 成功 | 正常响应 |
| 400 | 40001 | 请求参数非法 | 缺 `message` / 格式错误 |
| 400 | 40002 | 文件缺失或损坏 | 未上传文件 |
| 400 | 40003 | 不支持的图片格式 | 传了非 jpg/png/webp/gif |
| 400 | 40004 | 图片超限 | >10MB（或超提供方限制） |
| 401 | 40101 | 后端未配置对应 API Key | `DEEPSEEK_API_KEY` 为空 |
| 404 | 40401 | 资源不存在 | `task_id` 找不到 |
| 500 | 50001 | 内部错误 | 未捕获异常 |
| 502 | 50201 | 上游模型 API 错误 | TokenHub/DeepSeek 4xx/5xx（message 附提供方与错误码） |
| 502 | 50202 | 上游超时 | 超过 120s 未响应 |
| 503 | 50301 | 队列已满 / 并发超限 | 待处理任务超过上限（如 100） |

### 9.2 任务级（轮询 `data.error.code`）

| code | 含义 | 说明 |
|---|---|---|
| 61001 | 上游模型 API 错误 | message 附提供方 + 上游错误码（如 TokenHub `401007` / DeepSeek `rate_limit_exceeded`） |
| 61002 | 上游超时 | 单任务处理超过上限（如 300s） |
| 61003 | 图片下载/解码/转存失败 | 拿到结果但落盘或编码失败 |
| 61004 | 主 Agent 路由失败 | LLM 调用失败或工具异常 |
| 61999 | 未知任务失败 | 兜底 |

---

## 10. 日志格式

后端所有日志输出**单行 JSON** 到 stdout：

| 字段 | 示例 | 说明 |
|---|---|---|
| `ts` | `2026-08-27T12:00:00.000Z` | ISO8601 UTC |
| `level` | `INFO` | DEBUG/INFO/WARN/ERROR |
| `logger` | `task_queue` | 模块名 |
| `event` | `task.completed` | 事件名（kebab-case） |
| `request_id` | `9f1c…` | 透传的 X-Request-Id |
| `thread_id` | `t_ab12` | 会话 |
| `task_id` | `42` | 任务 |
| `provider` | `hunyuan-image` | 外部提供方（deepseek/hunyuan-image） |
| `duration_ms` | `3200` | 耗时 |
| `message` | `生成完成` | 人类可读说明 |

**示例**：
```json
{"ts":"2026-08-27T12:00:00.000Z","level":"INFO","logger":"task_queue","event":"task.started","request_id":"9f1c2d","thread_id":"t_ab12","task_id":42,"kind":"generate","message":"worker 开始处理"}
{"ts":"2026-08-27T12:00:05.100Z","level":"WARN","logger":"providers","event":"provider.retry","request_id":"9f1c2d","task_id":42,"provider":"hunyuan-image","duration_ms":4900,"message":"上游超时，第 1 次重试"}
{"ts":"2026-08-27T12:00:08.300Z","level":"INFO","logger":"task_queue","event":"task.completed","request_id":"9f1c2d","thread_id":"t_ab12","task_id":42,"provider":"hunyuan-image","duration_ms":8300,"message":"线稿生图完成"}
```

- 访问日志（uvicorn）单独保留；应用日志统一走上述 JSON 格式。
- 禁止把 API Key 写进日志；上游响应体过长时截断（如 500 字符）。

---

## 11. 删除 / 保留清单

### 删除（本次重构后不再需要）

| 路径 | 说明 |
|---|---|
| `backend/` 整个目录 | Java Spring Boot + MySQL，删除 |
| `Server/ControlNetServer.py`、`Server/StableDiffusionEngine.py`、`Server/tools/`、`Server/utils.py` | 本地推理栈，删除 |
| `Server/agent/` 整个目录 | 旧占位 Agent 实现，删除 |
| `Server/static/index.html` | 旧简易聊天页，删除 |
| `cldm/`、`ldm/`、`annotator/`、`models/` | vendored ControlNet 代码与权重目录，删除 |
| `frontend/src/views/`、`components/*`、`router/`、`api/taskApi.js`、`store/index.js` | 旧生成式工作台 UI 与 Java 对接代码，删除 |
| 根目录 `config.py`、`environment.yaml`、`tmp_images/` | 迁入/重写，见 §12、§13 |

### 保留

- **紫色主题**：`frontend/src/assets/styles/main.css` 的 `:root` 颜色变量整体保留（硬需求）。
- **`API's Usage/`**：API 手册原始出处，保留为**本地**参考（其内容已提炼进 §7；含真实密钥，按 §7.6 应 gitignore、不入库）。
- `README.md`、`GithubPage/`（宣传素材）。

---

## 12. 目标目录结构

```
Server/
  main.py              # FastAPI 入口：装配路由 / 任务引擎 / 静态托管 / storage
  config.py            # 环境配置（全量 env：DeepSeek/TokenHub/CORS/端口）
  schemas.py           # Pydantic：ChatRequest / UploadOut / TaskResult / ErrorBody
  task_queue.py        # asyncio.Queue + Worker + 内存任务注册表 + 淘汰策略
  providers/
    __init__.py        # 统一工厂：按用途暴露 generate/edit/qa/route 函数
    deepseek.py        # OpenAI 兼容：文本路由 + 视觉 QA
    tokenhub.py        # 统一生图 hy-image-v3：文生图 + 图生图（Bearer 认证）
  agents/
    __init__.py
    supervisor.py      # 主 Agent：单跳路由（START→router→(tool?)→END）
    generation.py      # 文生图子 Agent
    editing.py         # 线稿生图子 Agent（图像编辑）
    qa.py              # 图像问答子 Agent
    prompts.py         # 系统提示词
  storage/             # 临时图片目录（/images 静态挂载）
  static/              # 生产环境挂载 frontend/dist
frontend/
  index.html
  package.json         # 移除 vue-router
  src/
    main.js
    App.vue            # 对话壳：消息流 + 输入区
    api/chatApi.js     # uploadImage / sendChat / getTask / getThread
    store/chat.js      # Pinia：messages / threadId / send() / 轮询
    assets/styles/main.css  # 紫色主题（保留扩展）
    components/
      ChatBubble.vue   # 文本 / 图片 / 生成中 / 结果图 形态
      ChatInput.vue    # 输入 + 图片附件/预览 + 发送
      TypingIndicator.vue
```

---

## 13. 运行方式与命令

### 环境变量（后端 `.env`，均有默认值）

> `config.py` 用 `python-dotenv` 读取 `Server/.env`（该文件进 `.gitignore`）；真实密钥只放 `.env`（值见 §7.5），不写进代码或仓库内其它文件。

```
# DeepSeek（路由 + QA）
DEEPSEEK_API_KEY=...
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash
VLM_MODEL=deepseek-v4-flash-vision-exp

# TokenHub 统一生图（文生图 + 线稿生图）
TOKENHUB_API_KEY=...
# TOKENHUB_API_URL=https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v3-generation
# HUNYUAN_IMAGE_MODEL=hy-image-v3
# HUNYUAN_IMAGE_SIZE=1024x1024

# 服务
CORS_ALLOW_ORIGINS=http://localhost:5173,https://<user>.github.io
MAIN_SERVER_HOST=0.0.0.0
MAIN_SERVER_PORT=8000
```

### 命令

```bash
# 后端依赖
pip install "fastapi" "uvicorn[standard]" httpx langgraph langchain-openai \
            pydantic python-multipart python-dotenv openai Pillow

# 后端（开发，热重载，:8000）
cd Server
uvicorn main:app --reload --port 8000

# 前端（开发，:5173，/api 代理到 :8000）
cd frontend
npm install
npm run dev

# 生产构建 + 本地演示（FastAPI 托管 dist）
cd frontend && npm run build
cd ../Server && uvicorn main:app --port 8000     # 访问 http://localhost:8000

# 部署到 GitHub Pages
cd frontend && npm run build
# 将 dist/ 推送到 gh-pages 分支或独立 Pages 仓库；
# 子路径部署先设 vite.config.js 的 base 与 VITE_API_BASE
```

---

## 14. 实施顺序（Spec Coding 里程碑）

1. **M1 骨架与配置**：`config.py`（全部 env）、`main.py` 空壳 + `/healthz`、`schemas.py`。
2. **M2 任务引擎**：`task_queue.py`（asyncio 队列 + Worker + 内存注册表 + 状态机 + JSON 日志）。
3. **M3 提供方适配**：`providers/deepseek.py`（文本路由 + 视觉 QA）、`providers/tokenhub.py`（统一生图 hy-image-v3），先用 mock 占位确认接口形态，再逐个接真实 API 冒烟。
4. **M4 子 Agent**：`generation.py` / `editing.py` / `qa.py`，各自可独立联调（接真实 Key）。
5. **M5 主 Agent**：`supervisor.py`（单跳路由，结果直接返回）。
6. **M6 API 层**：`/api/chat`、`/api/images`、`/api/tasks/{id}`、`/api/threads/{id}/messages`、错误码、CORS。
7. **M7 前端**：对话式 UI（紫色主题）、上传/预览、轮询、localStorage 历史。
8. **M8 部署与联调**：`npm run build` 静态托管、CORS 白名单、GitHub Pages 部署验证、端到端用例跑通。

---

## 15. 验收用例（端到端 Smoke）

每个用例都应在 `GET /api/tasks/{id}` 轮询下走完 `PENDING → PROCESSING → COMPLETED/FAILED`，日志为单行 JSON、含 `request_id`。

| # | 操作 | 期望 `result` | 成功判定 |
|---|---|---|---|
| 1 | 纯文本"帮我想三个海报标题" | `{kind:"text"}` | 返回 3 个标题，无图片 |
| 2 | 纯文本"做一张赛博朋克海报"（无参考图） | `{kind:"images", images:[1]}` | 返回 1 张图（TokenHub `hy-image-v3` 文生图） |
| 3 | 上传黑白线稿 + "按这个上色成赛博朋克插画" | `{kind:"images", images:[1]}` | 返回 1 张完整绘制图（TokenHub `hy-image-v3` 图生图，走 §7.2 转存逻辑） |
| 4 | 上传照片 + "这张图里有什么？" | `{kind:"text"}` | 返回文本分析（DeepSeek vision） |
| 5 | 多轮：对 #2 结果继续"换红色" | 正常分发 | `thread_id` 生效、上下文可用 |
| 6 | 未配置某 Key 时调用对应能力 | 任务 `FAILED`，`error.code=40101` | 错误码正确、日志含 `request_id` |
| 7 | 上游图片 URL 过期（TokenHub 12h） | 无失效 | 后端已转存到本站 `/images/{file}` |
| 8 | 前端刷新页面 | 本地历史仍在 | localStorage 恢复对话 |
| 9 | 并发提交 > 并发上限（如 100） | 第 101 个请求 | 提交即返回 `code=50301`，不排队 |

> 未列出的能力（如参数面板、数据库持久化）v1 一律不做，验收时明确排除。
