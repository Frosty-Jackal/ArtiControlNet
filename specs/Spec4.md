# ArtiControlNet Spec 4：用户使用统计（4 类调用计数）

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：给管理端加一个「数据统计」面板——按 **对话 / 文生图 / 图文生图 / 图像QA** 四类展示调用**总数、占比、人均次数**；用户每次**成功调用**自动计入持久数据库 `artcn.db`。
> 本 Spec 是 **Spec.md / Spec2.md 的增量补充**，不推翻原有架构。**不新增依赖**（沿用 Spec2 的 SQLite 账号库模式），只复用既有 `users` 库扩展一张 `usage` 表 + 一个管理员只读统计接口 + 前端一个统计面板。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 Spec2 的 `artcn.db` 外无其他数据库。

---

## 1. 功能目的

- **让管理员看得见产品在怎么被用**：内网穿透公网部署后，管理员能查看用户调用情况，了解 4 类能力（对话 / 文生图 / 图文生图 / 图像QA）的使用热度。
- **只做聚合统计，不做用户级监控**：面板只展示全站聚合数字（总数、占比、人均），**不展示任何用户名、对话内容或图片**。
- **自动采集**：普通用户正常使用聊天页即可，后端在任务成功完成后自动计数，用户无感、无需任何操作。
- **管理端入口**：聊天页头部新增「数据统计」按钮（仅管理员可见），进入独立面板——形态与「用户管理」一致（见 §7）。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 统计口径 | **成功完成的任务**（COMPLETED）才计数 | 失败 / 超时 / 排队被拒不计；口径清晰、实现最简（只在成功路径记一次） |
| 存储 | 与账号同库 `artcn.db`，新增 `usage` 表 | 已持久化、已 gitignore、管理员可访问，与 Spec2 先例完全一致 |
| 表设计 | **计数表**（每用户一行、4 个计数列） | 本次只需 4 类总数 / 占比 / 人均，无时间维度需求；写路径是最省的单条 UPSERT |
| 分类来源 | Supervisor 结果上**打 `tool` 标签** | 见 §2.1：任务的 `kind` 恒为 `"chat"`，真正类别只能由路由决策导出 |
| 人均分母 | **注册用户总数**（含 0 次调用用户） | 「人均」的自然含义；无需区分活跃与否 |
| 管理员是否计入 | **计入** | 管理员也是用户；若想排除，只需在记录处加 `is_admin` 判断（一处改动） |

> 排除项：事件明细表（一行一次调用，可做时间序列 / 活跃 / 留存，但超出本次「只探究统计」的范围）；成功率 / 失败率、活跃用户数、注册总数展示、时段分布——用户明确不需要。

### 2.1 为什么必须给结果打 `tool` 标签

后端所有任务都由 `POST /api/chat` 提交，`kind` 恒为 `"chat"`（`main.py`），真正的类别由 Supervisor 在运行时路由决定。而且子 Agent 的返回值类别有歧义：

| 场景 | 子 Agent 返回 |
|---|---|
| 纯文本对话 | `{"kind": "text"}` |
| 文生图 `generate_image` | `{"kind": "images"}` |
| 图文生图 `edit_image` | `{"kind": "images"}` |
| 图像 QA `qa_image` | `{"kind": "text"}` |

**仅看 `kind` 无法区分「对话 vs 图像QA」（都是 text）、「文生图 vs 图文生图」（都是 images）**。所以 Supervisor 的 `tool_node` 必须在执行完子 Agent 后把选中工具名写进结果：`result["tool"] = name`，统计据此归类。这是本 Spec 最关键的正确性细节。

---

## 3. 需求边界

### 范围内
- 每用户 4 类计数：对话 / 文生图 / 图文生图 / 图像QA（代码内 `chat / generate / edit / qa`）。
- 任务**成功完成**后自动 +1；失败 / 超时 / 排队被拒（50301）**不计入**。
- 管理端只读统计：4 类总数、占比（%）、人均次数，以及注册用户总数、调用总次数。
- 前端「数据统计」面板，形态与「用户管理」一致；入口按钮仅管理员可见。
- 删除用户时同步删除其计数行（保证总数 / 人均分母一致）。

### 范围外（本 Spec 不做）
- 成功率 / 失败率、活跃用户数、注册总数展示、时段 / 日期分布、留存。
- 用户级明细（哪个用户调了多少次、调了什么）、对话内容 / 图片的落库。
- 统计历史留存 / 时间序列 / 图表。
- 修改 / 重置计数（只增不减，无管理端清零）。
- 不修改 Spec.md / Spec2.md / Spec3.md 中已有的任何功能与接口。

### 统计口径（写入本文档，避免误读）
- 「对话次数」= 未路由到任何工具、直接文本回复的**成功**任务；路由到生图 / QA 的消息按对应类别计，不计入对话。
- 「文生图 / 图文生图 / 图像QA」= 对应工具**成功**执行的任务。
- 「人均次数」= 各类总数 ÷ 注册用户总数（含从未调用的用户）。
- 「占比」= 各类总数 ÷ 4 类总次数（百分比，保留 1 位小数）。
- 管理员调用也计入（见 §2 决策记录）。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | 无新依赖 | 复用 `sqlite3`（Spec2 已有）；仅 `db.py` 加表与函数 |
| 前端 | 无新依赖 / 无新框架 | 新增一个 `StatsPanel.vue`，复用现有紫色主题样式 |

---

## 5. 架构设计（增量）

### 5.1 分层

```
Vue 3 SPA（聊天页 + 用户管理 + 数据统计）
   │ Authorization: Bearer <JWT>
FastAPI
   │ 任务成功完成后 record_call(user_id, category)
SQLite Server/artcn.db（users 表 + usage 表）
```

### 5.2 关键数据流

1. **采集**：`POST /api/chat` 提交任务时，把当前登录用户的 `id` 写入任务 request（`request["user_id"]`）——目前没有，这是本 Spec 的主要缺口。
2. **归类**：Supervisor `tool_node` 执行完子 Agent 后写 `result["tool"] = name`（§2.1）。
3. **计数**：worker 在 `main.py` 的 `handle_task` 中，`run_supervisor` **成功返回**后调用 `db.record_call(request["user_id"], category(result))`。失败路径不调用。
4. **读取**：管理员打开「数据统计」→ `GET /api/admin/stats` → 后端聚合 `usage` 表 + `users` 表人数 → 返回 4 类总数 / 人均 / 占比。
5. **删除一致性**：`delete_user` 时连带删除该用户 `usage` 行。

### 5.3 分类映射

| `result["tool"]` | 类别（DB 列 / 前端文案） |
|---|---|
| 无（纯文本回复） | `chat` · 对话 |
| `generate_image` | `generate` · 文生图 |
| `edit_image` | `edit` · 图文生图 |
| `qa_image` | `qa` · 图像QA |

### 5.4 数据表（usage）

| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | INTEGER 主键 | 对应用户 id；删用户时级联删除 |
| chat | INTEGER NOT NULL DEFAULT 0 | 对话成功次数 |
| generate | INTEGER NOT NULL DEFAULT 0 | 文生图成功次数 |
| edit | INTEGER NOT NULL DEFAULT 0 | 图文生图成功次数 |
| qa | INTEGER NOT NULL DEFAULT 0 | 图像QA成功次数 |
| updated_at | TEXT | 最近一次更新（ISO8601） |

计数用 UPSERT：`INSERT … ON CONFLICT(user_id) DO UPDATE SET <列> = <列> + 1`（列名取自固定白名单，不拼接外部输入）。

---

## 6. 接口约定

### 6.1 新增端点

| 方法 & 路径 | 鉴权 | 请求 | 成功响应 `data` | 说明 |
|---|---|---|---|---|
| `GET /api/admin/stats` | 管理员 | 无 | `{user_count, total_calls, totals, per_user_avg, shares}` | 4 类调用聚合统计（只读） |

响应示例：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "user_count": 12,
    "total_calls": 345,
    "totals":        { "chat": 200, "generate": 80, "edit": 40, "qa": 25 },
    "per_user_avg":  { "chat": 16.7, "generate": 6.7, "edit": 3.3, "qa": 2.1 },
    "shares":        { "chat": 58.0, "generate": 23.2, "edit": 11.6, "qa": 7.2 }
  }
}
```

- `totals[?]` = 各类成功调用总数；`total_calls` = 四者之和。
- `per_user_avg[?]` = `totals[?] / user_count`（保留 1 位小数；`user_count` 为 0 → 全部 0）。
- `shares[?]` = `totals[?] / total_calls * 100`（保留 1 位小数；`total_calls` 为 0 → 全部 0）。
- `user_count` = `users` 表当前注册人数（含 0 次调用者）。

### 6.2 鉴权约定

- 复用 Spec2 §6.2 现有中间件：非管理员访问 → `403`（`40301`）；未登录 → `401`（`40103`）。**零改动、无新错误码。**
- 不新增任何公开接口；前端其他 API 不变。

---

## 7. 前端交互

- 管理员登录后，聊天页头部新增「**数据统计**」按钮（仅 `auth.isAdmin` 显示，与「用户管理」并列）。
- 点击 → 渲染 `StatsPanel.vue`（形态照抄 `AdminPanel.vue`：头部标题 + 「返回聊天」按钮 + 提示行 + 表格）。
- 面板内容：
  - 提示行：`当前登录：<用户名>（管理员）· 数据仅展示聚合统计，不含个人内容`
  - 汇总：`注册用户 N 人 · 调用总次数 M`
  - 表格：表头 `类型 | 总数 | 占比 | 人均次数`，4 行（对话 / 文生图 / 图文生图 / 图像QA）。
- 「数据统计」与「用户管理」两个视图**互斥**：打开一个自动关闭另一个；任一面板内「返回聊天」回到聊天页。
- 复用现有样式类（`.admin-panel / .admin-head / .user-table / .btn-clear / .btn-primary` 等），不新起主题。

---

## 8. 文件改动清单

| 文件 | 改动 |
|---|---|
| `Server/db.py` | 新增 `usage` 建表 + `record_call(user_id, category)` + `get_usage_stats()`；`delete_user` 连带删 usage 行 |
| `Server/agents/supervisor.py` | `tool_node` 执行子 Agent 后写 `result["tool"] = name` |
| `Server/main.py` | `create_chat` 提交时把 `request.state.user["id"]` 写入任务 request；`handle_task` 成功返回后 `record_call`；新增 `GET /api/admin/stats` 路由 |
| `frontend/src/api/chatApi.js` | 新增 `getUsageStats()` |
| `frontend/src/views/StatsPanel.vue` | 新建：统计面板（汇总 + 表格） |
| `frontend/src/App.vue` | 头部加「数据统计」按钮（仅管理员）；`showStats` 状态与渲染，与 `showAdmin` 互斥 |

> 无 `.env` / `.gitignore`（`artcn.db` 已在 Spec2 忽略）变更；无 `requirements.txt` 变更。

---

## 9. 实施顺序（里程碑）

1. **A1 数据库层**：`db.py` —— `usage` 表、`record_call`（UPSERT）、`get_usage_stats`、`delete_user` 级联。
2. **A2 Supervisor 打标**：`tool_node` 结果写 `tool`。
3. **A3 后端采集 + 统计接口**：`main.py` —— 任务带 `user_id`、成功路径 `record_call`、`GET /api/admin/stats`。
4. **A4 前端统计面板**：`chatApi.js` + `StatsPanel.vue` + `App.vue` 入口。
5. **A5 验收**：按 §10 端到端 Smoke。

---

## 10. 验收用例（端到端 Smoke）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 管理员登录，发一条纯文本消息，任务完成 | 「数据统计」→「对话」总数 +1 |
| 2 | 普通用户登录，文生图成功 | 「文生图」+1 |
| 3 | 图文生图成功 | 「图文生图」+1 |
| 4 | 上传图片问一个问题（图像QA）成功 | 「图像QA」+1，**「对话」不加**（QA 虽返回文本，但不能误计入对话） |
| 5 | 制造一个生图失败（如临时清掉 TokenHub key） | 任务 FAILED，**任何计数都不加** |
| 6 | 让队列排满触发 50301 | 不计入 |
| 7 | 未登录调 `GET /api/admin/stats` | `401`（`40103`） |
| 8 | 普通用户调 `GET /api/admin/stats` | `403`（`40301`） |
| 9 | 管理员点「数据统计」 | 面板显示用户数、4 类总数 / 占比 / 人均，数字与实测一致；「返回聊天」正常 |
| 10 | 「数据统计」与「用户管理」互斥 | 打开一个自动关闭另一个 |
| 11 | 删除一个有计数的用户 | 该用户计数行删除，总数 / 人均随之减少 |
| 12 | 重启后端 | `usage` 计数仍在（与账号库同持久化） |
| 13 | 检查面板响应 / 页面 | 只见聚合数字，**无任何用户名、对话文本或图片** |

> 验收时明确排除的能力（成功率、活跃用户、时段分布、用户级明细、计数清零）v4 一律不做。
