# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ArtiControlNet is a **design-empowering AIGC system** for designers ("基于进化算法的条件扩散模型高效架构探究", a university innovation project). Users describe what they want in natural language (optionally attaching a reference image); a Supervisor agent does a single intent-routing pass, and child agents complete "text-to-image / sketch-to-image / image QA" via **external cloud model APIs**, returning results **directly to the user**.

**Hard constraints**: no local inference, **no database**, only two tiers (frontend + backend). All API keys live in backend env vars only — never in the frontend or committed files. **唯一例外**：本地单文件 SQLite `Server/artcn.db`（持久化，与 storage/ 无关）——Spec2 起承载账号库；Spec17 起同一个库再加对话历史（`conversations` / `chat_messages`）、帖子评论（`post_comments`）与任务号计数器（`app_meta.task_id_seq`）。除这一个文件外，仍然没有数据库。

Design source of truth: **`specs/Spec.md`** (do what it says; this file is a quick orientation)。增量需求见 **`specs/Spec2.md`**（登录认证 + 用户管理，已实现）。

## Architecture (two tiers)

```
Vue 3 SPA (frontend/)            FastAPI orchestrator (Server/)         External APIs
──────────────                   ────────────────────────                ─────────────
Chat UI, upload, polling,    →   /api/chat  /api/images                 DeepSeek (routing +
hosted 对话侧边栏                  /api/tasks/{id} /api/conversations/...    vision QA)
                                  async TaskQueue (asyncio, in-memory)   TokenHub (hy-image-v3,
                                  Supervisor (LangGraph, single-hop)       text→img + sketch→img)
                                  SQLite artcn.db（账号/对话/评论）
```

- **Frontend** — Vue 3 + Vite + Pinia + Axios, **no vue-router**. Chat-style SPA; uploads first via `/api/images`, then `POST /api/chat` → polls `GET /api/tasks/{id}` every ~1.5s. 聊天历史**不再存 localStorage**（Spec17：在 `artcn.db` 里按用户分多段对话，左侧 `ConversationSidebar.vue` 常驻），本地只记 `artcn_current_conv:<username>`（刷新后回到上次那段对话）。Purple theme in `frontend/src/assets/styles/main.css` (`:root` vars — preserve)。
- **Backend** (`Server/`) — FastAPI；除 `Server/artcn.db` 外无状态：
  - `main.py` — routes, lifespan (storage cleanup, worker start), error handlers, static hosting; 统一鉴权中间件 + auth/admin 路由（Spec2）；`ThreadStore`（内存路由上下文，启动时按 `conversation_id` 从 `chat_messages` 回填）。
  - `db.py` — SQLite 账号库（users 表 CRUD、首次启动自动建初始管理员）+ Spec17 的 `conversations` / `chat_messages` / `post_comments` 与 `app_meta` 键值。
  - `chat_history.py` — 对话历史业务层（Spec17）：归属校验（越权与不存在同码 40407）、消息行 ↔ 路由上下文条目转换、助手结果落库。
  - `auth.py` — bcrypt 哈希 + JWT 签发/校验 + 登录限速。
  - `task_queue.py` — `asyncio.Queue` + single worker + in-memory task registry. Statuses `PENDING → PROCESSING → COMPLETED/FAILED`. `task_id` 自 `app_meta.task_id_seq` **续号**（重启不回到 1，否则与 `feedback` 的 `UNIQUE(task_id)` 撞车）。
  - `agents/` — `supervisor.py` (LangGraph `START → router → (tools?) → END`, tool return value **is** the final response, never re-summarized) + child agents `generation.py` (text→image), `editing.py` (sketch+text→image), `qa.py` (image+question→text), plus `prompts.py`.
  - `providers/` — `deepseek.py` (OpenAI-compatible text routing + vision QA), `tokenhub.py` (unified image gen via `POST /v1/wand/hunyuan-image/v3-generation`, Bearer auth; text→image and sketch→image share one endpoint). All calls are sync (SDK/httpx) wrapped in `asyncio.to_thread` (see `run_sync`/`with_retry`).
  - `media.py` — image storage in `Server/storage/` (served at `/images`, TTL 1h, cleared on startup), fetch/downscale/sketch-input enforcement (≤2000px, base64 ≤6MB).
  - `schemas.py`, `errors.py` (error-code classes per Spec §9), `logging_setup.py` (single-line JSON logs per Spec §10).
- **API contract** — every response is `{ "code": 200, "message": "ok", "data": ... }`. `POST /api/chat` returns immediately `{task_id, thread_id}`; results/failures arrive via polling `data.error` / `data.result`. Requests may carry `X-Request-Id`, propagated into logs.

## Configuration

- **`Server/config.py`** is the single source of env config, read from **`Server/.env`** via python-dotenv (`.env.example` has placeholders). Real keys never go in the repo.
  - DeepSeek: `DEEPSEEK_API_KEY`, `OPENAI_BASE_URL` (default `https://api.deepseek.com`), `MODEL_NAME` (`deepseek-v4-flash`), `VLM_MODEL` (`deepseek-v4-flash-vision-exp`).
  - TokenHub: `TOKENHUB_API_KEY` (Bearer), `TOKENHUB_API_URL` (default `https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v3-generation`), `HUNYUAN_IMAGE_MODEL` (`hy-image-v3`), `HUNYUAN_IMAGE_SIZE` (default `1024x1024`). The old Tencent Cloud TC3 path (`TENCENTCLOUD_SECRET_ID/KEY`) is deprecated/deleted.
  - Service: `CORS_ALLOW_ORIGINS`, `MAIN_SERVER_HOST` (0.0.0.0), `MAIN_SERVER_PORT` (8000), `PUBLIC_BASE_URL` (optional), `MAX_PENDING_TASKS` (100), `TASK_TIMEOUT_SECONDS` (300).
  - 认证（Spec2）: `JWT_SECRET`（必填，只放 .env）、`JWT_EXPIRE_SECONDS`（默认 604800）、`ADMIN_USERNAME`/`ADMIN_PASSWORD`（仅 users 表为空时用于首次建初始管理员）。账号库路径 `AUTH_DB_PATH = Server/artcn.db`。
  - 对话 / 评论（Spec17）: `COMMENT_TEXT_MAX`（默认 200，**前端 `CommunityPanel.vue` 的 `COMMENT_MAX` 是同值副本，改要一起改**）、`CONVERSATION_LIST_LIMIT`（默认 50）。
- **Frontend** — dev proxies `/api` and `/images` → `localhost:8000` (`frontend/vite.config.js`). GitHub Pages: set `VITE_BASE` for sub-path, `VITE_API_BASE` for a remote backend.

## Important notes / gotchas

- **Single-hop routing**: once the Supervisor selects a tool, the tool's result is returned to the user as-is. The Supervisor does not call the LLM a second time to summarize. Don't "fix" this to add a second LLM pass.
- **No multi-tool chaining in v1**: composite tasks ("first analyze, then generate") are out of scope; they go through multi-turn chat.
- **Model weights are gone**: v1's ControlNet/LDM stack (`backend/`, `cldm/`, `ldm/`, `annotator/`, `Server` inference files) was deleted per Spec §11. Recoverable from git history only.
- **`API's Usage/`** is the raw vendor API handbook (contains real keys). It is gitignored and must never be committed. `specs/Spec.md` §7.5 also holds real keys — do not push them; if `specs/Spec.md` is committed, strip §7.5 first.
- **storage/** is transient: cleared at startup, TTL 1h. Don't treat generated/uploaded images as durable.
- **`Server/artcn.db` is persistent**: 后端重启不清库，已在 .gitignore。初始管理员由 `.env` 的 `ADMIN_USERNAME/ADMIN_PASSWORD` 在首次启动时创建（表空时）。除 `POST /api/auth/login` 外所有 `/api` 接口都要带 `Authorization: Bearer <JWT>`，无 token → 40103；普通用户访问 `/api/admin/*` → 40301。
- **聊天图片按 `images.id` 引用作品库**（Spec17 §5.2A）：`chat_messages.image_id` 指向 `images` 表，渲染走 `GET /api/gallery/{id}/file`，**不复制字节**。因此用户在「我的作品」里删图后，历史消息里的引用会悬挂——前端渲染「图片已删除」占位（`useAuthedImage` 的 `missing`），后端不做补偿；删对话**不删**作品库图片。
- **评论只增 / 删 / 查，没有编辑**（Spec17 §2.3）：`post_comments` 表没有 `updated_at` 列，这是全仓唯一没有 `PUT` 的资源，有意为之——别顺手补一个编辑接口。
- **帖子弹窗的 flex 塌陷陷阱**（Spec17 §14.1）：`.post-comments` 是 `.community-modal-body`（flex 列）的子项且**自身是滚动容器**，`min-height: auto` 会解析成 0，于是它**先于**别的元素被压到 0 高——曾经导致带图帖的评论区整个消失（`comment-form` 不是滚动容器，压不动，所以只有评论区让位）。保命的是那行 `min-height: 110px`，别删；改动弹窗高度分配时（图片 `max-height: 45vh`、固定内容 `flex-shrink: 0`）要一并考虑。
- **`posts.image_file` / `ext` 可空**（Spec17 §5.2D）：纯文字帖是合法形态，读图路径（`community.read_post_image`）在无图时返回 40404；`community.list_posts` 会把内部字段 `image_file` 从响应里 `pop` 掉，只给 `image_url`。
- There are **no automated tests and no linter** in any tier.

## Commands

```bash
# Backend — create venv + install (one-time), then run (:8000)
cd Server
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn main:app --reload --port 8000   # (Git Bash) or uvicorn main:app --reload

# Frontend — dev (:5173, proxies /api,/images → :8000)
cd frontend && npm install && npm run dev

# Production build + backend hosts dist/ (single-port demo at :8000)
cd frontend && npm run build
cd ../Server && .venv/Scripts/python -m uvicorn main:app --port 8000
```

## Deployment

- **Frontend (GitHub Pages)**: `npm run build` → push `dist/`; set Vite `base` (`VITE_BASE`) for sub-paths and `VITE_API_BASE` for the backend origin.
- **Backend (public server)**: FastAPI + Uvicorn anywhere reachable; all keys via env vars; stateless. Or serve `frontend/dist` directly from the backend (one port).
