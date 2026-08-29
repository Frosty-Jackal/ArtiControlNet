# ArtiControlNet Spec 3：会话历史按用户隔离

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：修复"不同登录用户共享同一份会话历史"的 bug——把前端 `localStorage` 里**全局一份**的会话历史（键 `artcn_chat_v2`）改成**每个用户名一份**，并在登录 / 登出 / token 失效时正确切换，让每个用户只能看到自己的历史。
> 本 Spec 是 **Spec.md / Spec2.md 的增量补充**，不推翻原有架构。**纯前端改动，后端接口零改动**；不影响登录认证、管理员、生图 / 问答等既有能力。

---

## 1. 功能目的

- **按用户隔离历史**：会话历史与登录用户绑定。用户 A 登录后看到自己的历史，用户 B 在同一浏览器登录后看到的是**空会话**（不再继承 A 的）。
- **登出不互扰**：登出 / 切换账号时，不同用户之间的历史互不可见、互不覆盖。
- **保留个人历史**：同一用户再次登录仍能恢复自己的历史（见 §3 已知限制：持久化在浏览器 localStorage，非服务器）。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 历史归属 | 前端 `localStorage`，按键按用户隔离 | 历史本就由前端负责持久化（Spec.md），最小改动；不引入后端状态 |
| 登出行为 | **按用户保留** | 同一用户再登录可恢复自己的历史；不同用户按键隔离，互不可见 |
| 旧数据 | **忽略**旧的单一键 `artcn_chat_v2` | 旧数据是多人共享的混杂数据（本次 bug 的产物），来源不明，直接废弃 |
| 后端线程 | **不做**归属校验（本次范围外） | 线程是内存态、重启即失（§3）；正常 UI 路径下用户拿不到他人 `thread_id` |

> 排除项：把会话历史搬进 SQLite（`artcn.db`）——那会让历史变成"服务器可靠持久化"，违背现有"前端管历史、后端无状态"的分层，且超出本 bug 范围（见 §3 范围外 / 已知限制）。

---

## 3. 需求边界

### 范围内
- 前端 `localStorage` 历史键按用户名隔离：`artcn_chat_v2:<username>`（username 在 users 表唯一，直接用作区分符，后端零改动）。
- 登录成功 → 加载**该用户**的历史；登出 / token 失效回登录页 → 清空会话（`threadId` / `messages` / `sending`），**不读任何历史**。
- 未登录状态下不读写任何历史键。
- 旧的单一键 `artcn_chat_v2` 不再读写（忽略）。
- 聊天页「清空」按钮语义不变：只清**当前用户**自己的历史。

### 范围外（本 Spec 不做）
- 服务端持久化会话历史 / 跨设备同步（历史仍只存浏览器）。
- 后端线程（`ThreadStore`，`Server/main.py`）按用户隔离或归属校验。
- 多会话列表管理（同时保存多个会话、切换历史会话）。
- 历史中图片文件的持久化（`Server/storage/` TTL 1h 是 Spec.md 既有行为，本 Spec 不改）。
- 不修改 Spec.md / Spec2.md 中已有的任何功能与接口。

### 已知限制（写入本文档，避免误读）
- 历史持久化于**浏览器 `localStorage`**（按用户，无过期时间）；一旦清除浏览器站点数据、或换设备/浏览器登录，历史即不可见。
- **后端重启后 AI 续聊上下文丢失**：服务端线程（内存 `ThreadStore`）只保留每线程最近 20 条、且进程重启即清空；气泡仍在，但继续旧线程时 AI 会从空白上下文续接。
- **历史中的旧图会过期裂图**：生成/上传图片存于 `storage/`，TTL 1 小时、启动清空；气泡里的图片 URL 尚在但文件可能已删除。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 前端 | 无新依赖 / 无新框架 | 仅修改现有 Pinia store 与 App 挂载逻辑 |

> 后端 `requirements.txt`、`Server/*`、`.env`、`artcn.db` 均不涉及。

---

## 5. 实现方案

### 5.1 历史键按用户隔离（`frontend/src/store/chat.js`）

- 将固定常量 `STORAGE_KEY = 'artcn_chat_v2'`（现 `chat.js:4`）改为**按用户名生成键**：
  ```
  chatKey(username) => `artcn_chat_v2:${username}`
  ```
- `loadHistory()` 需要**当前用户名**参数：无用户名，或键不存在 / JSON 损坏 → 返回 `{ threadId: null, messages: [] }`（损坏数据忽略，沿用现有 try/catch）。
- `persist()` 按**当前用户名**取键写入；未登录（无用户名）→ 跳过，不落盘。
- chat store 状态里**新增 `username` 字段**，由下面的 `resetForUser` 维护——chat store 保持与 auth store 解耦（不直接 import auth），便于复用与测试。

### 5.2 用户切换时重载（`frontend/src/store/chat.js` + `frontend/src/App.vue`）

新增 action：

```
resetForUser(username):
  this.username   = username
  this.threadId   = null
  this.messages   = []
  this.sending    = false
  if (username) 从 chatKey(username) 加载历史到 this
  （无用户名 → 保持空会话，不读任何历史键）
```

触发点（在 App.vue 的登录态流转处调用）：

| 时机 | 调用 |
|---|---|
| 启动时 token 校验通过 | `chat.resetForUser(auth.username)` |
| 登录成功 | `chat.resetForUser(auth.username)` |
| 登出 / token 失效回登录页 | `chat.resetForUser(null)` |

> 注意：当前 `App.vue:64-65` 在启动时无条件 `store.init()` 读旧键——升级后 `init()` 改为 `resetForUser(auth.username)`，且必须在 auth 校验完成（`auth.loaded === true`）后再执行，避免拿到空用户名。

---

## 6. 文件改动清单

| 文件 | 改动 |
|---|---|
| `frontend/src/store/chat.js` | 键改为按用户名生成；`loadHistory` / `persist` 感知当前用户；新增 `username` 状态与 `resetForUser(username)` |
| `frontend/src/App.vue` | 登录成功 / 登出 / token 失效 / 启动校验通过时触发 `resetForUser` |

> 无后端改动、无新文件、无 .env / .gitignore / 依赖变更。

---

## 7. 实施顺序（里程碑）

1. **A1 改造 chat store**：键函数 + `username` 状态 + 感知用户的 `loadHistory` / `persist` + `resetForUser`。
2. **A2 接入切换触发点**：App.vue 在启动校验、登录、登出、失效四处调用 `resetForUser`。
3. **A3 验收**：按 §8 用例端到端 Smoke。

---

## 8. 验收用例（端到端 Smoke）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 用户 A 登录 → 发一条消息 → 登出 | 正常发消息并完成任务 |
| 2 | 用户 B 登录 | **空会话**，看不到 A 的任何历史 |
| 3 | B 发一条消息 → 登出；A 再登录 | A 看到**自己的**历史（含第 1 步的消息），无 B 的消息 |
| 4 | 浏览器刷新 | 只显示当前登录用户自己的历史 |
| 5 | 聊天页点「清空」 | 仅当前用户历史消失；其他用户键不受影响（另一账号登录后仍见其历史） |
| 6 | 升级前旧键 `artcn_chat_v2` 存在 | 升级后**任何用户**都读不到它（被忽略） |
| 7 | token 失效回登录页（未登录态） | 不加载任何历史；重新登录后从**该用户自己**的历史开始 |

> 验收时明确排除的能力（服务端持久化、跨设备同步、后端线程归属校验、多会话管理）v3 一律不做。
