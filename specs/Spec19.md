# ArtiControlNet Spec 19：品牌 LOGO 上线、注册申请与审批、README 官网入口

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：三件事 ——
> **(1) LOGO 上线**：把新做的 ACN 标识（去掉浅紫底、做透明）贴到登录卡片顶部与 README 标题上方；
> **(2) 注册申请与审批**：登录页底部开一个「新用户注册」入口，但**注册不是自助开号，而是一条"申请 → 审批"链**——
> 用户填表（账号/密码/手机号或邮箱/付款备注）+ 当场扫码预充值 → 落进新表 `register_requests` →
> 管理员在「用户管理」页逐条**同意 / 拒绝 / 删除**，**只有同意时才真正在 `users` 表建号**，并顺手把限额设好；
> **(3) README 官网入口**：加一条比购买按钮更醒目的「官方网址 ArtiControlNet.fun」横条，购买按钮改为直达官网注册页。
> 本 Spec 是 **Spec.md / Spec2~18 的增量补充**，不推翻原有架构。数据库变化：**新增 1 张表**（`register_requests`），
> **无补列迁移、无存量回填**（这是一张全新的空表，`CREATE TABLE IF NOT EXISTS` 即可，不需要 Spec18 那种"判据式回填"）。
> **无新依赖、无新持久目录**；新增 **3 个环境变量**（均有默认值）+ **1 条 .gitignore**（收款码不进仓库）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 `artcn.db` 外无其他数据库。
> **不新增 provider、不新增模型、不改任何一个上游调用链。**

---

## 1. 功能目的

### 1.1 为什么现在做

- **品牌要露脸。** 系统已经能对外给设计专业的学生用了，但登录卡片上只有一个紫色小圆点 + 一行文字，README 首屏也没有标识。新做的 ACN 标识（紫色立体 A + 轨道环 + ACN 字）是现在唯一的视觉资产，两处都该贴上。
- **"想用"的人没有落点。** 现在的账号只能由管理员在后台一个个手建（Spec2），README 上留的是"发邮件给我"。结果是：每来一个人都要走一轮"发邮件 → 我回复 → 我建号 → 我发密码"，且**没有任何机制保证对方先付了钱**。Spec18 已经把"计费"做成了 `users.quota_limit` 这个可编辑的数字，缺的只是一条**从"想用"到"有号"的通道**。
- **"先付款再开号"需要一个能对账的凭据。** 收款码扫过去是一笔匿名的微信转账，到账通知里只有一个昵称。所以申请表必须收一个**付款用的微信昵称**，管理员才能把「这笔钱」和「这条申请」对上——这不是多余字段，它是整条链路的对账键。
- **官网域名有了。** `ArtiControlNet.fun` 已经可用，README 上却没有一个能点的正式入口，读者只知道 GitHub 仓库。

### 1.2 三件事

1. **LOGO 上线**：登录卡片顶部一枚透明底标识；README 标题上方同一个标识。
2. **注册申请与审批**：登录页「新用户注册」→ 弹窗填表 + 扫码预付 → 管理员「用户管理」页逐条审批 → 同意即建号（带限额）。
3. **README 官网入口**：一条醒目横条 + 购买按钮改指向官网注册页 + 两处文案微调。

### 1.3 注册链路的口径（这是本 Spec 最容易理解错的地方）

**注册申请不是"注册"，它不创建任何用户。** 整条链路只有两个写操作：

| 时刻 | 写什么 | 谁触发 |
|---|---|---|
| 用户点「提交申请」 | `register_requests` **插入一行**（`status='pending'`） | 匿名访客（无需登录态） |
| 管理员点「同意」 | **同一事务**：`users` 插入一行 + `register_requests` 那行改 `status='approved'` | 管理员 |

也就是说：**申请阶段不碰 `users` 表**，"账号已存在"这类判断在申请时只是**提前告知**，真正的唯一性约束仍然由 `users.username` 的 UNIQUE 索引在**同意那一刻**兜底（§3.3-2）。

三个动作的语义（用户原话，逐字落实）：

| 动作 | 效果 | 记录还在吗 | 按钮之后怎么显示 |
|---|---|---|---|
| **同意** | 建号（用申请里的用户名 + 密码哈希 + 管理员当次填的限额） | **在**，`status='approved'` | 「已同意」纯文字 |
| **拒绝** | 什么都不建 | **在**，`status='rejected'` | 「已拒绝」纯文字 |
| **删除** | 只删这一行记录 | **不在** | 条目消失 |

> 「同意 / 拒绝 都不自动删除申请记录」是用户明确要求的行为：处理过的记录**留下来当台账**，要清理得手动点「删除」。

---

## 2. 决策记录（为什么这么选）

### 2.1 为什么是"申请-审批"而不是"自助注册"

| 决策 | 选择 | 理由 |
|---|---|---|
| 注册要不要即时开号 | **不即时**。申请落库、人工审批后才建号 | 系统按次计费（Spec18），而付费走的是**微信个人收款码**——没有任何自动对账的接口。即时开号等于"先给货后收钱"，且无法验证对方到底付没付 |
| 申请时收哪些信息 | 账号 / 密码 / 手机号或邮箱 / **付款用的微信昵称** | 前四项是建号与联系所需；**微信昵称是唯一的对账键**（到账通知里只有它）。见 §1.1 |
| 手机号与邮箱的关系 | **二选一必填**，两个都填也允许 | 用户原话"手机号 or 邮箱"。两个都填不是错误，是更完整的联系方式，没有理由拒绝 |
| 手机号为什么限 11 位 | 纯数字 + 长度 11 | 用户要求"查验是否纯数字"。只查纯数字的话 `1` 也能过——一个联系不上的申请等于废记录。11 位是中国大陆手机号的定长，是最省事又不误伤的下限 |
| 邮箱为什么只查 `@` | 含 `@`，且 `@` 前后都非空 | 用户原话。**刻意不引入正则/`email-validator`**：校验强度提升有限，却多一个依赖与一套要维护的规则；真正的验证手段是**审批时人工联系** |
| 密码什么时候哈希 | **提交申请时就 bcrypt**，库里全程没有明文 | 与 Spec2 的账号库同款处理。明文密码在"申请"这张表里躺到管理员点同意为止（可能是几小时），这个窗口没有理由存在 |
| 同意后还留着密码哈希吗 | **不留**：同一事务里把该行的 `password_hash` 置为空串 | 哈希已经在 `users` 里了（事务内同步写入），台账表里再留一份是**同一个秘密的第二份副本**，没有任何用途。置空而不是删列，是因为 `NOT NULL` 约束仍在（§5.1a） |
| 管理员点同意时要不要设限额 | **要**，弹输入框（默认值 = `QUOTA_DEFAULT_LIMIT`） | 弹窗里写着「1 元约 10 次」，管理员按实收金额填（收 1 元 → 填 10）才算把"预付"落到了账上。与隔壁「改限额」同款 `window.prompt`，不改交互习惯（§2.4） |

### 2.2 防重复的口径：同一个 IP，24 小时一次

用户给了两句不同的话：「一个台机子只能申请注册一个账号」与弹窗文案「每人每天只能申请一个账号」。**以后者为准**（它是要写给用户看的，必须与真实行为一致），落地为：

| 决策 | 选择 | 理由 |
|---|---|---|
| 判据是什么 | **IP**（`auth.client_ip`，经 cloudflared / 反代时读 `X-Forwarded-For` 首个 IP） | 系统没有设备指纹，也不该有（那是另一个量级的复杂度）。IP 是后端**已经**在用的东西（登录限速就是按 IP），复用零成本 |
| 窗口多长 | **24 小时（滚动窗口）**，不是自然日 | "每天一次"的两种实现里，滚动窗口不需要引入时区/跨零点重置的逻辑，也不会出现"23:59 申请完，00:01 又能申请"的漏洞 |
| 冷却期从什么时刻算 | 该 IP **最近一条申请记录的 `created_at`** | 只有**成功落库**的提交才占用配额。这一点是刻意的（见下条） |
| 校验为什么不放在最前面 | **格式校验全部排在 IP 冷却判定之前** | 若先查 IP，一个手滑把手机号打成 10 位的用户会被直接锁 24 小时——为一次笔误付出的代价过大。顺序：格式 → 用户名占用 → IP 冷却（§6.2 的完整表） |
| 被拒绝的申请占不占配额 | **占** | 记录还在库里，就还是"这台机子今天申请过了"。这也与弹窗文案「若操作失误或其他需求请联系在线客服」一致——**误操作的出路是找客服，不是立刻重试** |
| 删掉记录能解封吗 | **能**（这是一条有意的逃生通道） | 管理员点「删除」= 那行记录没了 = 该 IP 的冷却期立刻结束。所以"用户手滑了，客服让他重填"这个真实场景是有解的：管理员删掉那条废申请即可 |
| 要不要把 IP 展示给管理员 | **不展示**，也不出现在任何接口响应里 | 用户要看的三个字段里没有它，它对"批准谁"这个决策也没有帮助。存下来只为判重，属于最小必要留存 |

### 2.3 LOGO 的处理

| 决策 | 选择 | 理由 |
|---|---|---|
| 底图怎么处理 | **删掉铺满画布的那条浅紫矩形**（`#F5EFFC`），保留图形本体 | 登录卡片是深紫底（`--bg-surface: #1e1533`），原图贴上去是一个刺眼的亮方块。透明之后图形本色（紫→浅紫渐变）在深底上直接成立；README 的浅色/深色主题下同样成立 |
| 用 SVG 还是 PNG | **SVG**（20 KB vs PNG 的 1.1 MB） | 同一枚标识要在弱网下被 README 与登录页各拉一次。矢量在任何缩放下都清晰，且体积小两个数量级 |
| 母版动不动 | **不动** `GithubPage/LOGO.svg`（带底色的原始稿），另存两份透明版 | 原始稿是设计资产，删了就没了。透明版是"为上线改的副本" |
| 为什么要两份透明版 | `frontend/src/assets/logo.svg`（打包进 dist）+ `GithubPage/assets/logo.svg`（README 相对路径引用） | 前端必须从 `src/` 里 import 才会被 Vite 打进产物；README 的图片引用走仓库相对路径（与 `btn-buy.png` 等既有资产同一条链路）。两者**内容完全相同**，是 Spec 里少见的"同值副本"之一（另一个是 `COMMENT_TEXT_MAX`），改动时必须一起改 |
| 登录卡片上会不会重复 | **不重复**：标识 + 原有「● ArtiControlNet」标题都留 | 标识里只有图形与「ACN」三个字母，没有全称；标题提供全称，两者互补 |

### 2.4 管理端的三个交互决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 「待审批注册用户」区块放哪 | 放在**用户表格之后**（页面底部） | 用户原话"用户管理下面新增一个待审批注册用户"。代价是管理员要滚过用户表才看得到，因此配套：把待审批条数写进页面顶部那行提示（`.admin-tip`），一眼可见。**若实际用起来嫌远，把它挪到表格之前是一次五行的移动**（已记在 §14.3） |
| 同意时怎么设限额 | `window.prompt`，默认值 `String(QUOTA_DEFAULT_LIMIT)`，与隔壁「改限额」逐字同款 | `AdminPanel.vue` 现有的编辑动作（重置密码、改限额）都是 `window.prompt`。为这个动作单独造一个行内编辑组件，会在这个 256 行的文件里引入**唯一一套**编辑态/校验/回滚逻辑。一致性 > 体验微优化 |
| 同意时的限额能不能留空 | **不能**，必须是 `0 ~ QUOTA_LIMIT_MAX` 的整数 | 留空会引出"留空 = 用默认值"的隐藏分支。管理员不想设就照默认值直接确定，两步变一步而已 |
| 三个按钮的禁用态 | 只有 `pending` 的行显示三个按钮；`approved` / `rejected` 的行**只显示一行纯文字**，且**没有删除按钮吗？——有** | 已处理的记录仍要能被清理，否则台账只进不出。所以：已处理行 = 「已同意」/「已拒绝」纯文字 + 「删除」按钮 |

---

## 3. 需求边界

### 3.1 范围内

- `db.py`：新增 `register_requests` 表 + 2 个索引 + `_register_row_to_dict` + 6 个函数（§5.1d）。
- `errors.py`：新增 5 个错误类（§9）。
- `config.py`：新增 `SUPPORT_EMAIL` / `REGISTER_ENABLED` / `REGISTER_IP_WINDOW_SECONDS` + 两句提示语 + `PAYMENT_QR_PATH`；`QUOTA_CONTACT_EMAIL` 的默认值改为跟随 `SUPPORT_EMAIL`（§8）。
- `schemas.py`：`RegisterRequestCreate` / `RegisterApproveRequest`。
- `main.py`：`PUBLIC_AUTH_PATHS` 加 2 条；新增 6 个路由（3 公开 + 3 管理端）。
- 前端：`assets/logo.svg`（新增）、`views/Login.vue`、`views/RegisterModal.vue`（新增）、`views/AdminPanel.vue`、`api/chatApi.js`、`assets/styles/main.css`。
- 资产：`GithubPage/assets/logo.svg`（新增）、`GithubPage/assets/site-banner.svg`（新增）。
- `README.md`：LOGO + 官网横条 + 购买按钮链接 + 两处文案。
- `.gitignore`、`.env.example`、`CLAUDE.md` 同步。

### 3.2 不在范围内（明确不做）

- **不做自助注册**：申请通过后账号才存在。任何"提交即登录""自动开通试用"的形态都不在本 Spec。
- **不做任何在线支付集成**：不接微信支付 API、不做对账自动化。收款码是一张静态图，对账靠管理员人眼比对「微信昵称」。
- **不做审批通知**：同意/拒绝之后不自动发邮件/短信。用户原话已经给了答案——「注册成功会联系到您」，联系是**人工的**（管理员照手机号/邮箱去联系）。
- **不做"申请状态查询"**：申请人不登录，也没有身份，无法查询自己的申请进度。提示语里给的是客服邮箱。
- **不做拒绝理由**：`register_requests` 没有 `reason` 列。拒绝就是拒绝，要解释走客服邮箱。
- **不做申请记录的分页/筛选**：`GET /api/admin/register-requests` 一次返回全部（与 `list_all_suggestions` 同款）。量级由 IP 冷却天然限制（每台设备每天最多 1 条）。
- **不改 `users` 表结构**：`register_requests` 不往 `users` 加列（Spec18 §2.2 的同一理由：`users` 是纯粹的账号表）。"这个人是从申请来的"不单独记录——台账表本身就是记录。
- **不做 LOGO 的其它落点**：App 头部、帮助弹窗、favicon 一概不动（favicon 是既有的紫色 `favicon.svg`）。
- **不改 Spec18 的限额逻辑一个字**：审批时设的限额走的就是既有的 `users.quota_limit` 列，判定仍在鉴权中间件与登录接口（Spec18 §6.3/§6.4）。

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **IP 冷却会误伤"同一台电脑的两个人"。** 宿舍共用一台电脑、或同一个校园网出口 NAT，第二个人的申请会被 40902 拒掉。这是"每台设备每天一次"的必然代价，出路是联系客服（管理员删掉前一条废申请即可放行，见 §2.2）。
2. **申请期间用户名可能被抢走。** 用户 A 申请 `zhangsan`（pending），同一时间管理员在后台手建了 `zhangsan`。A 的申请被同意时会撞 `users.username` 的 UNIQUE → `40901`「用户名已被占用」，记录**停在 pending**（不能静默改成 rejected——那是在替管理员做决定）。管理员看到报错后的处置：联系申请人换个名字（删掉这条重建），或手动建号后把它标记为拒绝。
3. **申请里的密码在同意之前一直是"活的"。** 换名重建意味着密码也要重填（哈希无法复用给另一个用户名？——其实可以，但**不提供这个功能**：让用户重填一次比给管理员一个"搬密码"的口子简单得多）。
4. **已同意/已拒绝的记录不会自动消失。** 台账只进不出，长期会积累。清理方式是「删除」。**删除某条已同意的记录不会删除它建出来的用户**——用户是 `users` 表的资源，申请记录是另一件事（§5.3）。
5. **申请人的密码哈希在被拒绝后会一直留在库里。** 拒绝路径不置空（这条申请从未被使用）。要彻底清掉只能删掉那条记录。这是"保留完整台账"与"最小化秘密留存"之间的取舍，选择前者——被拒绝的记录里那个密码**从来没有生效过**。
6. **收款码是公开可访问的静态资源。** `GET /api/auth/payment-qr` 无登录态（因为注册弹窗在登录之前）。也就是说任何知道地址的人都能取到这张图。这是"未登录用户必须能扫码付款"的直接后果，**收款码本身就是拿来给人扫的**，不构成新的暴露面。
7. **`REGISTER_ENABLED=false` 时前端会隐藏注册入口。** 深链接 `?register=1` 也随之失效（弹窗不打开）。此时 `/api/auth/register` 返回 `40305`——两层都拦，前端那层只是体验。
8. **README 的「购买」按钮不再发邮件了。** 它现在直达官网注册页。发邮件的路径仍在（下面那行「如果想试用 ArtiControlNet，请发邮件到 …」与 Issue 链接都没动）。

---

## 4. 技术栈增量

**无。** 零新依赖、零新 provider、零新模型、零新持久目录、零新前端库。收款码用的是既有的 `Server/` 目录与 FastAPI 的 `Response`（与 `GET /share/{token}/image` 同一条链路）。

配置里新增 3 个环境变量（都有默认值，都可以不配）。

---

## 5. 架构设计（增量）

### 5.1 数据变更

#### a. 新表 `register_requests`（Spec19）

`db.py` 顶层新增常量，`init_db()` 的建表清单里加两行（表 + 索引）：

```python
# 注册申请（Spec19 §5.1a）：一行 = 一条待处理/已处理的注册申请。
# **不是用户表**：申请阶段不创建任何 users 行，同意时才在同一事务里建号（§1.3）。
# 刻意**没有** UNIQUE(username)：同一用户名允许多条被拒绝的历史记录，
# 唯一性由 users.username 的 UNIQUE 在同意那一刻兜底（§3.3-2）。
# ip 列是防重复的唯一判据（§2.2），不对外暴露（接口响应里没有它）。
_CREATE_REGISTER_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS register_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,             -- 申请的用户名（同意时原样建号）
    password_hash TEXT NOT NULL,             -- bcrypt；同意后置为 ''（§2.1）
    phone         TEXT,                      -- 手机号（纯数字 11 位）；与 email 至少有一个
    email         TEXT,                      -- 邮箱；与 phone 至少有一个
    wechat        TEXT NOT NULL,             -- 用于支付的微信昵称（管理员对账用）
    ip            TEXT NOT NULL,             -- 提交来源 IP（防重复判据，不出接口）
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at    TEXT NOT NULL,             -- 提交时刻（UTC ISO）
    reviewed_at   TEXT                       -- 同意/拒绝的时刻（NULL = 尚未处理）
)
"""

# 冷却期查询走这条索引：WHERE ip = ? AND created_at >= ? ORDER BY id DESC
_CREATE_REGISTER_REQUESTS_IP_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_register_requests_ip "
    "ON register_requests(ip, created_at DESC, id DESC)"
)

# 列表查询走这条：pending 优先 + 组内 id 倒序（§6.4）
_CREATE_REGISTER_REQUESTS_STATUS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_register_requests_status "
    "ON register_requests(status, id DESC)"
)
```

`init_db()` 里加在建表清单中（放在 `_CREATE_POST_COMMENTS_*` 之后，与其它 `CREATE TABLE IF NOT EXISTS` 同段）：

```python
        conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)
        conn.execute(_CREATE_REGISTER_REQUESTS_IP_INDEX)
        conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)
```

> **不需要迁移函数。** 这是一张全新的空表，`CREATE TABLE IF NOT EXISTS` 对新库与存量库行为一致。Spec18 的 `_backfill_user_quota` 之所以要"判据式回填"，是因为它要给**已存在的数据**补一份派生账本；这里没有已存在的数据。

#### b. 状态白名单

```python
# 申请状态白名单（approve / reject 校验，不拼接外部输入）
_REGISTER_STATUSES = ("pending", "approved", "rejected")
```

#### c. 行 → dict

与 `_row_to_dict` 的既有约定同款：**默认不外泄密码哈希**。

```python
def _register_row_to_dict(row: sqlite3.Row | None, *, with_secret: bool = False) -> dict | None:
    """申请行 → dict（Spec19 §5.1c）。

    与 _row_to_dict（users）同样的约定：**默认不带出 `password_hash`**。
    它只有一处真正需要——同意时把哈希写进新建的 users 行（批准路径），
    因此 `with_secret=True` 全仓只出现在 `approve_register_request` 与
    批准路由的预检两处。列表接口（GET /api/admin/register-requests）
    拿到的字典在结构上就不可能有这个键。

    另外**不带出 `ip`**：它只服务于冷却期判定，接口层没有它的位置（§2.2）。
    """
    if row is None:
        return None
    record = {
        "id": row["id"],
        "username": row["username"],
        "phone": row["phone"],
        "email": row["email"],
        "wechat": row["wechat"],
        "status": row["status"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }
    if with_secret:
        record["password_hash"] = row["password_hash"]
    return record
```

#### d. 6 个 db 函数

```python
# ---------- 注册申请与审批（Spec19 §5.1d）----------

def create_register_request(username: str, password_hash: str, phone: str | None,
                            email: str | None, wechat: str, ip: str) -> dict:
    """插入一条 pending 申请，返回完整记录（**不含** password_hash）。"""

def get_register_request(request_id: int, *, with_secret: bool = False) -> dict | None:
    """按 id 取申请；不存在返回 None。"""

def list_register_requests() -> list[dict]:
    """全部申请：**pending 优先**，组内 id 倒序（最新在前）。不含 password_hash / ip。

    排序写成 `ORDER BY (status = 'pending') DESC, id DESC`：
    SQLite 里布尔表达式求值为 0/1，所以"是 pending 的排前面"是一行 SQL 的事。
    已处理的记录按时间倒序跟在后面——它们是台账，不是待办。
    """

def find_recent_register_by_ip(ip: str, window_seconds: int) -> dict | None:
    """该 IP 在冷却期内的最近一条申请；没有则 None（Spec19 §2.2）。

    截止时刻在 **Python 侧**算好再传进 SQL，不用 SQLite 的 datetime('now','-1 day')：
    created_at 是 `YYYY-MM-DDTHH:MM:SS.mmmZ` 形态（_now_iso），
    与 SQLite 默认的 `YYYY-MM-DD HH:MM:SS` 格式**字符串不可比**。
    同格式同宽度的 ISO 串，字典序即时间序，直接 `>=` 比较是安全的。
    """

def approve_register_request(request_id: int, quota_limit: int) -> dict | None:
    """同意：**单事务**内建号 + 改状态 + 置空哈希。返回新建的用户 dict；
    该行已不是 pending（并发抢跑）时返回 None（调用方转 40903）。
    用户名撞 UNIQUE 时抛 DuplicateUsernameError（调用方转 40901）。"""

def reject_register_request(request_id: int) -> dict | None:
    """拒绝：只改状态。**保留 password_hash**（该密码从未生效，见 §3.3-5）。
    该行已不是 pending 时返回 None。"""

def delete_register_request(request_id: int) -> bool:
    """删掉一条申请记录（任意状态）。**不触碰 users**（§5.3）。返回是否有行被删。"""
```

`approve_register_request` 的实现要点（**这是全 Spec 唯一需要小心的事务**）：

```python
def approve_register_request(request_id: int, quota_limit: int) -> dict | None:
    req = get_register_request(request_id, with_secret=True)
    if req is None:
        return None
    now = _now_iso()
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at, quota_limit) "
                "VALUES (?, ?, 0, ?, ?)",
                (req["username"], req["password_hash"], now, quota_limit),
            )
            user_id = cur.lastrowid
            # 并发判据用 WHERE ... AND status='pending' 的 rowcount，而不是"先查后写"：
            # 两个管理员同时点同意时，后到的那个 UPDATE 影响 0 行 → 整个事务回滚
            # （sqlite3 的 `with conn` 在异常/显式 rollback 时丢弃未提交的写）。
            marked = conn.execute(
                "UPDATE register_requests "
                "SET status = 'approved', reviewed_at = ?, password_hash = '' "
                "WHERE id = ? AND status = 'pending'",
                (now, request_id),
            )
            if marked.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
    except sqlite3.IntegrityError as exc:      # users.username UNIQUE 撞车
        raise DuplicateUsernameError(f"用户名已存在: {req['username']}") from exc
    return get_user_by_id(user_id)
```

> **为什么必须一个事务**：若先 `create_user()` 提交、再单独改状态，中间会开出一个"**号已经建了，但申请记录还是 pending**"的窗口。管理员此时再点一次「同意」→ 撞 `40901 用户名已存在` → **那条记录永远停在 pending、永远点不动**（三个按钮都在，点同意报错、点拒绝又不甘心）。这与 Spec18 §5.1g「`record_call` 必须一次事务写两张表」是同一类错误：**跨表的状态必须同生同死**。
>
> **为什么 `quota_limit` 直接写在 INSERT 里**，而不是建完号再调 `set_user_quota`：后者是第二次事务，同样会开出"号建了但限额还是默认值"的窗口。`users.quota_limit` 本来就有列默认值（`QUOTA_DEFAULT_LIMIT`），显式传值只是覆盖它——一条语句解决。
>
> **`user_quota` 行不用建**：`_USER_SELECT` 用 `LEFT JOIN user_quota ... COALESCE(q.used, 0)`，没有 quota 行等价于"已用 0 次"。新建的号由第一次 `record_call` 的 UPSERT 建行——**与既有的 `create_user` 行为完全一致**，不引入第二条路径。

`find_recent_register_by_ip` 的实现要点：

```python
def find_recent_register_by_ip(ip: str, window_seconds: int) -> dict | None:
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=window_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM register_requests WHERE ip = ? AND created_at >= ? "
            "ORDER BY id DESC LIMIT 1",
            (ip, cutoff),
        ).fetchone()
    return _register_row_to_dict(row)
```

（`datetime` / `timedelta` 已在 `db.py` 顶部导入过 `datetime, timezone`，需要补 `timedelta`。）

### 5.2 关键数据流

#### A. 提交申请（公开路径，无登录态）

```
浏览器 RegisterModal
  → POST /api/auth/register
  → 中间件：路径在 PUBLIC_AUTH_PATHS 里 → 直接放行
            （不查 token、不查限额、不碰 request.state.user）
  → 路由 register_request()：
      ① config.REGISTER_ENABLED 为假            → 40305
      ② 格式校验（§6.2 的九步表，顺序即契约）    → 40018
      ③ db.get_user_by_username(username) 命中  → 40901
      ④ db.find_recent_register_by_ip(ip, 窗口) 命中 → 40902
      ⑤ auth.hash_password(password)
         → db.create_register_request(...)
  → _ok({"id": <新行 id>})
```

> 第 ⑤ 步**排在最后**：bcrypt 是故意慢的（约 100 ms 量级），没有理由在一条注定要被拒的请求上做它。

#### B. 同意（管理员）

```
管理员点「同意」→ window.prompt 填限额 → POST /api/admin/register-requests/{id}/approve
  → 中间件：/api/admin/* 前缀 + is_admin 已确认（Spec2 既有）
  → 路由 approve()：
      ① quota_limit 越界（<0 或 > QUOTA_LIMIT_MAX） → 40017
      ② db.get_register_request(id, with_secret=True) 为 None → 40409
      ③ status != 'pending'                                → 40903
      ④ db.approve_register_request(id, quota_limit)
           ├─ 撞用户名 UNIQUE → DuplicateUsernameError      → 40901
           └─ rowcount == 0（并发抢跑）                      → 40903
  → _ok({"id": <新用户 id>, "username": ..., "quota_limit": ...})
  → 前端 load() 重拉列表：该行按钮变「已同意」纯文字，用户表格里多一行
```

#### C. 拒绝 / 删除（管理员）

```
拒绝： POST /api/admin/register-requests/{id}/reject
        → 40409（不存在）/ 40903（已处理）
        → UPDATE status='rejected', reviewed_at=now WHERE id=? AND status='pending'
        → 前端该行变「已拒绝」纯文字

删除： DELETE /api/admin/register-requests/{id}
        → 40409（不存在）
        → DELETE FROM register_requests WHERE id=?   ← 单语句，任意状态都能删
        → 前端该行消失；若它是那个 IP 唯一的记录，该 IP 的冷却期就此结束（§2.2）
```

### 5.3 一致性 / 失败语义

| 场景 | 语义 |
|---|---|
| 申请落库失败（磁盘/锁） | 抛 `sqlite3` 异常 → 全局 500 处理器 → `50001`。前端停在表单、错误行显示后端 `message`，用户可以重试（**不占用冷却期**，因为没落库） |
| 同意时用户名被抢 | `40901`，记录**保持 pending**（不替管理员改状态），前端报错、列表刷新后该行仍在 |
| 两个管理员同时点同意 | 只有一个成功：后到的 `UPDATE ... AND status='pending'` 影响 0 行 → 事务回滚（**连刚 INSERT 的 users 行一起回滚**）→ `40903`。不会出现"建了两个号"或"号建了但记录还 pending" |
| 删除一条**已同意**的记录 | 只删记录。**建出来的用户不动**——`users` 是账号资源，`register_requests` 是审批台账，两者没有级联关系 |
| 删除一个**用户** | `db.delete_user` **不碰** `register_requests`（Spec19 不修改该函数的级联清单）。理由同上：台账记录的是"审批发生过"，与账号是否存在无关 |
| 收款码文件不存在 | `40410`，文案含客服邮箱。**注册链路的其余部分照常工作**（用户可以先提交申请，管理员线下联系时再收款） |

---

## 6. 接口约定

统一的 `{code, message, data}` 契约不变（Spec §8）。

### 6.1 新增：`GET /api/auth/register-config`（**公开**）

给注册弹窗喂"只能由后端提供"的四样东西——**是否开放、客服邮箱、收款码地址、两句提示语**。前端对客服邮箱与提示语**零副本**（与 Spec18 的 `QUOTA_EXCEEDED_MESSAGE` 同一条原则）。

```json
{
  "code": 200, "message": "ok",
  "data": {
    "enabled": true,
    "contact_email": "frostyj@qq.com",
    "qr_url": "http://localhost:8000/api/auth/payment-qr",
    "price_notice": "请先预充值，1 元起充，参考价格：1 元约 10 次设计服务",
    "daily_notice": "每人每天只能申请一个账号，若操作失误或其他需求请联系在线客服 frostyj@qq.com"
  }
}
```

- `qr_url` 用既有的 `_public_base(request)` 拼**绝对地址**（与作品/分享图的处理一致），前端 `<img :src="cfg.qr_url">` 直接用，不做任何拼接——这样 `VITE_API_BASE` 的独立部署场景也不用管。
- **永远返回 200**，即使 `enabled=false`（前端要读 `contact_email` 才能显示客服行、读 `enabled` 才知道要不要画注册按钮）。

### 6.2 新增：`POST /api/auth/register`（**公开**）

请求体：

```json
{ "username": "zhangsan", "password": "123456",
  "phone": "13800000000", "email": "", "wechat": "张三" }
```

`schemas.py`：

```python
class RegisterRequestCreate(BaseModel):
    """POST /api/auth/register 请求体（Spec19 §6.2）。

    全部字段都是裸 str：格式规则（长度、纯数字、@ 位置）一律在路由层判，
    好让每一条都有自己的中文 message。Pydantic 只负责"字段在不在"。
    """
    username: str
    password: str
    phone: Optional[str] = None
    email: Optional[str] = None
    wechat: str
```

**校验顺序即契约**（顺序变了，用户体验就变了，理由见 §2.2）：

| # | 检查 | 失败码 | message |
|---|---|---|---|
| 1 | `config.REGISTER_ENABLED` | `40305` | 注册申请暂未开放，请联系客服 {SUPPORT_EMAIL} |
| 2 | `username.strip()` 长度 2~32 | `40018` | 用户名需为 2~32 个字符 |
| 3 | `password` 长度 6~72 | `40018` | 密码需为 6~72 位 |
| 4 | `wechat.strip()` 非空且 ≤64 | `40018` | 请填写用于支付的微信昵称 |
| 5 | `phone` / `email` 至少有一个非空 | `40018` | 手机号与邮箱请至少填写一项 |
| 6 | `phone` 非空时：`isdigit()` 且长度 11 | `40018` | 手机号需为 11 位数字 |
| 7 | `email` 非空时：含 `@`、`@` 前后都非空、≤128 | `40018` | 邮箱格式不正确（需包含 @，且 @ 前后都有内容） |
| 8 | `db.get_user_by_username(username)` 无命中 | `40901` | 用户名已存在（复用既有错误类） |
| 9 | `db.find_recent_register_by_ip(ip, 窗口)` 无命中 | `40902` | 每台设备每天只能提交一次注册申请，请明天再试或联系客服 {SUPPORT_EMAIL} |

空串与 `None` 一律先 `strip()` 再判空：`phone=""` 与 `phone=null` 等价（前端两个输入框总是提交字符串）。

响应：`_ok({"id": 7})`。

落库前把 `phone` / `email` 的空串**存成 `NULL`**，不存 `""`——"没填"只有一种表示（与 Spec17 的 `posts.image_file` 可空同款思路）。

### 6.3 新增：`GET /api/auth/payment-qr`（**公开**）

- 读 `config.PAYMENT_QR_PATH`（= `Server/payment.jpg`）原始字节，`Response(content=data, media_type="image/jpeg")`
- 响应头加 `Cache-Control: public, max-age=3600`（收款码不会天天换，弹窗每次打开都重拉一遍没必要）
- 文件不存在 → `40410`（**不是 500**：这是"部署时忘了放图"，不是服务坏了）
- **不放在 `/api` 前缀之外的路径**（如 `/payment.jpg`）：与分享页那种"故意公开的页面"不同，这是一张给弹窗用的静态资源，留在 `/api` 下语义更一致，且 `PUBLIC_AUTH_PATHS` 机制本来就能表达"公开"

### 6.4 新增：`GET /api/admin/register-requests`

响应 `data` 为数组（**pending 优先，组内 id 倒序**），每项：

```json
{ "id": 7, "username": "zhangsan", "phone": "13800000000", "email": null,
  "wechat": "张三", "status": "pending",
  "created_at": "2026-09-19T03:12:44.512Z", "reviewed_at": null }
```

- **不含** `password_hash`（`_register_row_to_dict` 的默认行为，结构性保证）
- **不含** `ip`
- 无分页、无筛选参数（§3.2）

### 6.5 新增：`POST /api/admin/register-requests/{id}/approve`

请求体 `{"quota_limit": 10}`：

```python
class RegisterApproveRequest(BaseModel):
    """POST /api/admin/register-requests/{id}/approve 请求体（Spec19 §6.5）。

    非整数由 Pydantic 拦下 → 40001；取值范围在路由层判 → 40017（复用 Spec18）。
    """
    quota_limit: int
```

成功 → `_ok({"id": <新用户 id>, "username": "zhangsan", "is_admin": false, "quota_limit": 10})`
失败 → `40017`（越界）/ `40409`（不存在）/ `40903`（已处理）/ `40901`（用户名被占用）

### 6.6 新增：`POST /api/admin/register-requests/{id}/reject`

无请求体。成功 → `_ok({"id": 7})`；失败 → `40409` / `40903`。

### 6.7 新增：`DELETE /api/admin/register-requests/{id}`

成功 → `_ok({"id": 7})`；失败 → `40409`。

### 6.8 变更：`PUBLIC_AUTH_PATHS`

```python
# 放行列表：除登录与注册链路的三个公开接口外，所有 /api 接口都需登录态（Spec19 §6.8）
PUBLIC_AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/register",        # Spec19：提交注册申请（无登录态）
    "/api/auth/register-config", # Spec19：注册弹窗的公开配置
    "/api/auth/payment-qr",      # Spec19：收款码图片
}
```

> 这四个是**精确匹配**（`path not in PUBLIC_AUTH_PATHS`），不是前缀匹配——新增路径时必须原样写全，别写成 `/api/auth/register` 就以为能覆盖 `-config`。

### 6.9 不变

`POST /api/auth/login`、`GET /api/auth/me`、`/api/admin/users*` 全部系列、其余所有接口的请求/响应结构与错误码**一个字都不变**。Spec18 的限额判定（中间件 + 登录）也完全不动——注册链路的三个公开路径**不走限额判定**（它们连 `request.state.user` 都没有）。

---

## 7. 前端交互

### 7.1 LOGO 资产与登录卡片

**改法（两处，内容完全相同）：**

1. 复制 `GithubPage/LOGO.svg` → 删掉第 4 行那条铺满画布的 `<path ... fill="#F5EFFC" transform="translate(0,0)"/>` → 另存为：
   - `frontend/src/assets/logo.svg`
   - `GithubPage/assets/logo.svg`
2. `GithubPage/LOGO.svg`（母版）**保持原样不动**。

**`views/Login.vue` 模板**（头部）：

```vue
<div class="login-card">
  <img class="login-logo" :src="logoUrl" alt="ArtiControlNet" />
  <div class="login-brand">
    <span class="brand-dot"></span>
    <h1>ArtiControlNet</h1>
  </div>
  <p class="login-sub">赋能设计的 AIGC 系统 · 登录后使用</p>
  ...
```

```js
import logoUrl from '../assets/logo.svg'
```

（Vite 对 `.svg` 的默认导入形态就是 URL 字符串，不需要 `?url` 后缀，也不需要 `vite-svg-loader` 之类的插件。）

**样式**（追加到 `main.css`）：

```css
/* Spec19 §7.1：登录卡片顶部的品牌标识（透明底 SVG，深色卡片上直接成立） */
.login-logo {
  display: block;
  width: 96px;
  height: 96px;
  margin: 0 auto 4px;
  user-select: none;
  -webkit-user-drag: none;
}
```

`.login-card` 的 `padding` 由 `36px 32px 32px` 改为 `28px 32px 32px`：卡片的"变高"由标识自己贡献（96px），顶部内边距顺手收一点，免得整块头重脚轻。

### 7.2 登录页的两个新元素（`Login.vue`）

表单**之后**：

```vue
      </form>

      <!-- Spec19 §7.2：注册入口（REGISTER_ENABLED=false 时整体不渲染按钮，客服行保留） -->
      <div v-if="regCfg" class="login-register">
        <button v-if="regCfg.enabled" type="button" class="btn-register" @click="showRegister = true">
          新用户注册
        </button>
        <p class="login-service">有问题请致信官方客服：{{ regCfg.contact_email }}</p>
      </div>
    </div>

    <!-- Spec19 §7.3：注册申请弹窗 -->
    <RegisterModal v-if="showRegister" :config="regCfg" @close="showRegister = false" />
```

脚本部分：

```js
const regCfg = ref(null)
const showRegister = ref(false)

onMounted(async () => {
  // Spec18 §7.4 的既有逻辑（限额提示）保持不变，本段追加在其后
  try {
    regCfg.value = await getRegisterConfig()
  } catch {
    regCfg.value = null      // 取不到就不画注册入口（登录本身不受影响）
  }
  // Spec19 §7.4：?register=1 深链接 → 自动打开注册弹窗
  if (new URLSearchParams(window.location.search).get('register') === '1' && regCfg.value?.enabled) {
    showRegister.value = true
  }
})
```

> `regCfg` 取不到时**静默降级**：不画注册入口、不报错。登录页的首要职责是登录，注册接口挂了不该让它连带报错。

### 7.3 新增 `views/RegisterModal.vue`

结构（自上而下，与用户描述逐条对应）：

```vue
<template>
  <div class="reg-overlay" @click.self="close">
    <div class="reg-card" role="dialog" aria-modal="true" aria-label="新用户注册">
      <button class="reg-close" title="关闭" @click="close">×</button>

      <!-- 提交成功：整卡换成结果面板，用户自己关掉（不自动关，让他看清提示） -->
      <template v-if="done">
        <h2 class="reg-title">申请已提交</h2>
        <p class="reg-done-text">
          我们会在 1~2 天内通过您填写的手机号或邮箱与您联系，请留意消息。
        </p>
        <button class="btn-primary reg-submit" @click="close">关闭</button>
      </template>

      <template v-else>
        <h2 class="reg-title">新用户注册</h2>
        <p class="reg-lead">提交后由管理员审核开通，账号会在审核通过后创建。</p>

        <form class="reg-form" @submit.prevent="submit">
          <label class="reg-label">账号 <b class="reg-star">*</b></label>
          <input v-model="username" class="login-input" placeholder="2~32 个字符" autocomplete="off" />

          <label class="reg-label">密码 <b class="reg-star">*</b></label>
          <input v-model="password" type="password" class="login-input"
                 placeholder="至少 6 位" autocomplete="new-password" />

          <label class="reg-label">联系方式 <b class="reg-star">*</b></label>
          <p class="reg-hint">手机号与邮箱至少填一项，注册成功会联系到您</p>
          <input v-model="phone" class="login-input" placeholder="手机号（11 位数字）" autocomplete="off" />
          <input v-model="email" class="login-input" placeholder="邮箱" autocomplete="off" />

          <div class="reg-pay">
            <p class="reg-pay-title">请先预充值，1 元起充，参考价格：1 元约 10 次设计服务</p>
            <img class="reg-qr" :src="config.qr_url" alt="收款码" />
          </div>

          <label class="reg-label">支付备注 <b class="reg-star">*</b></label>
          <input v-model="wechat" class="login-input"
                 placeholder="用于支付的微信昵称（便于我们核对）" autocomplete="off" />

          <p class="reg-note">{{ config.daily_notice }}</p>
          <p v-if="error" class="login-error">{{ error }}</p>
          <button class="btn-primary reg-submit" type="submit" :disabled="loading">
            {{ loading ? '提交中…' : '提交申请' }}
          </button>
        </form>
      </template>
    </div>
  </div>
</template>
```

**校验策略（只做两条客户端校验，其余交给后端）**：

```js
function submit() {
  // 只拦"必填"与"二选一"——那是 * 号承诺的东西，本地拦能立刻给反馈。
  // 手机号 11 位、邮箱 @ 位置这些**不在前端复制**：它们各有自己的中文 message，
  // 已经在后端（40018）实现了一份，前端再抄一份就是第二个会漂移的副本。
  if (!username.value.trim() || !password.value || !wechat.value.trim()) {
    error.value = '请填写账号、密码与支付备注'
    return
  }
  if (!phone.value.trim() && !email.value.trim()) {
    error.value = '手机号与邮箱请至少填写一项'
    return
  }
  // ...POST → 成功 done=true；失败 error = e.message
}
```

**两个文案不写死在这里**：`请先预充值…`（`price_notice`）与 `每人每天…`（`daily_notice`）都从 `config` 来。模板里的 `1 元起充…` 那一行按上面的骨架写死是**错的**，必须绑 `{{ config.price_notice }}`——它们与客服邮箱同源（§8），是配置项不是模板文案。

**收尾细节**：

- 关闭弹窗不重置 `done`（再来一次就重开一个组件，`v-if` 已经保证）
- `loading` 期间按钮 disabled（防连点重复提交；后端还有 IP 冷却兜底，但没必要让用户先撞一次 40902）
- 弹窗打开时**不锁定页面滚动**（与 `HelpModal` 一致，本页本来就不滚）

### 7.4 `?register=1` 深链接

已在 §7.2 的 `onMounted` 里。补充两条约定：

- **不清理 URL**：关掉弹窗后地址栏仍是 `?register=1`，刷新会再次打开。对 README 引流的场景这是**期望行为**（用户从官网链接进来，中途刷新，注册窗还在）。
- `regCfg.enabled === false` 时**不打开**（§3.3-7）。

### 7.5 `views/AdminPanel.vue`

**(a) 顶部提示行改写**（原文案已经过时——"无公开注册"不再成立）：

```vue
<p class="admin-tip">
  当前登录：{{ auth.username }}（{{ auth.isAdmin ? '管理员' : '普通用户' }}）
  · 账号可由管理员创建，或由用户申请后审批开通
  · <b class="tip-pending">待审批注册申请 {{ pendingCount }} 条</b>
</p>
```

```js
const pendingCount = computed(
  () => requests.value.filter((r) => r.status === 'pending').length
)
```

**(b) 「待审批注册用户」区块**（放在 `.admin-table-wrap` **之后**）：

```vue
    <!-- Spec19 §7.5b：注册申请台账。pending 在前（后端已排好序），已处理的原样留在下方 -->
    <section class="reg-admin">
      <h3 class="reg-admin-title">待审批注册用户</h3>
      <p v-if="requests.length === 0" class="reg-admin-empty">暂无注册申请</p>

      <div v-for="r in requests" :key="r.id" class="reg-row">
        <div class="reg-row-info">
          <span class="reg-row-user">{{ r.username }}</span>
          <span class="reg-row-cell">手机号：{{ r.phone || '—' }}</span>
          <span class="reg-row-cell">邮箱：{{ r.email || '—' }}</span>
          <span class="reg-row-cell">支付微信：{{ r.wechat }}</span>
          <span class="reg-row-cell reg-row-time">{{ r.created_at }}</span>
        </div>

        <div class="reg-row-actions">
          <template v-if="r.status === 'pending'">
            <button class="btn-mini" :disabled="busyRegId === r.id" @click="approve(r)">同意</button>
            <button class="btn-mini" :disabled="busyRegId === r.id" @click="reject(r)">拒绝</button>
          </template>
          <span v-else class="reg-row-done">
            {{ r.status === 'approved' ? '已同意' : '已拒绝' }}
          </span>
          <button class="btn-mini danger" :disabled="busyRegId === r.id" @click="removeRequest(r)">
            删除
          </button>
        </div>
      </div>
    </section>
```

**(c) 三个处理函数**（与既有的 `editQuota` / `remove` 同款：`window.prompt`/`confirm` + `busyId` + `flash` + `load`）：

```js
// Spec19 §7.5c：同意 = 弹框填限额（与「改限额」逐字同款交互，默认值取后端配置）
async function approve(r) {
  // 不传 prompt 的第二个参数（不给默认值）——理由见 §7.5e
  const input = window.prompt(
    `同意「${r.username}」的注册申请，并设置服务限额（累计可用次数）：`
  )
  if (input === null) return                       // 取消
  const raw = input.trim()
  const n = Number(raw)
  // 与 editQuota 同样的三个坑：raw 为空必须单独拦（Number('') === 0 会让
  // "清空直接确定"静默变成限额 0 = 禁用该账号）；用 Number.isInteger 而非
  // parseInt（parseInt('25abc') 会静默变成 25）；上限交给后端 40017 报。
  if (!raw || !Number.isInteger(n) || n < 0) {
    error.value = '限额需为不小于 0 的整数'
    return
  }
  // ...POST approve(r.id, n) → flash(`已开通账号：${r.username}`) → load() + loadUsers()
}
```

- `approve` 成功后要**同时**刷新两张表：`loadRequests()` 与 `load()`（用户表格里多了一行）。这是本文件里唯一一个影响两处数据的动作。
- `reject` → `window.confirm('确定拒绝「x」的注册申请？')` → 刷新申请列表
- `removeRequest` → `window.confirm('确定删除这条申请记录？此操作不可撤销。')` → 刷新申请列表。确认文案里**不提"账号"**（删除记录不动账号，别让管理员误会会删号）

**(d) `onMounted`**：并行拉两张表。

```js
onMounted(() => {
  load()
  loadRequests()
})
```

**(e) 新增 `defaultQuota`**：从 `GET /api/auth/register-config` 拿不到 `QUOTA_DEFAULT_LIMIT`（那是后端的建号默认值，没在公开配置里）。两个选择：写死 25，或者不加默认值（`window.prompt` 的第二参数传空串 → 输入框是空的）。**选后者**：`window.prompt(msg)` 不传第二参数即可，避免在前端复制一个会漂移的常量（Spec18 §7.5 对 `QUOTA_LIMIT_MAX` 就是这个理由）。管理员填多少由他跟用户的实际付款决定，本来就不该被一个前端默认值暗示。

### 7.6 `api/chatApi.js` 新增

```js
// ---- Spec19：注册申请与审批 ----

export async function getRegisterConfig() {
  const { data } = await http.get('/api/auth/register-config')
  return data
}

export async function submitRegisterRequest({ username, password, phone, email, wechat }) {
  const { data } = await http.post('/api/auth/register', {
    username, password, phone, email, wechat
  })
  return data
}

export async function listRegisterRequests() {
  const { data } = await http.get('/api/admin/register-requests')
  return data
}

export async function approveRegisterRequest(id, quotaLimit) {
  const { data } = await http.post(`/api/admin/register-requests/${id}/approve`, {
    quota_limit: quotaLimit
  })
  return data
}

export async function rejectRegisterRequest(id) {
  const { data } = await http.post(`/api/admin/register-requests/${id}/reject`)
  return data
}

export async function deleteRegisterRequest(id) {
  const { data } = await http.delete(`/api/admin/register-requests/${id}`)
  return data
}
```

> **拦截器不用改。** `40305`（注册未开放）与既有的 `40301/40302/40303/40304` 互不干扰：拦截器只在 `code === 40304` 时才登出（Spec18 §7.2），而 40305 只可能出现在 `/api/auth/register` 上（一个未登录用户根本不会被登出）。`40902/40903` 是 409，拦截器不处理 409。

### 7.7 样式约定（`assets/styles/main.css`）

追加一段（**变量一律取自 `:root`，不写死颜色**）：

| 类名 | 用途 | 要点 |
|---|---|---|
| `.login-logo` | 登录卡片标识 | §7.1 已给 |
| `.login-register` | 注册入口容器 | `margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border-color);` |
| `.btn-register` | 「新用户注册」按钮 | 描边按钮（**不是**主色实心）：`border: 1px solid var(--purple-500); color: var(--purple-300); background: transparent; width: 100%; border-radius: var(--radius-full); padding: 10px;` —— 主色实心留给「登 录」，两个实心按钮会互相抢 |
| `.login-service` | 客服行 | `margin-top: 10px; text-align: center; font-size: 12px; color: var(--text-muted);` |
| `.reg-overlay` / `.reg-card` | 弹窗 | 抄 `HelpModal` 的 `.help-overlay` / `.help-card` 那套（`position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 100`），卡片 `max-width: 420px; max-height: 88vh; overflow-y: auto;` |
| `.reg-star` | 必填星号 | `color: #fca5a5;` |
| `.reg-hint` / `.reg-note` | 提示与批注 | 12px，`var(--text-muted)`；`.reg-note` 上方留一条分隔线 |
| `.reg-pay` / `.reg-qr` | 收款码块 | `.reg-qr { width: 200px; display: block; margin: 8px auto 0; border-radius: var(--radius-md); }` |
| `.reg-row*` | 管理端条目 | 一行 `display: flex; justify-content: space-between; align-items: center;`，左侧信息折行，右侧三个按钮；`padding: 12px; border: 1px solid var(--border-color); border-radius: var(--radius-lg); margin-bottom: 8px;` |
| `.reg-row-done` | 「已同意 / 已拒绝」 | `font-size: 13px; color: var(--text-muted);` |
| `.tip-pending` | 顶部待审批条数 | `color: var(--purple-300);` |

---

## 8. 配置 / 环境变量 / .gitignore

`Server/config.py` 新增一段（放在 Spec18 的限额块之后）：

```python
# ===== 注册申请与审批（Spec19）=====
# 客服 / 管理员邮箱（**唯一来源**）。Spec18 的 QUOTA_CONTACT_EMAIL 默认跟随它，
# 于是"超额提示里的邮箱"与"注册页客服邮箱"永远是同一个地址。
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "frostyj@qq.com").strip()

# 注册申请开关：置 false 时 /api/auth/register 返回 40305，前端同时隐藏注册入口（§3.3-7）。
# 取值照抄"字符串转布尔"的宽松写法，只有明确的假值才算关。
REGISTER_ENABLED = os.getenv("REGISTER_ENABLED", "true").strip().lower() not in (
    "0", "false", "no", "off", "",
)

# 同一 IP 的申请冷却期（秒）。默认 86400 = 24 小时（§2.2 的滚动窗口）。
REGISTER_IP_WINDOW_SECONDS = int(os.getenv("REGISTER_IP_WINDOW_SECONDS", "86400"))

# 收款码文件（**不进仓库**，见 .gitignore；部署时手动放到这个位置）。
# 不是环境变量：它是一条路径，与 AUTH_DB_PATH 同类。
PAYMENT_QR_PATH = BASE_DIR / "payment.jpg"

# 两句给用户看的提示语（唯一来源，前端零副本——与 QUOTA_EXCEEDED_MESSAGE 同一原则）
REGISTER_PRICE_NOTICE = "请先预充值，1 元起充，参考价格：1 元约 10 次设计服务"
REGISTER_DAILY_NOTICE = (
    f"每人每天只能申请一个账号，若操作失误或其他需求请联系在线客服 {SUPPORT_EMAIL}"
)
```

**Spec18 块的一行改动**（消除同一个邮箱的两份默认值）：

```python
# 原：QUOTA_CONTACT_EMAIL = os.getenv("QUOTA_CONTACT_EMAIL", "frostyj@qq.com").strip()
# 现：默认跟随 SUPPORT_EMAIL（显式配了 QUOTA_CONTACT_EMAIL 仍以它为准）
QUOTA_CONTACT_EMAIL = os.getenv("QUOTA_CONTACT_EMAIL", SUPPORT_EMAIL).strip()
```

> **位置约束**：`SUPPORT_EMAIL` 必须定义在 `QUOTA_CONTACT_EMAIL` **之前**（Python 从上往下执行）。若把注册块放在限额块之后，这一行会 `NameError`。

`.env.example` 追加：

```bash
# ---- 注册申请与审批（Spec19，均可留空用默认值）----
# SUPPORT_EMAIL=frostyj@qq.com          # 客服邮箱（超额提示与注册页共用）
# REGISTER_ENABLED=true                 # 置 false 关闭注册入口
# REGISTER_IP_WINDOW_SECONDS=86400      # 同一 IP 的申请冷却期（秒）
# 收款码：把微信收款码图片放到 Server/payment.jpg（该文件不进仓库）
```

`.gitignore` 追加：

```
# 收款码（Spec19：含个人收款二维码与实名，仅本地留存）
Server/payment.jpg
```

`CLAUDE.md` 同步（配置段加 3 个变量、gotchas 加注册链路与"两处 LOGO 同值副本"）。

---

## 9. 错误码

追加到 Spec18 §9 之后（**已有的码一个都不动**）：

| code | HTTP | 类 | 触发 | message |
|---|---|---|---|---|
| `40018` | 400 | `RegisterRequestError` | 申请字段格式非法（九步表的 ②③④⑤⑥⑦） | 逐条不同，见 §6.2 |
| `40305` | 403 | `RegisterClosedError` | `REGISTER_ENABLED=false` | `注册申请暂未开放，请联系客服 {SUPPORT_EMAIL}` |
| `40409` | 404 | `RegisterRequestNotFoundError` | 申请 id 不存在 | `注册申请不存在` |
| `40410` | 404 | `PaymentQrMissingError` | `Server/payment.jpg` 不存在 | `收款码暂未配置，请联系客服 {SUPPORT_EMAIL}` |
| `40902` | 409 | `RegisterRateLimitedError` | 同 IP 冷却期内已有申请 | `每台设备每天只能提交一次注册申请，请明天再试或联系客服 {SUPPORT_EMAIL}` |
| `40903` | 409 | `RegisterAlreadyReviewedError` | 该申请已被同意/拒绝（或并发抢跑） | `该申请已处理` |

**复用不新增**：用户名已被占用 → 既有 `40901`；审批限额越界 → 既有 `40017`。

```python
# ---- 注册申请与审批（Spec19 §9，追加到 Spec18 §9 之后）----

class RegisterRequestError(BadRequestError):
    """注册申请字段非法（长度 / 纯数字 / @ 位置）。"""
    def __init__(self, message: str = "注册申请信息非法"):
        super().__init__(message, code=40018)


class RegisterClosedError(AppError):
    """注册申请暂未开放（REGISTER_ENABLED=false）。"""
    def __init__(self, message: str | None = None):
        super().__init__(
            40305,
            message or f"注册申请暂未开放，请联系客服 {config.SUPPORT_EMAIL}",
            status_code=403,
        )


class RegisterRequestNotFoundError(NotFoundError):
    """注册申请不存在。"""
    def __init__(self, message: str = "注册申请不存在"):
        super().__init__(message, code=40409)


class PaymentQrMissingError(NotFoundError):
    """收款码文件缺失（部署时忘了放 Server/payment.jpg）。"""
    def __init__(self, message: str | None = None):
        super().__init__(
            message or f"收款码暂未配置，请联系客服 {config.SUPPORT_EMAIL}", code=40410
        )


class RegisterRateLimitedError(AppError):
    """同一 IP 在冷却期内已提交过申请（Spec19 §2.2）。"""
    def __init__(self, message: str | None = None):
        super().__init__(
            40902,
            message or (f"每台设备每天只能提交一次注册申请，"
                        f"请明天再试或联系客服 {config.SUPPORT_EMAIL}"),
            status_code=409,
        )


class RegisterAlreadyReviewedError(AppError):
    """该申请已被处理（或两个管理员同时点了同意，后到的那个）。"""
    def __init__(self, message: str = "该申请已处理"):
        super().__init__(40903, message, status_code=409)
```

> `NotFoundError` / `BadRequestError` / `AppError` 的既有基类语义照用：`NotFoundError(message, code=...)` 与 `BadRequestError(message, code=...)` 都接受关键字覆盖（见 `SuggestionNotFoundError`、`GalleryNoteError`）。

---

## 10. 日志约定

沿用 Spec §10 的单行 JSON。新增四类事件：

| event | 时机 | 关键字段 |
|---|---|---|
| `auth.register_submitted` | 申请落库成功 | `request_id`、`username`、`has_phone`、`has_email`（**不记手机号/邮箱本身，也不记 IP**） |
| `auth.register_blocked` | 被 40902 拒 | `request_id`（**不记 IP**——日志会被贴进 issue） |
| `auth.register_reviewed` | 同意 / 拒绝成功 | `request_id`、`operator`（管理员用户名）、`target_user`、`decision`、`quota_limit`（仅同意） |
| `auth.register_deleted` | 删除记录 | `request_id`、`operator`、`target_user`、`was_status` |

> **IP 一律不进日志**。它已经存在库里（判重必需），再往日志里抄一份只是让排障截图变成一次额外的信息泄露。这与 Spec18 在 `auth.quota_blocked` 里记 `username`/`used` 的分寸一致：**记决策需要的，不记顺手的**。

---

## 11. 目录结构增量

```
ArtiControlNet/
├── GithubPage/
│   ├── LOGO.svg                       # 母版，**不动**
│   └── assets/
│       ├── logo.svg                   # 新增：透明底（README 用，§7.1）
│       ├── site-banner.svg            # 新增：官网横条（§12 前的资产小节）
│       └── ...                        # 既有 jpg/png 不动
├── frontend/src/
│   ├── assets/
│   │   ├── logo.svg                   # 新增：与上面那份**内容相同**
│   │   └── styles/main.css            # 追加 §7.7 的类
│   ├── api/chatApi.js                 # 追加 6 个函数
│   └── views/
│       ├── Login.vue                  # 标识 + 注册入口 + 深链接
│       ├── RegisterModal.vue          # 新增
│       └── AdminPanel.vue             # 提示行 + 待审批区块 + 三个处理函数
└── Server/
    ├── payment.jpg                    # 新增但 **.gitignore**（部署时手动放）
    ├── config.py / errors.py / schemas.py / main.py / db.py
    └── artcn.db                       # 新增 register_requests 表
```

**README 的资产小节（`GithubPage/assets/site-banner.svg`）**——横条的完整内容，可直接采用：

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="720" height="132" viewBox="0 0 720 132"
     role="img" aria-label="官方网址 ArtiControlNet.fun">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6D3FD6"/>
      <stop offset="0.55" stop-color="#A97BEA"/>
      <stop offset="1" stop-color="#C6A8EF"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="720" height="132" rx="20" fill="url(#bg)"/>
  <text x="360" y="44" text-anchor="middle"
        font-family="'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
        font-size="20" font-weight="500" fill="#F5EFFC" opacity="0.92">官方网址</text>
  <text x="360" y="86" text-anchor="middle"
        font-family="'Helvetica Neue',Helvetica,Arial,sans-serif"
        font-size="38" font-weight="700" fill="#FFFFFF" letter-spacing="0.5">ArtiControlNet.fun</text>
  <text x="360" y="114" text-anchor="middle"
        font-family="'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
        font-size="15" fill="#F5EFFC" opacity="0.85">点此注册 · 登录即用</text>
</svg>
```

**README 的三个改动**（文件头部）：

```markdown
<div align="center">
<img src="./GithubPage/assets/hero-banner.jpg" width="100%" alt="ArtiControlNet —— 赋能设计的 AIGC 系统">
</div>

<p align="center">
  <img src="./GithubPage/assets/logo.svg" width="130" alt="ArtiControlNet Logo">
</p>

<h1 align="center">ArtiControlNet</h1>
```

```markdown
<p align="center">
  <!-- Spec19：官方网址横条 → 官网首页；比下面的购买按钮更宽更醒目 -->
  <a href="https://ArtiControlNet.fun">
    <img src="./GithubPage/assets/site-banner.svg" width="680" alt="官方网址 ArtiControlNet.fun">
  </a>
  <br><br>
  <!-- Spec19：改为直达官网注册页（登录页 ?register=1 会自动弹开注册窗） -->
  <a href="https://ArtiControlNet.fun/?register=1">
    <img src="./GithubPage/assets/btn-buy.png" width="320" alt="购买 ArtiControlNet">
  </a>
  <br><br>
  <a href="https://github.com/Frosty-Jackal/ArtiControlNet">
    <img src="./GithubPage/assets/btn-star.png" width="160" alt="给 ArtiControlNet 点个 Star">
  </a>
</p>

<p align="center">
  如果想试用 ArtiControlNet，请发邮件到 <b>frostyj@qq.com</b>，说一句「想试用」<br>
  GitHub 来的宝子走专属通道，我开好账号发你，打开官方网址登录即用
</p>
```

三处文字改动逐条对照用户原话：

| 原 | 改 |
|---|---|
| 如果想试用**/购买** ArtiControlNet，请发邮件到 … | 如果想试用 ArtiControlNet，请发邮件到 … |
| 我开好账号发你，打开**链接**登录即用 | 我开好账号发你，打开**官方网址**登录即用 |
| 购买按钮 → `mailto:frostyj@qq.com` | 购买按钮 → `https://ArtiControlNet.fun/?register=1` |

---

## 12. 实施顺序（里程碑）

| 阶段 | 内容 | 完成判据 |
|---|---|---|
| **M1 数据层** | `db.py`：建表 + 2 索引 + 白名单 + `_register_row_to_dict` + 6 个函数；`config.py` 三个变量与两句提示语 + `QUOTA_CONTACT_EMAIL` 改默认源 | 直接 `python -c "import db; db.init_db()"` 后 `artcn.db` 里有 `register_requests` 表；`find_recent_register_by_ip` 手工插两行能正确命中/不命中 |
| **M2 后端接口** | `errors.py` 5 个类、`schemas.py` 2 个模型、`main.py` 6 个路由 + `PUBLIC_AUTH_PATHS` | §13 的 curl 全绿；尤其**公开路径真的能不带 token 访问** |
| **M3 LOGO 与前端** | 两份透明 SVG、`Login.vue`（标识 + 入口 + 深链接）、`RegisterModal.vue`、`main.css` | 登录页深色卡片上标识无白框；`http://localhost:5173/?register=1` 直接弹出注册窗 |
| **M4 管理端** | `AdminPanel.vue` 提示行 + 待审批区块 + 三个动作；`chatApi.js` 6 个函数 | §13 的端到端一条龙走通 |
| **M5 资产与文档** | `site-banner.svg`、README 三处改动、`.gitignore`、`.env.example`、`CLAUDE.md` | README 在 GitHub 上渲染正常（横条可点、LOGO 无白底） |

---

## 13. 验收用例（端到端 Smoke）

前置：后端 :8000 运行，`Server/payment.jpg` 存在，`.env` 里有管理员账号。

### 公开链路（不带 token）

```bash
# 1. 配置可读，qr_url 是绝对地址
curl -s localhost:8000/api/auth/register-config
#    → {"code":200,...,"data":{"enabled":true,"contact_email":"frostyj@qq.com",
#       "qr_url":"http://localhost:8000/api/auth/payment-qr","price_notice":"...","daily_notice":"..."}}

# 2. 收款码能取到（HTTP 200 + image/jpeg）
curl -sI localhost:8000/api/auth/payment-qr | head -3

# 3. 正常提交 → code 200 + 一个 id
curl -s -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"tester01","password":"123456","phone":"13800000000","email":"","wechat":"小明"}'

# 4. 紧接着再提交 → 40902（同一 IP 冷却）
curl -s -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"tester02","password":"123456","phone":"13800000001","email":"","wechat":"小红"}'
#    → {"code":40902,...}

# 5. 格式用例（逐条单独验，**每条都要在不同 IP 或用 4 之后的库**）
#    手号 10 位      → 40018 手机号需为 11 位数字
#    手号含字母      → 40018
#    email "abc@"    → 40018（@ 后为空）
#    email "abc"     → 40018（无 @）
#    phone/email 都空 → 40018 请至少填写一项
#    wechat 空        → 40018
#    password 5 位    → 40018
#    username 1 字符  → 40018
#    已存在的用户名   → 40901（**注意：这条要排在第 4 条之前验，否则先撞 40902**）
```

> **验格式用例的正确姿势**：`REGISTER_IP_WINDOW_SECONDS` 临时设为 1，或每验一条就把库里那行删掉——否则第二个用例起全是 40902，什么都验不到。

### 管理端链路（带管理员 token）

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"<管理员>","password":"<密码>"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")

# 6. 列表：pending 在最上面，**没有 password_hash、没有 ip**
curl -s localhost:8000/api/admin/register-requests -H "Authorization: Bearer $TOKEN"

# 7. 同意并设限额 10 → 用户表立刻多一行、限额 10、已用 0
curl -s -X POST localhost:8000/api/admin/register-requests/1/approve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"quota_limit":10}'
curl -s localhost:8000/api/admin/users -H "Authorization: Bearer $TOKEN"
#    → 新用户 quota_limit=10, used=0

# 8. 新号能登录（密码就是申请时填的那个）
curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"tester01","password":"123456"}'   # → code 200

# 9. 再点一次同意 → 40903（记录已处理）
curl -s -X POST localhost:8000/api/admin/register-requests/1/approve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"quota_limit":10}'

# 10. 拒绝一条 pending → 200；列表里它变 rejected，仍**在**列表里
# 11. 删除一条 → 200；列表里它**消失**；若它是该 IP 唯一记录 → 该 IP 能立刻重新申请
# 12. 删除那条已同意的记录 → 200，**用户仍在**（GET /api/admin/users 里还在）
# 13. 越界限额 → 40017；不存在的 id → 40409
```

### 边界与回归

| 用例 | 期望 |
|---|---|
| `REGISTER_ENABLED=false` 重启后提交申请 | 40305；前端登录页**没有**「新用户注册」按钮；客服行仍在 |
| 把 `Server/payment.jpg` 改名后打开弹窗 | 收款码位置是破图/40410 的 message；**表单仍能提交** |
| 普通用户 token 访问 `/api/admin/register-requests` | 40301（既有中间件，不动） |
| 超额用户（`used >= quota_limit`）访问三个公开注册接口 | **正常放行**（公开路径不过限额判定） |
| `?register=1` 直接打开 | 弹窗自动出现；关掉再刷新页面又出现（§7.4 有意行为） |
| 登录页外观 | 深色卡片上 LOGO **没有白/浅色方块背景**；卡片比改动前高 |
| README | 横条比购买按钮明显更宽更醒目；横条点进官网首页；购买按钮点进 `?register=1`；两处文案已按 §11 的表改 |
| **回归**：Spec2 登录/用户管理、Spec18 限额与超额踢出 | 行为一字不变 |

---

## 14. 补充

### 14.1 与 Spec2「账号仅由管理员创建」的关系

Spec2 把"账号只能由管理员创建"当作安全决策（无公开注册 = 无公开攻击面）。**本 Spec 不推翻它**：自助注册仍然不存在，用户能做的只是**提交一份申请**，账号的产生时机与产生者都没变——仍然是管理员点「同意」那一刻、仍然由后端用 `db` 写 `users` 行。变化的是：管理员不用再手工敲用户名和密码了，他从申请记录里直接取。

`AdminPanel.vue` 里那句"账号仅由管理员创建，无公开注册"必须改（§7.5a）——它现在是**不准确的**，而一个不准确的界面说明比没有说明更糟。

### 14.2 为什么申请记录不设 `user_id` 外键

被同意之后，那条申请与它建出来的账号**确实**有关系（同一个用户名）。但：

- **被拒绝的申请没有对应账号**，这个列会是 NULL，于是"有外键"这句话只在半边成立；
- **删号之后台账要留着**（§5.3），有外键就会引出"删号时把台账也删了还是置 NULL"的新决策；
- 台账要回答的问题是"**这次审批发生了什么**"，不是"这个人现在怎么样了"——后者查 `users` 表。

二者通过 `username` 天然可对上（人名即键），需要时一次 JOIN 就能查，而**不设置**它换来的是一条永远不会失效的台账。这与 Spec18 §2.2 里 `user_quota` 独立成表的取舍同源：**该分开的账本不要强行绑在一起**。

### 14.3 两处待定的微调（写入本文档，供实际用起来之后回头改）

1. **「待审批注册用户」区块的位置**：现按用户原话放在用户表格**之后**（页面底部）。若管理员的实际感受是"每次审批都要先滚过用户表"，把它整段挪到 `.admin-table-wrap` **之前**即可——纯模板移动，无逻辑改动（§2.4）。
2. **`REGISTER_IP_WINDOW_SECONDS` 的默认值**：24 小时是照弹窗文案定的。若实际接单时发现"同一个人换了手机又申请一次"这类误伤偏多，把它调小（如 3600）比改文案更省事——两处都改也行，但**改了其中一个就要改另一个**（文案是给用户看的承诺）。
