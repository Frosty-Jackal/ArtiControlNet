# ArtiControlNet Spec 23：自助注册、免费试用额度与三处文案改版

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：**把注册从"提交申请 → 等管理员审批"改成"验证码一过就建号、当场登录进系统"**，新用户自带 **10 次免费试用额度**；顺带改帮助弹窗的 6 处文案、给充值弹窗的参考价加一个划线原价。
> 本 Spec 是 **Spec.md / Spec2~22 的增量补充**，但**推翻 Spec19 的注册审批模型**（§1.3 有完整清单）。
> **删除 1 张表**（`register_requests`，**带数据丢失**）、**删除 4 条管理端路由**、**删除 7 个 db 函数**、**删除 1 封邮件**、**删除 2 个错误码**、**删除 3 个 config 常量**。
> **无新表**、**无新依赖**、**无新持久目录**、**无新 provider / 新模型**、**无新后端文件**、**无新前端组件**。
> **0 个新增环境变量**；改 1 个默认值（`QUOTA_DEFAULT_LIMIT` 25 → 10）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有凭据只在后端环境变量、除 `artcn.db` 外无其他数据库。
> ⚠️ **本 Spec 是不可逆的**：`DROP TABLE register_requests` 之后，Spec19~22 的历史注册申请台账**永久消失**，回滚只能靠**备份文件**（§2.2、§5.3）。

---

## 0. 三件事一览（用户原话 → 落点）

| # | 用户原话 | 本 Spec 的落点 |
|---|---|---|
| 1 | 「新用户注册」里**不展示**预充值提示 / 付款码 / 「用于支付的微信昵称（以便后台核对）」三个填写窗口；填完剩下的信息就能注册成功，不用先充值；**新用户自动送 10 次总调用额度** | §2.1~§2.5、§5.4、§6.1、§7.1、§7.2、§7.3 |
| 2 | 「帮助」里 6 处文案：服务次数那行改写；文生图删「没有参考图？」；图文生图前面加「例如，」；删上传格式那行；标题换成「快速上手ArtiControlNet」；删副标题与「✨」；「服务次数」→「收费政策」 | §7.4（逐字 diff） |
| 3 | 「余额与充值」页那句「充值参考：0.9元约10次设计服务」的「0.9」前面加一个**被横线穿过的 6.99** | §2.8、§5.6、§6.4、§7.5、§8.1 |

> 第 2 条里的「是不是首次进入系统会弹出帮助？」是一个**问句**，不是需求。答案：**是**，`App.vue:125-131` 按用户名记 `artcn_help_seen:<username>`，该账号第一次登录时自动弹一次，之后只在点「帮助」按钮时出现（Spec8 起的行为，本 Spec 不动）。

### 用户在答复里改的口径（**实现时按这一列，不要按上面那列的字面**）

| # | 原话的字面 | 改成 | 为什么 |
|---|---|---|---|
| 1-a | 「用户填写没被取消的信息**就可以注册成功**」 | 注册**不再需要管理员审批**：验证码一过直接建号 | 用户在两选一里明确选了「改成填完即注册成功，不需要审批」。原字面也可以读成"不充值也能**提交申请**"，但那样「送 10 次」就没有落点（限额一直是管理员审批时当场填的），所以按前者做。**这是本 Spec 最大的一处推翻**，§1.3 列了它连带作废的东西。 |
| 1-b | （未提及）审批链路怎么办 | **彻底删除**：表 + 4 条管理端路由 + AdminPanel 审批区 + 审批邮件 + `RegisterApproveRequest` + 2 个错误码 | 用户在二选一里明确选了「彻底删掉」。理由见 §2.2。 |
| 1-c | （未提及）注册相关的两封邮件 | **只留发给管理员的那封**，删掉发给用户本人的「注册成功」 | 用户在多选里只勾了这一项。 |
| 1-d | 「送 10 次总调用额度」 | 落在 `QUOTA_DEFAULT_LIMIT` 上，**25 → 10**，**不新增变量** | 用户在二选一里选了「把 `QUOTA_DEFAULT_LIMIT` 从 25 改成 10」。连带 `create_user` 必须改成显式传值（§2.4，那里有个坑）。 |
| 1-e | 「就可以注册成功」（是否停在登录页） | **建号的同时签发 JWT，前端当场进主界面** | 用户在二选一里选了「直接自动登录进主界面」。 |
| 2-a | 「把『服务次数』换成『收费政策』」 | 标题变「**💰 收费政策**」 | ⚠️ **`💰` 是本 Spec 自己挑的**。用户只要求换字，没说换图标；原文是 `📊`，那个图标是给「服务次数」选的，配「收费政策」别扭。**若要保留 📊，改 `HelpModal.vue` 那一行即可，其余一个字不用动。** |
| 2-b | 服务次数那行给出的是「新注册用户会收到一定的免费试用额度，」（**带逗号，句子没完**） | 后半句「用尽后需充值才能继续使用噢！」**保留**，整行连成一句 | 用户给的是替换**前半句**，结尾的逗号说明后半句还在。新句与旧句的后半段逐字相同，所以这是一次**前半句替换**，不是整行重写。 |
| 3-a | 「请把『0.9』前面加一个被横线穿过的『6.99』数字」 | 划线片段插在「0.9」**紧前面**，即「充值参考：~~6.99~~ 0.9元约10次设计服务」 | 照字面。**不要**把它挪到整句最前面（那样会读成「~~6.99~~ 充值参考：0.9元…」，那个「6.99」就不知道该跟谁比了）。 |
| 3-b | 只点了「余额与充值」页 | **欠费充值面板那句文案不动** | 「请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务」是另一个面（登录页被踢出来时弹的），用户没提它。两句话本来就被 Spec21 §7.3 定为**故意不同**，别"统一"。 |

---

## 1. 功能目的

### 1.1 为什么现在做

- **Spec19 的审批闸门，在 Spec22 之后已经基本是空转的。** 它当初存在的唯一理由是"没有别的办法确认这个邮箱是真的、这个人不是机器"——所以由人来兜底。Spec22 把邮箱验证码接上之后，**"这个人能收到这个邮箱的信"已经被机器验证过了**，管理员点「同意」那一刻其实无事可做：账号名是用户填的、密码是用户设的、邮箱是验证过的，管理员唯一要填的是**额度**。一个只用来填数字的审批，就是一次纯粹的等待。
- **审批带来的等待成本是真实的，而且是唯一一处"非工作时间不可用"的功能。** 用户在注册弹窗里看到的是「已通知管理员，在30秒内会通过短信/邮件告知您注册结果」——那句话本身就是一个承诺：**你得守着**。去掉它，注册从"几分钟到几小时"变成"几秒"。
- **预充值是审批模型的产物，不是产品意图。** 因为要人工填额度，就必须先有人告诉你"他付了多少钱"，于是注册表单里长出了收款码与微信昵称。一旦额度由系统自动给（10 次试用），**这三件东西（预充值提示、收款码、微信昵称）就同时失去了理由**——它们是同一根链条上的三个环。
- **"新用户先付钱"对一个设计工具是错的漏斗。** 用户还没见过一张图就先要扫码付款，这一步的流失率是看不见的（他们根本不会提交申请，你连台账里都看不到）。**先给 10 次试用，用完再让他自助充值**（Spec21 已经把充值做完了），才是这个产品该有的顺序。
- **三处文案是同一件事的三个落点**：定价故事变了（有免费额度了、有折扣价了），说法就得跟着变。帮助弹窗里还写着"每个用户在充值后会获得对应次数"——在送 10 次之后，这句话是**反的**。

### 1.2 一句话架构

**删掉"申请"这个中间态：`POST /api/auth/register` 从"落一条 `register_requests` 行"变成"验完码直接 `db.create_user()` + 签发 JWT"，额度由 `QUOTA_DEFAULT_LIMIT` 一个变量给；连带把审批链路（表 / 路由 / 前端 / 邮件 / 错误码）整条拆掉。**

### 1.3 与既有 Spec 的关系（**本 Spec 推翻的东西**）

| 既有件 | 本 Spec 怎么动它 |
|---|---|
| **Spec19 的注册审批模型** | **整体推翻**。`register_requests` 表、`GET/POST/DELETE /api/admin/register-requests*` 四条路由、`approve/reject/delete_register_request` 三个函数、`RegisterApproveRequest` schema、`admin_list_register_requests` 路由、`AdminPanel.vue` 的「待审批注册用户」整块，**全部删除**。Spec19 里凡以"申请台账"为前提的段落（§2.2 的 UNIQUE 讨论、§2.4 的台账语义、§6.4~§6.7、§7.5b）**随表一起作废**。 |
| **Spec19 的 `POST /api/auth/register`** | **契约变了**：请求体少一个 `wechat`、响应体从 `{id}` 变成 `{token, username, is_admin}`（与 `/api/auth/login` 同形）。**语义从"提交申请"变成"注册"**。 |
| **Spec22 §2.4 的三支查重** | 塌成**两支**（§2.7）。`EMAIL_CODE_PENDING_NOTICE` 常量删除，`db.find_pending_register_by_email` 删除。 |
| **Spec22 §5.7 E / §2.12 的「注册成功」邮件** | **删除** `mailer.send_register_approved_notification`（它挂在被删的 approve 路由上）。Spec20/21/22 三封发给用户的邮件变成**两封**（充值已到账 / 账号已恢复）。 |
| **Spec20 的 `send_register_notification`** | **保留**，但**签名少一个参数**（`wechat`），**正文重写**（§2.6）。Spec20 §13 里那条逐字引用旧签名的验收命令**要改**（§13 前置里列了）。 |
| **Spec21 §7.3 的两个 `price_notice`** | `GET /api/recharge/info` 与 `GET /api/auth/register-config` 的 **`price_notice`(str) 变成 `price_line`(list)**（§2.8）。两个端点形状**故意保持一致**，好让 `RechargeModal` 两个模式共用一个渲染分支。 |
| **Spec18 的 `QUOTA_DEFAULT_LIMIT`** | 默认值 25 → 10，**语义升格**：它从"管理员手工建号的默认值"变成"**新用户的免费试用额度**"。`create_user` 必须改成显式传值（§2.4）。 |
| **Spec22 的 `PublicAuthPaths`（10 条）** | **不变**。`/api/auth/register` 与 `/api/auth/register-config` 都还在原来的位置上，一条不多一条不少。 |
| Spec17 / Spec21 的其余全部 | 一字不动。 |

---

## 2. 决策记录（为什么这么选）

### 2.1 注册改成自助：审批这道闸门为什么可以撤

审批原本挡三件事，逐条看现在还挡不挡得住：

| 原本挡的 | 现在由谁挡 | 结论 |
|---|---|---|
| 邮箱是假的 / 是编的 | **邮箱验证码**（Spec22 §2.2） | 挡住。而且是机器判的，比人判准。 |
| 同一个人反复注册 | **`users.username` 与 `users.email` 的查重**（§5.4 的 ⑧⑩） | 一个邮箱一个号、一个用户名一个号，**都写在库里**。 |
| 注册是机器人刷的 | **登录限速**（同 IP 5 次 / 5 分钟，发码与验码各算一次） | **只挡住一部分**，代价见 §3.3-1。这是本 Spec 最重要的一条已知代价。 |
| 额度被冒领 | **没有挡**——额度本来就是送的 | 见 §3.3-1。上限是 `10 × 刷到的账号数`。 |

**唯一真正失去的是"你本人知道谁注册了"这个信息**，而它由 §2.6 保留的那封通知邮件补回来。

### 2.2 `register_requests` 表与审批链路：**真删**（不可逆）

| 选项 | 为什么不选 |
|---|---|
| 留着表、只删审批动作（历史只读） | 留一张**永远不会有 `pending` 行**的表，管理端还要为它维护一个只读区块——那是死 UI。Spec22 §2.1 为电话三列记过同一条：**留一列谁都不读写的死数据，是"看起来还在生效"的陷阱**。 |
| 表改当"注册台账"继续写行 | 收益是"能看到谁什么时候注册的"，而 `users` 表**已经有** `username` / `created_at` / `email`——那是同一份数据的第二份副本，还要额外停存 `password_hash`、还要给 `status` 一个恒为 `approved` 的假值。 |

**代价（已确认接受）**：Spec19~22 期间的所有历史申请行（含 `pending` / `rejected` 那些**从未建号**的）永久消失，回滚只能靠备份文件。

### 2.3 免费额度 10：复用 `QUOTA_DEFAULT_LIMIT`，不新增变量

一次改动管住三条路：自助注册、管理员手工建号（`POST /api/admin/users`）、新建库的列默认值。**不新增 `REGISTER_TRIAL_QUOTA` 之类的第二变量**——同样是新号，两条路给不一样的额度，以后必然忘。变量名不改（`QUOTA_DEFAULT_LIMIT`），只在注释里写明它现在就是「新用户免费试用额度」（§8.1）。

### 2.4 ⚠️ `create_user` 必须**显式**写 `quota_limit`（**列 DEFAULT 已经烤死在存量库里**）

**这是本 Spec 最容易漏、且漏了不报错的一处。**

`db.create_user()` 现在的 INSERT **不带 `quota_limit`**，靠的是 `_CREATE_TABLE` 里那行 `quota_limit INTEGER NOT NULL DEFAULT {_QUOTA_DEFAULT}`。而 SQLite 的列默认值是**建表那一刻写进 schema 的字符串**——对一个**已经存在**的库，`CREATE TABLE IF NOT EXISTS` 直接跳过，**把 `QUOTA_DEFAULT_LIMIT` 改成 10 对它没有任何影响**，那台机器上的默认值永远是 25。

后果：本机（存量库）上「管理员手工建号」给 **25**，而「用户自助注册」给 **10**，同一个系统两个价，而且**看代码看不出来**（代码里只有一个 `_QUOTA_DEFAULT`）。

**做法**：`create_user` 的 INSERT 显式带上 `quota_limit`,值取 `_QUOTA_DEFAULT`。

```python
cur = conn.execute(
    "INSERT INTO users (username, password_hash, is_admin, created_at, email, quota_limit) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    (username, password_hash, 1 if is_admin else 0, _now_iso(), email, _QUOTA_DEFAULT),
)
```

**不动 DDL 里那行 `DEFAULT`**（存量库改不掉，新库留着无害且与新值一致），但要知道它从此刻起是**仅供参考**的——真正的来源是 `_QUOTA_DEFAULT` 与那次显式传值。

### 2.5 注册成功即自动登录

后端在建号的同一个响应里签发 JWT，响应体**与 `/api/auth/login` 逐字同形**：`{token, username, is_admin}`。

- **不额外返回 `quota_limit`**：登录也不返回它，前端的余额来自 `GET /api/recharge/info`（Spec21 §2.9）。多一个只有注册才有的键，就是让前端为"我刚注册"这条路径写分支。
- 前端在 `store/auth.js` 里加一个 `register(...)` action，**收尾三行照抄 `loginByEmail`**（token / username / is_admin 一落，`App.vue` 的 `v-if` 自动切到聊天视图）。调用方（`RegisterModal`）不需要做任何事。
- **连带的好处**：`auth.username` 变化会触发 `App.vue` 那个 watcher，于是**首次登录自动弹帮助**的逻辑对"刚注册的人"自动生效——这正是我们想要的（他刚读完 §7.4 改过的那份帮助）。

### 2.6 邮件：只留给自己那封，正文重写

| 决策 | 选择 | 理由 |
|---|---|---|
| 留哪封 | **只留 `send_register_notification`**（发给你，收件人 `REGISTER_NOTIFY_TO`） | 用户在多选里只勾了这一项。它现在承担的是"**你知道有人注册了**"——在审批撤销之后，这是唯一的人工感知渠道（也是发现批量刷号的情报来源）。 |
| 删哪封 | **删 `send_register_approved_notification`** | 它的唯一挂点是 `POST /api/admin/register-requests/{id}/approve`，那条路由整个删了。**不是**把它改挂到注册路由上——那等于给每个注册的人发一封"你注册成功了"的邮件，而他人就在页面上看着成功提示（用户也没勾它）。 |
| 签名 | `send_register_notification(username, contact, created_at_iso)` —— **少一个 `wechat`** | 微信昵称不再是注册信息。**删参数不是留默认值**（Spec22 §5.1 为 `phone` 记过同一条：留参数就是留一条能写进已删概念的路）。 |
| 主题 | `ACN-{username}-{contact}` **不变** | 主题里没有微信昵称，不需要动。不变意味着 Spec20 §13 里那条 grep 主题的验收命令仍然有效。 |
| 正文 | **重写**（§5.6 给了逐字的新字符串） | 旧正文是「微信充值账号是{wechat}，注册时间是{...}，请立即审批！」——**三个词全废**：微信昵称没了、「请立即审批」没有审批了、而"注册时间"这个措辞可以留。⚠️ **新正文是本 Spec 拟的，用户没给原文**（与 Spec22 §8.1 第三句提示语同一处境），所以 §5.6 里把它单独标出来了。 |
| `register_id` 那几个日志字段 | **从 `_FIELDS` 白名单里删掉** | 它的四个生产者（注册路由、三条审批路由、那封被删的邮件）**全部消失**（§10.1）。 |

### 2.7 发码查重从三支塌成两支

`_reject_duplicate_email` 的 `register` 分支现在是三支，删掉中间那支：

| purpose | 判据 | 结果 |
|---|---|---|
| `register` | 邮箱已在 `users` | 40907「已注册账号{username}，请前往登录界面…」（**不变**） |
| ~~`register`~~ | ~~已有 `pending` 申请~~ | **删除**（表没了） |
| `login` / `reset` | 邮箱不在 `users` | 40907「还未注册，请宝子前往新用户注册~」（**不变**） |

代码与它自己的 docstring 表格一起塌（**那张表格是这张文档里唯一描述三支的地方，别只删代码不删表**）：

```diff
 def _reject_duplicate_email(email: str, purpose: str, request_id: str) -> None:
     """发码前的查重（Spec22 §2.4 那张表）。命中即记 `email_code.rejected` 并抛 40907。
 
     | purpose | 判据 | 结果 |
     |---|---|---|
     | `register` | 邮箱已在 `users` | 40907「已注册账号{username}，请前往登录界面…」 |
-    | `register` | 已有 `pending` 申请 | 40907「该邮箱已提交过注册申请，请等待管理员审批」 |
     | `login` / `reset` | 邮箱不在 `users` | 40907「还未注册，请宝子前往新用户注册~」 |
 
-    三句话共用一个码（40907）：前端本来也不需要知道是哪一种，显示 message 就完了。
+    两句话共用一个码（40907）：前端本来也不需要知道是哪一种，显示 message 就完了。
     文案**全部来自 config**，前端零副本（与 QUOTA_EXCEEDED_MESSAGE 同一原则）。
+
+    Spec23 §2.7：register 分支的中间那支（既有 pending 申请）随 register_requests
+    表一起删除。于是 register 分支剩下的判据与 login/reset 分支**互为镜像**
+    （一边查"在不在"，另一边查"不在不在"），但**不合并**：两句话不一样，
+    而且 register 那句要 .format(username=...)。
     """
     if purpose == "register":
         user = db.get_user_by_email(email)
         if user is not None:
             reason = "registered"
             message = config.EMAIL_CODE_REGISTERED_NOTICE.format(username=user["username"])
-        elif db.find_pending_register_by_email(email) is not None:
-            # 删掉 IP 冷却之后，这是"同一个人反复提交、你反复收到同一份审批邮件"
-            # 的**唯一**闸门（§2.4）。别把它当成可有可无的一层。
-            reason, message = "pending", config.EMAIL_CODE_PENDING_NOTICE
         else:
             return
     elif db.get_user_by_email(email) is None:
```

> ⚠️ `reason` 那个变量的取值集合同时少了一种（`"pending"`）。它只出现在 `email_code.rejected` 这条日志里，**不是** `_FIELDS` 白名单项，不需要动白名单。

**代价**：Spec22 §2.4 那句"这是'同一邮箱反复提交、你反复收到同一份审批邮件'的**唯一**闸门"随表一起失效（§3.3-1）。

### 2.8 划线价：后端下发**排版片段**，不是 `v-html`，也不是前端去找「0.9」

需求是「在『0.9』**紧前面**插一个带删除线的『6.99』」——删除线在**句子中间**。三个做法：

| 做法 | 为什么不用 |
|---|---|
| 前端用 `v-html` 渲染后端给的 `<s>6.99</s>…` | **这是一个 XSS 面**。今天这句话来自服务端常量，但那是"目前恰好安全"，不是结构性保证。 |
| 前端在 `price_notice` 里找 `"0.9"` 插进去 | 等于把**价格复制到前端**——本仓从 Spec18 起对提示语一律"前端零副本"，而价格是这句话里最不能漂移的部分。 |
| 后端返回两个键（`price_original` + `price_notice`），前端拼 | 拼不出"句中"这个位置：`<s>6.99</s>` 只能落在整句前面。 |
| **后端返回"排版片段"数组** ✅ | 位置信息是**数据**，不是约定。前端只有一个 `v-for`，没有解析器、没有 `v-html`、没有一个字的中文。 |

```python
RECHARGE_PRICE_LINE = (
    {"text": "充值参考："},
    {"text": "6.99", "strike": True},
    {"text": " 0.9元约10次设计服务"},
)
```

**`register-config` 那句也换成同一个形状**（`REGISTER_PRICE_LINE`，**单片段、无删除线**）：`RechargeModal` 两个模式把价格读进**同一个 ref**、走**同一个渲染分支**，形状不一致就得为一个字段分两种写法。**欠费面板那句文案本身一个字不改**（§0 第 3-b 条）。

> ⚠️ 「6.99」与「0.9」的**数字口径故意不一致**（前者是划掉的原价、后者是实收价折算的参考次数），这与 Spec21 §2.9 那条"余额公式与 `RECHARGE_PRICE_NOTICE` 口径故意不一致"是同一类东西——**别去"统一"**。

### 2.9 帮助那三处**连带修改**（删元素必须跟着动的地方）

删文案不是纯删行——有三处会因此变成死代码或坏布局：

| 删了什么 | 连带要做什么 | 否则会怎样 |
|---|---|---|
| `.help-lead`（副标题整行） | 删掉 `HelpModal.vue` 里那条 `.help-lead` CSS 规则；把它原有的 `margin-bottom: 20px` **挪给 `.help-title`** | 标题与第一张卡片会贴在一起；同时留一条没人用的 CSS 规则 |
| `.help-tip`（上传格式那行） | `.help-foot` 从 `justify-content: space-between` 改成**居中**；删掉 640px 媒体查询里那段 `flex-direction: column` | `space-between` 只有一个子元素时会把它**顶到左边**，按钮不在中间了；那段响应式规则也永远不再生效 |
| `.help-explore` 里的 `✨` | 只删那个字符，**别删整行** | 整行删掉会连带丢掉「以上三种只是基础玩法，更多神奇进阶功能，等你自己探索。」这句用户没要求删的话 |

### 2.10 存量用户**不追溯**

当时拿 25 次的账号**保持 25**，不改成 10。理由：改这个数只该影响**以后**新建的号；把已发出去的额度收回去是另一件事（而且 `user_quota.used` 已经涨上去了，收回 `quota_limit` 会让一些账号**立刻变成超额**被踢下线）。**用户在答复里已知悉这一点。**

---

## 3. 需求边界

### 3.1 范围内

**后端**

- `Server/db.py`：删 `_CREATE_REGISTER_REQUESTS_TABLE` 与 `_CREATE_REGISTER_REQUESTS_STATUS_INDEX` **两个常量** + 7 个函数 + `_register_row_to_dict`；新增 `_migrate_drop_register_requests()`；改 `_migrate_users_contact()`（删回填段）；**改 `_migrate_lowercase_emails()`（元组去 `register_requests`）**；改 `create_user()`（显式传 `quota_limit`）；`init_db()` 删两行 + 顺序调整（§5.3）。
- `Server/main.py`：`POST /api/auth/register` 改造（§5.4）；删 4 条管理端路由 + `admin_list_register_requests`；`_reject_duplicate_email` 塌成两支；`GET /api/auth/register-config` 的 `price_notice` → `price_line`；`GET /api/recharge/info` 的 `price_notice` → `price_line`；import 清理。
- `Server/schemas.py`：`RegisterRequestCreate` 删 `wechat`；**删** `RegisterApproveRequest`。
- `Server/errors.py`：**删** `RegisterRequestNotFoundError`(40409)、`RegisterAlreadyReviewedError`(40903)。
- `Server/config.py`：`QUOTA_DEFAULT_LIMIT` 默认 25 → 10；`REGISTER_PRICE_NOTICE` → `REGISTER_PRICE_LINE`；`RECHARGE_PRICE_NOTICE` → `RECHARGE_PRICE_LINE`；**删** `EMAIL_CODE_PENDING_NOTICE`。
- `Server/mailer.py`：`send_register_notification` 去 `wechat` 参数 + 重写正文；**删** `send_register_approved_notification`。
- `Server/logging_setup.py`：`_FIELDS` **删** `"register_id"` 与 `"has_email"`（§10.1）。
- `Server/.env.example`：改 `QUOTA_DEFAULT_LIMIT` 的注释与默认值。

**前端**

- `views/RegisterModal.vue`：删 `.reg-pay` 块、删微信昵称那一组、删 `config` prop、成功屏改自动登录。
- `views/HelpModal.vue`：6 处文案 + 3 处连带（§7.4）。
- `views/RechargeModal.vue`：`priceNotice`(str) → `priceLine`(list)，模板改 `v-for`。
- `views/AdminPanel.vue`：删「待审批注册用户」整块 + `requests` state + 4 个方法 + import；**CSS 一行不动**（§14 陷阱 1）。
- `views/Login.vue`：`<RegisterModal>` 去掉 `:config` 绑定。
- `store/auth.js`：+`register(username, password, email, code)`。
- `api/chatApi.js`：`submitRegisterRequest` 改签名与返回值注释；**删** `listRegisterRequests` / `approveRegisterRequest` / `rejectRegisterRequest` / `deleteRegisterRequest`；`getRegisterConfig` / `getRechargeInfo` 的返回注释改键名。

**文档**：`specs/Spec23.md`（本文）、`CLAUDE.md`。

### 3.2 不在范围内（明确不做）

| 不做的事 | 为什么不 |
|---|---|
| **不做"同一 IP 每日注册上限"** | 它是本 Spec 最明显的补丁，但会**误伤校园 / 实验室 / 宿舍 NAT 下的正常用户**（Spec22 §3.3-7 已经为点击统计记过同一类偏差）。误伤是**当场可见**的，刷号是**事后才发现**的。**要加也应该是独立的一次决策**，先看这次上线后的实际注册量。 |
| **不给 `users.email` 加 UNIQUE 约束** | Spec22 §2.8 的立场不变：查重是业务规则，约束面变更的风险大于收益。 |
| **不动 Spec22 的三条邮箱链路（登录 / 重置密码 / 发码）** | 除 §2.7 那一处查重塌分支外，一个字不动。 |
| **不动充值链路** | `recharge_requests` 的台账语义（`pending` / `approved` / `rejected` 三态 + 可再申请 + 冷却）**完全保留**——它是**收钱**的台账，与注册台账不是一回事。 |
| **不动 `<RegisterModal>` 的"账号 / 密码 / 确认密码 / 邮箱 / 验证码"五个字段与它们的校验** | 用户只要求删三个东西。密码下限仍是 2（Spec22 §2.10）、邮箱仍必填、二次确认仍只在前端判。 |
| **不做"注册后引导去充值"的任何弹窗 / 横幅** | 用户没要求。帮助里那句「新注册用户会收到一定的免费试用额度」（§7.4）就是全部的用户教育。 |
| **不清理 `users` 里手工建号留下的 `email = NULL`** | 那是**允许的形态**（Spec21 §3.3-6）。它们不能邮箱登录，但能密码登录——本次不动。 |
| **不动 `README.md` 第 95 行那句「每个账号都有一定次数免费额度，用完后需要联系管理员按量付费噢」** | 它**在 Spec21 做自助充值时就已经陈旧了**（"联系管理员"→ 早就可以自己充值），不是本 Spec 引入的。⚠️ **记在这里**：本 Spec 之后这句话离现实更远了一点（现在真的有免费额度了），**要改它是一次独立的文档改动**。 |
| **不动 `GithubPage/` 下的任何图与页** | 同上。 |

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **⚠️ 唯一的防线是登录限速，而且它很窄。** 撤销审批之后，注册的刹车只剩 Spec2 的登录限速（**同 IP 5 次 / 5 分钟 → 42901**），而发码与验码**各算一次**（Spec22 §2.6）——所以一个 IP 大约**每 5 分钟能注册 2 个账号**，每个账号自带 **10 次**免费调用。能刷的人需要 **N 个邮箱 + N 个出口 IP**，成本不为零但也不高。**上限 = 10 × 刷到的账号数**（上游是真花钱的，所以这不是"数据被偷"，是"账单变长"）。**已知、已接受**；补丁方案见 §3.2 第一行，是独立决策。
2. **校园 / 公司 NAT 下会误伤。** 同一出口 IP 的一群人共享那 5 次 / 5 分钟。Spec22 §3.3-7 为点击统计记过同一件事，这里更痛——**点击统计只是少算一个数，注册失败是用户直接走掉**。唯一的缓解是用户自己的手机热点。**这是本 Spec 引入的最实际的可用性风险。**
3. **`register_requests` 的历史数据永久丢失。** 含 Spec19~22 期间所有**被拒绝**的申请（那些人从未建号）。**回滚 = 用备份文件**，没有别的办法（与 Spec22 删电话三列同款）。
4. **用户名冲突的报错从"审批时"提前到"注册时"。** 原来两个人可以用同一个用户名提交申请，先被同意的拿到号；现在**先注册的拿到号**，后一个看到 40001「用户名已存在」。这是**改善**（用户当场就知道要换一个），但也意味着 §5.4 的 ⑩ 从"提前告知"变成了**真正的闸门**——它的判据仍只是"查一次库"，唯一的原子保证依然是 `users.username` 的 UNIQUE 索引（并发时由 `IntegrityError` → 40001 兜底，`create_user` 里已经这么做了）。
5. **注册验证码可以在 TTL 内被重放，但重放已经没有价值。** Spec22 §3.3-9 记过"码在 10 分钟内可重复使用"。现在同一个码第二次提交会在 ⑧（邮箱已注册）被拦——因为第一次提交**已经把那个邮箱注册掉了**。所以这个已知边界在注册这条路上**自动闭合**了（登录 / 重置密码两条路不变）。
6. **注册通知邮件里没有"微信昵称"了。** 你在审批时代靠"支付微信"对账的那套流程**只对充值有效**（`recharge_requests.wechat` 一个字没动）。**注册与对账从此刻起完全无关**——这是本 Spec 的设计意图，不是遗漏。
7. **帮助里的「一定的免费试用额度」是一个模糊词，而实际是 10 次。** 用户给的原文就是"一定的"，本 Spec 照抄。**所以改 `QUOTA_DEFAULT_LIMIT` 不需要同步改帮助文案**——这是那句话唯一的优点，别把它"写具体"成"10 次"。
8. **`💰` 是自选的图标**（§0 第 2-a 条），不是用户要求的。
9. **新通知邮件正文的措辞是本 Spec 拟的**（§2.6），用户没给原文。
10. **「送 10 次」实际能用 **11** 次。** 这不是本 Spec 引入的，是 Spec21 §5.7 那条判据（`used > quota_limit`，而非 `>=`）的直接推论：新号 `used=0`、`quota_limit=10`，第 11 次调用时 `used` 才等于 10，`10 > 10` 为假 → **放行**；第 12 次时 `used=11 > 10` 才被拦。**已确认是有意口径**（"限额用满还能再用一次"，避免"钱花了结果拿不到"），所以不去"修"。写在这里只是因为本 Spec 第一次把"送几次"当成一句用户可见的话说出来——**如果哪天要对外承诺精确数字，承诺的是 10，用户看到的是 11，这是已知的一格偏差。**
    - 顺带记一条**不成立**的担心：新号在库里**没有** `user_quota` 行（那行由首次 `record_call` 的 `ON CONFLICT DO UPDATE` 建）。`_USER_SELECT` 用 `LEFT JOIN ... COALESCE(q.used, 0)`，缺行退化成 `used=0`——**这正是对的**（他确实一次没用过），限额判定不会因此变成"无限免费"。**别为此在 `create_user` 里补一条 `INSERT INTO user_quota`**：那会给"用户可能还没有 user_quota 行"这个被显式设计过的降级路径引入第二个建行的地方。

---

## 4. 技术栈增量

| 项 | 增量 |
|---|---|
| 新依赖（`requirements.txt`） | **0** |
| 新后端文件 | **0** |
| 新前端组件 / 工具 | **0** |
| 新表 / 新列 | **0** |
| 删除的表 | **1**（`register_requests`） |
| 新环境变量 | **0** |
| 改默认值的环境变量 | **1**（`QUOTA_DEFAULT_LIMIT` 25 → 10） |
| 新错误码 | **0** |
| 退休错误码 | **2**（40409、40903） |
| 新路由 | **0** |
| 删除路由 | **4**（管理端注册审批四条） |
| 新增 / 修改的邮件函数 | **-1 / 1** |

---

## 5. 架构设计（增量）

### 5.1 删除面总表（**一张表看全，逐项打勾用**）

**后端**

| 文件 | 删掉的东西 |
|---|---|
| `db.py` | 常量 `_CREATE_REGISTER_REQUESTS_TABLE` 与 `_CREATE_REGISTER_REQUESTS_STATUS_INDEX`；函数 `create_register_request` / `get_register_request` / `list_register_requests` / `find_pending_register_by_email` / `approve_register_request` / `reject_register_request` / `delete_register_request` / `_register_row_to_dict`；`init_db()` 里 `conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)` 与 `conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)` **两行都要删**；`_migrate_users_contact()` 里的回填 `UPDATE`；⚠️ **`_migrate_lowercase_emails()` 的循环元组去掉 `"register_requests"`**（不改则删表后**每次启动都崩**，§5.3） |
| `main.py` | 路由 `GET /api/admin/register-requests`、`POST /api/admin/register-requests/{id}/approve`、`POST /api/admin/register-requests/{id}/reject`、`DELETE /api/admin/register-requests/{id}`；import 里的 `RegisterRequestNotFoundError` / `RegisterAlreadyReviewedError`；`_reject_duplicate_email` 的 `pending` 分支 |
| `schemas.py` | `RegisterApproveRequest`；`RegisterRequestCreate.wechat` |
| `errors.py` | `RegisterRequestNotFoundError`(40409)、`RegisterAlreadyReviewedError`(40903) |
| `config.py` | `EMAIL_CODE_PENDING_NOTICE`；`REGISTER_PRICE_NOTICE`（改名，不是纯删） |
| `mailer.py` | `send_register_approved_notification` |
| `logging_setup.py` | `_FIELDS` 里的 `"register_id"`、`"has_email"` |

**前端**

| 文件 | 删掉的东西 |
|---|---|
| `views/RegisterModal.vue` | `.reg-pay` 整块、微信昵称 label+input、`wechat` ref、`config` prop、`done` 那一屏 |
| `views/AdminPanel.vue` | 「待审批注册用户」`<section>` 整块、`requests` ref、`listAllRequests` / `approve` / `reject` / `removeRequest` 四个方法、四个 import、`busyRegId` ref |
| `api/chatApi.js` | `listRegisterRequests` / `approveRegisterRequest` / `rejectRegisterRequest` / `deleteRegisterRequest` |
| `views/Login.vue` | `<RegisterModal>` 上的 `:config="regCfg"`（`regCfg` 本身**保留**——`enabled` 与 `contact_email` 还在用） |

> ⚠️ **前端一处都不许删的 CSS**：`AdminPanel.vue` 的 `.reg-admin` / `.reg-admin-title` / `.reg-admin-empty` / `.reg-row` / `.reg-row-info` / `.reg-row-user` / `.reg-row-cell` / `.reg-row-time` / `.reg-row-actions` / `.reg-row-done`，以及 `main.css` 里的 `.reg-pay` / `.reg-qr` / `.reg-pay-title` / `.reg-done-text`。**它们全都有第二个消费者**（充值台账 / `RechargeModal`），见 §14 陷阱 1。

### 5.2 `db.py` 的增删清单

**删除**

```python
# Spec23 删除：register_requests 整张表与它的 7 个函数 + _register_row_to_dict
#   注册不再是"申请 → 审批"，表没有生产者了（§2.2）。
#   留在库里的是 DROP TABLE（§5.3），不是这张表的定义。
_CREATE_REGISTER_REQUESTS_TABLE = """..."""

# Spec23 删除（Spec22 §5.5 已删过它的兄弟 find_recent_register_by_ip）：
#   find_pending_register_by_email(email)
#   唯一消费者是发码前的查重（Spec22 §2.4 三支里的"已提交过申请"那支），
#   表没了，那支也没了（§2.7）。
```

**改：`_migrate_users_contact()` —— 只留"补列"，删掉"回填"**

```python
def _migrate_users_contact(conn: sqlite3.Connection) -> None:
    """存量库补 users.email 列（Spec21 §5.1）。

    Spec23 §2.2：**回填那一段整个删掉**——回填源 register_requests 已经不存在了。
    函数因此瘦成"补一列"，连 `else: return` 都不需要了：那个分支原本的语义是
    "补过列就不再回填"，没有回填之后它无事可做。

    已知边界（原 §3.3-7，**随回填一起作废**）：用户被删后重建同名账号时，回填会把
    前一个人的联系方式填到新账号上——那个边界是**回填**带出来的，回填没了，边界也没了。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        # 日志去掉"并回填"三个字：这个函数不再回填任何东西。
        logger.info("users.email 列已补齐", extra={"event": "db.migrate"})
```

**改：`_migrate_lowercase_emails()` —— 循环元组少一个表（⚠️ 不改就崩）**

```python
    # Spec23：register_requests 已删（§2.2），元组只剩 users。
    # ⚠️ 这一处**必须改**，而且它与 §5.3 的顺序约束是**两条独立的保险**：
    #    · 只改顺序（把 DROP 排到这里之后）而不改元组 → 第一次启动没事，
    #      **第二次启动**在这行 UPDATE 上抛 "no such table" —— 服务再也起不来。
    #    · 只改元组而不改顺序 → 已在跑的库没事，但一个 pre-Spec23 的库升级上来时，
    #      DROP 先跑、这里再 UPDATE users 之前那个表已经没了 → 同样崩。
    #    两条都做，才既对"升级那次"成立、也对"之后每一次"成立。
    # 注释里的"两条 UPDATE 各自幂等"一并改成"一条 UPDATE 幂等"。
    for table in ("users",):
        conn.execute(f"UPDATE {table} SET email = LOWER(email) WHERE email <> LOWER(email)")
    conn.commit()
```

> ⚠️ **回填删掉之后，本函数与 `_migrate_drop_register_requests` 之间已经没有数据依赖**（它不再读那张表）。但**位置仍要求"补列在前"**，理由与 Spec22 §5.1 那条同款：将来若有人把回填加回来、或加一条新的以这张表为源的迁移，排错顺序的代价是静默丢数据，而写死顺序的成本是 0。
>
> ⚠️ **本 Spec 真正的硬顺序约束在下一节**：`_migrate_drop_register_requests` 必须排在 **`_migrate_lowercase_emails`** 之后（§5.3）——那条排错了服务起不来。

**改：`create_user()`** —— INSERT 显式加 `quota_limit`（§2.4 的坑）

```python
def create_user(username: str, password_hash: str, is_admin: bool = False,
                email: str | None = None) -> dict:
    """建号。email 只有**自助注册**这条路会传（Spec23 §2.1）；管理员手工建号
    （`POST /api/admin/users`）不传，落 NULL，前端显示「无」。

    Spec21 §5.1 加 email 列时，它的唯一来源是"审批通过时把申请行的邮箱带过来"；
    Spec23 撤销审批之后，注册路由自己建号、自己带 email——**传参的人换了，字段没变**。

    Spec22 §5.1：`phone` 参数**整个删掉**，不是留个默认值——留参数就是留一条
    能写进已删列的路。Spec23 沿用同一条规矩：**没有 wechat 参数**。

    ⚠️ Spec23 §2.4：`quota_limit` 必须**显式**出现在 INSERT 里。列上的
    `DEFAULT {_QUOTA_DEFAULT}` 是建表那一刻烤进 schema 的，对一个**已存在**的库，
    改 `QUOTA_DEFAULT_LIMIT` 对它毫无影响——不显式传值，存量库上这里永远给 25。
    """
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at, email, quota_limit) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, _now_iso(), email, _QUOTA_DEFAULT),
            )
            conn.commit()
            user_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        # Spec23 §3.3-4：自助注册之后，这里是用户名唯一性的**唯一**原子保证
        # （旧流程还有"管理员点同意时撞 UNIQUE"兜底，现在没有了）。
        raise DuplicateUsernameError(f"用户名已存在: {username}") from exc
    return get_user_by_id(user_id)
```

**改（注释）：`delete_user()` 的 docstring 与注释里两处提到 `register_requests`**

`db.py:1053-1054` 与 `:1062` 的括号注（"register_requests 不在级联清单里——它是审批台账且没有 user_id"）**描述一张不再存在的表**。删掉那两句括号注即可，**级联清单本身一行不动**（它本来就不含 `register_requests`）。同款：`db.py:2151` 那句"排序写法与 `list_register_requests` 同款"要改指 `list_recharge_requests` 自己。

**新增：`_migrate_drop_register_requests()`**

```python
def _migrate_drop_register_requests(conn: sqlite3.Connection) -> None:
    """删掉 register_requests 表（Spec23 §2.2）。**不可逆**，回滚只能靠备份文件。

    判据是 sqlite_master 里还有没有这张表（而不是"表里有没有行"）——空表同样要删，
    留着它就是留一个"看起来还在生效"的空壳（Spec22 §2.1 的同一条理由）。

    ⚠️ 硬位置约束：**必须排在 _migrate_lowercase_emails 之后**（§5.3 那张表）。
    那一步会 `UPDATE register_requests SET email = LOWER(email)`，排在它前面的话
    表先没了、它当场抛 `no such table`，**服务起不来**。这是本 Spec 唯一一条
    "排错就崩"的约束（其余几条排错只是静默失效或读取顺序难看）。
    ⚠️ 同时 §5.2 那个元组也要改——**两条缺一不可**：只改顺序不改元组，
    第二次启动崩；只改元组不改顺序，升级那一次崩。

    另两条软约束（排错不报错，但顺序是错的）：_migrate_users_contact 历史上读过
    这张表（回填，今天已删）、_migrate_drop_phone_and_ip 会对它做 PRAGMA
    （对不存在的表返回空集，无害）。

    幂等：第二次启动时 sqlite_master 判据为假，直接返回，不打日志。
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'register_requests'"
    ).fetchone()
    if row is None:
        return
    conn.execute("DROP TABLE register_requests")
    logger.warning(
        "register_requests 表已删除（Spec23：注册改为自助，审批台账不再产生）"
        "——此操作不可逆，历史申请数据已永久丢失",
        extra={"event": "db.migrate", "reason": "register_requests_dropped"},
    )
```

> **用 `logger.warning` 而不是 `info`**：这是本仓唯一一条"删掉了一张带数据的表"的迁移日志，Spec22 的删列用的是 warning（`sqlite_too_old` 那条），对齐它。将来在日志里搜"我的申请记录呢"，这行就是答案。

**`_register_row_to_dict` 一并删掉**：它唯一的作用是把 `register_requests` 的行转成 dict，消费者只有被删的那 7 个函数。⚠️ 别把它与 `_row_to_dict`（`users` 的）搞混——后者留着。

**`_USER_SELECT` / `_row_to_dict` / `set_user_quota` / `user_quota` 全部不动。**

### 5.3 `init_db()` 的调用顺序（位置约束总表）

`init_db()` 里**碰过 `register_requests` 的地方一共四处**，删表必须排在它们之后。**第 1、2 处排错只是"读起来不对"或静默失效；第 3、4 处排错是服务起不来**——而第 4 处不经手顺序（它就是那两行代码本身，删不删的问题），所以**真正的顺序约束只有第 3 处**：

| # | 位置 | 它怎么碰这张表 | 排错了会怎样 |
|---|---|---|---|
| 1 | `_migrate_users_contact` (872) | 历史上 `UPDATE ... (SELECT r.email FROM register_requests ...)` 回填 | 今天回填已删（§5.2），**无实际影响**；顺序仍写死，见下 |
| 2 | `_migrate_drop_phone_and_ip` (876) | `PRAGMA table_info(register_requests)` + `ALTER TABLE register_requests DROP COLUMN` | 对不存在的表 PRAGMA 返回**空集**，不报错 → 静默变成无操作，**可接受** |
| 3 | `_migrate_lowercase_emails` (879) | **`UPDATE register_requests SET email = LOWER(email)`** | **`sqlite3.OperationalError: no such table` → 启动直接失败** |
| 4 | `init_db` 的建表/建索引两行 (855 / 858) | `CREATE TABLE ...` / `CREATE INDEX ... ON register_requests` | 同上，**启动直接失败** |

```python
        # Spec19 §5.1a：注册申请表。   ← Spec23 删除：这两行整行删掉
        # conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)
        # Spec22 §5.8 删除：conn.execute(_CREATE_REGISTER_REQUESTS_IP_INDEX)
        # Spec23 删除：conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)
        #   ⚠️ 这个**索引**那行与建表那行同样致命：CREATE INDEX ... ON register_requests
        #      对不存在的表直接报错。Spec22 已经为 ip 索引踩过一次，
        #      那条"漏删就起不来"的注释就写在它上面一行，照着同一个教训处理。
        #      （常量 _CREATE_REGISTER_REQUESTS_STATUS_INDEX 也要一并删，§5.2）

        # Spec21 §5.1：users 补 email（Spec23 起只补列、不回填，因为回填源要没了）。
        _migrate_users_contact(conn)

        # Spec22 §5.1：删掉 users.phone / register_requests.phone / register_requests.ip。
        # ⚠️ 位置约束：必须排在 _migrate_users_contact 之后（Spec22 §5.1）。
        # Spec23 之后这张表已经不在了 → PRAGMA 返回空集 → 这段对 register_requests
        #   自然变成无操作（users.phone 那半照常工作）。**不要**给它加"表不存在就跳过"
        #   的判断——PRAGMA 对不存在的表返回空 list 本来就是它的行为，加判断是多余的。
        _migrate_drop_phone_and_ip(conn)

        # Spec22 §2.8：存量邮箱小写化。
        # ⚠️ Spec23：它的循环元组必须从 ("users", "register_requests") 改成 ("users",)
        #    ——见 §5.2。**这一条与下面那行的顺序是两道独立的保险，都要做。**
        _migrate_lowercase_emails(conn)

        # Spec23 §2.2：删掉 register_requests 表。⚠️ 不可逆。
        # ⚠️ 硬位置约束（排错了**服务起不来**，不是"读起来不对"）：
        #   必须排在 _migrate_lowercase_emails **之后**——那一步会
        #   UPDATE register_requests.email，表先没了它当场抛 no such table。
        #   这是本 Spec 唯一一条"排错就崩"的约束。
        # 两条软约束（排错不报错，但读起来是错的顺序）：
        #   · _migrate_users_contact 历史上读过这张表（回填），今天回填已删
        #   · _migrate_drop_phone_and_ip 会对这张表做 PRAGMA（对不存在的表返回空集）
        _migrate_drop_register_requests(conn)
```

**四条必须写进代码注释的顺序约束**：

1. **建表那行与建索引那行都要删**，不能留 `CREATE TABLE IF NOT EXISTS` + 后面的 `DROP TABLE`——那样每次启动都建了又删，`sqlite_master` 判据永远为真、日志里每次都有那条 warning。**索引那行漏删的后果更重：启动直接失败。**
2. **`_migrate_lowercase_emails` 的元组要去掉 `"register_requests"`**（§5.2），且删表排在它**之后**。只做一件都不够：只改顺序不改元组 → 第一次启动没事、**第二次启动崩**；只改元组不改顺序 → 已在跑的库没事、**升级那一次崩**。
3. `_migrate_drop_register_requests` 排在**所有**会碰这张表的迁移之后，紧随 `_migrate_lowercase_emails` 即可（不必放到文件最后）。
4. 全流程在**一个事务**里（`with _connect() as conn:` + 末尾 `conn.commit()`），与现状一致——`DROP TABLE` 与其它迁移同生同死。

### 5.4 `main.py` 的注册路由（改造后逐行）

```python
@app.post("/api/auth/register")
async def register(payload: schemas.RegisterRequestCreate, request: Request,
                   background_tasks: BackgroundTasks,
                   x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """自助注册（Spec23 §5.4，Spec22 §6.1 的改造版）：**验证码一过直接建号 + 签发 JWT**。

    与旧版（Spec19/22）的区别，按影响面排序：
      1. **不再落申请行**——`db.create_register_request` 换成 `db.create_user`（§2.1）
      2. **响应体从 {id} 变成 {token, username, is_admin}**，与 /api/auth/login 逐字同形（§2.5）
      3. **请求体少一个 wechat**（§0 第 1 条）——连带删掉那一条格式校验
      4. 不再有"审批"这个概念，所以 `auth.register_submitted` 事件改名 `auth.registered`

    校验顺序即契约（顺序变了，用户体验就变了）：格式 → 邮箱已注册 → 验证码 → 用户名占用。
    ⚠️ **⑧ 必须排在 ⑨ 之前**（Spec22 §6.1 记过）：查重不泄露新东西——发码那条路本来
    就会把同一句话说给任何知道这个邮箱的人（Spec22 §3.3-3）；而对**填错邮箱的正常用户**，
    这个提示有用得多。
    """
    request_id = _request_id(x_request_id)
    ip = auth.client_ip(request)

    # ⓪ 限速（Spec22 §2.6）。注册的码校验是四个校验点之一，而限速是两半：
    #    入口判 42901 + 失败计数。只记不判的话，被限速的人换个 URL 就能接着猜码。
    _reject_if_rate_limited(ip, request_id, "register")

    # ① 开关
    if not config.REGISTER_ENABLED:
        raise RegisterClosedError()

    # ②~⑥ 格式（每条都有自己的中文 message，所以都在这里判，而不是交给 Pydantic）
    username = (payload.username or "").strip()
    password = payload.password or ""
    email = _norm_email(payload.email)      # Spec22 §2.8：strip + lower 一条规则
    code = (payload.code or "").strip()
    if not 2 <= len(username) <= 32:
        raise RegisterRequestError("用户名需为 2~32 个字符")
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise RegisterRequestError(
            f"密码需为 {auth.MIN_PASSWORD_LEN}~{auth.MAX_PASSWORD_LEN} 位"
        )
    # Spec23 删除：微信昵称那一条（"请填写用于支付的微信昵称"）。表单里已经没有
    #   这个字段了，留着就是一条永远走不到的分支 + 一句指向不存在输入框的报错。
    if not _email_ok(email):
        raise RegisterRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")
    if not _code_ok(code):
        raise RegisterRequestError("请填写 4 位数字验证码")

    # ⑦ 邮箱已注册（提交时**再查一遍**：从发码到提交隔着几分钟，中间可能有人
    #    先注册了同一个邮箱。Spec23 之后这是**唯一的**邮箱唯一性业务判据，
    #    因为"pending 申请"那道闸门随表消失了 —— 它的分量比 Spec22 时更重）
    existing = db.get_user_by_email(email)
    if existing is not None:
        raise EmailCodeRejectedError(
            config.EMAIL_CODE_REGISTERED_NOTICE.format(username=existing["username"])
        )

    # ⑧ 验证码（注册是一条公开的猜码入口，所以这里的失败**计入登录限速**，Spec22 §2.6）
    _verify_code(request_id, ip, email, "register", code)

    # ⑨ 用户名占用。Spec23 之后这条从"提前告知"变成了**真正的闸门**（§3.3-4）：
    #    旧流程最后还有管理员点同意时撞 UNIQUE 兜底，现在没有那一步了，所以
    #    这里的报错就是用户唯一会看到的东西。仍然只是"查一次库"——并发的原子
    #    保证依旧是 users.username 的 UNIQUE 索引（create_user 里 IntegrityError → 40001）。
    if db.get_user_by_username(username) is not None:
        raise DuplicateUsernameError()

    # ⑩ 建号（限额由 create_user 显式写 _QUOTA_DEFAULT，见 §2.4）
    #    email 走 create_user 的参数——这是 Spec23 之后**唯一**会传 email 的调用方
    #    （管理员手工建号仍不传，落 NULL，那是允许的形态）。
    user = db.create_user(username, auth.hash_password(password), email=email)

    # ⑪ 签发 token（与 /api/auth/login 逐字同款）
    token = auth.create_token(user["id"], user["username"])

    logger.info("新用户已注册", extra={
        "event": "auth.registered", "request_id": request_id,
        "username": username, "user_id": user["id"],
    })

    # Spec20：注册通知邮件。在 return **之前**登记（否则任务不会被登记），
    # 在响应发出**之后**才跑——注册接口的耗时一秒都不涨。
    # Spec23 §2.6：少了 wechat 参数、正文重写；仍然**永不抛异常**（Spec20 §2.4）。
    background_tasks.add_task(
        mailer.send_register_notification,
        username,
        email,
        user["created_at"],
    )

    return _ok({"token": token, "username": user["username"], "is_admin": user["is_admin"]})
```

**三处必须照做的细节**：

- **`background_tasks` 的参数位置不能动**：它没有默认值，**必须**排在 `request: Request` 之后、`x_request_id`（有默认值）之前。Spec20 §6.1 为这条路由踩过一次 SyntaxError。
- **`created_at` 取 `user["created_at"]`**（建号那一刻，库里存的 UTC ISO），不是"现在"再算一次——两者差几毫秒，但用返回值是唯一不会漂的来源。
- **函数名从 `register_request` 改成 `register`**：旧名字描述的是"提交申请"，那个动作没有了。⚠️ 路由路径 `/api/auth/register` **一个字不变**（`PUBLIC_AUTH_PATHS` 里的字符串、前端 `chatApi.js`、Spec19 的文档全都引用它）。

### 5.5 `schemas.py`

```python
class RegisterRequestCreate(BaseModel):
    """POST /api/auth/register 请求体（Spec23 §5.4，Spec22 §6.1 的改造版）。

    全部字段都是裸 str：格式规则（长度、纯数字、@ 位置）一律在路由层判，
    好让每一条都有自己的中文 message。Pydantic 只负责"字段在不在"。

    Spec23：**`wechat` 删掉了**。删字段**不是**改成 Optional —— 留一个可选字段，
    就留了一条能被写进已删概念的路（Spec22 删 phone 时定的规矩，同款）。
    """

    username: str
    password: str
    email: str          # Spec22：必填
    code: str           # Spec22：邮箱验证码（4 位数字，格式在路由层判）
```

```python
# Spec23 删除：class RegisterApproveRequest(BaseModel)
#   唯一消费者是 POST /api/admin/register-requests/{id}/approve，那条路由整个删了（§2.2）。
#   它的 docstring 里那句"非整数由 Pydantic 拦下 → 40001"随它一起作废。
```

> ⚠️ **`RegisterApproveRequest` 是 `QuotaLimitError`(40017) 的三个生产者之一**，但**另外两个还在**（`PUT /api/admin/users/{id}/quota`、`POST /api/admin/recharge-requests/{id}/approve`），所以 **40017 不退休**。

### 5.6 `mailer.py`

```python
def send_register_notification(username: str, contact: str, created_at_iso: str) -> None:
    """发一封"有新用户注册"的提醒。**同步阻塞**，调用方负责丢进线程池（Spec20 §2.1）。

    三种结局，全部静默（Spec20 §2.4）：
      未配置 SMTP_PASSWORD → warning 日志，直接返回
      发送成功             → info 日志
      发送失败             → warning 日志（异常被吞掉，绝不冒泡到注册请求上）

    日志里**不带**用户邮箱 / IP（Spec20 §10）：邮箱是申请人的 PII 且已在邮件正文里，
    IP 是 Spec19 §10 定的"任何日志都不带"。`to` 是配置里的固定值，可以记。

    ⚠️ **本函数必须保持为同步 def**。改成 async def 会让 Starlette 在事件循环里
    直接 await 它，smtplib 的阻塞 IO 会卡死整个循环（所有并发请求一起等），
    而且**不报错、只是变慢**——最难查的那类劣化。同步 def 才会被丢进 threadpool。

    Spec23 §2.6 的两处改动：
      · 签名少一个 `wechat`（微信昵称不再是注册信息；删参数不是留默认值）
      · 正文重写——旧正文「微信充值账号是{wechat}，注册时间是{...}，请立即审批！」
        里的三个词全废（微信昵称没了、"请立即审批"没有审批了）
    ⚠️ 新正文是 **Spec23 拟的，用户没给原文**（§2.6 已记录）。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("注册通知未发送：SMTP 未配置", extra={
            "event": "notify.register_mail_skipped",
            "reason": "smtp_not_configured",
            "username": username,
        })
        return

    msg = EmailMessage()
    msg["Subject"] = f"ACN-{username}-{contact}"       # 不变
    msg["From"] = formataddr((_FROM_NAME, config.SMTP_USER))
    msg["To"] = config.REGISTER_NOTIFY_TO
    msg.set_content(
        f"新用户{username}已完成注册，邮箱是{contact}，注册时间是{beijing_time_text(created_at_iso)}。"
    )
    # ...（SMTP_SSL 发送与两处日志，与现状逐字相同）
```

```python
# Spec23 删除：send_register_approved_notification(...)
#   它的唯一挂点是 POST /api/admin/register-requests/{id}/approve，路由已删（§2.2）。
#   ⚠️ 连带：它用的 register_id 日志字段从 _FIELDS 白名单里删掉（§10.1）；
#      它引用的 timefmt.beijing_time_text 仍有其它消费者，不动。
```

### 5.7 关键数据流

**注册（新）**

```
用户填 账号/密码/确认密码/邮箱/验证码
   ↓ 点「获取验证码」（可选，先做）
POST /api/auth/email-code {email, purpose:"register"}
   ↓ ① SMTP 未配 → 50302 ② 格式 ③ purpose 白名单 ④ 冷却(40906) ⑤ 查重(40907，现在两支)
   ↓ 落 email_verifications 行 + BackgroundTasks 发码
   ↓
POST /api/auth/register {username, password, email, code}
   ↓ ⓪ 限速 ① 开关 ②~⑥ 格式 ⑦ 邮箱已注册 ⑧ 验码 ⑨ 用户名占用 ⑩ create_user ⑪ create_token
   ↓ BackgroundTasks: send_register_notification(username, email, created_at)
   ↓ 200 {token, username, is_admin}
前端 store.register() → token/username/is_admin 三落
   ↓ App.vue 的 v-if 切到聊天视图；watcher 触发 resetForUser + 首次自动弹帮助
   ↓ 用户直接在主界面（弹窗已关）
```

**注册（旧，供对照）**：`... → db.create_register_request → 200 {id} → 等管理员 → approve → create_user`。**中间那个"等"没有了，这就是本 Spec 的全部价值。**

---

## 6. 接口约定

### 6.1 变更：`POST /api/auth/register`（**公开**）

**请求体**

```jsonc
{ "username": "newuser", "password": "ab", "email": "new@qq.com", "code": "4821" }
// Spec23：wechat 删除
```

**响应 200**

```jsonc
{ "code": 200, "message": "ok",
  "data": { "token": "eyJ...", "username": "newuser", "is_admin": false } }
// Spec23：从 {id: N} 变成与 /api/auth/login 逐字同形的三个键
```

**错误**（**错误码一个没变，只是少了一个字段带来的分支**）

| 码 | 触发 | message |
|---|---|---|
| 42901 | ⓪ 限速 | 「尝试过于频繁，请 5 分钟后再试」 |
| 40305 | ① `REGISTER_ENABLED=false` | 「注册暂未开放，请联系客服 …」 |
| 40018 | ② 长度 / 密码 / ⑤ 邮箱格式 / ⑥ 码形状 | 各自的中文 message |
| 40907 | ⑦ 邮箱已注册 | 「已注册账号{username}，请前往登录界面…」 |
| 40020 | ⑧ 验证码错 / 过期 | 「验证码错误或已过期」 |
| 40001 | ⑨ 用户名占用 | 「用户名已存在」 |

> **`wechat` 那一条 40018 的 message**（「请填写用于支付的微信昵称」）**删除**。请求体里带 `wechat` 时**不报错也不理会**——Pydantic 的默认行为是忽略未知字段，改动它（`model_config = ConfigDict(extra="forbid")`）会让旧的、还带着 wechat 的前端构建**当场 400**，而 GitHub Pages 上的旧版前端可能还在跑。**这是有意的宽容。**

### 6.2 删除：4 条管理端路由

```
GET    /api/admin/register-requests            ← 删
POST   /api/admin/register-requests/{id}/approve   ← 删
POST   /api/admin/register-requests/{id}/reject    ← 删
DELETE /api/admin/register-requests/{id}           ← 删
```

删除后这些路径会落到 FastAPI 的默认 404（**不是**本仓的 `{code, message, data}` 信封，因为那是 `AppError` 处理器负责的）。**这是可接受的**：它们只被管理端旧版前端调用，而那个前端与后端**同一次部署**（`Server/static/` 直接托管 `dist/`），不存在版本错配。若在跨域独立部署下用旧前端，管理员点「同意」会看到一个 404——**刷新页面即可**。

### 6.3 变更：`GET /api/auth/register-config`（公开）

```jsonc
// 旧
{ "enabled": true, "contact_email": "frostyj@qq.com",
  "qr_url": "http://…/api/auth/payment-qr",
  "price_notice": "请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务" }

// 新（Spec23）—— 只有最后一个键改名 + 换形状
{ "enabled": true, "contact_email": "frostyj@qq.com",
  "qr_url": "http://…/api/auth/payment-qr",
  "price_line": [ { "text": "请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务" } ] }
```

- **`qr_url` 保留**：`RegisterModal` 不再用它了，但**欠费充值面板**（`RechargeModal mode="overdue"`）还在用。
- **`price_line` 是单片段**（无删除线）——欠费面板的文案一个字不改（§0 第 3-b 条）。
- **仍然永远返回 200**，即使 `enabled=false`（Spec19 §6.1）。

### 6.4 变更：`GET /api/recharge/info`（需鉴权）

```jsonc
// 旧
{ "balance": 2.5, "quota_limit": 35, "used": 10,
  "qr_url": "http://…/api/auth/payment-qr",
  "price_notice": "充值参考：0.9元约10次设计服务" }

// 新（Spec23）—— 同样只有最后一个键改名 + 换形状
{ "balance": 2.5, "quota_limit": 35, "used": 10,
  "qr_url": "http://…/api/auth/payment-qr",
  "price_line": [ { "text": "充值参考：" },
                  { "text": "6.99", "strike": true },
                  { "text": " 0.9元约10次设计服务" } ] }
```

- **`balance` / `quota_limit` / `used` / `qr_url` 一字不变**。
- **`strike` 键只在需要划线时出现**（其它片段**不带这个键**，不是 `false`）——前端用 `seg.strike` 判真值即可，两种写法都对。

### 6.5 不变

`/api/auth/payment-qr`、`/api/auth/email-code`、`/api/auth/verify-email-code`、`/api/auth/login-by-email`、`/api/auth/reset-password`、`/api/auth/login`、`/api/auth/me`、`/api/click`，以及**全部** `/api/admin/users*`、`/api/admin/recharge-requests*`、`/api/admin/stats`、`/api/admin/clicks/clear` —— **一字不动**。

**`PUBLIC_AUTH_PATHS` 仍是 10 条，一条不多一条不少**（`/api/auth/register` 与 `/api/auth/register-config` 都在原地）。

> ⚠️ **`/api/auth/register` 仍在白名单里，所以中间件**不判限额**——这是对的**：一个还没注册的人当然不该被判 40304。注册成功后的**第一次** `/api/auth/me` 会照常判，而新号带 10 次额度，不会触发。

---

## 7. 前端交互

### 7.1 `views/RegisterModal.vue`

**删掉的三块**（用户点名的正是这三件）

```diff
-          <div class="reg-pay">
-            <p class="reg-pay-title">{{ config.price_notice }}</p>
-            <img class="reg-qr" :src="config.qr_url" alt="收款码" />
-          </div>
-
-          <!-- 标签直接用完整的那句话（与 RechargeModal 同一次改版），占位提示随之删掉。… -->
-          <label class="reg-label">用于支付的微信昵称（以便后台核对） <b class="reg-star">*</b></label>
-          <input v-model="wechat" class="login-input" autocomplete="off" />
```

**连带删**：`const wechat = ref('')`、`submit()` 里的 `!wechat.value.trim()` 与那句「请填写账号、密码与微信昵称」、`submitRegisterRequest` 入参里的 `wechat`、`defineProps({ config })` 整个 props 声明与 `defineEmits` 上方那段"来自 GET /api/auth/register-config"的注释。

> ⚠️ **必填校验那句话要改**，不能只删 `wechat` 那一项：「请填写账号、密码与微信昵称」→「**请填写账号与密码**」。这正是 Spec22 §0 第 6-a 条记过的那类问题（**提示语指向一个不存在的输入框**）。

**成功路径从"结果屏"改成"直接进系统"**

```diff
-      <!-- 提交成功：整卡换成结果面板，用户自己关掉（不自动关，让他看清提示） -->
-      <template v-if="done">
-        <h2 class="reg-title">申请已提交</h2>
-        <p class="reg-done-text">
-          已通知管理员，在30秒内会通过短信/邮件告知您注册结果。
-        </p>
-        <button class="btn-primary reg-submit" @click="close">关闭</button>
-      </template>
-
-      <template v-else>
+      <template>
```

```js
async function submit() {
  // 只拦"必填"——那是 * 号承诺的东西。
  // ⚠️ 邮箱 @ 位置、密码长度这些**不在前端复制**：它们各有自己的中文 message（40018 / 40020）。
  if (!username.value.trim() || !password.value) {
    error.value = '请填写账号与密码'      // Spec23：不再提微信昵称
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'   // Spec22 §2.10：后端收不到 confirm
    return
  }
  if (!email.value.trim()) { error.value = '请填写邮箱'; return }
  if (!/^\d{4}$/.test(code.value.trim())) {
    error.value = '请填写 4 位数字验证码'; return
  }
  error.value = ''
  loading.value = true
  try {
    // Spec23 §2.5：一次调用完成"建号 + 登录"。store 里 token/username/is_admin
    // 三个一落，App.vue 的 v-if 自动切到聊天视图——**这里不需要 emit 任何东西**，
    // 组件随后被父级的 v-if 卸掉。这正是 loginByEmail 的收尾方式，照抄。
    await auth.register(username.value.trim(), password.value, email.value.trim(), code.value.trim())
  } catch (e) {
    error.value = e.message || '注册失败'
  } finally {
    loading.value = false
  }
}
```

- **`done` ref 整个删掉**（成功路径不再需要它）。
- **组件不再需要 `config` prop**，但**仍然需要 `emit('close')`**（右上角 × 与取消）。
- **`<style>` 块：本文件本来就没有 scoped style**（样式全在 `main.css`），不需要动。

### 7.2 `store/auth.js`

```js
    // Spec23 §2.5：自助注册。后端在同一次响应里签发 token，所以收尾三行与
    // login() / loginByEmail() **逐字相同**——三个一落，App.vue 的 v-if 自动切视图。
    //
    // 与 login() 的处境差别只有一个：这里**不会**遇到 40304（新号刚拿到 10 次额度，
    // 不可能超额），所以不需要调用方挂欠费面板。
    async register(username, password, email, code) {
      const res = await apiRegister({ username, password, email, code })
      this.token = res.token
      this.username = res.username
      this.isAdmin = res.is_admin
      localStorage.setItem(TOKEN_KEY, res.token)
    },
```

### 7.3 `api/chatApi.js`

```js
// ---- 注册申请与审批（Spec19 §7.6）----   ← Spec23：这段注释整段重写，不再是"申请与审批"
// 注意：拦截器不用改。40305（注册未开放）与既有的 40301/40302/40303/40304 互不
// 干扰——拦截器只在 code === 40304 时才登出，而 40305 只可能出现在
// /api/auth/register 上（一个未登录用户根本不会被登出）。40907 是 409，拦截器不处理。

export async function getRegisterConfig() {
  const { data } = await http.get('/api/auth/register-config')
  // Spec23：price_notice(str) → price_line(片段数组)，见 §6.3
  // { enabled, contact_email, qr_url, price_line }
  return data.data
}

// Spec23 §2.5：注册 = 建号 + 登录，一次调用。
// 原（Spec19）：submitRegisterRequest({ username, password, phone, email, wechat }) → { id }
// 新（Spec23）：wechat 删除（表单里也没有了）；**没有 confirm**（它不提交，Spec22 §2.10）
export async function submitRegisterRequest({ username, password, email, code }) {
  const { data } = await http.post('/api/auth/register', {
    username, password, email, code
  })
  return data.data // { token, username, is_admin } —— 与 /api/auth/login 同形
}

// Spec23 删除：listRegisterRequests / approveRegisterRequest /
//              rejectRegisterRequest / deleteRegisterRequest
//   四条管理端路由整个删了（§6.2）。管理端「待审批注册用户」那块 UI 也没了。
```

**`getRechargeInfo` 的注释**（`/api/recharge/info`）同款改键名：`// { balance, quota_limit, used, qr_url, price_line }`。

### 7.4 `views/HelpModal.vue`（**逐字 diff，照抄**）

```diff
-      <h2 class="help-title">认识 ArtiControlNet</h2>
-      <p class="help-lead">赋能设计的 AIGC 系统——你说想法，它出图。</p>
+      <h2 class="help-title">快速上手ArtiControlNet</h2>
```

> ⚠️ 用户原文就是 `快速上手ArtiControlNet`，**「上手」与「ArtiControlNet」之间没有空格**（中文与拉丁字母之间不加空格，本仓既有标题也不是全加）。照抄。

```diff
       <div class="help-item">
         <p class="help-item-title">🎨 文生图</p>
-        <p class="help-item-desc">没有参考图？直接描述想要的画面，它生成一张新图。</p>
+        <p class="help-item-desc">直接描述想要的画面，它生成一张新图。</p>
```

```diff
       <div class="help-item">
         <p class="help-item-title">🖌 图文生图</p>
-        <p class="help-item-desc">文字 + 参考图。把设计线稿传上来，按你的要求上色、上风格。</p>
+        <p class="help-item-desc">文字 + 参考图。例如，把设计线稿传上来，按你的要求上色、上风格。</p>
```

> ⚠️ 「例如，」加在**「把设计线稿传上来」前面**，不是加在「文字 + 参考图。」前面（用户原话：「『把设计线稿传上来，按你的要求上色、上风格。』前面加个『例如，』」）。所以「文字 + 参考图。」这个**前缀保留**。

```diff
-      <p class="help-explore">✨ 以上三种只是基础玩法，更多神奇进阶功能，等你自己探索。</p>
+      <p class="help-explore">以上三种只是基础玩法，更多神奇进阶功能，等你自己探索。</p>
```

```diff
-      <!-- Spec18 §7.7：服务次数说明（Spec21 §7.5 改文案：两句删、一句换；
-           后来再次改口——不再提「联系管理员续费」，因为现在用户自己能充值） -->
+      <!-- Spec18 §7.7：收费政策说明。
+           Spec21 §7.5 改过一次（删两句、换一句：不再提「联系管理员续费」）；
+           Spec23 §7.4 再改一次——前半句换成「新注册用户会收到一定的免费试用额度，」，
+           因为现在真的有免费额度了。后半句一个字没动。 -->
       <div class="help-item">
-        <p class="help-item-title">📊 服务次数</p>
+        <p class="help-item-title">💰 收费政策</p>
         <p class="help-item-desc">
-          每个用户在充值后会获得对应次数，用尽后需充值才能继续使用噢！
+          新注册用户会收到一定的免费试用额度，用尽后需充值才能继续使用噢！
         </p>
       </div>
```

> ⚠️ `💰` 是**自选**的（§0 第 2-a 条）。`📊` → `💰` 只改这一个字符。
> ⚠️ 「一定的」是**模糊词，故意的**——它不与 `QUOTA_DEFAULT_LIMIT` 绑定，改那个数不用改这里（§3.3-7）。

```diff
       <div class="help-foot">
-        <p class="help-tip">支持 jpg / png / webp / gif，≤10MB。每条消息都能带图。</p>
         <button class="btn-primary help-start" @click="close">开始使用</button>
       </div>
```

**CSS 三处连带**（§2.9）

```diff
 .help-title {
   font-size: 20px;
   font-weight: 700;
   letter-spacing: 0.5px;
   text-align: center;
-  margin-bottom: 8px;
+  margin-bottom: 20px;      /* Spec23：原 .help-lead 的间距挪到这里（副标题已删） */
   background: linear-gradient(...);
 }

-/* Spec23 删除：.help-lead —— 副标题整行删掉了，这条规则没有消费者。
-   它原来的 margin-bottom: 20px 已挪给 .help-title（上面）。 */

 .help-foot {
   display: flex;
   align-items: center;
-  justify-content: space-between;
+  justify-content: center;   /* Spec23：只剩一个按钮，space-between 会把它顶到左边 */
   gap: 12px;
   border-top: 1px solid var(--border-color);
   padding-top: 16px;
 }

-/* Spec23 删除：.help-tip —— 上传格式那行删掉了 */

 @media (max-width: 640px) {
   .help-card { padding: 22px 18px 18px; }
-  .help-foot {              /* Spec23 删除：只剩一个按钮，不再需要列布局 */
-    flex-direction: column;
-    align-items: stretch;
-    text-align: center;
-  }
 }
```

> ⚠️ 640px 媒体查询里删掉 `.help-foot` 那一块后，**整个 `@media` 块仍然有用**（`.help-card` 那条留着），别把整块删掉。

### 7.5 `views/RechargeModal.vue`

```diff
-          <div class="reg-pay">
-            <img v-if="qrUrl" class="reg-qr rc-qr" :src="qrUrl" alt="收款码" />
-            <p v-if="priceNotice" class="reg-pay-title rc-note">{{ priceNotice }}</p>
-          </div>
+          <div class="reg-pay">
+            <img v-if="qrUrl" class="reg-qr rc-qr" :src="qrUrl" alt="收款码" />
+            <!-- Spec23 §2.8：参考价改成"排版片段"。片段里的 strike 为真时套一层 <s>
+                 （删除线）——划线位置是**后端给的数据**，不是前端在前缀里找 "0.9"。
+                 没有 v-html：那是个 XSS 面，而这句话里有服务端可控的数字。 -->
+            <p v-if="priceLine.length" class="reg-pay-title rc-note">
+              <template v-for="(seg, i) in priceLine" :key="i"
+                ><s v-if="seg.strike">{{ seg.text }}</s><template v-else>{{ seg.text }}</template></template>
+            </p>
+          </div>
```

```diff
-// 参考价的措辞两个模式**故意不同**（Spec21 §7.3）：前者出自需求 4 的原话，
-// 后者出自需求 6 的原话。两句都来自后端，前端一个字的文案副本都不放。
+// 参考价两个模式**故意不同**（Spec21 §7.3）：前者出自需求 4 的原话，后者出自需求 6 的原话。
+// Spec23 §2.8：两边都是"排版片段数组"（形状一致，所以下面两个分支共用一份渲染），
+// 只有 /api/recharge/info 那份带一个 strike 片段。
+// 两句都来自后端，前端一个字的文案副本都不放。
-const priceNotice = ref('')
+const priceLine = ref([])
```

```diff
       const cfg = await getRegisterConfig()
       qrUrl.value = cfg.qr_url
-      priceNotice.value = cfg.price_notice
+      priceLine.value = cfg.price_line
     } else {
       const info = await getRechargeInfo()
       qrUrl.value = info.qr_url
-      priceNotice.value = info.price_notice
+      priceLine.value = info.price_line
       balance.value = info.balance
     }
```

**`.rc-note` 那条 CSS 不动**（`margin-top: 10px`，Spec21 §7.3 的布局：备注在收款码**下方**）。

### 7.6 `views/AdminPanel.vue`

删掉整个 `<section class="reg-admin">`（「待审批注册用户」那块，含 `requests.length === 0` 的空态、`v-for`、同意/拒绝/删除按钮），以及：

- `<script setup>` 里：`const requests = ref([])`、`const busyRegId = ref(null)`
- 四个方法：拉列表的那个（`loadRequests` 之类）、`approve(r)`、`reject(r)`、`removeRequest(r)`
- `import` 里的 `listRegisterRequests` / `approveRegisterRequest` / `rejectRegisterRequest` / `deleteRegisterRequest`
- `onMounted` 里拉注册列表的那一次调用

**⚠️ 一行 CSS 都不许删**（§14 陷阱 1）。那套 `.reg-*` 类名是 Spec21 充值台账在用的。

**「用户管理」表里的「联系方式」列保持不动** —— 它显示的是 `users.email`（Spec21 §5.1 补的列），与注册申请无关。手工建的号显示「无」。

### 7.7 `views/Login.vue`

```diff
-    <RegisterModal v-if="showRegister" :config="regCfg" @close="showRegister = false" />
+    <!-- Spec23：不再传 config —— 注册弹窗里的收款码与预充值提示都删了，
+         它是 config 的唯一消费者。regCfg 本身**保留**：enabled 决定注册按钮
+         画不画、contact_email 是下面那行客服。 -->
+    <RegisterModal v-if="showRegister" @close="showRegister = false" />
```

**客服行（`login-service`）不动**，`regCfg.contact_email` 仍在用。

### 7.8 样式（`assets/styles/main.css`）

**不改动。** ⚠️ 特别地：`.reg-pay` / `.reg-qr` / `.reg-pay-title` / `.reg-done-text` **全部保留** —— `RechargeModal` 还在用前三个，第四个在 `RechargeModal` 的成功屏里（「充值申请已提交」）还在用。

---

## 8. 配置 / 环境变量

### 8.1 `config.py`

```python
# ===== 注册（Spec19 / Spec23）=====
# Spec23 §2.3：这个数现在就是「**新用户的免费试用额度**」。它同时管三条路
# （自助注册 / 管理员手工建号 / 新建库的列默认值）。
# ⚠️ 它**只影响新建的账号**，存量账号（当时拿 25 的）不被追溯修改（§2.10）。
# ⚠️ 但 `create_user` 必须**显式**把它写进 INSERT —— 列 DEFAULT 在建库那一刻就
#    烤死在 schema 里了，改这个常量对**已存在**的库的列默认值毫无影响（§2.4）。
QUOTA_DEFAULT_LIMIT = int(os.getenv("QUOTA_DEFAULT_LIMIT", "10"))

# Spec23 删除：REGISTER_PRICE_NOTICE（改成下面的 REGISTER_PRICE_LINE）
#   它原来还兼着"注册弹窗里那句预充值提示"的职责，那个块整个删了（§7.1）。
#   现在它只服务**欠费充值面板**（登录页被踢出来时弹的那个），文案一个字不改。

# 欠费充值面板的参考价（Spec19 §6.1 起就有的那个键，Spec23 换了形状）。
# 单片段、无删除线——需求只要求给「余额与充值」页加划线价（§0 第 3-b 条）。
REGISTER_PRICE_LINE = (
    {"text": "请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务"},
)

# Spec23 删除：RECHARGE_PRICE_NOTICE（改成下面的 RECHARGE_PRICE_LINE）
# 充值弹窗里那句参考价（唯一来源，前端零副本）。
# Spec23 §2.8：拆成"排版片段"——删除线在**句子中间**（"0.9"紧前面），
#   一整串字符串表达不了那个位置。strike=True 的片段前端套 <s>。
# ⚠️ 用片段数组，**不是** v-html（XSS 面），**也不是**让前端在句子里找 "0.9"
#    （那等于把价格复制到前端，正是本仓从 Spec18 起一直在避免的）。
# ⚠️ "6.99" 与 "0.9" 的口径**故意不一致**（划掉的原价 vs 实收价折算的参考次数），
#    与 Spec21 §2.9 的余额公式是同一条立场——别去"统一"。
RECHARGE_PRICE_LINE = (
    {"text": "充值参考："},
    {"text": "6.99", "strike": True},
    {"text": " 0.9元约10次设计服务"},
)

# Spec23 删除：EMAIL_CODE_PENDING_NOTICE
#   原文「该邮箱已提交过注册申请，请等待管理员审批」。它的唯一触发分支是
#   "该邮箱已有一条 pending 注册申请"，而 register_requests 表整个删了（§2.2、§2.7）。
#   留着一句描述不存在状态的提示语，正是 CLAUDE.md 为 QUOTA_CONTACT_EMAIL /
#   REGISTER_DAILY_NOTICE 记过的那类静默失败。
```

> ⚠️ **`RECHARGE_PRICE_LINE` 里第一个片段末尾的空格**（`" 0.9元约10次设计服务"` 前面那个空格）：它替代了原来 "6.99" 与 "0.9" 之间的分隔。**别用 `{"text": " "}` 单独做一个片段**——空片段在 `v-if`/`v-for` 里没有任何好处，还会让"三个片段"变成"四个"。

### 8.2 `.env.example`

```diff
-# QUOTA_DEFAULT_LIMIT=25               # 新建用户的默认限额（累计次数）
+# QUOTA_DEFAULT_LIMIT=10               # 新用户的免费试用额度（累计次数）。Spec23 起
+                                       # 它就是"新注册送几次"。只影响新建账号。
```

其余全部不动（`QUOTA_LIMIT_MAX`、`REGISTER_ENABLED`、`SUPPORT_EMAIL`、SMTP 段、Spec22 段）。

### 8.3 变量总览（本 Spec 触及的）

| 变量 | 动作 |
|---|---|
| `QUOTA_DEFAULT_LIMIT` | **默认值 25 → 10**；语义升格为"免费试用额度" |
| `REGISTER_PRICE_NOTICE` | **改名 + 换形状** → `REGISTER_PRICE_LINE`（片段数组） |
| `RECHARGE_PRICE_NOTICE` | **改名 + 换形状** → `RECHARGE_PRICE_LINE`（片段数组，带一个 strike） |
| `EMAIL_CODE_PENDING_NOTICE` | **删除** |
| 其余全部 | 不动 |

---

## 9. 错误码

```python
# Spec23 删除：class RegisterRequestNotFoundError(NotFoundError)   # 40409
#   唯一语义是"这条注册申请不存在/已被删"，消费者是 approve/reject/delete 三条路由
#   （它们都删了，§6.2）。
#
# Spec23 删除：class RegisterAlreadyReviewedError(AppError)       # 40903
#   唯一语义是"这条申请已经不是 pending 了"，消费者同上（含 db 层并发抢跑返回 None
#   的那两支）。
#
# ⚠️ **不把这两个码改嫁给任何新语义**：重定义既有码会让旧日志里的 40409 / 40903
#    变成假话（Spec22 §2.11 删 40902 时定的规矩，同款）。
```

| 码 | 动作 |
|---|---|
| 40409 | **退休**（`RegisterRequestNotFoundError`） |
| 40903 | **退休**（`RegisterAlreadyReviewedError`） |
| 40018 | **保留**（`RegisterRequestError`）—— 注册的格式消息还在用它 |
| 40017 | **保留**（`QuotaLimitError`）—— 生产者还剩两个（管理员改限额、充值审批） |
| 40001 / 40305 / 40907 / 40020 / 42901 | **保留**，语义与文案一字不变 |

---

## 10. 日志约定

| 事件 | 何时 | 字段 |
|---|---|---|
| `auth.registered` | 自助注册建号成功 | `request_id`、`username`、`user_id` |
| `notify.register_mail_skipped` | 未配 SMTP | `username`、`reason`（**不变**） |
| `notify.register_mail_sent` | 注册通知已发出 | `username`、`to`（**不变**） |
| `notify.register_mail_failed` | 注册通知发送失败 | `username`、`error`（**不变**） |
| `db.migrate` | `DROP TABLE register_requests` 那一次 | `reason="register_requests_dropped"`（**新增的一条**） |
| ~~`auth.register_submitted`~~ | — | **改名**为 `auth.registered`（它现在真的建了号，旧名字描述的是"提交了申请"这个已不存在的动作） |
| ~~`auth.register_reviewed`~~ | — | **删除**（三条审批路由都没了） |

### 10.1 ⚠️ `logging_setup.py` 的字段白名单（**这是第四次动它，但这次是"删"**）

Spec20 §10 / Spec21 §10.1 / Spec22 §10.1 连续三次记过同一条：**没登记的 extra 键会被 `JsonFormatter` 静默丢弃**——不报错、不警告，日志看起来"正常"，只是少一个字段。这次的方向反过来：

```diff
-               # Spec19 注册申请与审批事件字段。注意这里用 register_id 而不是
-               # Spec19 §10 表里写的 request_id：后者在本仓已经是"HTTP X-Request-Id"
-               # 的固定含义（每个路由的每行日志都带它），两者同名会让排查时
-               # 拿 request_id 一搜就串味。注册申请 id 一律叫 register_id。
-               # Spec22 删除："has_phone" —— 注册表单已经没有任何电话字段了，
-               #   留着它就是一个永远不会被传进来的白名单项。
-               "register_id", "has_email",
+               # Spec23 删除："register_id" 与 "has_email"。
+               #   前者的四个生产者全部消失（注册路由 / 三条审批路由 / 那封被删的
+               #   注册成功邮件）；"has_email" 的唯一生产者是注册路由那条日志，
+               #   而它现在永远为 True（Spec22 起邮箱必填），是个常量字段。
+               #   ⚠️ 本条是**第四次**动这个白名单，但前三次都是"忘了加"，
+               #   这次是"该删" —— 别把这两件事混了：删掉一个**没有生产者**的键
+               #   是安全的，而漏加一个有生产者的键是静默丢字段。
                "decision", "was_status",
```

- ⚠️ **`"recharge_id"` 留着** —— 它是 Spec21/22 充值链条在用的。
- ⚠️ **`"user_id"` 早就在白名单里**（Spec12 wiki 事件），不需要新增。
- ⚠️ **`"decision"` / `"was_status"` 留着** —— 充值审批（reject）还在用。

### 10.2 绝不进日志的四样（**不变，重申一次**）

`password` / 验证码 `code` / 用户邮箱 / 用户 IP。新事件 `auth.registered` 只带 `username` 与 `user_id` —— **不带 email**（它是 PII，而 `username` 已经在既有的注册日志里出现过，口径一致）。

---

## 11. 目录结构增量

**无新增文件、无删除文件。** 全部改动落在既有文件里：

```
Server/
  config.py          ← QUOTA_DEFAULT_LIMIT 改值；两个 *_PRICE_LINE；删 EMAIL_CODE_PENDING_NOTICE
  db.py              ← 删两个常量（表定义 + status 索引）+ 7 函数 + _register_row_to_dict；
                       +_migrate_drop_register_requests；改 _migrate_lowercase_emails 的元组；
                       改 _migrate_users_contact / create_user / init_db
  main.py            ← register 路由改造；删 4 条管理端路由；_reject_duplicate_email 塌两支；
                       两个端点的 price_notice → price_line
  schemas.py         ← 删 RegisterApproveRequest；RegisterRequestCreate 去 wechat
  errors.py          ← 删 40409 / 40903 两个类
  mailer.py          ← send_register_notification 去 wechat + 改正文；删 send_register_approved_notification
  logging_setup.py   ← _FIELDS 删 "register_id" / "has_email"
  .env.example       ← QUOTA_DEFAULT_LIMIT 的注释与默认值

frontend/src/
  views/RegisterModal.vue   ← 删三块 + 成功即登录
  views/HelpModal.vue       ← 6 处文案 + 3 处连带
  views/RechargeModal.vue   ← price_line 渲染
  views/AdminPanel.vue      ← 删审批区（CSS 不动）
  views/Login.vue           ← 去掉 :config 绑定
  store/auth.js             ← +register()
  api/chatApi.js            ← 改 submitRegisterRequest；删 4 个函数
```

---

## 12. 实施顺序（里程碑）

**顺序是有讲究的：先做不可逆的那一步，再做依赖它的。**

| # | 做什么 | 为什么排这里 |
|---|---|---|
| 1 | **备份 `Server/artcn.db`** | `DROP TABLE register_requests` 不可逆，回滚只有这一条路（§2.2）。**先备份，再改一行代码。** |
| 2 | `config.py`：改 `QUOTA_DEFAULT_LIMIT`、两个 `*_PRICE_LINE`、删 `EMAIL_CODE_PENDING_NOTICE` | 所有后端改动的依赖源 |
| 3 | `db.py`：`create_user` 显式传 `quota_limit` + `_migrate_users_contact` 删回填 + **`_migrate_lowercase_emails` 元组去 `register_requests`** + `_migrate_drop_register_requests` + `init_db` 顺序（§5.3 的四条） | 数据库层先定。**必须连起两次服务**（§13 用例 2/3）：第一次走升级路径、第二次走稳态路径，两个症状不同，只起一次会漏掉其中一个 |
| 4 | `db.py`：删 `_CREATE_REGISTER_REQUESTS_TABLE` + 7 个函数 + `_register_row_to_dict` | 表已经没了，函数才敢删 |
| 5 | `errors.py` / `schemas.py` / `logging_setup.py` / `mailer.py` | 叶子节点，删完不影响别的 |
| 6 | `main.py`：注册路由改造 + 删 4 条管理端路由 + `_reject_duplicate_email` 塌分支 + 两个端点的 `price_line` | 依赖 2~5 全部就位 |
| 7 | **后端自测**（§13 的 A / B / C 组） | 后端契约冻结之后才动前端 |
| 8 | `api/chatApi.js` + `store/auth.js` | 前端的地基 |
| 9 | `RegisterModal.vue` → `Login.vue` | 有依赖关系 |
| 10 | `HelpModal.vue` | 独立，随便插 |
| 11 | `RechargeModal.vue` | 独立，但要等 §6.4 的后端 |
| 12 | `AdminPanel.vue` 删审批区 | 独立 |
| 13 | **前端自测**（§13 的 D / E 组） | — |
| 14 | `npm run build` + 重新构建静态产物 | 与 Spec20/21/22 的 `build:` 提交同款 |
| 15 | 更新 `CLAUDE.md` | 见 §15 |

---

## 13. 验收用例（端到端 Smoke）

### 前置

- **库副本**：`cp Server/artcn.db /tmp/acn-spec23.db`，用 `AUTH_DB_PATH` 指过去跑（不要拿真库练 `DROP TABLE`）。
- **假发信**：`SMTP_PASSWORD= .venv/Scripts/python -m uvicorn main:app --port 8000` —— 空 `SMTP_PASSWORD` 时**注册通知与验证码都不发**（`load_dotenv` 默认不覆盖已有环境变量，所以前缀有效）。⚠️ **但发码接口会直接返回 50302**（Spec22 §2.5：未配 SMTP 是硬错误），所以第 2 组之后要用**真 SMTP + 你能收到的邮箱**跑。**别拿陌生人的地址当靶子。**
- **一律用 `127.0.0.1`，不要用 `localhost`**（本机每请求白等 2 秒）。
- **限速用例排最后**（42901 是 5 次 / 5 分钟，跑早了会把后面的用例全挡掉）。

### A. 迁移（**不可逆，先做**）

```bash
# 1. 备份前的库：确认表还在、有几行
sqlite3 /tmp/acn-spec23.db "SELECT COUNT(*) FROM register_requests;"
#    ✅ 记下这个 N（下面第 4 步对比）

# 2. 启动一次（跑的是 §12 第 3 步的代码）—— 这一跑走的是"升级路径"
#    ✅ **服务起得来**（不是 traceback）
#       ⚠️ 这一条专门验 §5.3 那个**硬**顺序约束：如果 _migrate_drop_register_requests
#          排在了 _migrate_lowercase_emails 前面，这里会当场抛
#          sqlite3.OperationalError: no such table: register_requests
#    ✅ 启动日志里恰好一条：
#       {"event":"db.migrate","reason":"register_requests_dropped", ...}
#    ✅ 日志级别是 WARNING（不是 info）
#    ✅ 日志里**没有** no such table / no such column 字样

# 3. 再启动一次 —— 这一跑走的是"稳态路径"（表已经不在了）
#    ✅ **服务起得来**
#       ⚠️ 这一条专门验 §5.2 的元组改动：如果 _migrate_lowercase_emails 的循环
#          还带着 "register_requests"，第一次启动没事，**这一次**会抛
#          no such table —— 而用户看到的现象是"改完之后再也起不来"，
#          很容易误判成"是那次 DROP 把库弄坏了"。
#    ✅ 不报错、**没有第二条** db.migrate / register_requests_dropped
#       （幂等：sqlite_master 判据在第二次为假）
#    ✅ 同样**没有** no such table / no such column

# 4. 确认表真的没了
sqlite3 /tmp/acn-spec23.db "SELECT name FROM sqlite_master WHERE name='register_requests';"
#    ✅ 空输出
sqlite3 /tmp/acn-spec23.db "SELECT username, email, quota_limit FROM users LIMIT 5;"
#    ✅ users 表**一行没少**（删表不碰用户）
#    ✅ 存量用户的 quota_limit 仍是 25（§2.10 不追溯）

# 5. phone/ip 那半段仍然工作
#    ✅ 启动日志里**没有** db.migrate / sqlite_too_old（如果之前已经跑过）
#    ✅ 对着一张 pre-Spec22 的旧库副本跑，仍然能看到那条删列日志
#       —— _migrate_drop_phone_and_ip 对不存在的 register_requests 做 PRAGMA
#          返回空集，不报错
```

### B. 免费额度 10（§2.4，**这里最容易静默错**）

```bash
# 6. 管理员手工建号 → 必须也是 10
curl -s -X POST 127.0.0.1:8000/api/admin/users -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"spec23manual","password":"ab"}' | python -m json.tool
#    ✅ data.quota_limit == 10
#    ⚠️ 这一条就是 §2.4 那个坑的验收：如果 create_user 还靠列 DEFAULT，
#       这里会返回 **25**（本机是存量库）——那就说明显式传值没做。
```

### C. 注册（§5.4、§6.1）

```bash
# 7. 发码（真 SMTP，用你能收到的邮箱）
curl -s -X POST 127.0.0.1:8000/api/auth/email-code -H 'Content-Type: application/json' \
  -d '{"email":"spec23@qq.com","purpose":"register"}'
#    ✅ {"code":200,"data":{"sent":true}}
#    ✅ 收件箱收到 4 位码；响应里**没有** code 字段

# 8. 提交注册（用**已经注册过**的邮箱）
#    ✅ 40907「已注册账号{username}，请前往登录界面…」
#    ✅ 日志 email_code.rejected, reason=registered

# 9. 提交注册（**不再有 pending 分支**）
#    ✅ 同一个未注册邮箱第二次发码，只要过了 60 秒冷却就**正常发出**
#       （旧口径下这里会被 EMAIL_CODE_PENDING_NOTICE 挡成 40907）
#    ✅ 库里查不到任何 register_requests 相关的表 / 行

# 10. 正常注册
curl -s -X POST 127.0.0.1:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"spec23new","password":"ab","email":"spec23@qq.com","code":"4821"}'
#    ✅ data 含 token / username / is_admin 三个键（与 /api/auth/login 同形）
#    ✅ data **没有** id 键（旧契约的残留）
#    ✅ 日志 auth.registered, username=spec23new, user_id=N
#    ✅ 日志里**没有** email、**没有** IP
#    ✅ 收件箱（frostyj@qq.com，你自己）收到：主题 ACN-spec23new-spec23@qq.com
#       正文「新用户spec23new已完成注册，邮箱是spec23@qq.com，注册时间是<北京时间>。」
#       ✅ 正文里**没有**「微信充值账号」
#    ✅ 新号 quota_limit == 10（`SELECT quota_limit FROM users WHERE username='spec23new'`）
#    ✅ 2 位密码**通过**（Spec22 §2.10 不变）

# 11. 用拿到的 token 直接打 /api/auth/me
curl -s 127.0.0.1:8000/api/auth/me -H "Authorization: Bearer $NEWTOKEN"
#    ✅ 200，且**不是** 40304（新号 10 次额度，used=0 < 10）

# 12. 旧契约的残留检查
curl -s -X POST 127.0.0.1:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"spec23x","password":"ab","email":"spec23x@qq.com","code":"4821","wechat":"张三"}'
#    ✅ **不因为 wechat 报错**（未知字段被忽略，§6.1 的宽容）；报错只会是码或重名
#    ✅ 报错文案里**没有**「微信昵称」四个字（那条 40018 已删）

# 13. 用户名占用
#    ✅ 用已存在的 username + 一个新邮箱（先发码）→ 40001「用户名已存在」
#    ✅ 日志 **没有** auth.registered（建号失败就不该有这条）

# 14. 验证码错 / 过期
#    ✅ code=1111 → 40020「验证码错误或已过期」+ 日志 email_code.verify_failed
#    ✅ 先删掉 email_verifications 那行再提交 → 同样 40020

# 15. 管理端四条路由已消失
curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:8000/api/admin/register-requests \
  -H "Authorization: Bearer $ADMIN"
#    ✅ 404（FastAPI 默认 404，不是本仓的 {code,...} 信封 —— §6.2 已说明）
#    ✅ FRONTEND：管理端页面上**没有**「待审批注册用户」这一块，
#       而「待审批充值记录」那块**布局完好**（§14 陷阱 1）
```

### D. 前端交互（§7.1~§7.3、§7.5、§7.6）

```text
16. 注册弹窗
    ✅ 只有 账号 / 密码 / 确认密码 / 邮箱 / 验证码 五个输入框
    ✅ **没有**收款码图片、**没有**预充值那句话、**没有**「用于支付的微信昵称」
    ✅ 只填账号和密码点提交 → 红字「请填写账号与密码」（**不提微信昵称**）

17. 注册成功 → 自动进主界面
    ✅ 弹窗关闭，直接是聊天界面（不是登录页）
    ✅ **帮助弹窗自动弹出**（首次登录逻辑；且此时已经是改过文案的那一份）
    ✅ 刷新页面仍在登录态（token 落了 localStorage）

18. 帮助弹窗
    ✅ 标题「快速上手ArtiControlNet」，下面**没有**副标题那一行
    ✅ 文生图：「直接描述想要的画面，它生成一张新图。」
    ✅ 图文生图：「文字 + 参考图。例如，把设计线稿传上来，按你的要求上色、上风格。」
    ✅ 探索那句**没有**开头的 ✨
    ✅ 「💰 收费政策」+「新注册用户会收到一定的免费试用额度，用尽后需充值才能继续使用噢！」
    ✅ 底部**只有**一个「开始使用」按钮，**居中**（不是靠左）
    ✅ 底部**没有**「支持 jpg / png / webp / gif…」那一行

19. 余额与充值
    ✅ 那行显示成「充值参考：6.99 0.9元约10次设计服务」，其中 **6.99 带删除线**、0.9 不带
    ✅ 0.9 与 6.99 之间有一个空格
    ✅ 收款码仍然显示（这个弹窗没动它）

20. 欠费充值面板（登录页被踢出来时弹的那个）
    ✅ 那句仍是「请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务」
    ✅ **没有**删除线、**没有** 6.99（§0 第 3-b 条：只改余额页）

21. 管理端
    ✅ 「待审批注册用户」整块消失
    ✅ 「待审批充值记录」照常工作：同意 / 拒绝 / 删除**三个按钮都能点**
       （这一条专门验 CSS 没被误删，§14 陷阱 1）
    ✅ 用户管理表的「联系方式」列还在（显示 email 或「无」）

22. 首次登录帮助只弹一次
    ✅ 刷新页面（同一账号）→ **不再**自动弹
    ✅ 换个新注册的账号登录 → 弹（按用户名分别记）
```

### E. 回归（**别把没要求改的改坏了**）

```text
23. 邮箱登录 / 修改密码（Spec22 三条链路）
    ✅ 用 spec23new@qq.com 走「邮箱登录」→ 进得去
    ✅ 走「修改密码」→ 改完能用新密码登录
    ⚠️ 这两条**必须**验：本 Spec 动了 _reject_duplicate_email（§2.7），
       而它是三条链路共用的

24. 充值链路
    ✅ 主动充值提交 → 管理端出现 pending → 同意 → 额度 +N → 用户收到「充值已到账」
    ✅ 欠费账号走登录页充值 → source=overdue → 同意 → 「账号已恢复」
    ✅ 冷却 3 分钟（40905）仍然生效
```

### F. 限速（**排最后**）

```text
25. 同 IP 5 次 / 5 分钟（发码与验码共用）
    ✅ 连续发码 / 提交错码共 5 次后 → 第 6 次 42901
    ✅ 注册路由的**入口**就判（不是只记失败）
    ✅ 被限速期间换到 /api/auth/register 提交，**仍然** 42901
       （Spec22 §2.6 的那道防线没被本 Spec 拆掉）
```

---

## 14. 陷阱清单（**实现时逐条对照**）

1. **⚠️ 前端一套 `.reg-*` CSS 有两个消费者，一个都不许删。**
   - `AdminPanel.vue`：删「待审批注册用户」那块时，`.reg-admin` / `.reg-admin-title` / `.reg-admin-empty` / `.reg-row` / `.reg-row-info` / `.reg-row-user` / `.reg-row-cell` / `.reg-row-time` / `.reg-row-actions` / `.reg-row-done` **全部保留** —— Spec21 §7.2 的充值台账（「待审批充值记录」）是**照抄这个块**建的，共用同一套类名。删了它，充值台账当场裸奔。
   - `main.css`：`.reg-pay` / `.reg-qr` / `.reg-pay-title` / `.reg-done-text` **全部保留** —— `RechargeModal` 的收款码块与成功屏还在用。**本 Spec 对 `main.css` 的改动量是 0。**
   - **这是本 Spec 最容易犯的错**：删 `<section>` 时眼睛看着那一片，很容易顺手把 `<style>` 里对应的规则一起删。**验证方法**：第 21 条用例（充值台账三个按钮能点）。

2. **⚠️ `create_user` 的显式 `quota_limit`（§2.4）。** 不做这一条，本机上管理员手工建号给 25、自助注册给 10，**代码里看不出差别**（只有一个 `_QUOTA_DEFAULT`）。**唯一能发现它的地方是第 6 条验收用例。**

3. **⚠️⚠️ 本 Spec 最容易踩、后果最重的一处：删表这件事有**两道独立的保险**，缺一不可（§5.2、§5.3）。**
   - **保险一**：`_migrate_lowercase_emails` 的循环元组从 `("users", "register_requests")` 改成 `("users",)`。
   - **保险二**：`_migrate_drop_register_requests` 排在 `_migrate_lowercase_emails` **之后**。

   两者**各自都必要**，而且**症状不同**，很容易只做一件就以为完事：

   | 只做了 | 第一次启动（升级那次） | 第二次启动（之后每一次） |
   |---|---|---|
   | 只改元组 | ✅ | ✅ |
   | 只改顺序 | **❌ no such table 崩** | **❌ 崩** |
   | **两件都做** | ✅ | ✅ |

   ⚠️ **"只改顺序"那一行是最阴的**：它让**每一次启动都崩**，而用户的第一反应是"是不是那次 DROP 把库弄坏了"——其实库好好的，是那句 `UPDATE register_requests` 在找一个双方都同意已经不存在的表。**第 2、3 条验收用例分别盯着这两种症状。**

   另两条**软**顺序约束（排错不报错，但顺序是错的）：`_migrate_users_contact` 历史上读过这张表（回填，今天已删）、`_migrate_drop_phone_and_ip` 会对它做 PRAGMA（对不存在的表返回空集，无害）。这两条**故意写死**：将来若有人把回填加回来，排错顺序的代价是静默丢数据，写死顺序的成本是 0。

4. **⚠️ `init_db` 里那**两行**都要真删：`conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)` 与 `conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)`。**
   - 只删建表那行、留着建索引那行 → `CREATE INDEX ... ON register_requests` 对不存在的表**当场报错，服务起不来**。⚠️ 这一条不是假设：Spec22 已经为 `_CREATE_REGISTER_REQUESTS_IP_INDEX` 踩过一次，那条教训的注释（"留着这句每次启动都撞 no such column: ip，服务直接起不来"）**就写在这两行的正上方**，照着它处理。
   - 两行都留着不删 → 每次启动都"建了又删"，`sqlite_master` 判据永远为真、那条 warning 每次启动都打一遍（第 3 条用例会抓到）。
   - 常量 `_CREATE_REGISTER_REQUESTS_TABLE` / `_CREATE_REGISTER_REQUESTS_STATUS_INDEX` 也要一并删（§5.1 的表）。

5. **⚠️ `send_register_notification` 必须保持同步 `def`（Spec20 §2.1）。** 改成 `async def` 会让 `smtplib` 的阻塞 IO 卡死事件循环——**不报错、只是变慢**，最难查的那类劣化。本 Spec 只改它的签名与正文，**不许动这个性质**。

6. **⚠️ `background_tasks` 的参数位置（Spec20 §6.1）。** 它没有默认值，必须排在 `request: Request` 之后、`x_request_id`（有默认值）之前。本 Spec 改的是同一个路由的签名，**这个顺序一个字都不能动**。

7. **⚠️ `_FIELDS` 白名单这次是"删"不是"加"（§10.1）。** 前三次都是漏加（Spec20/21/22），这次方向相反。**删掉一个没有生产者的键是安全的；漏加一个有生产者的键会静默丢字段。** 别把两件事混了——实现时唯一要检查的是："`register_id` 的四个生产者是不是真的都删干净了"（§5.1 的表可以拿去数）。

8. **⚠️ 提示语"指向不存在的输入框"是这一族 Spec 反复踩的坑。** 本 Spec 有两处：`RegisterModal` 的「请填写账号、密码与微信昵称」（必须改成「请填写账号与密码」），以及 `_reject_duplicate_email` 里那句「该邮箱已提交过注册申请，请等待管理员审批」（必须整句删掉，因为它描述的"等待审批"不存在了）。**改完拿 `grep -rn "微信昵称\|等待管理员审批" frontend/src Server` 扫一遍**。

9. **⚠️ `QUOTA_DEFAULT_LIMIT` 改的是**默认值**，不是现有账号。** 存量用户（25 的）保持 25（§2.10）。**别写一条"把所有人的额度刷成 10"的迁移** —— 那会让一些账号当场变超额被踢下线。

10. **⚠️ 帮助里「一定的免费试用额度」不要去跟 `QUOTA_DEFAULT_LIMIT` 同步。** 那是个模糊词（§3.3-7），是它唯一的优点。

11. **⚠️ `price_line` 的 `strike` 键只在需要划线时出现。** 前端用真值判断（`v-if="seg.strike"`），别去比较 `=== true` 之类的（虽然结果一样，但会让"没有这个键"和"键为 false"两种形态在代码里看起来不同）。**后端不写 `"strike": false`。**

12. **⚠️ 别给注册请求体加 `extra="forbid"`（§6.1）。** 那会让还带着 `wechat` 的旧前端构建**当场 400**，而 GitHub Pages 上可能还跑着旧版。

13. **⚠️ 运行验收前先看 `SMTP_PASSWORD`。** 本机 `Server/.env` 里它是**配好的**，所以拿真实邮箱跑第 7 条会**真的发信**到那个地址——**请用你能收到的邮箱测**（Spec22 §13 同一条）。想验"未配 SMTP"分支就给进程一个空的 `SMTP_PASSWORD`（前缀写法有效）。

---

## 15. 收尾：`CLAUDE.md` 要改的段落

| 段落 | 怎么改 |
|---|---|
| 项目概述里的 `artcn.db` 清单 | 去掉「Spec19 起再加注册申请台账（`register_requests`）」→ 改成「Spec19 加过注册申请台账（`register_requests`），**Spec23 已整表删除**」 |
| `db.py` 那一行 | 去掉 `register_requests`，加一句「Spec23 整表删除，见 gotcha」 |
| **新增一条 gotcha** | 「**删 `register_requests` 这件事有**两道独立的保险**，缺一不可**：① `_migrate_lowercase_emails` 的循环元组去掉 `"register_requests"`；② `_migrate_drop_register_requests` 排在它**之后**。只做 ①→升级那次崩；只做 ②→**每次启动都崩**（症状像"库被 DROP 弄坏了"，其实是那句 UPDATE 在找一个双方都同意已不存在的表）。`init_db` 里的 `_CREATE_REGISTER_REQUESTS_STATUS_INDEX` 那行也要删，否则 `CREATE INDEX` 对不存在的表直接报错。」 |
| `main.py` 那一行 | 「统一鉴权中间件 + auth/admin 路由」不变；`PUBLIC_AUTH_PATHS` 仍是 10 条 |
| **新增一条 gotcha** | 「**注册是自助的：验证码一过直接建号 + 自动登录**（Spec23）。`register_requests` 表与四条管理端审批路由已整表删除（不可逆，回滚靠备份）。「送 10 次」= `QUOTA_DEFAULT_LIMIT`，且 `create_user` **必须显式传**它——列 DEFAULT 在建库那一刻就烤死了，改常量对存量库无效。」 |
| **新增一条 gotcha** | 「**前端 `.reg-*` CSS 有两个消费者**（AdminPanel 注册区已删 / 充值台账还在；main.css 的 `.reg-pay` 等 RechargeModal 在用）——删注册 UI 时一行 CSS 都不许删。」 |
| **新增一条 gotcha** | 「**提示语别指向不存在的输入框**：注册表单已无微信昵称与收款码（Spec23）。」 |
| 配置段的 `QUOTA_DEFAULT_LIMIT` | 从「默认 25」改成「默认 10；Spec23 起它就是新用户的免费试用额度，只影响新建账号」 |
| 配置段新增 | `REGISTER_PRICE_LINE` / `RECHARGE_PRICE_LINE`（片段数组的由来与"不是 v-html"的理由）；`EMAIL_CODE_PENDING_NOTICE` 已删 |
| 「Important notes」里的注册相关条目 | Spec19 那几条（台账语义、`UNIQUE(username)` 的有意缺席）**随表一起作废，删掉**——留着就是描述一张不存在的表 |
| Spec 索引 | 加一行 `specs/Spec23.md` |
