# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ArtiControlNet is a **multi-agent AIGC chat workbench** for designers ("基于进化算法的条件扩散模型高效架构探究", a university innovation project). Users describe what they want in natural language (optionally attaching a reference image); a Supervisor agent does a single intent-routing pass, and child agents complete "text-to-image / sketch-to-image / image QA" via **external cloud model APIs**, returning results **directly to the user**.

**Hard constraints**: no local inference, **no database**, only two tiers (frontend + backend). All API keys live in backend env vars only — never in the frontend or committed files.

Design source of truth: **`Spec.md`** (do what it says; this file is a quick orientation).

## Architecture (two tiers)

```
Vue 3 SPA (frontend/)            FastAPI orchestrator (Server/)         External APIs
──────────────                   ────────────────────────                ─────────────
Chat UI, upload, polling,    →   /api/chat  /api/images                 DeepSeek (routing +
localStorage history              /api/tasks/{id} /api/threads/...          vision QA)
                                  async TaskQueue (asyncio, in-memory)   TokenHub (hy-image-v3,
                                  Supervisor (LangGraph, single-hop)       text→img + sketch→img)
```

- **Frontend** — Vue 3 + Vite + Pinia + Axios, **no vue-router**. Chat-style SPA; uploads first via `/api/images`, then `POST /api/chat` → polls `GET /api/tasks/{id}` every ~1.5s. History persisted to `localStorage` (`artcn_chat_v2`). Purple theme in `frontend/src/assets/styles/main.css` (`:root` vars — preserve).
- **Backend** (`Server/`) — FastAPI, stateless, no DB:
  - `main.py` — routes, lifespan (storage cleanup, worker start), error handlers, static hosting.
  - `task_queue.py` — `asyncio.Queue` + single worker + in-memory task registry. Statuses `PENDING → PROCESSING → COMPLETED/FAILED`.
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
- **Frontend** — dev proxies `/api` and `/images` → `localhost:8000` (`frontend/vite.config.js`). GitHub Pages: set `VITE_BASE` for sub-path, `VITE_API_BASE` for a remote backend.

## Important notes / gotchas

- **Single-hop routing**: once the Supervisor selects a tool, the tool's result is returned to the user as-is. The Supervisor does not call the LLM a second time to summarize. Don't "fix" this to add a second LLM pass.
- **No multi-tool chaining in v1**: composite tasks ("first analyze, then generate") are out of scope; they go through multi-turn chat.
- **Model weights are gone**: v1's ControlNet/LDM stack (`backend/`, `cldm/`, `ldm/`, `annotator/`, `Server` inference files) was deleted per Spec §11. Recoverable from git history only.
- **`API's Usage/`** is the raw vendor API handbook (contains real keys). It is gitignored and must never be committed. `Spec.md` §7.5 also holds real keys — do not push them; if `Spec.md` is committed, strip §7.5 first.
- **storage/** is transient: cleared at startup, TTL 1h. Don't treat generated/uploaded images as durable.
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
