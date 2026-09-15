# ArtiControlNet Spec 18：API 服务调用计量与用户限额

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：把「每个用户消耗了多少次 AI 服务」从一个**只有全局聚合、谁也没在看**的统计数字，升级成**按用户可查、可设限、超额即锁**的计量体系——用户管理页每个用户多两列（**服务总调用次数** / **服务限额**，限额可编辑，默认 25），普通用户用满限额后**登录被直接拒掉、已在系统里的被强行踢出**，并在登录界面弹出续费提示。
> 本 Spec 是 **Spec.md / Spec2~17 的增量补充**，不推翻原有架构。数据库变化：**新增 1 张表**（`user_quota`）+ **2 次补列迁移**（`users.quota_limit`、`usage.style`）+ **1 次存量回填**（`user_quota.used` ← 既有 `usage` 求和）。
> **无新依赖、无新持久目录**；新增 3 个可选环境变量（均有默认值）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 `artcn.db` 外无其他数据库。**不新增 provider、不新增模型**。

---

## 1. 功能目的

### 1.1 为什么现在做

- **计数早就有，只是没人看得到。** Spec4 起后端就在每个任务成功完成后调 `db.record_call(user_id, category)`，`usage` 表已经**按用户**存着 `chat / generate / edit / qa` 四列计数。但唯一的出口是 `GET /api/admin/stats`——**全库聚合**（总次数、人均、占比），管理员**看不到任何一个具体用户用了多少次**。数据在库里躺了 14 个 Spec，没有一个界面把它按人摊开。
- **没有成本闸门。** 系统对所有人开放且无限量：一个账号可以把 TokenHub 的图像额度和 DeepSeek 的 token 无限烧下去。这是"能对外给人用"与"只能自己演示"之间的唯一一道门槛。
- **「续费」需要一个可执行的落点。** 作者要的是一句可对外的说明（"次数用完请联系管理员续费"）。那就必须存在一个**管理员能改的数字**，改完立刻生效——否则那句话是空头支票。

### 1.2 四件事

1. **看得见**：用户管理页每个普通用户那一行，直接显示「服务总调用次数」与「服务限额」。
2. **改得动**：管理员可编辑任意用户的「服务限额」，改完**立刻**生效（不需要对方重新登录、不需要重启后端）。
3. **锁得住**：普通用户`已用 ≥ 限额`时——**登录接口直接拒绝**；**已在系统里的，下一个请求就被踢回登录页**。
4. **说得清**：两种被锁的路径都在登录界面弹出同一句警告，告诉用户去哪续费。

### 1.3 计量的口径（这是本 Spec 最容易理解错的地方）

「服务总调用次数」= **该用户从建号至今消耗掉的 AI 服务次数总和**，由五类构成：

| 类别 key | 界面名 | 一次 = 什么 |
|---|---|---|
| `chat` | 对话 | 一个成功完成的纯文本对话任务 |
| `generate` | 文生图 | 一个成功完成的文生图任务 |
| `edit` | 图文生图 | 一个成功完成的线稿/图生图任务 |
| `qa` | 图像QA | 一个成功完成的图像问答任务 |
| `style` | 风格归纳 | **一次真实发出的**风格分析上游调用（每张上传图 1 次、风格合成 1 次） |

前四类**沿用 Spec4 的既有口径，一个字都不改**（一个任务算一次，不管 Supervisor 在背后调了几次上游；失败/超时/排队被拒**不**计数）。第五类是本 Spec 新增的，粒度与前四类**有意不同**——理由见 §2.1。

---

## 2. 决策记录（为什么这么选）

### 2.1 计量模型

| 决策 | 选择 | 理由 |
|---|---|---|
| 「服务总调用次数」按什么粒度 | **沿用 Spec4 的 usage 口径**：一个成功完成的任务算 1 次 | 一次 `/api/chat` 背后其实是 2 次上游调用（Supervisor 路由 1 次 + 子 Agent 1 次），但用户在界面上看到的是"我做了一件事"。按上游调用计会让「数据统计」页的四个数**当场对不上**——那里已经按任务口径统计了 14 个 Spec。作者拍板：口径统一优先于成本精确 |
| 「服务总调用次数」= 哪个数 | **`user_quota.used`**（终身累计计数器），不是 `usage` 五列之和 | `usage` 会被 Spec11 的「清空调用统计」删行重置（那是"开一段新统计区间"）。若拿它当额度，管理员点一次清空 = 给所有超额用户**集体解封**——一个统计按钮不该有这种副作用。详见 §2.2 |
| 风格归纳（`style`）的粒度 | **按实际发出的上游调用数**，不是按任务 | 作者拍板。一次 `POST /api/wiki/style/refresh` 内部会发 `N`（未纳入的上传图，≤`WIKI_UPLOAD_QA_MAX`）+ `1`（风格合成文本）次真实调用，N 随图片数浮动，"算一次"会严重低估 |
| 风格归纳为什么不能沿用"成功才计" | **调用发出前就记账** | Excel 里的四类任务是"用户可见的一次交付"，失败 = 用户什么都没拿到，不计费成立。但风格归纳是**逐张图片**的调用：3 张里失败 1 张，用户**已经拿到了**另外 2 张的分析结果和一份新风格——"整次成功"这个判据在这里不成立。而且 Spec15 §5.2B 已经写明失败的那张**下次点按钮会重新分析**，即**同一张图会再花一次钱**。计费必须跟着真实发生的调用走 |
| 风格归纳的文本合成调用 | **也计 1 次**，且只在真正发起时计 | `nothing_new`（无待考虑作品）与 `analysis_failed`（材料全不可用）两条路径**不发起**文本调用，都是 0。见 §5.2 |
| 超额判定边界 | **`used >= quota_limit`** | 作者拍板。"限额 25 次" = 最多用满 25 次，第 26 次起被锁。若写成 `used > quota_limit`，用户实际能用 26 次，与"限额"的字面含义不符 |
| 判定用什么比较 | `used >= quota_limit`，**管理员整体豁免** | `is_admin = 1` 的用户**永远不判限额**（`used` 照常累计、照常展示）。管理员是系统的运维者，把自己锁在门外没有意义 |
| 计数何时减 | **永不减** | `user_quota.used` 单调递增，只增不清。管理员的"续费"动作 = **把限额改大**，不是把已用次数改小（§2.4） |

### 2.2 两张表的分工（为什么不复用 `usage`）

| 表 | 语义 | 可清零 | 服务于 |
|---|---|---|---|
| `usage`（既有） | **区间统计** | ✅ Spec11 的「清空调用统计」删全表 | 「数据统计」页（管理员看全局趋势） |
| `user_quota`（**新增**） | **计费账户** | ❌ 只增不减 | 「用户管理」页的「服务总调用次数」+ 限额判定 |

| 决策 | 选择 | 理由 |
|---|---|---|
| 额度计数器放哪 | **新建 `user_quota` 表**，不放 `users` 列 | 作者拍板"额度用独立计数器"。放在 `users` 表也能跑，但 `users` 现在是纯粹的"账号"表（id/用户名/哈希/角色/时间），把可变计数塞进去会让 `_row_to_dict`、`list_users`、登录查询全部跟着变宽；独立表还能让"删用户"的级联删除自成一条 |
| 两处写入要不要同事务 | **要**，`record_call` 内一次 `commit` | 这是选独立表而不是"每次现算"的核心理由：**统计与计费永远同生同死**，不存在"统计涨了但没扣费"的窗口 |
| 清零后两个数不一致怎么办 | **接受**，并在「数据统计」页的确认文案里写明 | 清零后 `user_quota.used` 会**大于** `usage` 五列之和，这是有意的：清空统计不是退钱。管理员想知道"某人到底用了多少"看用户管理页，想知道"最近这段用了多少"看数据统计页 |
| 管理员的 `used` 也累计吗 | **累计，也展示** | 管理员的用量同样有价值（比如判断"是不是我自己的调试把额度烧完了"），只是不参与判定 |

### 2.3 拦在哪、怎么拦

| 决策 | 选择 | 理由 |
|---|---|---|
| 登录时怎么拒 | `POST /api/auth/login` **密码校验通过之后**再判限额，抛 `40304`（HTTP 403） | **顺序是契约的一部分**：先验密码，否则任何人都能拿一个用户名探测出"这个账号超额了"。代价是超额用户知道自己的密码是对的——可接受 |
| 拒登录算不算"登录失败" | **不算** | 不调 `record_login_failure`（那是防暴力破解的，本场景已经证明密码正确）。限额检查放在 `reset_login_failures` **之前**：被拒绝的请求不该产生任何"部分成功"的副作用 |
| 在系统里怎么踢 | **统一鉴权中间件**（`main.py` 的 `auth_middleware`）里判，超额返回 `40304` | 这是**唯一**能覆盖全部 `/api` 的关口，且它**每个请求都实时查库**（Spec2 为"撤销管理员即时生效"建立的能力），天然满足"改完限额立刻生效、不用重新登录"。放在 `request.state.user` 赋值之后、`/api/admin/*` 权限判断之前 |
| 拦哪些路径 | **`/api/*` 全拦**，只放行 `/api/auth/login`（既有 `PUBLIC_AUTH_PATHS` 不变） | 作者原话"在系统里则强行直接退出登录"。半拦（只拦 `/api/chat`）会让用户在系统里继续浏览却什么都做不了，比直接踢出去更糟 |
| 要不要为它加一次查库 | **不加** | 中间件本来就在查 `db.get_user_by_id`。把 `used` 用 `LEFT JOIN user_quota` **并进同一条查询**，每个请求的查询次数**一个都不增加** |
| 前端怎么知道被踢了 | 复用既有 `artcn:unauthorized` 的同款机制，新增 `artcn:quota_exceeded` 事件 | 既有 401 处理已经验证过这条链路（拦截器清 token → 派发事件 → `App.vue` 登出 → 渲染登录页）。不发明第二套 |
| 前端怎么区分 40304 与 40301/40302/40303 | 拦截器**按 `code` 精确匹配 40304**，不看 HTTP 状态 | 四个 403 里只有一个是"该踢人"。现状拦截器只判断 `status === 401`，本 Spec 给它补上 `code` 字段（§7.2） |

### 2.4 「续费」怎么操作

| 决策 | 选择 | 理由 |
|---|---|---|
| 续费的实现 | **管理员把「服务限额」改大**（25 → 30），**已用次数不动** | `used` 是历史事实，改小它就是伪造账目。改限额既解封，又保留了"这人累计用了多少"的真实记录 |
| 要不要一个「重置某人已用次数」的接口 | **不做**（见 §3.3） | 作者只要求"设定限额"。提高限额已经能解封，而重置计数会引入"两个口径哪个才是真的"的新歧义。YAGNI |
| 改限额要不要通知对方 | **不通知**，对方下一个请求自然就通了 | 没有站内信/推送设施；而他被锁时停在登录页，点一次登录就知道好了 |
| 改限额的交互 | **`window.prompt`**，与隔壁「重置密码」同款 | `AdminPanel.vue` 现有的两个编辑动作（重置密码）就是用 `window.prompt` 做的。为限额单独做一个行内编辑组件，会在这个 199 行的文件里引入**该文件唯一的**编辑态/校验/回滚逻辑。一致性 > 体验微优化 |

---

## 3. 需求边界

### 3.1 范围内

- `db.py`：新增 `user_quota` 表 + 存量回填；`users.quota_limit`、`usage.style` 两处补列迁移；`record_call` 双写；`get_usage_stats()` 覆盖第五类；`clear_usage()` 覆盖第五类；`delete_user()` 级联补 `user_quota`；用户查询带出 `used`，并**顺手停止外泄 `password_hash`**（§5.1f）。
- `errors.py`：新增 `40304 QuotaExceededError`。
- `config.py`：`QUOTA_DEFAULT_LIMIT` / `QUOTA_LIMIT_MAX` / `QUOTA_CONTACT_EMAIL` 与拼好的提示语。
- `main.py`：鉴权中间件加限额判定；`POST /api/auth/login` 加限额判定；`GET /api/admin/users` 返回 `used` / `quota_limit`；新增 `PUT /api/admin/users/{user_id}/quota`。
- `wiki.py`：`refresh_style` 与 `_analyze_uploads` 里的两处计数埋点。
- `schemas.py`：`AdminSetQuotaRequest`。
- 前端：`utils/quotaNotice.js`（新增）、`App.vue`（`artcn:quota_exceeded` 监听）、`api/chatApi.js`（错误带 `code`、40304 分支、`updateUserQuota`）、`store/auth.js`（`init` 的 40304 分支）、`views/Login.vue`、`views/AdminPanel.vue`（两列 + 编辑 + 超额标记）、`views/StatsPanel.vue`（第五行 + 文案）、`views/HelpModal.vue`（一句说明）、`assets/styles/main.css`（`.quota-over-tag`）。
- `.env.example`、`CLAUDE.md` 同步。

### 3.2 不在范围内（明确不做）

- **不改任何一个上游调用链**：不新增 provider、不新增模型、不改路由、不改 prompt。
- **不给用户看自己的余额**：`GET /api/auth/me` 不返回 `used`/`quota_limit`，聊天页不显示"剩余次数"。作者没要求；而且"用一次少一次"的倒计时显示会显著改变产品的心理感受，不该顺手塞进这个 Spec。
- **不做用量明细**：不记"每次调用发生在何时、对应哪个 task"。只需要一个总数。
- **不做分档/套餐/多级限额**：所有普通用户同一个默认值，管理员逐人改。
- **不做额度到期时间**（月配额、周期重置）——那是另一套模型（时间窗 vs 累计），会推翻 §2.1 的"只增不减"。
- **不做注册/自助付费**：账号仍只由管理员创建（Spec2）。
- **不动 `POST /api/admin/usage/clear` 的语义**：它仍然只清 `usage` 表、仍然不可撤销。只是确认文案要改（§7.6b）。
- **不迁移历史 `style` 计数**：`usage.style` 是新列，存量行一律为 0；`user_quota` 的回填**只回填前四类**（§5.1e）。Spec15 之前没有风格归纳，Spec15~17 期间发生的视觉调用**无法追溯**（没记过），如实留空而不是猜。

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **临界那一次，用户看不到结果。** 普通用户第 25 次任务**成功完成**后 `used` 变成 25，立刻满足 `>= 25`。前端的轮询（`GET /api/tasks/{id}`，每 ~1.5s 一次）随即被 `40304` 拒绝 → 被踢回登录页 → **这一轮生成的图他没看到**。
   - 图**没有丢**：作品库入库（`gallery`）排在 usage 记账之前，图已经在「我的作品」里；续费后登录就能看到。
   - **不为此开后门**：让轮询豁免会破坏"用户已用满即完全无法访问"的简单契约（§2.3），也会引入"中间件要解析路径参数并校验任务归属"的新复杂度。这是"强制退出"这个要求的必然代价，作者已知悉。
2. **超额用户被锁在登录页，不能用任何功能**，包括与 API 无关的浏览（作品库、社区、建议箱全部在被拦的 `/api/*` 里）。这是 §2.3"全拦"的直接后果，有意为之。
3. **`user_quota.used` 与「数据统计」页的数是两个数。** 未清零时相等；清零后前者恒大于后者。见 §2.2 的分工表。
4. **存量用户会被立刻锁。** 回填按既有 `usage` 求和，因此**旧库里任何已用满 25 次的普通用户，升级后第一次请求就被踢**。这是回填的本意（否则上线即等于给所有人清零），处置方式是管理员把那个人的限额改大（§2.4）。
5. **`QUOTA_DEFAULT_LIMIT` 改了不会影响已存在的用户。** 它只用于「新建用户」和「补列迁移时给存量行填初值」。要改某个已有用户的限额，走 `PUT /api/admin/users/{id}/quota`。
6. **撤销管理员 = 立刻受限额约束。** 一个 `used = 300` 的用户被撤销管理员后，下一个请求直接 `40304`。中间件实时查库（Spec2 的既有行为），没有缓存窗口。
7. **风格归纳的计数对"图片"敏感，对"按钮"不敏感。** 点一次 `refresh` 消耗 `N+1` 次（N = 本次真正进入分析的上传图数，≤ `WIKI_UPLOAD_QA_MAX`），不是固定 1 次。同一批图若整次失败（`UpstreamApiError` 抛出），**已花掉的视觉调用照样计入**（§2.1），下次重点按钮会**再计一次**——因为钱确实又花了一次。

---

## 4. 技术栈增量

**无。** 零新依赖、零新 provider、零新模型、零新持久目录、零新前端库。

配置里新增 3 个环境变量（都有默认值，都可以不配）。

---

## 5. 架构设计（增量）

### 5.1 数据变更

#### a. 新表 `user_quota`（Spec18）

```python
_CREATE_USER_QUOTA_TABLE = """
-- 计费账户（Spec18 §5.1a）：每用户一行，单调累计，**永不清零**。
-- 与 usage 表的分工见 Spec18 §2.2：usage 是"区间统计"（可被 Spec11 的清空按钮删行），
-- user_quota 是"终身账本"（只增不减）。两处由 record_call 在同一事务里写入，永远同步。
-- 管理员同样有行（照常累计与展示），只是不参与限额判定。
CREATE TABLE IF NOT EXISTS user_quota (
    user_id    INTEGER PRIMARY KEY,
    used       INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL
)
"""
```

> 建表**不放进 `init_db` 的建表清单**，由 §5.1e 的回填函数负责——那正是它的幂等判据。见 §5.1e 的说明。

#### b. `users` 补列（Spec18）

```python
# db.py 顶层：_CREATE_TABLE 由普通字符串改为 f-string，多一列
_QUOTA_DEFAULT = int(config.QUOTA_DEFAULT_LIMIT)   # 只在 DDL 里用；int() 过一遍，无注入面

_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    quota_limit   INTEGER NOT NULL DEFAULT {_QUOTA_DEFAULT}
)
"""
```

存量库由 `_migrate_users_quota_limit` 补（§5.1d），**用同一个 `_QUOTA_DEFAULT`**。

> **`create_user` 一个字都不用改**。它现有的 `INSERT INTO users (username, password_hash, is_admin, created_at)` 不列 `quota_limit`，于是由 DDL 的 `DEFAULT` 兜底——而新库的 `_CREATE_TABLE` 与存量库的 `ALTER` 都取自 `_QUOTA_DEFAULT`，**默认限额在全仓只有一个来源**。若改成在 `create_user` 里显式拼值，同一个默认值就会同时存在于 config、`_CREATE_TABLE`、`ALTER` 三处，改一处忘两处的风险远大于省下的这一行。

`quota_limit` 的语义：该用户**累计**可消耗的服务次数上限。
**`NOT NULL` 而非可空**——可空（`NULL` = 跟随默认）看起来更灵活，但会让管理端的编辑框在"显示的是 25、存的是 NULL"之间产生不一致：管理员没动过这一格，保存时到底要不要写？写 25 就等于把"跟随默认"变成"锁死 25"，不写则下次改默认值时这个人会莫名其妙跟着变。**每一行都有一个明确的数字**是这个界面唯一自洽的模型。

#### c. `usage` 补列（Spec18）

```sql
-- 建表语句 _CREATE_USAGE_TABLE 追加一列（新库）：
--     style INTEGER NOT NULL DEFAULT 0
-- 存量库由 _migrate_usage_style 补（§5.1d）。
-- _USAGE_CATEGORIES 同步从 4 元组扩为 5 元组（record_call 的列名白名单）。
```

#### d. 两次补列迁移（`init_db` 内，幂等）

沿用 Spec12 §5.1b / Spec16 §5.1b 的「先查 `PRAGMA table_info` 后 `ALTER`」模式：

```python
def _migrate_users_quota_limit(conn: sqlite3.Connection) -> None:
    """存量库补 users.quota_limit（Spec18 §5.1b）：PRAGMA 查得无该列才 ALTER，幂等。

    默认值取模块级的 _QUOTA_DEFAULT（= config.QUOTA_DEFAULT_LIMIT，§5.1b），
    与新库的 _CREATE_TABLE 同源。**它只在建表/补列时生效，改它不影响已存在的用户**
    （见 §3.3-5）。
    列顺序：存量库追加在末尾，新库在 _CREATE_TABLE 里；读取一律按列名，行为无差别。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "quota_limit" not in cols:
        conn.execute(
            f"ALTER TABLE users ADD COLUMN quota_limit INTEGER NOT NULL "
            f"DEFAULT {_QUOTA_DEFAULT}"
        )
        logger.info("users.quota_limit 列已补齐", extra={"event": "db.migrate"})


def _migrate_usage_style(conn: sqlite3.Connection) -> None:
    """存量库补 usage.style（Spec18 §5.1c）：PRAGMA 查得无该列才 ALTER，幂等。

    存量行一律为 0：Spec15 之前的风格归纳调用**没有记过**，无法追溯（§3.2）。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(usage)").fetchall()}
    if "style" not in cols:
        conn.execute("ALTER TABLE usage ADD COLUMN style INTEGER NOT NULL DEFAULT 0")
        logger.info("usage.style 列已补齐", extra={"event": "db.migrate"})
```

#### e. 存量回填 `user_quota.used`（**只执行一次**）

**幂等判据是"表是否刚被本次启动创建"**，而不是"表是否为空"——后者会把一个合法的"所有用户都 0 次"的库反复回填（结果一样但每次都要扫全表），也无法区分"新建的库"和"回填过的库"。

```python
def _backfill_user_quota(conn: sqlite3.Connection) -> None:
    """首次引入 user_quota 表时，把既有 usage 的前四类求和回填为已用次数（Spec18 §5.1e）。

    判据：sqlite_master 里查不到 user_quota 表 → 说明这是升级后的第一次启动，
    此刻建表并回填。之后每次启动该表都存在，直接返回（绝不覆盖运行期数据）。

    **只回填 chat/generate/edit/qa**：style 是本次新加的列，存量行恒为 0，
    回填它没有意义（Spec15~17 期间的视觉调用没记过，§3.2）。

    回填的直接后果：旧库里已用满默认限额的普通用户，升级后立刻被锁（§3.3-4）。
    这是本函数存在的理由——不回填等于上线即给所有人清零，与"计费"语义矛盾。
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_quota'"
    ).fetchone()
    if exists:
        return
    conn.execute(_CREATE_USER_QUOTA_TABLE)
    conn.execute(
        "INSERT INTO user_quota (user_id, used, updated_at) "
        "SELECT user_id, "
        "       COALESCE(chat, 0) + COALESCE(generate, 0) "
        "     + COALESCE(edit, 0) + COALESCE(qa, 0), "
        "       ? "
        "FROM usage WHERE user_id IS NOT NULL",
        (_now_iso(),),
    )
    _upsert_meta(conn, QUOTA_BACKFILLED_KEY, _now_iso())
    logger.info("user_quota 已建表并回填存量用量", extra={"event": "db.migrate"})
```

`init_db` 里的调用位置有两条硬约束：

```python
        conn.execute(_CREATE_META_TABLE)
        # …既有建表…
        _migrate_upload_wiki_used(conn)
        _migrate_images_note(conn)
        # Spec18 §5.1d：两次补列迁移，必须在 _backfill_user_quota **之前**
        _migrate_users_quota_limit(conn)
        _migrate_usage_style(conn)
        # Spec18 §5.1e：建 user_quota 表 + 回填存量用量。
        # 位置约束一：必须在 _migrate_usage_style 之后（否则求和语句里没有 style 列）。
        # 位置约束二：必须在 _CREATE_META_TABLE 之后（回填会写 app_meta 键）。
        # 它**不在**上面的建表清单里——`CREATE TABLE IF NOT EXISTS` 会让
        # `sqlite_master` 判据在第一次启动时提前成立，回填被静默跳过。
        _backfill_user_quota(conn)
        _migrate_posts_nullable_image(conn)
        conn.commit()
```

`usage` 表若为空（全新库），`INSERT ... SELECT` 插 0 行，等价于无操作。

`app_meta` 新增 1 个键：

```python
# app_meta 键：user_quota 存量回填的执行时间（UTC ISO）。
# 信息性——真正的幂等判据是 sqlite_master 里表存在与否（§5.1e），这个键只供排障。
QUOTA_BACKFILLED_KEY = "quota_backfilled_at"
```

#### f. 用户查询：带上 `used`，并停止外泄 `password_hash`

三处对 `users` 的 `SELECT *` 统一改为一条带上配额状态的查询：

```python
# LEFT JOIN 而非 JOIN：用户可能还没有 user_quota 行（理论上不该有，但缺失时
# 必须退化成"已用 0 次"而不是"查不到这个人")。
_USER_SELECT = (
    "SELECT u.*, COALESCE(q.used, 0) AS used "
    "FROM users u LEFT JOIN user_quota q ON q.user_id = u.id"
)
```

`_row_to_dict` 加两个字段、**去掉一个**：

```python
def _row_to_dict(row: sqlite3.Row | None, *, with_secret: bool = False) -> dict | None:
    """users 行 → dict。

    Spec18 §5.1f：**默认不再带出 `password_hash`**。它是 bcrypt 哈希、不是明文，
    但 `GET /api/admin/users` 一直在把它返回给前端，而前端从来没用过——一个只在
    登录时需要的秘密，没有任何理由出现在列表接口里。改成"要用必须显式要"，
    这个保证就从"调用方自觉"变成了结构性的。

    新增：`quota_limit`（users 列）、`used`（user_quota 累计，见 _USER_SELECT）。
    """
    if row is None:
        return None
    record = {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "quota_limit": int(row["quota_limit"]),
        "used": int(row["used"]),
    }
    if with_secret:
        record["password_hash"] = row["password_hash"]
    return record
```

**唯一的 `with_secret=True` 调用方是 `get_user_by_username`**（登录时校验密码用）。`get_user_by_id` / `list_users` 一律走默认值。

**检查清单**（落地时逐个确认，改了 `_row_to_dict` 之后全仓只有这几处受影响）：

| 调用点 | 是否读 `password_hash` | 处置 |
|---|---|---|
| `main.py:1015`（`login`） | ✅ 读 | 经 `get_user_by_username`，**已带**（`with_secret=True`） |
| `main.py:343`（鉴权中间件） | ❌ 只读 `id`/`username`/`is_admin` | 不加 |
| `main.py:896`（分享页取作者名） | ❌ 只读 `username` | 不加 |
| `main.py:1069 / 1085 / 1102`（管理员三个用户操作） | ❌ 只读 `id`/`username`/`is_admin` | 不加 |
| `main.py:1052`（`admin_create_user` 的返回） | ❌ 只读 `id`/`username`/`is_admin` | 不加 |
| `db.create_initial_admin` | ❌ 丢弃返回值 | 不加 |

即：**`with_secret=True` 全仓只有 `get_user_by_username` 一处**。

#### g. `record_call` 双写（同一事务）

```python
# 计数列白名单（record_call 据此拼列名，绝不拼接外部输入）
_USAGE_CATEGORIES = ("chat", "generate", "edit", "qa", "style")


def record_call(user_id: int, category: str) -> None:
    """累计一次调用：usage（区间统计）+ user_quota（计费账户）**同一事务**写入。

    Spec18 §2.2：两个表的和必须永远同步，否则会出现"统计涨了但没扣费"的窗口。
    因此这里刻意开一次连接、写两条语句、一次 commit —— 不要拆成两个函数、
    也不要在调用方串两次。

    调用时机由调用方决定，本函数不做任何"该不该计"的判断：
    - 四类任务（chat/generate/edit/qa）：任务**成功完成后**计一次（Spec4 既有口径，不变）；
    - style：**上游调用发出前**计一次（Spec18 §2.1，理由见 §2.1"为什么不能沿用成功才计"）。
    """
    if category not in _USAGE_CATEGORIES:
        raise ValueError(f"未知统计类别: {category}")
    values = {c: (1 if c == category else 0) for c in _USAGE_CATEGORIES}
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage (user_id, chat, generate, edit, qa, style, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "chat = chat + excluded.chat, "
            "generate = generate + excluded.generate, "
            "edit = edit + excluded.edit, "
            "qa = qa + excluded.qa, "
            "style = style + excluded.style, "
            "updated_at = excluded.updated_at",
            (user_id, values["chat"], values["generate"], values["edit"],
             values["qa"], values["style"], now),
        )
        conn.execute(
            "INSERT INTO user_quota (user_id, used, updated_at) VALUES (?, 1, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "used = used + 1, updated_at = excluded.updated_at",
            (user_id, now),
        )
        conn.commit()
```

**注意**：`style` 的埋点是在**并发**路径里调用的（`_analyze_uploads` 用 `asyncio.Semaphore` 并发 3 路）。`record_call` 是全同步函数（内部没有 `await`），在 asyncio 单线程里不会被打断；SQLite 侧有 WAL + `timeout=10`，安全。

#### h. 其余两处 db 改动

- `get_usage_stats()`：五列都进 `totals` / `per_user_avg` / `shares`（`total_calls = sum(totals.values())` 自动含 `style`）。
- `clear_usage()`：清零前的 `cleared` 计数从四列求和改为五列求和。
- `delete_user()`：级联列表最前面加 `conn.execute("DELETE FROM user_quota WHERE user_id = ?", (user_id,))`（**只删账本行，不删 `usage` 的既有语句**）。

### 5.2 关键数据流

#### A. 一次生成任务的计数（既有路径，只有落点变了）

```
POST /api/chat → TaskQueue → handle_task
   ├─ run_supervisor(...)                       ← 成功
   ├─ 结果落库 / 内存上下文（不变）
   ├─ persist_reply(task, result)               ← 不变
   └─ category = _usage_category(result)        ← 不变（四类映射表一个字没改）
      └─ db.record_call(user_id, category)      ← 现在同时写 usage + user_quota
```

四类的计数**时机、条件、归类逻辑全部不变**。变的只有 `record_call` 内部多写一张表。

#### B. 一次风格归纳的计数（新埋点）

```
POST /api/wiki/style/refresh → wiki.refresh_style(user_id)
   ├─ pending = list_pending_style_images(user_id)
   ├─ pending 为空 → _skip("nothing_new")            → 0 次（未发起任何调用）
   ├─ uploads = [待分析的上传图][:WIKI_UPLOAD_QA_MAX]
   └─ _analyze_uploads(user_id, uploads)
        └─ 每张图： read_gallery_file → to_data_uri → **db.record_call(user_id, "style")** → qa(...)
                    ↑ 记在 qa() 之前：调用"即将发出"就记账。
                      读图/解码失败（图已被删）不会走到这里 → 不记账（§2.1）
   ├─ not analyses and not refs → _skip("analysis_failed")  → 只有上面已记的 N 次
   └─ **db.record_call(user_id, "style")** → deepseek.chat_text(...)   ← 文本合成，发出前记账
```

**为什么记在 `await` 之前**：`qa()` / `chat_text()` 抛异常时（超时、上游 5xx），调用**已经真实发生并计费**。记在 `await` 之后会让"失败的那一半"全部免费。记在之前 = 记"发起"，与 §2.1 选的粒度（按实际发出的调用）一致。

落点具体位置：

```python
# wiki.py — _analyze_uploads.one() 内，qa() 之前
async def one(item: dict) -> dict:
    async with sem:
        _, image_bytes = gallery.read_gallery_file(item["id"], user_id)
        data_uri = media.to_data_uri(image_bytes, max_side=config.WIKI_UPLOAD_QA_MAX_SIDE)
        # Spec18 §5.2B：调用即将发出即记账（不是"成功后记"）。放在 read_gallery_file /
        # to_data_uri 之后，保证"图已被删"这类**根本没发出调用**的情况不被计费。
        db.record_call(user_id, "style")
        text = (await qa(data_uri, WIKI_UPLOAD_QA_PROMPT)).strip()
    ...

# wiki.py — refresh_style 内，chat_text() 之前
    history = db.get_wiki(user_id)["style"]
    # Spec18 §5.2B：风格合成也是一次真实调用；nothing_new / analysis_failed 两条
    # 跳过路径都到不了这里，所以它们天然是 0。
    db.record_call(user_id, "style")
    raw = await deepseek.chat_text(_build_messages(history, analyses, refs))
```

### 5.3 一致性 / 失败语义

| 场景 | 行为 |
|---|---|
| `record_call` 的第二次写入失败 | 与第一次同事务，整体回滚：**要么都记要么都不记**。调用方**不吞异常也不捕获**——账目出错应该吵。两条路径的既有语义是：`handle_task` 里异常冒到 Worker 的 except，任务标 `FAILED`；`_analyze_uploads.one()` 里抛出的 `sqlite3.Error` **不是** `AppError`，会被既有的 `if not isinstance(res, AppError): raise res` 判据整次抛出（这正是想要的，别把它改成"归入 `failed` 列表"）。 |
| 四类：扣费后任务随后失败 | 不可能：`record_call` 排在 `handle_task` 里所有可能失败的动作**之后**（`persist_reply` 也排在它前面），它执行完只剩 `return`。（既有行为，本 Spec 未改变：若 `record_call` 自己抛异常，助手消息其实已经落库了，但用户仍会看到任务失败——这是 Spec4 起就有的边界，不在本次范围内。） |
| 风格归纳：图分析成功、文本合成失败 | 视觉那 N 次**已计**，文本那次**也已计**（记在 `await` 前）。`UpstreamApiError` 照常抛出，wiki 与 `images.wiki_used` 保持原样（Spec15 既有语义），用户下次重点按钮会**再计一次**——因为确实又花了一次钱。 |
| 管理员在用户请求的间隙改限额 | 下一个请求立即按新限额判定（中间件每请求实时查库）。不存在缓存窗口。 |
| 限额被改小到低于当前 `used` | 立即锁定。`used = 30`、限额被改成 `20` → 下一个请求 `40304`。 |
| 回填时 `usage` 里某用户行不存在 | 该用户没有 `user_quota` 行，`_USER_SELECT` 的 `LEFT JOIN` 返回 `used = 0`。首次调用时 `record_call` 的 UPSERT 会建行。 |
| `QUOTA_DEFAULT_LIMIT` 设为 0 或负数 | 0 是**合法**取值：等于禁止该用户使用任何服务（新建即锁）。负数同样合法且表现为立刻锁定。不做额外校验——管理员想禁用某账号，这是最直接的手段。 |

---

## 6. 接口约定

### 6.1 变更：`GET /api/admin/users`

**返回**（`data` 为数组，每项）：

```json
{
  "id": 2,
  "username": "alice",
  "is_admin": false,
  "created_at": "2026-09-01T08:12:33.014Z",
  "quota_limit": 25,
  "used": 25
}
```

**变化**：

| 字段 | 变化 |
|---|---|
| `password_hash` | **删除**（§5.1f）。前端从未使用；`AdminPanel.vue` 无需改动即可继续工作 |
| `quota_limit` | 新增。该用户的累计服务次数上限 |
| `used` | 新增。该用户的累计已用次数（`user_quota`） |

> **不返回**"是否超额"这个派生布尔。前端用 `!u.is_admin && u.used >= u.quota_limit` 现算——超额的判据只有一处（§5.1b 的常量口径），把它复制到接口层就多了一个会漂移的副本。

### 6.2 新增：`PUT /api/admin/users/{user_id}/quota`

设置某用户的累计服务限额。**仅管理员**（`/api/admin/*` 前缀，中间件保证）。

**请求**

```json
{ "quota_limit": 30 }
```

**校验与错误**

| 情况 | 响应 |
|---|---|
| `quota_limit` 不是整数 | `40001 BadRequestError`（FastAPI 请求体校验，schema 用 `int`） |
| `quota_limit < 0` 或 `> QUOTA_LIMIT_MAX` | `40017 QuotaLimitError`（§9） |
| `{user_id}` 不存在 | `40402 UserNotFoundError` |

**响应**

```json
{ "code": 200, "message": "ok",
  "data": { "id": 2, "quota_limit": 30, "used": 25 } }
```

回带 `used` 让前端不必再拉一次整表就能就地更新那一行（前端实际仍会 `load()`，但接口自洽）。

**允许对管理员设置限额**（返回值照常），只是判定时被 `is_admin` 豁免——这样"设为管理员/撤销管理员"不需要连带处理限额字段，两个动作正交。

**日志**：

```python
logger.info("设置服务限额", extra={
    "event": "auth.admin.set_quota", "request_id": request_id,
    "username": operator["username"], "target_user": target["username"],
    "quota_limit": payload.quota_limit,
})
```

### 6.3 变更：`POST /api/auth/login`

在密码校验成功后、`reset_login_failures` **之前**插入：

```python
    # Spec18 §6.3：限额判定放在密码校验之后（否则任何人都能拿用户名探测账号状态），
    # 放在 reset_login_failures 之前（被拒绝的请求不产生任何"部分成功"的副作用）。
    if not user["is_admin"] and user["used"] >= user["quota_limit"]:
        logger.warning("服务次数已达上限，拒绝登录", extra={
            "event": "auth.quota_blocked", "request_id": request_id,
            "username": user["username"], "used": user["used"],
            "quota_limit": user["quota_limit"],
        })
        raise QuotaExceededError()
```

**响应**：HTTP **403**，`{"code": 40304, "message": "您的服务次数已达上限，请联系管理员续费可继续使用！（管理员邮箱：frostyj@qq.com）", "data": null}`。**不签发 token**。

管理员永远走不到这个分支。

### 6.4 变更：统一鉴权中间件

在 `request.state.user` 赋值之后、`/api/admin/*` 权限判断之前插入：

```python
        # Spec18 §6.4：普通用户服务次数用满即全拦（含 /api/auth/me），
        # 前端据 40304 清 token 回登录页并弹出提示。
        # 位置：放在 request.state.user 之后（日志/上下文需要它），
        #       放在 /api/admin/* 判断之前（管理员恒豁免，顺序上先排掉更省分支）。
        if not user["is_admin"] and user["used"] >= user["quota_limit"]:
            return _quota_reject(request, user)
```

```python
def _quota_reject(request: Request, user: dict) -> JSONResponse:
    """服务次数耗尽：与 _auth_reject 分开，用独立 event 名（排障时一眼可辨）。"""
    logger.warning("服务次数已达上限，拒绝访问", extra={
        "event": "auth.quota_blocked",
        "request_id": request.headers.get("x-request-id"),
        "username": user["username"], "used": user["used"],
        "quota_limit": user["quota_limit"],
        "path": request.url.path,
    })
    return JSONResponse(
        status_code=403,
        content={"code": 40304, "message": config.QUOTA_EXCEEDED_MESSAGE, "data": None},
    )
```

- **HTTP 403**（不是 401）：登录态本身是有效的，只是无权继续使用。用 401 会让前端既有的"401 → 清 token"分支把它当成 token 失效，虽然结果一样，但语义错。
- **`PUBLIC_AUTH_PATHS` 不变**：`/api/auth/login` 天然豁免（登录是"重新获得使用资格"的唯一入口）。
- **`GET /api/auth/me` 也会被拦**——这是有意的：前端启动时若拿不到身份，就走登出路径。

### 6.5 不变

| 接口 | 说明 |
|---|---|
| `POST /api/chat` | 一个字不改。**不在提交时预判限额**——判定统一收在中间件，避免"提交被拒"与"下一请求被踢"两套语义并存 |
| `GET /api/admin/stats` | **响应结构完全不变**，只是 `totals` / `per_user_avg` / `shares` 里多了 `style` 键（前端读取方式不变） |
| `POST /api/admin/usage/clear` | 语义不变（只清 `usage`，不动 `user_quota`）。仅 `cleared` 的求和口径从四类变五类 |
| `POST /api/admin/users`、`PUT .../password`、`PUT .../admin`、`DELETE /api/admin/users/{id}` | 全部不变。新建用户的 `quota_limit` 由建表默认值给（`QUOTA_DEFAULT_LIMIT`） |
| `DELETE /api/admin/users/{id}` | 行为不变，级联列表里多一行 `user_quota`（§5.1h） |
| 其余全部接口 | 不变 |

---

## 7. 前端交互

### 7.1 提示通道：`utils/quotaNotice.js`（新增）+ `App.vue` 监听

被踢与登录被拒是**两条不同的路径**，却要显示**同一句话**，而且要跨"登出 → 渲染登录页"这个组件切换。这条通道由三部分组成，缺一不可。

**a. `utils/quotaNotice.js`** —— 一个只有一个 ref 的模块，当消息的传递通道：

```js
// 服务次数耗尽提示的唯一落点（Spec18 §7.1）。
// 两条写入方：api/chatApi.js 的 40304 拦截分支（在系统里被踢）、
//             store/auth.js 的 init() 40304 分支（启动时已超额）。
// 一个读取方：views/Login.vue 挂载时取走并弹窗。
// 用完即清（take 而非 get）：同一条警告只弹一次，用户点了"确定"之后再刷新页面
// 不该又被弹一遍。
import { ref } from 'vue'

export const quotaNotice = ref('')

export function setQuotaNotice(message) {
  if (message) quotaNotice.value = message
}

export function takeQuotaNotice() {
  const message = quotaNotice.value
  quotaNotice.value = ''
  return message
}
```

**b. `App.vue`** —— 踢出的落点。在既有的 `artcn:unauthorized` 监听旁边加一条：

```js
// Spec18 §7.1b：服务次数耗尽 → 与 401 同样地登出并关掉所有面板。
// 处理体与上面那条完全相同，但**不复用同一个事件名**：两者的原因不同
// （登录态坏了 vs 额度用完了），日志和将来可能的分叉处理都需要能分开。
window.addEventListener('artcn:quota_exceeded', () => {
  auth.logout()
  closeAllPanels()
})
```

> 为什么不在拦截器里直接 `window.alert`：那一刻界面上可能还开着作品库/社区/管理面板，弹窗压在什么上面是不确定的；而 `Login.vue` 是**登出之后才挂载**的，在它 `onMounted` 里弹，用户看到的一定是"我已经回到登录页了，并且告诉我为什么"。提示语本身由拦截器提前写进 §7.1a 的通道。

### 7.2 `api/chatApi.js`

**a. 错误对象带上 `code`**——拦截器现在只知道 HTTP 状态，无法区分四种 403：

```js
function httpError(message, status, code) {
  const e = new Error(message || '请求失败')
  e.status = status
  e.code = code            // Spec18：业务错误码，前端据此区分 40304（限额）与 40301/02/03
  return e
}
```

`http.interceptors.response.use` 的三处 `httpError(...)` 调用与 `Promise.reject(...)` 全部补上 `body?.code`。

**b. 40304 分支**——在既有的 401 分支旁边加一条，**两条互斥**：

```js
// 成功响应体里的非 200 code（既有逻辑，补 code 字段）
if (body && body.code !== 200) {
  return Promise.reject(httpError(body.message, resp.status, body.code))
}
```

```js
// 错误分支（err 回调），与既有 401 处理并列：
const code = body?.code
// Spec18 §7.2：服务次数耗尽 → 清 token 回登录页 + 记下提示，
// 由 Login.vue 挂载时弹出。守卫 !url.includes('/api/auth/login') 与 401 分支同款：
// 登录接口自己被拒时，用户本来就在登录页，不该派发"被踢"事件。
if (resp?.status === 403 && code === 40304 && !url.includes('/api/auth/login')) {
  clearToken()
  setQuotaNotice(body?.message)
  window.dispatchEvent(new Event('artcn:quota_exceeded'))
}
```

blob 分支（`responseType === 'blob'` 的异步解析）里同样加这一段——作品库/社区图片的 `<img>` 渲染请求也会被中间件拦，不处理会让图片静默裂掉而没有登出。

**c. 新增 API 函数**：

```js
// Spec18 §6.2：设置某用户的累计服务限额（仅管理员）
export async function updateUserQuota(userId, quotaLimit) {
  const { data } = await http.put(`/api/admin/users/${userId}/quota`, {
    quota_limit: quotaLimit
  })
  return data.data // { id, quota_limit, used }
}
```

### 7.3 `store/auth.js`

`init()` 的 catch 目前只 `logout()`——被踢的用户会**静默**回到登录页，不知道发生了什么。补上提示：

```js
      } catch (e) {
        // Spec18 §7.3：启动时已超额（如换了设备登录、或后端在本设备停用期间被改小限额）
        if (e.code === 40304) setQuotaNotice(e.message)
        this.logout()
      } finally {
        this.loaded = true
      }
```

`login()` **不改**——限额拒绝要让 `Login.vue` 拿到错误对象才能弹窗（§7.4），在这里吞掉就弹不出来了。

### 7.4 `views/Login.vue`

```js
import { onMounted, ref } from 'vue'
import { takeQuotaNotice } from '../utils/quotaNotice'

// Spec18 §7.4：落地到登录页时，若有一条待显示的限额警告 → 红色提示行 + 弹窗。
// 用户原话要求"弹出提示警告"，所以是 window.alert（而不是只写一行小字）。
onMounted(() => {
  const msg = takeQuotaNotice()
  if (msg) {
    error.value = msg
    window.alert(msg)
  }
})
```

`submit()` 的 catch 里，被拒时同样弹窗（用户原话："每次该类超额普通用户要登录，就在登录界面拒绝掉，并弹出提示警告"）：

```js
  } catch (e) {
    error.value = e.message || '登录失败'
    if (e.code === 40304) window.alert(e.message)
  }
```

**模板不变**：`error` 已经是登录卡片里那一行 `.login-error` 红字，499 字以内的中文提示会自然换行。**不加**关闭按钮、不加"续费"链接（后端没这个页面，加一个死链更糟）。

### 7.5 `views/AdminPanel.vue`

**a. 表头加两列**（插在「角色」之后、「创建时间」之前）：

```
ID | 用户名 | 角色 | 服务总调用次数 | 服务限额 | 创建时间 | 操作
```

> 7 列会超过 `.admin-table-wrap` 的常规宽度。该容器已有 `overflow-x: auto`（`main.css:804`），**不会撑破布局**，窄屏横向滚动即可。落地后若在 1280px 下仍需滚动，优先收紧「创建时间」列（`cell-muted`，信息密度最低）。

**b. 两列的渲染**：

```html
<td class="cell-quota">
  {{ u.used }}
  <span v-if="isOverQuota(u)" class="quota-over-tag">已超额</span>
</td>
<td class="cell-quota">
  <template v-if="u.is_admin">
    <span class="cell-muted">不受限</span>
  </template>
  <template v-else>
    {{ u.quota_limit }}
    <button class="btn-mini" :disabled="busyId === u.id" @click="editQuota(u)">
      改限额
    </button>
  </template>
</td>
```

```js
// Spec18 §7.5：超额的判据与后端一致（used >= quota_limit），管理员恒不超额
function isOverQuota(u) {
  return !u.is_admin && u.used >= u.quota_limit
}

async function editQuota(u) {
  const input = window.prompt(
    `为「${u.username}」设置服务限额（累计可用次数，当前 ${u.quota_limit}）：`,
    String(u.quota_limit)
  )
  if (input === null) return                  // 取消
  const raw = input.trim()
  const n = Number(raw)
  // raw 为空必须单独拦：Number('') === 0，是个整数——不拦的话"清空输入框直接确定"
  // 会把限额静默设成 0（= 禁用该账号）
  if (!raw || !Number.isInteger(n) || n < 0) {
    error.value = '限额需为不小于 0 的整数'
    return
  }
  error.value = ''
  busyId.value = u.id
  try {
    await updateUserQuota(u.id, n)
    flash(`已将「${u.username}」的服务限额设为 ${n} 次`)
    await load()
  } catch (e) {
    error.value = e.message || '设置限额失败'
  } finally {
    busyId.value = null
  }
}
```

- `Number.isInteger` 而非 `parseInt`：`parseInt("25abc")` 会静默变成 25，静默纠正用户的输入是坏事。
- 上限（`QUOTA_LIMIT_MAX`）**不在前端校验**——它是防误输入的服务端护栏，前端复制一份就多一个会漂移的常量（CLAUDE.md 里 `COMMENT_TEXT_MAX` / `GALLERY_NOTE_MAX` 那两处同值副本是已知的技术债，不再新增第三个）。超过上限时由 `40017` 的 `message` 显示在 `error` 行。
- 管理员那一行**不给编辑入口**，显示灰字「不受限」——判定里管理员恒豁免（§2.1），给一个改了没用的输入框是骗人。
- 超额标记用新增的 `.quota-over-tag`，样式抄 `.me-tag`（`main.css:843`）的形状、换成红底。**不用**整行变红：一个用户超额不该让整行变成警告色，那会让表格看起来全是错的。

**c. `load()` / `flash()` / `busyId` 复用既有实现，不新增状态。**

### 7.6 `views/StatsPanel.vue`

**a. 类别表加第五行**：

```js
const CATEGORIES = [
  { key: 'chat', label: '对话' },
  { key: 'generate', label: '文生图' },
  { key: 'edit', label: '图文生图' },
  { key: 'qa', label: '图像QA' },
  { key: 'style', label: '风格归纳' }      // Spec18：按实际图片数计，粒度与前四类不同
]
```

`rows` 与摘要行的「调用总次数」都是 `computed` 出来的，**零额外改动**自动包含第五类。

**b. `clearUsageStats()` 的确认文案**——必须同时说清"清什么"和"不清什么"，否则管理员会以为它顺带解封：

```js
if (!window.confirm(
  '确定清空全部调用统计？对话 / 文生图 / 图文生图 / 图像QA / 风格归纳 的计数将归 0。\n' +
  '注意：这只重置统计区间，**不影响**各用户在「用户管理」页的服务限额与已用次数。\n此操作不可撤销。'
)) return
```

> `window.confirm` 里 `**` 不会渲染成粗体。落地时改用「不影响」前后的中文引号或【】标注，不要留 Markdown 语法在纯文本弹窗里。

### 7.7 `views/HelpModal.vue`

在已有条目之后加一小节（与 Spec17 §14.2 的帮助页文案改动同性质）：

> **📊 服务次数**　每个账号有一定的服务调用额度（默认 25 次，含对话、文生图、图文生图、图像 QA、风格归纳）。次数用满后需要联系管理员续费才能继续使用。管理员不受额度限制。

### 7.8 样式约定（`assets/styles/main.css`）

只新增一个类：

```css
/* Spec18：超额标记（用户管理页），形状抄 .me-tag（main.css:843） */
.quota-over-tag {
  margin-left: 6px;
  padding: 1px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  background: rgba(220, 38, 38, 0.12);
  color: #dc2626;
}
```

`.cell-quota` 直接用既有的 `.cell-muted` 的思路（`white-space: nowrap` 由 `.user-table td` 统一提供，无需新增规则）。**紫色主题的 `:root` 变量一个字不动**。

---

## 8. 配置 / 环境变量 / .gitignore

`Server/config.py` 新增一节：

```python
# ===== 服务限额（Spec18：API 服务调用计量与用户限额）=====
QUOTA_DEFAULT_LIMIT = int(os.getenv("QUOTA_DEFAULT_LIMIT", "25"))    # 新建用户的默认限额（累计次数）
QUOTA_LIMIT_MAX = int(os.getenv("QUOTA_LIMIT_MAX", "100000"))        # 管理员可设的限额上限（防误输入天文数字）
QUOTA_CONTACT_EMAIL = os.getenv("QUOTA_CONTACT_EMAIL", "frostyj@qq.com").strip()
# 超额提示语（唯一来源；前端只负责显示后端返回的 message，不做同值副本）
QUOTA_EXCEEDED_MESSAGE = (
    f"您的服务次数已达上限，请联系管理员续费可继续使用！（管理员邮箱：{QUOTA_CONTACT_EMAIL}）"
)
```

`Server/.env.example` 追加：

```dotenv
# ---- 服务限额（Spec18，均可留空用默认值）----
# QUOTA_DEFAULT_LIMIT=25          # 新建用户的默认限额（累计次数）
# QUOTA_LIMIT_MAX=100000          # 管理员可设的限额上限
# QUOTA_CONTACT_EMAIL=frostyj@qq.com   # 超额提示里显示的续费联系邮箱
```

> **注意 `QUOTA_DEFAULT_LIMIT` 的作用域**：它只在**新建用户**与**补列迁移给存量行填初值**两处生效。改它**不会**影响任何已存在的用户（§3.3-5）。这行注释必须写进 `.env.example`，否则会有人以为改这里能一键给所有人加额度。
>
> **提示语不要在前端复制一份**：`COMMENT_TEXT_MAX`（Spec17）与 `GALLERY_NOTE_MAX`（Spec16）的同值副本是既有的技术债；本 Spec 的提示语**经后端 `message` 字段原样回传**，前端零副本。

`.gitignore` **不变**（没有新增任何需要忽略的路径或文件）。

---

## 9. 错误码

新增 2 个，追加到 Spec17 §9 的 `CommentNotFoundError` 之后：

```python
# ---- 服务限额（Spec18 §9，追加到 Spec17 §9 之后）----

class QuotaExceededError(AppError):
    """普通用户的服务调用次数已达限额（登录被拒 / 已在系统里被踢出）。

    HTTP 403 而非 401：登录态本身是有效的，只是无权继续使用。用 401 会被前端
    既有的"401 → 清 token"分支当成 token 失效处理——结果碰巧一样，但语义错，
    且会让日志里分不清"登录态坏了"和"额度用完了"。

    提示语来自 config.QUOTA_EXCEEDED_MESSAGE（唯一来源，前端零副本）。
    """

    def __init__(self, message: str | None = None):
        super().__init__(40304, message or config.QUOTA_EXCEEDED_MESSAGE, status_code=403)


class QuotaLimitError(BadRequestError):
    """管理员设置的限额非法（负数，或超过 QUOTA_LIMIT_MAX）。"""

    def __init__(self, message: str | None = None):
        super().__init__(
            message or f"服务限额需为 0~{config.QUOTA_LIMIT_MAX} 之间的整数",
            code=40017,
        )
```

`errors.py` 需新增 `import config`。检查过：`config.py` 只 import `os` / `pathlib` / `dotenv`，**不 import `errors`**，无循环依赖。

**复用不新增**：

| 场景 | 复用 | 理由 |
|---|---|---|
| `PUT .../quota` 的 `quota_limit` 不是整数 | `40001 BadRequestError`（FastAPI 请求体校验） | Pydantic 的 `int` 类型校验已经在中间件之前拦掉，不需要业务层再判一次 |
| `PUT .../quota` 的 `{user_id}` 不存在 | `40402 UserNotFoundError` | 与 `PUT .../password`、`PUT .../admin` 的既有口径完全一致 |
| 管理员访问 `/api/admin/*` | `40301 ForbiddenError` | 不变（限额判定排在它之前，管理员恒豁免） |

**错误码全表（Spec18 后，只列 4xx）**：

| 码 | 类 | HTTP | 场景 |
|---|---|---|---|
| 40001 | `BadRequestError` | 400 | 通用参数非法（含 `quota_limit` 非整数） |
| 40011 | `PostContentError` | 400 | 帖子内容非法（Spec17） |
| 40015 | `GalleryNoteError` | 400 | 作品备注非法（Spec16） |
| 40016 | `CommentContentError` | 400 | 评论空/超长（Spec17） |
| **40017** | **`QuotaLimitError`** | **400** | **限额为负或超上限** |
| 40102 | `LoginFailedError` | 401 | 用户名或密码错误 |
| 40103 | `AuthTokenError` | 401 | 登录态缺失/无效/过期 |
| 40301 | `ForbiddenError` | 403 | 非管理员访问 `/api/admin/*` |
| 40302 | `PostForbiddenError` | 403 | 删他人帖子（Spec9） |
| 40303 | `CommentForbiddenError` | 403 | 删他人评论（Spec17） |
| **40304** | **`QuotaExceededError`** | **403** | **服务次数已达上限（登录被拒 / 请求被踢）** |
| 40402 | `UserNotFoundError` | 404 | 用户不存在 |
| 40403 | `GalleryItemNotFoundError` | 404 | 作品不存在/非本人 |
| 40404 | `PostNotFoundError` | 404 | 帖子不存在 |
| 40405 | `ShareNotFoundError` | 404 | 分享失效（Spec9） |
| 40406 | `SuggestionNotFoundError` | 404 | 建议不存在（Spec9） |
| 40407 | `ConversationNotFoundError` | 404 | 对话不存在/非本人（Spec17） |
| 40408 | `CommentNotFoundError` | 404 | 评论不存在（Spec17） |
| 42901 | `LoginRateLimitedError` | 429 | 登录过于频繁 |

---

## 10. 日志约定

沿用 Spec §10 的单行 JSON，新增 2 个事件：

| event | 触发 | 附带字段 |
|---|---|---|
| `auth.quota_blocked` | 中间件拦下超额请求 **或** 登录接口拒绝超额用户 | `username`, `used`, `quota_limit`；中间件路径额外带 `path` / `request_id` |
| `auth.admin.set_quota` | 管理员设置某用户限额成功 | `username`（操作者）, `target_user`, `quota_limit` |

沿用不改的：

| event | 说明 |
|---|---|
| `usage.cleared` | Spec11 既有，只改 `cleared` 的求和口径（四类 → 五类） |
| `db.migrate` | Spec12/16/17 既有，本 Spec 的两次补列迁移 + 一次回填都复用这个 event 名 |
| `wiki.style_updated` / `wiki.refresh_skipped` | Spec12/15 既有，**不新增**计数相关的字段。用了多少次由 `user_quota` 的增量体现，日志里再记一遍是冗余 |

**不新增**每次 `record_call` 的日志——那会让每个任务多打一行，而它每天都发生。要看某个用户用了多少，看用户管理页；要看全局趋势，看数据统计页。

**隐私**：`auth.quota_blocked` 只记 `username` / 数字，不含任何消息正文（与 Spec16/17 对用户文字的处理一致）。

---

## 11. 目录结构增量

```
frontend/src/
  utils/
    quotaNotice.js          ← 新增（Spec18 §7.1）
```

后端**无新增文件**（`db.py` / `errors.py` / `config.py` / `main.py` / `wiki.py` / `schemas.py` 原地改）。数据库**无新增文件**（仍是 `Server/artcn.db` 一个，新表进同一个库）。**无新增目录。**

---

## 12. 实施顺序（里程碑）

依赖关系决定顺序，**每一步都能独立跑起来**：

1. **M1 — 数据层地基**
   `config.py`（3 个环境变量 + `QUOTA_EXCEEDED_MESSAGE`）；`db.py` 的 `user_quota` 建表 + `_migrate_users_quota_limit` + `_migrate_usage_style` + `_backfill_user_quota` + `QUOTA_BACKFILLED_KEY` + `_USER_SELECT` + `_row_to_dict(with_secret)` + `record_call` 双写 + `get_usage_stats`/`clear_usage` 覆盖第五类 + `delete_user` 级联。
   **验证**（§13 #1~#6）：`.schema` 三处变化；重启两次不重复回填；`record_call` 后两个数一致。

2. **M2 — 后端判定**
   `errors.py`（`QuotaExceededError` / `QuotaLimitError`）；`main.py` 中间件 + 登录 + `GET /api/admin/users` 少一个字段多两个字段 + `PUT .../quota` 路由；`schemas.py` 的 `AdminSetQuotaRequest`。
   **验证**（§13 #7~#20，纯 curl，前端还没改）：新用户默认 25；用满即锁；管理员豁免；改限额立刻生效；撤销管理员立刻受限；`password_hash` 不再出现。

3. **M3 — 风格归纳计数**
   `wiki.py` 的两处 `db.record_call(user_id, "style")` 埋点。
   **验证**（§13 #21~#27）：3 张新上传图 → `+4`；`nothing_new` → `+0`；整次失败 → `+N`；图被删 → 不计。

4. **M4 — 前端**
   `utils/quotaNotice.js` + `api/chatApi.js`（`code` 字段、40304 分支、`updateUserQuota`）+ `store/auth.js` + `App.vue`（`artcn:quota_exceeded` 监听）+ `views/Login.vue` + `views/AdminPanel.vue` + `views/StatsPanel.vue` + `views/HelpModal.vue` + `main.css` 的 `.quota-over-tag`。
   **验证**（§13 #28~#38）。

5. **M5 — 收尾**
   `.env.example`；`CLAUDE.md` 同步（见下）。
   **验证**（§13「回归」#39~#46）。

**`CLAUDE.md` 需要同步的段落**（Spec18 落地后）：

- 「Project Overview」的硬约束例外条款：`Server/artcn.db` 现在承载的清单末尾补「**服务调用计量与限额**（`user_quota`）」。
- 「Backend」小节：`db.py` 的表清单加 `user_quota`；`record_call` 一句改为「双写 `usage`（区间统计）+ `user_quota`（计费账户）」；`main.py` 的说明里补「鉴权中间件顺带判服务限额（40304）」。
- 「Configuration」：新增 `QUOTA_DEFAULT_LIMIT` / `QUOTA_LIMIT_MAX` / `QUOTA_CONTACT_EMAIL` 三个变量，并**必须**带上"`QUOTA_DEFAULT_LIMIT` 只影响新建用户"这句。
- 「Important notes / gotchas」补三条：
  1. **`usage` 与 `user_quota` 是两个口径**：前者可被「清空调用统计」清零（区间统计），后者只增不减（计费），清零后两者不再相等——这是有意的。
  2. **`record_call` 必须一次事务写两张表**，不要拆开调用。
  3. **风格归纳的计数埋点在 `await` 之前**（调用发出即记账），与四类任务的"成功才计"不同，别顺手改成成功后才记。

---

## 13. 验收用例（端到端 Smoke）

### 数据层（M1）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 升级已有 `artcn.db` 后启动 | `sqlite3 Server/artcn.db ".schema user_quota"` 有表；`.schema users` 含 `quota_limit INTEGER NOT NULL DEFAULT 25`；`.schema usage` 含 `style` |
| 2 | 再启动一次 | 不重复 ALTER、不回填（`user_quota` 行数不变；日志无第二条 `db.migrate` 回填记录） |
| 3 | 查 `app_meta` | 有 `quota_backfilled_at` 键 |
| 4 | 存量用户回填 | 某用户 `usage` 四列和 = 100 → `user_quota.used = 100`，且 `users.quota_limit = 25` |
| 5 | 一个全新库（删掉 artcn.db 重启） | 表结构齐全、`user_quota` 为空、无非预期回填 |
| 6 | 未清零时对比 | 对每个用户：`user_quota.used` == `usage` 五列之和 |

### 后端判定（M2）

| # | 操作 | 期望 |
|---|---|---|
| 7 | 管理员新建用户 bob | `GET /api/admin/users` 里 bob 的 `quota_limit = 25`、`used = 0` |
| 8 | 该响应体 | **不含** `password_hash` 字段 |
| 9 | bob 正常用到第 25 次 | `used = 25`；第 25 次任务**正常返回结果** |
| 10 | bob 第 26 次任意 `/api/*` 请求 | HTTP 403 + `code 40304` + 完整提示语（含邮箱）；日志 `auth.quota_blocked`（带 `path`） |
| 11 | bob 再登录 | HTTP 403 + `40304`，**不返回 token**；日志 `auth.quota_blocked` |
| 12 | 管理员 `PUT .../users/{bob}/quota` body `{"quota_limit": 30}` | 200，返回 `{id, quota_limit:30, used:25}` |
| 13 | bob 立刻重新登录 | 成功（无需重启后端、无需管理员重新登录） |
| 14 | 管理员自己用到 100 次 | 一切正常；`used` 照常展示为 100 |
| 15 | 管理员 A 撤销管理员 B（B 的 `used = 300`） | B 的下一个请求立即 `40304`；B 重新登录被拒 |
| 16 | `PUT .../quota` 传 `{"quota_limit": -1}` | `40017` |
| 17 | `PUT .../quota` 传 `{"quota_limit": 999999}` | `40017` |
| 18 | `PUT .../quota` 传不存在的 user_id | `40402` |
| 19 | `PUT .../quota` 传 `{"quota_limit": "abc"}` | `40001` |
| 20 | 普通用户调 `PUT .../quota` | `40301` |

### 风格归纳计数（M3）

| # | 操作 | 期望 |
|---|---|---|
| 21 | 直传 3 张新图，点「更新风格」且成功 | `used` +4（3 视觉 + 1 文本）；`usage.style` +4 |
| 22 | 不传新图再点一次 | `used` 不变（`nothing_new`） |
| 23 | 3 张图中 2 张分析失败、至少 1 张成功 | `used` +4（3 视觉仍全发 + 1 文本） |
| 24 | 3 张图**全部**分析失败 | `used` +3（无文本调用）；返回 `reason = "analysis_failed"` |
| 25 | 上游抛 `UpstreamApiError` 的整次失败 | 已发出的调用**照常计入**；wiki 与 `images.wiki_used` 保持原样 |
| 26 | 上传作品在点按钮前被删掉 | 该张**不**计入（`read_gallery_file` 在记账之前抛出） |
| 27 | 一次上传 15 张（超过 `WIKI_UPLOAD_QA_MAX = 10`） | 本次最多 +11（10 视觉 + 1 文本） |

### 前端（M4）

| # | 操作 | 期望 |
|---|---|---|
| 28 | 登录页：超额账号输入正确密码 | 红字提示行 + `window.alert` 弹出完整提示语；停留在登录页。**不**重复清 token、**不**派发 `artcn:quota_exceeded`（用户本来就在登录页，§7.2b 的守卫） |
| 29 | 用户管理页 | 7 列，新增「服务总调用次数」「服务限额」；bob 显示 `25 / 25` + 红色「已超额」标签 |
| 30 | 点 bob 那行的「改限额」→ 输入 30 | 提示"已将「bob」的服务限额设为 30 次"；列表刷新后 bob 显示 `25 / 30`，超额标签消失 |
| 31 | 点管理员那一行的限额列 | 灰字「不受限」，**没有**编辑按钮 |
| 32 | 「改限额」输入 `abc` / `-1` / 空串 | 红字"限额需为不小于 0 的整数"，不发请求 |
| 33 | 「改限额」点取消 | 无任何变化 |
| 34 | 已用 24 次的用户在页面里发第 25 条消息 | 任务成功、`used` 变 25；约 1.5s 内下一次轮询收到 40304 → 清 token → 回到登录页 → `window.alert` 弹出提示 |
| 35 | 承上，去「我的作品」找那一轮生成的图 | **图在**（§3.3-1：入库先于计费） |
| 36 | 数据统计页 | 类别表 5 行，末行为「风格归纳」；摘要「调用总次数」含它；「清空调用统计」的 confirm 文案写明不影响限额 |
| 37 | 点「清空调用统计」并确认 | `usage` 归零、统计页五项全 0；**用户管理页的 `used` 不变**、超额用户仍被锁（§2.2） |
| 38 | 帮助页 | 有「服务次数」一节，写明默认 25 次与管理员不受限 |

### 回归（Spec18 不应破坏的既有行为）

| # | 操作 | 期望 |
|---|---|---|
| 39 | 普通用户走完一轮对话 / 文生图 / 图文生图 / 图像QA | 四类计数照常 +1（`usage` 与 `user_quota` 同步涨） |
| 40 | 故意让一个任务失败（拔掉 provider key） | 四类**不**计数；`used` 不变；任务标 FAILED |
| 41 | 队列满（`50301`） | 不计数 |
| 42 | 重置密码 / 设为管理员 / 删除用户 | 全部照常；删除用户后 `user_quota` 无残留行 |
| 43 | `GET /api/admin/stats` | 前端两处读取（`totals[key]` / `per_user_avg[key]` / `shares[key]`）不报错，第五类正常显示 |
| 44 | 作品库 / 社区 / 分享链接 / 建议箱 / 对话历史 | 全部照常，无 40304 误伤 |
| 45 | 分享页 `/share/{token}`（免登录） | 照常可访问——它不在 `/api/*` 下，天然不被中间件拦 |
| 46 | 普通用户浏览作品库图片（blob 请求） | 照常渲染；超额时应触发登出而不是静默裂图（§7.2） |

---

## 14. 补充

### 14.1 与 Spec11「清空调用统计」的关系（一句话）

Spec11 的清零从此**只重置统计区间，不再有任何计费含义**。这是本 Spec 引入 `user_quota` 的直接原因（§2.2），也是 `StatsPanel.vue` 确认文案必须改写的原因（§7.6b）。若将来有人觉得"用户管理页的数和数据统计页对不上"，先读这一条。

### 14.2 为什么不给「剩余次数」做 UI

用户的诉求是"管理员能看、能改、能锁"，不是"让用户自己数着用"。后者的产品含义完全不同（会引入"省着用"的行为、需要"剩余不足"的预警、需要解释"为什么这次没扣"），是另一个 Spec 的规模。见 §3.2。
