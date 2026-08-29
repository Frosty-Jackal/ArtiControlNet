# ArtiControlNet Spec 2：登录认证 + 用户管理

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：给现有对话工作台加一层**账号登录**——所有业务接口必须登录后才能访问；账号**仅由管理员在管理端创建**；管理员可在前端「用户管理」界面增删改查账号。
> 本 Spec 是 **Spec.md 的增量补充**，不推翻原有架构，只在现有「前后端两层」里加：SQLite 单文件数据库 + bcrypt 密码哈希 + JWT 登录态 + 管理端。
> 硬约束仍遵守 Spec.md：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量。唯一的例外是：本 Spec 引入一个**本地单文件 SQLite** 作为账号库（见 §2 决策记录）。

---

## 1. 功能目的

- **登录保护**：部署方式是内网穿透 = 服务公网可达。聊天 / 生图 / 问答等业务接口不再裸奔，必须登录后访问。
- **账号体系**：用户名 + 密码。账号**只由管理员创建**（不做公开注册），避免路人随意注册。
- **管理端（管理员专属）**：在前端聊天页内嵌「用户管理」视图，可创建账号 / 重置密码 / 删除账号 / 设置或撤销管理员。
- **轻量存储**：账号库用 Python 标准库 `sqlite3` 存本地单文件 `Server/artcn.db`，满足"数据库放在项目文件夹里"。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 数据库 | **SQLite**（Python 内置 `sqlite3`） | 零新依赖、单文件、事务安全、能扛并发；完全符合"轻量 + 放项目里" |
| 密码存储 | **bcrypt**（加盐哈希） | 抗暴力破解/彩虹表强；见 §2.1 通俗解释 |
| 登录态 | **JWT**（`PyJWT` 库） | 无状态，契合现有无状态后端；token 存前端 localStorage |
| 注册策略 | **仅管理员创建** | 公网暴露下最安全，不做公开注册 |
| 管理端位置 | **嵌在现有 Vue 前端** | 复用紫色主题，体验统一，不新增 vue-router |

> 排除项：纯 JSON 文件存密码（无原子写、并发会坏数据）；TinyDB（并发/原子性弱）；MySQL/Postgres（要装数据库服务，违背"轻量"）。

### 2.1 什么是 bcrypt（通俗版，给 FJ 看的）

> **bcrypt** 是一种"密码加盐哈希"算法，作用是把明文密码变成一段看不懂的固定长度密文（叫"哈希"），存进数据库。
>
> 它有两个关键特性：
> 1. **加盐**：每次哈希都掺入一段随机"盐"，所以同一个密码，两次存出来是完全不同的两串。攻击者拿到数据库也查不出"谁的密码和谁一样"，更没法用现成的彩虹表反查。
> 2. **故意算得慢**：bcrypt 有个可调"成本因子"，让哈希计算刻意耗时（几十到几百毫秒）。单次登录无所谓，但对攻击者来说，穷举/暴力破解每个密码的成本被放大了成千上万倍。
>
> 对比一下为什么不能用别的：
> - **存明文**：数据库文件一旦泄露（git 误提交、被拖库），所有密码全暴露。
> - **MD5 / SHA 这类快哈希**：算得太快，攻击者一秒能试几百万个，极易破解。
>
> 所以 bcrypt 是主流登录系统的标准选择。代码上就两句话：注册/建号时 `bcrypt.hashpw(密码)` 生成哈希入库；登录时 `bcrypt.checkpw(密码, 库里的哈希)` 校验，返回对/错。
> 代价：后端 `requirements.txt` 多一个依赖 `bcrypt`。

---

## 3. 需求边界

### 范围内
- 用户名 + 密码登录，签发 JWT 登录态；登出 = 前端清掉本地 token。
- 管理员在管理端创建 / 重置密码 / 删除账号 / 设置或撤销管理员（管理端 CRUD）。
- 所有业务 `/api` 接口（chat / images / tasks / threads）统一鉴权，未登录返回 401。
- 登录失败限速，防暴力破解。
- SQLite 数据库文件放 `Server/`，加入 `.gitignore`，绝不入库。

### 范围外（本 Spec 不做）
- 公开注册 / 第三方登录（微信、OAuth）/ 找回密码 / 邮箱验证 / 多因素认证。
- 服务端会话撤销 / 强制下线（JWT 无状态；重置密码后旧 token 因签名不变仍有效，接受此边界）。
- 用户级数据隔离 / 多租户（所有登录用户共享同一个工作台）。
- 复杂密码策略（仅基础校验：用户名 ≥2 字符、密码 ≥6 位）。
- 不修改 Spec.md 中已有的任何功能与接口。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | `sqlite3`（Python 标准库） | 本地单文件数据库，**无需安装** |
| | `bcrypt`（pip 依赖） | 密码哈希 |
| | `PyJWT`（pip 依赖） | JWT 签发 / 校验 |
| 前端 | 无新框架 | 复用 Vue3 + Pinia；新增登录页 + 管理视图组件 |

> `requirements.txt` 追加两行：`bcrypt>=4.0`、`PyJWT>=2.8`。`sqlite3` 随 Python 自带，不写进依赖。

---

## 5. 架构设计（增量）

### 5.1 分层

```
Vue 3 SPA（登录页 + 聊天页 + 管理视图）
   │ 请求头带 Authorization: Bearer <JWT>
FastAPI（中间件统一校验 token；/api/auth/login 放行）
   │ 读写
SQLite 单文件 Server/artcn.db（users 表）
```

### 5.2 关键数据流

- **登录**：`POST /api/auth/login`（用户名 + 密码）→ 后端 `bcrypt.checkpw` 校验 → 签发 JWT → 前端存 localStorage。
- **建号**：管理员在管理端填用户名 + 初始密码 → `POST /api/admin/users` → 后端 `bcrypt.hashpw` 入库。
- **业务请求**：前端拦截器自动带 `Authorization: Bearer <token>` → 后端中间件验签 → 通过才放行。
- **权限判定（实时）**：JWT 只携带用户身份（`user_id` / `username`），**不把 `is_admin` 写死进 token**；每次请求由中间件实时查库取该用户最新的 `is_admin`。因此撤销某人的管理员权限**立即生效**，无需等旧 token 过期。
- **首次启动**：数据库不存在时自动建表；若 `users` 表为空，自动创建**初始管理员**（用户名/密码从 `.env` 读，如 `ADMIN_USERNAME` / `ADMIN_PASSWORD`），避免"建号需要管理员但还没有管理员"的死锁。
- **数据库文件生命周期**：`artcn.db` 是持久化的，**与 storage/ 无关**——后端重启不清库，账号不丢。

### 5.3 数据表（users）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER 自增主键 | 用户 ID |
| username | TEXT 唯一（NOT NULL） | 登录名，≥2 字符 |
| password_hash | TEXT（NOT NULL） | bcrypt 哈希，**绝不存明文** |
| is_admin | INTEGER（0/1） | 是否管理员 |
| created_at | TEXT | 创建时间（ISO8601） |

---

## 6. 接口约定

### 6.1 新增端点

| 方法 & 路径 | 鉴权 | 请求 | 成功响应 `data` | 说明 |
|---|---|---|---|---|
| `POST /api/auth/login` | 公开 | `{username, password}` | `{token, username, is_admin}` | 登录，签发 JWT |
| `GET /api/auth/me` | 登录 | 无 | `{username, is_admin}` | 当前登录用户信息（前端启动时校验 token） |
| `POST /api/admin/users` | 管理员 | `{username, password}` | `{id, username, is_admin}` | 创建账号 |
| `GET /api/admin/users` | 管理员 | 无 | `[{id, username, is_admin, created_at}]` | 用户列表 |
| `PUT /api/admin/users/{id}/password` | 管理员 | `{password}` | `{id}` | 重置某用户密码 |
| `PUT /api/admin/users/{id}/admin` | 管理员 | `{is_admin}` | `{id}` | 设置 / 撤销某用户管理员 |
| `DELETE /api/admin/users/{id}` | 管理员 | 无 | `{id}` | 删除账号（**不能删自己**，不能删最后一个管理员） |

### 6.2 鉴权约定

- 除 `POST /api/auth/login` 外，**所有 `/api` 接口**需带 `Authorization: Bearer <token>`。
- 未带 / 无效 / 过期 token → `401`（错误码 `40103`）。
- **权限按角色判定**：`is_admin` 实时查库（见 §5.2），非管理员访问 `/api/admin/*` → `403`（错误码 `40301`）。
- 业务接口保持现有 `{code, message, data}` 包装，仅新增 §9 认证相关错误码，不改已有接口形态。

**权限对照表（普通用户 vs 管理员）**

| 操作 | 普通用户 | 管理员 |
|---|---|---|
| 登录 / 查看自己信息（`/api/auth/*`） | ✅ | ✅ |
| 聊天 · 生图 · 问答（`/api/chat` `/api/images` `/api/tasks/*` `/api/threads/*`） | ✅ | ✅ |
| 用户列表 / 创建 / 重置密码 / 删除 / 设撤管理员（`/api/admin/users*`） | ❌ 403 | ✅ |
| 前端「用户管理」入口 | 不显示 | 显示 |

> 普通用户即使绕过前端直接调 `/api/admin/*`，后端同样返回 `403`——管理能力**双重把关**（前端藏入口 + 后端验角色）。

### 6.3 前端交互

- 启动时若无 token，或 `GET /api/auth/me` 校验失败 → 显示**登录页**。
- 登录成功 → 进入聊天页；axios 请求拦截器自动附带 token。
- 任意请求返回 `401` → 清 token 回登录页。
- 管理员登录后，聊天页头部出现「用户管理」入口 → 打开**管理视图**（用户表格 + 创建表单 + 每行的重置/设管理员/删除操作）。
- 登录页 / 聊天页 / 管理视图均通过 `App.vue` 条件渲染切换（项目无 vue-router，不引入）。

---

## 7. 环境变量（追加到 `Server/.env` 与 `config.py`）

| 变量 | 用途 | 说明 |
|---|---|---|
| `JWT_SECRET` | JWT 签名密钥 | 随机长串，只放 `.env`，绝不入库 / 不进代码 |
| `JWT_EXPIRE_SECONDS` | token 有效期 | 默认 `604800`（7 天） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首次启动自动创建的初始管理员 | 仅当 users 表为空时使用；建号后即可改 |

> ① **没有默认管理员密码**：若这两项未配置且 `users` 表为空，后端启动时明确报错，提示先去 `.env` 配置，绝不自动生成弱口令。
> ② `config.py` 读取后拼出 `AUTH_DB_PATH = Server/artcn.db`（数据库路径常量）。

---

## 8. `.gitignore` 追加

```gitignore
# 本地认证数据库（含 WAL/SHM 伴生文件）
Server/artcn.db
Server/artcn.db-wal
Server/artcn.db-shm
```

---

## 9. 错误码新增（追加到 Spec.md §9）

> 与 Spec.md 已有错误码错开（已有：40001~40004 / 40101 / 40401 / 50001 / 50201 / 50202 / 50301 / 61001~61004 / 61999）。

| HTTP | code | 含义 | 触发示例 |
|---|---|---|---|
| 400 | 40010 | 用户名或密码格式非法 | 用户名 <2 字符 / 密码 <6 位 |
| 401 | 40102 | 用户名或密码错误 | 登录校验失败 |
| 401 | 40103 | 登录态无效 / 过期 | token 缺失、伪造或过期 |
| 403 | 40301 | 无权限（非管理员） | 普通用户访问 `/api/admin/*` |
| 404 | 40402 | 用户不存在 | 管理端操作不存在的用户 ID |
| 409 | 40901 | 用户名已存在 | 重复创建同名账号 |
| 429 | 42901 | 登录过于频繁 | 同 IP 短时登录失败超限（限速） |

---

## 10. 日志约定

- 沿用 Spec.md §10 单行 JSON 格式；新增认证事件：
  - `auth.login_success` / `auth.login_failed`（登录成功 / 失败，失败附用户名与 request_id）
  - `auth.admin.create_user` / `auth.admin.reset_password` / `auth.admin.delete_user` / `auth.admin.toggle_admin`（管理操作）
- **禁止把密码写入任何日志、响应体或前端。**

---

## 11. 目录结构增量

```
Server/
  db.py                 # SQLite 封装：建表 / 用户 CRUD / 初始管理员
  auth.py               # bcrypt 哈希 + JWT 签发/校验 + FastAPI 依赖注入
  main.py               # 追加 auth/admin 路由 + 统一鉴权中间件
  requirements.txt      # 追加 bcrypt、PyJWT
  artcn.db              # 运行时生成（gitignore）
frontend/src/
  store/auth.js         # Pinia：token / username / is_admin / login() / logout() / me()
  api/chatApi.js        # 拦截器自动带 token；新增 auth / admin 接口函数
  views/Login.vue       # 登录页（用户名 + 密码表单）
  views/AdminPanel.vue  # 用户管理视图（表格 + 创建表单 + 行操作）
  App.vue               # 按登录态分支渲染：登录页 or 聊天页（含管理入口）
```

---

## 12. 实施顺序（里程碑）

1. **A1 依赖与配置**：`requirements.txt` 追加 bcrypt / PyJWT；`config.py` + `.env` 追加 JWT_SECRET 等；`.gitignore` 追加 db 条目。
2. **A2 数据库层**：`db.py` —— 建表、用户 CRUD、首次启动自动建初始管理员。
3. **A3 认证层**：`auth.py` —— bcrypt 哈希、JWT 签发/校验、登录与 `/api/auth/me` 接口。
4. **A4 鉴权中间件**：业务接口统一校验 token，401/403 错误码接入现有异常体系。
5. **A5 管理接口**：`/api/admin/users` CRUD + 权限检查 + 自删/删最后一个管理员保护。
6. **A6 前端登录**：`auth.js` store、`Login.vue`、axios 拦截器带 token、401 回登录页。
7. **A7 前端管理端**：`AdminPanel.vue`（列表 + 创建 / 重置 / 删除 / 设管理员）。
8. **A8 验收**：见 §13 端到端用例。

---

## 13. 验收用例（端到端 Smoke）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 未带 token 调 `POST /api/chat` | `401`，`code=40103` |
| 2 | 用初始管理员登录（`.env` 里的 ADMIN_USERNAME/PASSWORD） | 成功，返回 token，`is_admin=true` |
| 3 | 带 token 发一条纯文本消息 | 正常走完 `PENDING → PROCESSING → COMPLETED` |
| 4 | 管理员创建普通账号 | 成功，`is_admin=false` |
| 5 | 用普通账号登录 | 成功，`is_admin=false` |
| 6 | 普通账号访问 `GET /api/admin/users` | `403`，`code=40301` |
| 7 | 管理员重置普通账号密码 | 旧密码无法登录，新密码可登录 |
| 8 | 管理员删除普通账号 | 该账号再登录失败（`40102`） |
| 9 | 错误密码连续多次尝试 | 触发限速，返回 `429`，`code=42901` |
| 10 | 重启后端 | `artcn.db` 仍在，账号不丢（storage/ 仍照常清空，两者无关） |
| 11 | 打开 `artcn.db` 查看 | 只见 username 与 password_hash，无明文密码 |

> 未列入的能力（公开注册、找回密码、第三方登录、强制下线等）v2 一律不做，验收时明确排除。
