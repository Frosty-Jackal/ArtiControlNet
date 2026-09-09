# ArtiControlNet Spec 11：调用统计手动清零 + 「上次清零时间」展示

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：给管理端「数据统计」的**四类调用计数（对话 / 文生图 / 图文生图 / 图像QA）**加**手动清零**（数据库清零），让管理员能以清零为界、逐段统计每一天/每一段日子的使用量；清零**前先 `confirm` 警告一次**防误触，清零后**记录并展示「上次清零时间」**作为当前统计区间的起点。**「AI 服务反馈（有用/没用）」同样记录并展示它自己的「上次清零时间」**（作者拍板：反馈那块也一样）。
> 本 Spec 是 **Spec.md / Spec2~10 的增量补充**，不推翻原有架构。无新依赖、无新环境变量。唯一数据库变化：**`usage` 表支持管理端清零**（原 Spec4 §3 把"重置计数"列为范围外，本 Spec 补上）+ 新增一张**极小 `app_meta` 键值表**记录 `usage_cleared_at` / `feedback_cleared_at` 两个清零时间。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 Spec2 的本地单文件 SQLite `artcn.db` 外无其他数据库。

---

## 1. 功能目的

- **给管理员一个"周期尺子"**：数据统计页目前只有"从上线累计至今"的只增计数（Spec4）。管理员想在**公测一段日子后看这段日子的用量**时无从下手。清零后计数从 0 重新累计，形成"上一段（清零前）→ 下一段（清零后）"的清晰分段。
- **清零可逆性为零，必须防误触**：清零是把 `usage` 表计数归 0，**不可恢复**，所以点清零前必须**弹一次确认框**（与「清空反馈统计」同构：原生 `window.confirm`）。
- **记录「上次清零时间」**：清零不只是把数字抹掉，还要记下这次清零的时刻。管理端统计页明示"这些数字从哪个时间点开始统计"，重启后端、隔几天再看都不糊涂。**作者拍板：下面那块「AI 服务反馈（有用/没用）」的清空同样记录并展示它自己的清零时间。**
- **只动计数，不伤其他**：清零只影响 `usage` 表的 4 个计数列，**users（注册用户数）/ images / posts / feedback 明细之外的任何数据都不动**——「注册用户 X 人」继续按真实在册用户统计，人均分母不受影响。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 清零对象 | `usage` 表 4 个计数列（chat / generate / edit / qa），**一键全清** | 与「清空反馈统计」一键清空三类的形态一致；作者列的是"四类调用总数一起支持清零"，无按类单选需求 |
| 清零实现 | **`DELETE FROM usage`**（删光计数行） | 清零后首次成功调用由 `record_call` 的 UPSERT 重新建行、从 0 累计；观察结果与逐列置 0 完全一致，实现最简 |
| `user_count` / 注册用户 | **不清**（users 表不动） | 它是"注册人数"不是调用指标；人均 = 总数 ÷ 注册总数 的分母保持真实在册数（Spec4 §2 口径不变） |
| 确认强度 | 原生 `window.confirm` **一次**，与「清空反馈统计」完全同构 | 作者原话「清空需要报警提示一次，免得误触」+「跟下面那个有用没用的清空一样」；口径统一、改动最小。~~更强（输入关键字）方案~~ 仅当作者要求再加 |
| 反馈清空确认 | **已存在，无需补** | 核对 `StatsPanel.vue` `clearFeedbackStats()`：`window.confirm('确定清空全部 AI 服务反馈统计？此操作不可撤销。')` 在 Spec9 落地时已有；本 Spec 不加也不改其确认逻辑 |
| 清零时间存哪 | 新增 `app_meta(key TEXT PRIMARY KEY, value TEXT)` 键值小表 | usage 是"每用户一行"的计数表，没有自然单行可挂"清零时刻"；键值表最省，两行即可（`usage_cleared_at` / `feedback_cleared_at`） |
| 反馈清零何时记时间 | **仅"全清"（不带 `?category=`）时更新 `feedback_cleared_at`** | 前端只调全清（Spec9）；按类单选清空会留下其它类旧数据，语义上不算"归零重计"，不更新展示的"上次清零"，避免误导 |
| 清零后展示 | 统计头部显示「上次清零：yyyy/MM/dd HH:mm（本地时区）」；从未清零显示「从未清零」 | 让管理员一眼看出当前数字的统计起点；时间由后端存 UTC ISO，前端 `toLocaleString` 转本地 |

> 时间语义：清零时间存 **UTC ISO（`_now_iso()`，与全库时间格式一致）**，前端按本地时区格式化展示。`usage_cleared_at` 与 `feedback_cleared_at` 是两个**独立**清零动作的时间（各管各的块），互不影响。

---

## 3. 需求边界

### 范围内

- `POST` 管理端清零 `usage`（四类计数一键归 0），前置 `confirm` 一次。
- 清零前/后不触碰：users 表、images / posts / feedback 明细 / shares / suggestions。
- 记录两个"上次清零时间"（usage / feedback 各自），`GET /api/admin/stats` 一并返回，前端两块区域各展示自己的清零时间。
- 删除用户仍级联删其 usage 行（Spec4 既有行为，不因本 Spec 改变）。
- 清零后重新统计：任何成功调用从 0 开始重新累计（`record_call` 自动建行）。

### 范围外（本 Spec 不做）

- **按类单选清零**（要分清"只清对话"等：不做，前端只有一键全清按钮）。
- 时间维度增强：不因清零引入"按时段查历史/图表/留存"（Spec4 §3 排除项维持）；清零时间仅作"当前区间起点"标注，不建调用明细事件表。
- 自动定时清零 / 清零权限细分（仍只有管理员能进 `/api/admin/*`）。
- 统计**明细**展示（含用户名 / 对话内容），维持 Spec4 只展示聚合的口径。
- 反馈清空确认逻辑改造、建议箱/社区等其它面板的任何改动。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | 无新依赖 | 仅 `db.py`（新增 `app_meta` 表 + `clear_usage()` + 读 meta；`clear_feedback()` 全清时顺带写 meta）与 `main.py`（新增 `POST /api/admin/usage/clear` 路由；`GET /api/admin/stats` 返回两个清零时间）微调 |
| 前端 | 无新依赖 / 无新框架 | `StatsPanel.vue` 增加「清空调用统计」按钮 + 两个清零时间展示；`chatApi.js` 增加 `clearUsage()` |

> 无新 pip / npm 依赖；无新环境变量；`config.py`、`.env`、`.gitignore` 均不变（`artcn.db` 已在 .gitignore，新表同库自动建）。

---

## 5. 架构设计（增量）

### 5.1 数据变更

新增小表（`init_db` 内建表，幂等）：

```sql
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

两个键（值均为 UTC ISO 时间，`_now_iso()`）：
- `usage_cleared_at` —— 最近一次「清空调用统计」时刻（无则为 NULL → 前端显示"从未清零"）。
- `feedback_cleared_at` —— 最近一次「清空反馈统计」（**全清**）时刻（无则为 NULL）。

`usage` 表结构**不变**；清零采用删行，`record_call` 照旧 UPSERT 自动重建。

### 5.2 关键数据流

- **清空调用统计**：管理端点「清空调用统计」→ `confirm` 通过 → `POST /api/admin/usage/clear` → `db.clear_usage()`：`SELECT` 四类 SUM 得 `cleared` 总数 → `DELETE FROM usage` → UPSERT `app_meta['usage_cleared_at']=now` → 返回 `{cleared}` → 前端 `load()` 刷新（总数/占比/人均归 0，头部出现新清零时间）。
- **清空反馈统计（既有，补记时间）**：`db.clear_feedback(None)` 在 `DELETE FROM feedback` 后 UPSERT `app_meta['feedback_cleared_at']=now`；带 `?category=` 时不写 meta（见 §2）。
- **读统计**：`GET /api/admin/stats` 在现有 data 上**新增** `usage_cleared_at` 与 `feedback_cleared_at`（null 或 ISO 字符串），不改变任何既有字段。

### 5.3 并发 / 口径说明

- 清零与正在完成的任务计数理论上有极小竞态：`DELETE` 之后、下一次 UPSERT 之前的成功调用会落在"新周期"里——语义上正是期望（清零后完成的调用计入新一段），无需加锁。
- 清零不触发任何级联删除（`usage` 无外键，`delete_user` 的清 usage 逻辑互不影响）。

---

## 6. 接口约定

### 6.1 新增

| 端点 | 鉴权 | 请求体 | 响应 `data` | 说明 |
|---|---|---|---|---|
| `POST /api/admin/usage/clear` | 管理员 | 无 | `{cleared}` | 清零四类调用计数并记录清零时间；`cleared` = 清零前四类调用总数（供日志/提示，信息性） |

> 命名对齐既有 `/api/admin/feedback/clear`（以被清的资源表 `usage` 命名，而非视图名 `stats`）。

### 6.2 变更

| 端点 | 变更 |
|---|---|
| `GET /api/admin/stats` | 响应 `data` **新增**两个字段：`usage_cleared_at`、`feedback_cleared_at`（均为 `null | "YYYY-MM-DDTHH:MM:SS.mmmZ"`）。既有字段不动 |
| `POST /api/admin/feedback/clear` | 行为微调：**全清（不带 `?category=`）**时额外记录 `feedback_cleared_at`；带 `?category=` 行为不变。响应体仍为 `{cleared}` |
| 其余全部接口 | **不变** |

### 6.3 鉴权约定

沿用 Spec2/Spec4：`/api/admin/*` 统一限管理员（普通用户 → `40301`）；非 `/api/auth/login` 的全 `/api` 接口需 Bearer JWT（无 → `40103`）。

---

## 7. 前端交互

- **`chatApi.js`** 新增：
  ```js
  export async function clearUsage() {
    const { data } = await http.post('/api/admin/usage/clear')
    return data.data // { cleared }
  }
  ```
- **`StatsPanel.vue`**：
  - **顶部调用统计区**：把现有 `.stats-summary` 那句扩成统计区头部条——左侧「注册用户 X 人 · 调用总次数 Y · 上次清零：{时间|从未清零}」；右侧新增「**清空调用统计**」按钮（样式复用 `btn-mini`，与下方反馈区按钮一致）。点击 → `window.confirm('确定清空全部调用统计？对话 / 文生图 / 图文生图 / 图像QA 的计数将归 0，此操作不可撤销。')` → 确认后调 `clearUsage()`（期间按钮 `disabled`），成功 `load()` 刷新。
  - **AI 服务反馈区**：头部「清空反馈统计」按钮**不变**；在其头（h3 或按钮旁）新增一行小字「上次清零：{时间|从未清零}」，数据取 `stats.feedback_cleared_at`。
  - **时间格式化**：`iso` 为 null → 显示「从未清零」；否则 `new Date(iso).toLocaleString('zh-CN')`。
  - `load()` 一并读入两个新字段，无需额外请求。

---

## 8. 配置 / 环境变量 / .gitignore

无新增。`config.py`、`.env`、`.gitignore` 均不变（`app_meta` 与 usage 同在 `artcn.db`，`init_db` 启动自动建表）。

---

## 9. 错误码

无新增错误码。非管理员调用 `/api/admin/usage/clear` / `/api/admin/stats` 沿用 `40301`；未带 token 沿用 `40103`。

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON 与既有事件。新增一条：

- `usage.cleared`（清零四类调用计数，附 operator / request_id / cleared=清零前总数，不含用户名外的个人数据）。

`feedback.cleared` 语义不变（若实现为"全清才记时间"，可在事件里附 `recorded_cleared_at: true|false` 便于对账；非必需）。

---

## 11. 目录结构增量

```
Server/
  db.py         # 新增 app_meta 建表 + get/写 meta 辅助；clear_usage()；clear_feedback 全清时写 meta
  main.py       # POST /api/admin/usage/clear 路由 + 日志；GET /api/admin/stats 返回两个清零时间
frontend/src/
  api/chatApi.js            # 新增 clearUsage()
  views/StatsPanel.vue      # 顶部「清空调用统计」按钮 + confirm；两块区域各展示「上次清零：…」
```

---

## 12. 实施顺序（里程碑）

1. **B1 后端**：`db.py` 新增 `app_meta` 建表（`init_db` 内）+ `clear_usage()` + meta 读写；`clear_feedback` 全清时写 `feedback_cleared_at`。
2. **B2 后端路由**：`main.py` 新增 `POST /api/admin/usage/clear`；`GET /api/admin/stats` 并入两个清零时间。
3. **F1 前端**：`chatApi.js` 加 `clearUsage()`；`StatsPanel.vue` 加按钮 + confirm + 两块清零时间展示。
4. **A1 验收**：`npm run build` + 后端冒烟（§13 用例）。

---

## 13. 验收用例

| # | 操作 | 期望 |
|---|---|---|
| 1 | 管理员打开数据统计，从未清零过 | 统计头部显示「上次清零：从未清零」；反馈区同显示「从未清零」 |
| 2 | 管理员点「清空调用统计」 | 先弹 `confirm` 警告一次 |
| 3 | confirm 点「取消」 | 不发起请求，计数原样、清零时间不变 |
| 4 | confirm 点「确定」 | 计数/占比/人均/调用总次数全部归 0；头部出现「上次清零：{当前时刻}」；注册用户 X 人**不变** |
| 5 | 清零后普通用户成功调用一次对话 | 对话计数变 1，其余仍 0（新周期重新累计） |
| 6 | 管理员再清零 → 再成功调用 → 数据统计 | 新清零时间覆盖旧值，只保留最近一次；计数从 0 重新长 |
| 7 | 管理员点「清空反馈统计」→ confirm 确定 | 有用/没用全归 0，反馈区出现「上次清零：{当前时刻}」 |
| 8 | 反馈清零后用户重新 👍 一次 | 该类型有用=1，其余 0；清零时间仍为上次那刻 |
| 9 | 普通用户直接 `curl -X POST /api/admin/usage/clear` | `403`（`40301`） |
| 10 | 未带 token 调 `/api/admin/stats` | `401`（`40103`） |
| 11 | 刷新页面再进数据统计 | 两个清零时间持久显示（重启后端仍在，来自 `artcn.db`） |
| 12 | 数据统计页样式回归 | 顶部区新头部条 / 新按钮与下方反馈区形态一致，深紫主题无白底 |

> 验收时明确排除：按类单选清零 / 调用明细历史 / 图表 / 自动清零 / feedback 确认框改造。
