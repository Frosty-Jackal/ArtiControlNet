# ArtiControlNet Spec 22：邮箱验证码体系与全站去手机号

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：**把"邮箱"从一条可选联系方式，变成这个系统唯一的身份凭证**——注册要过邮箱验证码、登录可以用邮箱验证码、改密码也要用邮箱验证码；同时把电话从库里彻底删掉，再给管理端加一张"入口点击（不重复 IP）"表。
> 本 Spec 是 **Spec.md / Spec2~21 的增量补充**，不推翻原有架构。
> **新增 2 张表**（`email_verifications` / `click_events`）+ **删除 3 列**（`users.phone`、`register_requests.phone`、`register_requests.ip`，其中带数据丢失）。
> **无新依赖**（仍是标准库 `sqlite3` / `smtplib` / `secrets`）、**无新持久目录**、**无新 provider / 新模型**。
> 新增 **1 个后端文件**（`verifications.py`）+ **1 个前端组件**（`EmailAuthModal.vue`）+ **1 个前端工具**（`utils/track.js`）+ **2 个环境变量**。
> **5 条公开路由**（`PUBLIC_AUTH_PATHS` 从 5 条变 10 条）+ **1 条管理端路由**。
> **4 封发给用户的新邮件**（验证码 / 注册成功 / 充值已到账 / 账号已恢复）——这是本仓**第一次给用户发信**（此前三封都发给你自己）。发信机制照抄 Spec20/21（`BackgroundTasks` + 同步 `def` + 永不抛异常），但 **2 条 approve 路由要各加一个 `background_tasks` 参数**，两处都有参数顺序的坑（§2.12）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有凭据只在后端环境变量、除 `artcn.db` 外无其他数据库。
> ⚠️ **本 Spec 引入了一条硬依赖**：没有 `SMTP_PASSWORD` 时，**自助注册、邮箱登录、修改密码三条链路全部不可用**（§2.5）。这与 Spec20/21「零配置只是不发通知」的性质**不同**，是本 Spec 最重要的边界。

---

## 0. 八件事一览（用户原话 → 落点）

| # | 用户原话 | 本 Spec 的落点 |
|---|---|---|
| 1 | 注册不准留电话，只能留邮箱；申请注册表、用户信息、申请充值记录里的**电话 key 都删掉** | §5.1（真删两列 `phone`）+ §5.5 + §7.1 + §7.7 |
| 2 | 注册要先过**邮箱验证码**：申请前查该邮箱有没有注册记录，有 → 红字拒绝；无 → 生成 4 位数字发信，10 分钟 TTL、1 分钟才能重发、**TTL 内任一码都对** | §2.2~§2.4、§5.2、§5.4、§6.2、§6.3、§7.1、§7.3 |
| 3 | 把"每人每天只能注册一个账号"的限制删掉 | §5.1（删 `ip` 列）+ §5.5（删 `find_recent_register_by_ip`）+ §8（删 `REGISTER_IP_WINDOW_SECONDS`）+ §9（**40902 退休**） |
| 4 | 记录**5 个入口点击**的不重复 IP 数（同一 IP 只计 1 次），展示在数据统计面板，同样支持清零与上次清零时间 | §5.3、§6.6、§6.7、§6.8、§7.4、§7.5、§7.8 |
| 5 | 注册的密码格式限制从 **≥6 位改成 ≥2 位**，提示文字同步改 | §2.11（三处副本一次收口）、§6.1、§7.1 |
| 6 | 登录界面「新用户注册」下方加**「修改密码」**与**「邮箱登录」**两个按钮，都走邮箱验证码 | §7.2、§7.3、§6.4、§6.5 |
| 7 | 管理员通过**充值**审批 → 给**该用户**发邮件（「充值已到账」/ 欠费的是「账号已恢复」） | §5.6、§6.11、§7.7 |
| 8 | 管理员通过**注册**审批 → 也给注册者发邮件，标题「ArtiConrtolNet-注册成功」，正文「您于<申请时间>申请的注册已通过，您现在可以开始享用ArtiControlNet啦！」 | §5.6、§6.11、§7.7、§2.12 |

> 第 7、8 条是**同一件事的两个入口**：管理端点「同意」→ 用户收到一封邮件。区别只在两张台账（`recharge_requests` / `register_requests`）与两套文案。**两处都必须挂 `BackgroundTasks`**，而且两处都有那个参数顺序的坑（§2.12 最后两行）。

### 四处订正 / 追加（**用户答复里改的口径，实现时按这一列，不要按上面那列的字面**）

| # | 原话 | 改成 | 为什么 |
|---|---|---|---|
| 6-a | 「**找回/修改密码**」按钮 | 按钮文案叫**「修改密码」** | 用户在原密码那条的答复里明确改名。**连带**：第 2 条那句红字里引用的按钮名要同步改成「修改密码」——否则提示语会在指一个不存在的按钮（§2.4） |
| 6-b | 重设界面「先展示用户的原密码」，再给「是否重设密码？」单选项 | **不展示原密码、不给单选项**：验证码一过就直接弹出「新密码 + 二次确认密码」 | `users.password_hash` 是 bcrypt 单向哈希，"展示原密码"在数学上不可能（要能显示就得存明文或可逆加密，那是严重的安全倒退）。用户已确认这么做，并**追加**了一条：**注册页的密码也要二次确认**（§7.1） |
| 5-a | 只说了"注册"的密码下限 | **三处一起改**：注册（40018）、管理员手工建号（40010）、管理员重置密码（40010） | 同一个系统里三条设定密码的路不能有两套规则。用户没点名后两处，但只改注册会留下"用户能自己注册 2 位密码、管理员却建不出 2 位密码"的静默不一致。**若要保留后两处的 6 位，改回来只是 §2.11 里那一行常量。** |
| 8-a | 第 8 条的标题写的是「**ArtiConrtolNet**-注册成功」 | 用「**ArtiControlNet**-注册成功」 | 原话里的 `ConrtolNet` 是 `ControlNet` 的 **`ol`/`lo` 字母换位**（同一句话的正文里 `ArtiControlNet` 拼对了三次），而本 Spec 另外两个给用户的标题也都是 `ArtiControlNet-`，发件人显示名（`_FROM_NAME`）同样是 `ArtiControlNet`。主题里唯一一处拼错会让收信人以为是钓鱼邮件——**这与 §0 第 6-a 条「红字引用了不存在的按钮」是同一类问题**：照抄一个字面笔误，代价是这封信变得可疑。**若你确实要那个拼写，改 `mailer.py` 里那一行字符串即可。** |

> **关于第 1 条的一处事实订正**：用户点名的三张表里，**「申请充值记录」本来就没有电话 key**——`recharge_requests` 表从 Spec21 起就没有 `phone` 列，`_recharge_row_to_dict` 也从不返回它（Spec21 §2.3 明确"本表不含任何多余 PII"）。真正带 `phone` 的只有两处：`users`（→ 管理端「用户管理」的「联系方式」列）与 `register_requests`（→ 管理端「待审批注册用户」那块的「手机号：」那一行）。本 Spec 把这两处**连同库里的列**一起删掉，即全仓 `phone` 归零。

---

## 1. 功能目的

### 1.1 为什么现在做

- **Spec19 的注册是"谁都能给你发一封审批邮件"**。它的唯一防线是"同一 IP 24 小时一次"，而这个判据既挡不住换 IP 的人，又会误伤同一个实验室/宿舍 WiFi 下的第二个人（Spec19 §2.2 自己就记了这条）。**邮箱验证把防线从 IP 换成了"这个邮箱是不是真的能收到信"**——它是可验证的，IP 不是。
- **Spec21 刚刚为"找回密码"埋了伏笔却没做**。`users.email` 是 Spec21 §5.1 才补上的列，当时只用来给注册/充值邮件当收件人。邮箱既然已经落库、已经被验证过一次（注册时），它就是这个系统里**唯一可信的身份凭证**——用户忘了密码时，除了联系你手工重置，本来无路可走（`PUT /api/admin/users/{id}/password` 是管理员专属）。
- **电话在这个系统里从来没有用途**。它对账靠的是**微信昵称**（Spec19 §1.1 / Spec20 §1.1 / Spec21 §2.7 都说过），联系用户靠的是**邮件**（Spec20 起）。电话只有一个作用：多存一份 PII。**删掉它是净收益。**
- **管理端现在完全看不见"有多少人真的来过"**。`GET /api/admin/stats` 有的全是"调用量"（usage 五列），那是**已经用起来的人**的数据。五个入口的点击 UV 才回答"漏斗顶端有多少人"——尤其是「打开登录页」与「点注册」的比值。
- **Spec19 的"每人每天一个账号"在邮箱验证上线后是多余的**。它挡的是"同一个人反复申请"，而邮箱查重（§2.4）挡得更准：同一个人如果只用一个邮箱，申请第二次就会被"已注册账号 X"挡住，且提示是**有用**的（告诉他去登录/改密码），而不像 IP 冷却那样只说"明天再来"。

### 1.2 一句话架构

**一个可复用的邮箱验证码服务（新表 `email_verifications` + 新模块 `verifications.py` + 一个新邮件函数），三个消费场景（注册 / 邮箱登录 / 修改密码）共用一套"发码 → 冷却 → 校验 → TTL 内任一命中"的规则。**

### 1.3 与既有 Spec 的关系

| 既有件 | 本 Spec 怎么动它 |
|---|---|
| `users.phone` | **删列**（Spec21 §5.1 加的，本 Spec §5.1 删） |
| `register_requests.phone` | **删列**（Spec19 加的） |
| `register_requests.ip` | **删列 + 删索引**（Spec19 §2.2 加的唯一用途是 IP 冷却，冷却随需求 3 一起消失） |
| `find_recent_register_by_ip` | **删除**（唯一消费者是那个冷却） |
| `_migrate_users_contact` | **改**：只补 `email` 一列，回填 SQL 去掉 phone 那半（§5.1） |
| Spec19 的四条注册路由 | `POST /api/auth/register` 变（+验证码、−电话、−冷却、密码下限）；`POST /api/admin/register-requests/{id}/approve` 变（**多挂一个后台任务**给注册者发通知，**响应一字不变**）；另两条管理端路由（`reject` / `delete`）**一字不动** |
| Spec19 的 `daily_notice` | **删**（那句"每人每天只能申请一个账号…"已不成立），`GET /api/auth/register-config` 少一个键 |
| Spec18 的限额判定 | **不动**。但 `POST /api/auth/login-by-email` 必须复用同一判据（§6.4）——否则邮箱登录就是一条绕过欠费拦截的后门 |
| Spec20 / Spec21 的邮件机制 | **原样复用**：`BackgroundTasks` + 同步 `def` + 永不抛异常。但"未配 SMTP"的处置**变了**（§2.5） |
| `mailer.beijing_time_text` | 不动（Spec21 已搬到 `timefmt.py`） |
| `AdminPanel.vue` 的三张表 | 用户表删「联系方式」里的电话、注册申请表删「手机号：」那一行；**注册审批与充值审批各多一步发信**（两处的确认文案都要说一声） |
| `GET /api/admin/stats` | 多一组 `clicks` 与一个 `clicks_cleared_at`（**不改任何既有键**） |
| `usage` / `user_quota` / `feedback` | **一个字不改**。新的点击统计与它们**没有任何关系**（不是计费、不进 usage） |

---

## 2. 决策记录（为什么这么选）

### 2.1 电话三列：**真删**（`ALTER TABLE ... DROP COLUMN`）

| 决策 | 选择 | 理由 |
|---|---|---|
| 删列还是留列 | **真删** | 用户答复里选了"真删列"。理由也站得住：留一列谁都不读不写的 `phone`，正是本仓反复记录的那类"看起来还在生效、其实早就不生效"的死数据（CLAUDE.md 为 `QUOTA_CONTACT_EMAIL` 记过同一条）。删掉之后，**库里从此不存在任何手机号**，这是一次真实的 PII 最小化。 |
| 代价 | **历史电话数据永久丢失，不可恢复** | 已当面确认。库外没有备份流程，所以这条是不可逆的——写在这里是为了让将来的人知道它是有意为之。 |
| 怎么删 | `ALTER TABLE ... DROP COLUMN`（SQLite 3.35+，2021-03） | 不重建表：这三列没有索引、没有约束、没有外键，`DROP COLUMN` 直接可用。重建表要复制全部数据 + 重放索引，为一个删列的动作引入那种风险不值得。 |
| SQLite 太老怎么办 | **记一条 warning 并跳过**，服务照常起 | 跳过之后那几列还在，但**没有任何代码读写它们**——等于自动降级成"保留列"形态（也是用户没选的那个选项），功能零影响。让服务因为一个删列失败而**起不来**，是拿可用性换洁癖。这条 warning 必须显眼（`db.migrate` 事件 + 明确写出 SQLite 版本），否则就是静默失败。 |
| **删 `ip` 列前必须先删索引** | **是** | `idx_register_requests_ip` 建在 `ip` 上，SQLite 会拒绝 `DROP COLUMN`（"error in index … after drop column"）。所以那条 `DROP INDEX IF EXISTS` 不是可选步骤，是**前置条件**。 |
| **必须同时删掉 `init_db` 里那句建索引** | **是** | 否则每次启动都会在已经删掉 `ip` 的库上执行 `CREATE INDEX ... ON register_requests(ip, …)` → **"no such column: ip"**，服务直接起不来。这是本 Spec 最容易漏的一处（§5.8 位置约束表里单列了一行）。 |
| 顺序 | 删列迁移必须排在 `_migrate_users_contact` **之后** | 先让 Spec21 那套"补列 + 回填"在没跑过的旧库上正常跑完，再删。顺序反了的话，一个 pre-Spec21 的库会先被删（无列可删）、再被 `_migrate_users_contact` 把 `phone` **加回来**。 |
| 新建的库呢 | DDL 里直接不写这三列 | `CREATE TABLE IF NOT EXISTS` 对新库生效，对存量库无效——两条路都要走（与 Spec21 §2.3 同款）。 |

### 2.2 验证码存哪：**新表 `email_verifications`**（不是内存）

| 决策 | 选择 | 理由 |
|---|---|---|
| 存内存还是落库 | **落库** | 内存更省事（`auth.py` 的登录限速就是内存），但这里有三个具体的坏处：① **开发时 `--reload` 一改代码就重启**，用户手上刚收到的码立刻全失效，而 1 分钟冷却还在内存里一起没了——测试体验会拧巴到无法判断"到底是我填错了还是重启了"；② 用户从"收到码"到"填进去"中间隔着一次页面操作，**生产上重启一次就等于让所有在路上的人白等**；③ Spec19 的 IP 冷却是查库的、Spec18/21 的台账也是查库的，本仓的"有状态的东西"默认都落库。 |
| 表名 | `email_verifications` | 与 `register_requests` / `recharge_requests` 同构词。 |
| 要不要 `purpose` 列 | **要**（`register` / `login` / `reset`） | 三个场景共用一张表，就必须回答"这个码是给哪个场景发的"。**校验时按 purpose 匹配**——否则一个为"注册"发的码可以直接拿去登录。多一列的代价换掉一个真实的越权面，划算。 |
| 要不要"已使用"标记 | **不要** | 用户原话是"10 分钟 TTL 内生成的数字串**只要有一个对了都算数**"。加个 `used` 标记就等于给"每个码只能用一次"，与那句话直接冲突。同一个码在 TTL 内被用第二次，前提是**它本来就在谁手里**——拿到码的人本来就能再走一遍流程，标记它挡不住任何人，只会让行为与文档不一致。 |
| 过期行怎么办 | **在每次发码时顺手删掉过期行**（同一个事务） | 表里最多只有"最近 10 分钟内发出的码"，不可能长大。不设后台清理任务（那要引入一个定时器，为一个几十行的表不值得）。 |
| 码能不能进日志/接口响应 | **都不能** | 它是凭据。发码接口的响应只有 `{"sent": true}`，**绝不回显码**；日志里也绝不出现（§10.2）。调试"为什么没收到"靠的是 `notify.email_code_mail_*` 三条日志的时间戳与 `error`。 |

### 2.3 4 位码的形态：**1000~9999，不带前导零**

| 决策 | 选择 | 理由 |
|---|---|---|
| 取值范围 | `1000`~`9999`（`secrets.randbelow(9000) + 1000`） | 用户要的是"4 位随机数字"。若真的生成 `0000`~`9999`（`f"{n:04d}"`），就会出现 `0042` 这种码——**用户十有八九会输成 `42`**，然后看到"验证码错误"而完全不知道错在哪。这是个 100% 会发生的假故障。排除前导零之后，用户收到的每一个码都是"看起来就是 4 位"的，这个坑从根上不存在。代价是熵从 10000 降到 9000（少 0.15 bit），可以忽略。 |
| 用 `secrets` 还是 `random` | `secrets` | 标准库，无新依赖。验证码是凭据，没有理由用可预测的 `random`。 |
| 前端输入框 | `type="text" inputmode="numeric" maxlength="4"`，**绝不用 `type="number"`** | `type="number"` 会丢前导零、还会在移动端弹出带小数点的键盘。虽然码本身不带前导零，但"输入框里的东西被浏览器改写"这类事一旦发生就极难排查——用文本输入框是最省心的。 |
| 长度写死还是配置 | **写死 4**（`verifications.CODE_LENGTH`） | TTL 与重发冷却才是运维旋钮（它们是"多久"的问题），**4 位是契约**：邮件正文的措辞、前端 `maxlength`、以及"1000~9999"这个范围都绑死它。把它做成环境变量只会让三者有机会不一致。 |

### 2.4 三处查重的口径与三句红字

**发码前的分流（`POST /api/auth/email-code`）**：

| `purpose` | 判据 | 结果 |
|---|---|---|
| `register` | 邮箱**已在 `users`** | 拒绝 → 「已注册账号{username}，请前往登录界面。忘记密码请前往登录界面"修改密码"」 |
| `register` | 邮箱**已有 `pending` 申请** | 拒绝 → 「该邮箱已提交过注册申请，请等待管理员审批」 |
| `register` | 都没有 | **发码** |
| `login` / `reset` | 邮箱**不在 `users`** | 拒绝 → 「还未注册，请宝子前往新用户注册~」 |
| `login` / `reset` | 邮箱在 `users` | **发码** |

| 决策 | 选择 | 理由 |
|---|---|---|
| 提示语从哪来 | **`config.py` 常量，前端零副本** | 与 `QUOTA_EXCEEDED_MESSAGE` / `REGISTER_PRICE_NOTICE` / `RECHARGE_COOLDOWN_MESSAGE` 同一原则。前端只把后端回传的 `message` 显示成红字，一个字都不抄。 |
| 三句红字共用一个错误码 | **是**（40907） | 与 Spec19 的 `40018`、Spec21 的 `40019` 完全同款：多个 message 共用一个码。好处是**前端零分支**——它本来也不需要知道是哪一种，显示 message 就完了。 |
| 「已注册账号 X」这句会泄露用户名 | **照用户原话，不脱敏** | 任何知道某个邮箱的人，都能通过这条接口问出"这个邮箱注册的账号叫什么"。这是**真实的信息泄露**，与 Spec21 §3.3-2 那条"公开欠费端点能被别人替交"同级：**用户明确要这句文案**（它的价值在于告诉用户"去登录、密码忘了就去改密码"，匿掉用户名会让这句话失去一半用处）。已写入 §3.3-3，**知悉并接受**。 |
| 为什么 `register` 要额外查 `pending` | 因为需求 3 删掉了 IP 冷却 | 删掉冷却后，邮箱查重是这个流程**唯一**的防重手段。不查 pending 的话，同一个人可以反复提交、你反复收到同一份审批邮件——而那正是 IP 冷却当初想挡的事。用户已确认"算，另给一句提示"。 |
| 「该邮箱已提交过注册申请」这句是谁拟的 | **本 Spec 拟的**（用户只给了"已注册"那句原文） | 因为它必须存在（上一行的理由），而且**不能**复用"已注册账号X"（那个人还没被开通，让他"前往登录界面"是错的）。措辞随时可改，位置固定在 `config.EMAIL_CODE_PENDING_NOTICE`。 |
| `POST /api/auth/register` 提交时还要不要再查一遍 | **查**（只查 `users`） | 从"发码"到"提交"之间隔着几分钟，中间可能有人先注册了同一个邮箱。提交那一遍是最后的闸门，用的是同一句话。**不再查 pending**：能走到这里的邮箱必然在发码时通过了 pending 检查，而管理员删掉那条 pending 是**期望中的逃生通道**（Spec19 §13 用例 11），不该在这里被挡住。 |
| 邮箱要不要转小写 | **要**，在路由入口 `.strip().lower()`（§2.8） | 手机键盘会自动把邮箱首字母大写，`A@qq.com` 与 `a@qq.com` 必须是同一个邮箱。 |

### 2.5 发信仍在 `BackgroundTasks`，但"未配 SMTP"改成**硬错误**

| 决策 | 选择 | 理由 |
|---|---|---|
| 发码邮件走同步还是后台 | **后台**（`BackgroundTasks` + 同步 `def`，照 Spec20 §2.1） | 保持"发信永不阻塞请求"这条既有铁律，不引入第二种发信模式。同步发信能覆盖的失败只有"SMTP 立刻报错"这一种，而多一次的代价是**每个用户点「获取验证码」都要等一次 SMTP 往返**（黑洞地址时是 10 秒）。 |
| 那"用户收不到码"怎么办 | 靠**前端提示语 + 重发**，不靠同步失败 | 提示语写「验证码已发送，若 1 分钟内未收到请重试」。SMTP 服务器接受后丢弃、授权码错、被丢进垃圾箱——这些**都不是同步发送能区分的**，同步只买到"知道它当场报错了"。把这条写进 §3.3-2，不假装它不存在。 |
| **`SMTP_PASSWORD` 为空时** | **路由层直接报错**（50302「邮箱服务暂不可用，请联系客服 {SUPPORT_EMAIL}」），**不落库、不发信** | 这是**唯一可以预知**的失败，而且它的后果是"用户永远等不到码"。Spec20/21 里静默降级是对的（邮件只是通知，不发不影响业务），但**验证码是业务的前置条件**——静默降级在这里的含义变成"接口 200、用户傻等"。所以本 Spec 把它从"静默"改成"明确报错"。**这是本 Spec 与 Spec20 §5.3 立场不同的一处，刻意不同。** |
| 检查写在哪 | **路由里**（`if not config.SMTP_PASSWORD: raise …`），**不在 `mailer.py` 里抛** | `mailer.py` 的"永不抛异常"契约一个字不改（Spec20 §5.3）。判断配置是路由的职责，与 Spec19 的 `REGISTER_ENABLED → 40305` 是同一个写法。 |
| 前端要不要跟着隐藏注册入口 | **不隐藏** | 隐藏需要往 `register-config` 里再加一个字段、前端再多一个分支，而收益只是"少一次点击"。用户点「获取验证码」时看到的那句红字**已经足够明确**（还带客服邮箱）。一个机制就够，不铺两个。 |
| 用户注册页提交时的注册通知（发给你自己的那封）呢 | **不动**，仍是静默降级 | 它依然是"通知"，不是"前置条件"。零配置时：**新用户注册不了，但你手工建号照常可用**——这是零配置下唯一的兜底路径（§3.3-1）。 |

### 2.6 验证码校验失败要计入登录限速

| 决策 | 选择 | 理由 |
|---|---|---|
| 为什么突然要限速 | 因为**邮箱登录是一条只靠 4 位码保护的登录通道** | 4 位数字只有 9000 种可能，10 分钟 TTL 内**不限次数地猜**，一个脚本几分钟就能撞开任意一个已知邮箱的账号。**这不是理论风险，是本 Spec 自己开出来的洞。** |
| 怎么限 | **复用 Spec2 的登录限速**：三个校验点失败都调 `auth.record_login_failure(ip)`，入口处先判 `auth.is_login_blocked(ip)` → 42901 | 已有现成机制（同 IP 5 次失败 / 300 秒窗口），复用它不新增任何配置、不新增错误码，而且**限速口径与密码登录一致**（同一个 IP 猜密码和猜验证码是一回事）。 |
| 哪三个校验点 | `verify-email-code`、`login-by-email`、`reset-password` | 注册的验证码校验（在 `POST /api/auth/register` 里）**也算**——它同样是一条公开的猜码入口。 |
| 函数名要不要改 | **不改**（`record_login_failure` / `is_login_blocked`），只把 docstring 扩成"登录 / 验证码校验" | 改名的收益是措辞准确，代价是 `main.py` 四处调用点 + Spec2 文档全线对不上。本仓的做法是**在 docstring 里写清楚**（Spec21 §2.2 搬 `beijing_time_text` 时是同样的取舍）。 |
| 猜中的概率还剩多少 | 5 次 / 5 分钟 / IP | 9000 种可能、10 分钟 TTL 内最多试 10 次（还是换 IP 的前提下），撞中概率 < 0.12%。而这还是**攻击者已经知道你某个用户的邮箱**的前提。 |

### 2.7 「修改密码」的重设界面：不展示原密码、不分单选项

| 决策 | 选择 | 理由 |
|---|---|---|
| 展示原密码 | **做不到，不做** | `password_hash` 是 bcrypt 单向哈希。要"展示原密码"就必须存明文或可逆加密——那会让一次库泄露直接等于所有账号失守，且要把登录校验、初始管理员、`update_password` 全部推翻重做。已当面确认改掉这一步（§0 第 6-b 条）。 |
| 「是否重设密码？」单选项 | **删掉** | 它的存在前提是"用户看到了原密码，所以可能决定不改"。既然看不到原密码，**点了「修改密码」按钮的人本来就是要改密码的**——再去问他"是否重设"是废话，而且选"否"的那条路（走完全部验证、什么也不做、点完成）是一次纯浪费。用户已确认：验证一过就直接弹密码栏。 |
| 那"找回"和"修改"要不要分成两个入口 | **不分**，合并成「修改密码」 | 忘记密码的人与想换密码的人，**在邮箱验证通过之后要做的事完全一样**：设一个新密码。分成两个入口就要两套 UI、两条路由、两句话，而它们的差异只存在于入口的名字里。 |
| 身份凭证是什么 | **邮箱验证码** | 这是"忘记密码"场景下唯一可用的凭证（密码本身已经不知道了）。 |
| 验证码要校验几次 | **两次**：`verify-email-code` 一次（用于展开密码栏），`reset-password` 再验一次 | 前端的状态不可信——"展开密码栏"只是 UI，真正授权的是提交那一刻。第二次校验是**服务端唯一能信的那次**，不能省。 |
| 改完密码后 | 关闭面板 → 回登录页 + 绿色提示「密码已修改，请用新密码登录」 | 用户原话是"按了之后回到登录页"。加一句成功提示是因为**什么都不说地回到登录页，用户无法区分"改成功了"与"我没点对"**。 |
| 已登录的旧 token 会被踢掉吗 | **不会** | 本仓从 Spec2 起就没有 token 黑名单（JWT 是无状态的、有效期 7 天）。所以**改密码不会让任何已经登录的会话失效**。这是真实的边界，写进 §3.3-4——要说"改了密码别人就进不来了"，那是错的。 |

### 2.8 邮箱大小写：入库前统一小写

| 决策 | 选择 | 理由 |
|---|---|---|
| 为什么必须处理 | 手机键盘会自动把首个字母大写 | 用户注册时打的是 `Zhang@qq.com`，改密码时打的是 `zhang@qq.com`——**同一个人在系统里变成两个邮箱**：改密码说他"还未注册"，注册又说"已注册账号 zhang"。这类故障用户根本描述不清。 |
| 在哪做 | **路由入口**：`email = (payload.email or "").strip().lower()` | 与其它字段的 `strip` 放在一起，一条规则、四个路由各一行。**db 层不做隐式转换**——本仓的立场是"规则只有一份，在路由层"（Spec19 对手机号/邮箱格式的处理就是这个立场）。 |
| 存量数据呢 | 加一次**幂等迁移**把 `users.email` 与 `register_requests.email` 小写化 | `UPDATE … WHERE email <> LOWER(email)`，第二次启动影响 0 行。不做的话，一个在 Spec21 时代用大写邮箱注册的账号，**邮箱登录永远进不去**（而他自己完全不知道为什么）。 |
| 查询要不要 `COLLATE NOCASE` | **不用** | 库里全是小写之后，等值查询就是对的。加 `COLLATE NOCASE` 等于承认库里可能有大写，反而把"写入口已经规范化了"这件事变得含糊。 |
| `users.email` 加 `UNIQUE` 吗 | **不加** | 唯一性由**发码前的查重**（§2.4）保证。加 `UNIQUE` 索引的风险是：存量库若已有一条重复（Spec21 的回填是按 username 逐条填的，理论上两条 approved 申请可以同邮箱），`CREATE UNIQUE INDEX` 会在**启动时抛异常**→ 服务起不来。收益（挡住新数据）与查重完全重叠，风险却是"服务不可用"。 |
| 那两条同邮箱的存量账号，邮箱登录进哪个 | **`ORDER BY id ASC LIMIT 1`**（先注册的那个） | 必须给一个确定的答案。`get_user_by_email` 的 docstring 里写明这条口径。 |

### 2.9 入口点击统计：一张 `(event, ip)` 去重表

| 决策 | 选择 | 理由 |
|---|---|---|
| 记什么 | `(event, ip, created_at)`，`UNIQUE(event, ip)` + `INSERT OR IGNORE` | 用户要的是"**不重复** IP 数"。去重交给数据库的唯一约束，`COUNT(*)` 就是答案——不要在应用层写"先查再插"（那是两个线程能同时通过检查的经典竞态）。 |
| 唯一性是"永久"还是"每天" | **永久**（直到清零） | 用户原话是"如果同一 IP 只计数 1 次"，没有时间窗口。加窗口就要回答"窗口多长、跨窗口怎么算"——而管理端的「清零」按钮本来就是手动重置这个口径的旋钮（与 Spec11 的调用统计同一个模型）。 |
| 哪 5 个事件 | `login_page` / `register` / `community` / `gallery` / `recharge` | 与用户点名的 5 个入口一一对应。**「点击登录主页」的口径是"打开登录页"**（用户已确认）：SPA 里没有任何指向 `ArtiControlNet.fun` 的链接，而"打开登录页"正好是漏斗的顶端。 |
| 为什么不加"合计" | **不显示总数** | 5 个事件的 IP 集合是**互相重叠**的（同一个人先打开登录页、再点社区）。把它们加起来得到的数没有任何含义，而放在表末会让人以为那是"总访问量"。 |
| IP 从哪来 | `auth.client_ip(request)`（`X-Forwarded-For` 首个 IP） | 与登录限速同一口径，不新写一份。反代的场景下 `X-Forwarded-For` 才是真实 IP，与 Spec2 的判断一致。 |
| IP 会出去吗 | **不会**：只落库、只参与 `COUNT` | 响应里只有 5 个数字，日志里也没有 IP（Spec19 §10 的规矩）。这一条要在 §3.3-5 写清楚：**统计面板展示的是"数量"，不是"名单"**。 |
| 前端怎么上报 | 新 `utils/track.js`，用**裸 `fetch`**（不走 `chatApi.js` 的 axios 实例），且 `catch` 掉一切异常 | 两个理由：① 那个 axios 实例的响应拦截器会在 401/40304 时触发 `artcn:unauthorized` / `artcn:quota_exceeded` 全局事件——**埋点绝不能把用户踢下线**；② 埋点失败不能影响任何主流程。用裸 `fetch` 是彻底解耦，也省掉"这条路由必须在白名单里否则会登出"这种隐式耦合。 |
| 上报要不要 `await` | **不等**（fire-and-forget） | 点击埋点是"顺手记一笔"，让用户等它没有任何意义。 |
| `POST /api/click` 放在公开路径 | **是**（`PUBLIC_AUTH_PATHS` +1） | 「打开登录页」与「点注册」这两个埋点**发生时用户还没有 token**。 |
| 事件名非法怎么办 | 40021「未知的埋点事件」 | 白名单校验（`_CLICK_EVENTS`），不拼接外部输入（本仓的既有做法）。**不静默忽略**：只有我们自己前端会调它，收到未知事件名说明代码写错了，静默会让这个错误永远不被发现。 |
| 日志量会不会爆 | **只在"新记下一个 IP"时打一行**（`INSERT OR IGNORE` 的 `rowcount == 1`） | 每个 IP 每个事件最多一行日志，正好就是"新增了一个不重复 IP"这件事。重复点击（同 IP 再点）不打日志——这既压住了量，又让日志本身就等于一份增量报表。 |

### 2.10 密码下限 2：三处副本一次收口

| 决策 | 选择 | 理由 |
|---|---|---|
| 有哪几处 | **3 处**：注册（`main.py:1159`，`6 <= len(password) <= 72`，40018）、管理员手工建号（`main.py:1374`，`len(password) < 6`，40010）、管理员重置密码（`main.py:1437`，同上） | 同一个系统里设定密码的路有三条，各有各的字面量。 |
| 怎么做 | 在 `auth.py` 里加 `MIN_PASSWORD_LEN = 2`，并把**已经存在但从未被引用**的 `MAX_PASSWORD_LEN = 72` 一起用起来；三处都改成引用这两个常量 | 那个 `MAX_PASSWORD_LEN` 是 Spec2 留下的**死代码**（全仓零引用，Spec19 的注册路由直接写死了 72）。既然这次要动同一个数字，就顺手把它变成活的——**一份规则，一个地方**。这正是 CLAUDE.md 反复记的那类"同值副本会漂移"的解法。 |
| 提示文案 | 「密码需为 2~72 位」（由常量 f-string 拼出） | 数字改了文案必须跟着改，否则就是"提示说 6 位、其实 2 位就过"的静默不一致。拼出来之后**不可能对不上**。 |
| 初始管理员那处（`db.py` 的 `ADMIN_PASSWORD`，也是 ≥6）要不要改 | **不改** | 它不是用户输入，是部署者自己写在 `.env` 里的口令；那道 ≥6 是给"顺手写个 123 当管理员密码"设的防呆线。改它只会让部署时的弱口令更容易通过，与"让用户能设 2 位密码"是两件事。**已记录，是有意不同。** |
| 前端要不要也校验 | **只改 placeholder**（「至少 6 位」→「至少 2 位」），不加代码校验 | 与 Spec19 §7.3 的立场一致：长度规则只有一份中文 message，在后端。前端唯一**新增**的代码校验是"两次密码是否一致"——那是后端**收不到**的信息（确认框根本不提交），必须在前端判。 |

### 2.11 删 IP 冷却后，**40902 退休**

| 决策 | 选择 | 理由 |
|---|---|---|
| `40902 RegisterRateLimitedError` | **整个类删掉** | 它的唯一语义是"同一 IP 24 小时内已提交过"。需求 3 把这个限制删了，这个码就**没有生产者**了。留着一个没人抛的异常类 + 一个不再出现的错误码，正是本仓最不喜欢的那种"看起来还在、其实早没了"的东西。 |
| 要不要把 40902 改嫁给"验证码重发冷却" | **不**，新开 `40906` | 重定义既有码的含义，会让**旧日志里的 40902 变成一句假话**（"40902 = 每 IP 每天一次"这条认知会一直留在文档和你的记忆里）。新开一个号只花一个数字，换来一条永远不会被误读的历史。 |
| 那 `REGISTER_IP_WINDOW_SECONDS` | **删掉**（`config.py` 里那一行） | 环境变量的唯一读者是那个冷却。留一个"设了也不生效"的变量，CLAUDE.md 已经为 `QUOTA_CONTACT_EMAIL` 记过一次教训。 |
| 那 `REGISTER_DAILY_NOTICE` | **删掉**，`register-config` 的 `daily_notice` 键**一并删掉**，前端那行 `<p class="reg-note">` 也删 | 那句原文是「每人每天只能申请一个账号，若操作失误或其他需求请联系在线客服 {SUPPORT_EMAIL}」——限制没了，这句话就成了假话。三个地方必须一起动，少一处就是"界面上还在承诺一个不存在的规则"。 |
| `auth.client_ip` 还留着吗 | **留着** | 它还有两个消费者：登录限速（42901）与新的点击埋点（§5.3）。删的是**注册的 IP 冷却**，不是 IP 这个工具。 |

### 2.12 审批通过后给用户发信：本 Spec 的 3 封"发给用户"的邮件

| 决策 | 选择 | 理由 |
|---|---|---|
| 谁收 | **用户本人** | 前三个邮件函数（Spec20 注册通知 / Spec21 两封充值通知）的收件人都是**你自己**。这**三封**是本仓第一次发给用户，所以：正文里不能再出现「微信充值账号是…请立即审批」这种内部话术，措辞必须能**公开见人**。 |
| 哪三封 | ① 注册审批同意 → 「注册成功」② 充值审批同意（`source='user'`）→ 「充值已到账」③ 欠费充值审批同意（`source='overdue'`）→ 「账号已恢复」 | ①挂在 `register_requests` 的 approve 上；②③挂在 `recharge_requests` 的 approve 上，由 `source` 分流——这正是那一列存在的意义（Spec21 §2.3 说它"是排障时第一个要看的字段"），这里成了它的第一个业务消费者。 |
| 主题前缀 | 「ArtiControlNet-」（用户原话），**不是**既有的「ACN…」 | 照抄用户原话（第 8 条那个字母换位除外，见 §0 第 8-a 条）。三封给管理员的邮件用 `ACN-` / `ACN充值-` / `ACN欠费充值-`，三封给用户的用 `ArtiControlNet-`——**不一致是有意的**，因为收件人不同（自己人 vs 用户）。 |
| 三封的正文措辞从哪来 | **全是用户逐字给的原文**，包括语气词（「啦」「~」）与那句在充值两封里**逐字重复**的「充值的金额已到账」 | 别"统一"成模板、别"润色"（Spec21 §2.7 的同一条立场）。用户在写第 8 条时特意换了句式（「申请的注册已通过」而不是「充值的金额已到账」），照抄。 |
| `<申请时间>` 取哪个字段 | ①`register_requests.created_at`（提交注册申请的时刻）②③`recharge_requests.created_at`（提交充值申请的时刻） | 用户给的三个句子说的都是「**申请**时间」。台账里**有** `reviewed_at`（审批时刻），**但三句话都不用它**——那正是"申请时间"与"到账时间"的区别所在。统一走 `timefmt.beijing_time_text()`（Spec21 §10 的口径：库里是 UTC，邮件里必须是北京时间，固定 +08:00）。 |
| 收件地址从哪取 | ①`record["email"]`（**申请行**上那个被验证码验证过的邮箱）②③`user["email"]` | 两者都由路由里已经取到的那一行提供，**不用再查一次库**：① 的 `record` 就是 `db.get_register_request(request_id, with_secret=True)` 那次预检的结果（`approve_register_request` 会把这个 email 原样复制进新用户行，所以与 `user["email"]` 恒等）；②③ 的 `user` 是 40402 预检时取到的那一行。 |
| 用户没有邮箱呢 | 跳过发信 + 一条 `*_mail_skipped`（`reason=no_email`），**业务照做** | ① 在 Spec22 之后**几乎不会发生**（注册邮箱已必填），但**仍要判**：一条 Spec22 之前提交的、只留了手机号的 pending 申请被同意时，`record["email"]` 就是 NULL。②③ 发生在管理员手工建的号上（`create_user` 不传 email），**这是允许的形态**，不是错误（Spec21 §3.3-6 已为同一情形定过口径）。**不发信，但额度照加 / 号照建**——邮件是通知，不是业务（Spec20 §5.3 的原则在这里仍然成立）。 |
| 挂在哪 | 两条 approve 路由的 `BackgroundTasks` | ⚠️ **两条路由当前都没有** `background_tasks` 参数，都要新增，而**参数顺序有坑**：`background_tasks` 没有默认值，Python 语法要求它排在所有带默认值的参数**之前**。两条路由的签名形状一样（`request_id` / `payload` / `request` 都无默认值，`x_request_id: Optional[str] = Header(...)` 有），所以**两处的插法也完全一样：插在 `request: Request` 之后、`x_request_id` 之前**。Spec20 §6.1 为 `register_request` 踩过一模一样的一次。 |
| 拒绝 / 删除要不要也发 | **不发** | 用户只要求"通过"时发。被拒的人本来就会来问你（Spec19 §3.3 的既有口径），而且"你的申请被拒绝了"这种邮件写起来有分寸问题，**不在范围内**。 |
| 邮件里要不要带上审批结果之外的信息（额度、余额、账号状态） | **不带** | 用户给的三段正文里一个字都没提这些。多写一句"您的额度已调整为 N 次"就要维护"额度怎么算成人话"这套逻辑，而它随时会与 Spec21 §2.9 那个"两套口径故意不一致"的余额公式打架。**三封信都只说一句话，做到。** |

---

## 3. 需求边界

### 3.1 范围内

**后端**

- **新增** `Server/verifications.py`：`generate_code()` + `PURPOSES`（§5.4）。
- `Server/db.py`：三列 DDL 删除 + `_migrate_drop_phone_and_ip()` + `_migrate_lowercase_emails()` + `_migrate_users_contact()` 改造；`_row_to_dict` / `_register_row_to_dict` / `create_user` / `create_register_request` / `approve_register_request` 去 phone/ip；**删** `find_recent_register_by_ip`；**新增** `get_user_by_email` + `email_verifications` 三函数 + `click_events` 四函数；`get_cleared_times()` 加一个键（§5.5）。
- `Server/config.py`：删 2 个变量、加 2 个变量 + 4 句提示语常量（§8）。`REGISTER_DAILY_NOTICE` 删除。
- `Server/errors.py`：+5 个类（40020 / 40021 / 40906 / 40907 / 50302），**删 1 个**（40902）。
- `Server/schemas.py`：`RegisterRequestCreate` 改造；+5 个请求体（§6.10）。
- `Server/mailer.py`：+`send_email_code()`、+`send_recharge_approved_notification()`、+`send_register_approved_notification()`（§5.6）。
- `Server/logging_setup.py`：`_FIELDS` **删** `has_phone`、**加** `purpose` / `click_event`（§10.1）。
- `Server/main.py`：注册路由改造 + 密码下限三处 + **5 条公开路由** + **1 条管理端清零路由** + `GET /api/admin/stats` 加一组 + `PUBLIC_AUTH_PATHS` 5 → 10 + 三处邮件调用的 contact 参数去 phone + **两条审批路由各挂一次发信**（注册 / 充值）。
- `Server/.env.example`：一段占位（+2 变量，−1 变量）。

**前端**

- **新增** `frontend/src/views/EmailAuthModal.vue`（两种模式：`login` / `reset`）。
- **新增** `frontend/src/utils/track.js`。
- `RegisterModal.vue`：删手机号、加邮箱必填 + 验证码 + 获取验证码（带倒计时）、加确认密码、placeholder 改「至少 2 位」、删 `daily_notice` 那一行。
- `Login.vue`：加两个按钮、挂 `EmailAuthModal`、加绿色成功提示、**两个埋点**（打开登录页 / 点注册）。
- `App.vue`：**三个埋点**（社区 / 我的作品 / 余额与充值）。
- `AdminPanel.vue`：用户表删电话、注册申请表删手机号那一行。
- `StatsPanel.vue`：新增「入口点击（不重复 IP）」区块 + 第三个清零按钮 + 上次清零时间。
- `store/auth.js`：+`loginByEmail(email, code)`。
- `api/chatApi.js`：+6 个函数、`submitRegisterRequest` 改签名。
- `assets/styles/main.css`：`.login-ok`、`.reg-code-row`、`.email-auth-*`。

**文档**：`specs/Spec22.md`（本文）、`CLAUDE.md`。

### 3.2 不在范围内（明确不做）

| 不做的事 | 为什么不 |
|---|---|
| **不做短信验证码** | 没有短信通道、没有签名报备、按条计费。邮箱是这个系统里唯一免费的、已经验证过的通道。 |
| **不做"密码强度"校验**（大小写/数字/符号） | 用户要的是**下限降到 2 位**——方向是"更宽松"，不是"更严格"。加复杂度要求是反着来。 |
| **不做 token 黑名单 / 改密码后踢下线** | 见 §2.7 最后一行。要做就得引入服务端会话表，那是另一个项目。 |
| **不做"已登录用户改密码"入口** | 「修改密码」按钮在**登录页**（用户明确指定了位置）。已登录的人想改密码，走"退出 → 修改密码 → 重新登录"，多两步但只维护一套 UI。 |
| **不做注册审批被拒 / 充值审批被拒时的通知邮件** | §2.12。用户只要求"通过"时发。 |
| **不做点击统计的"每日 UV / 趋势图"** | 用户要的是"不重复 IP 数"这一个数。时间序列要引入按天聚合、要定"按哪个时区切天"，是一个独立的需求。 |
| **不做点击统计的明细查询（谁点的）** | 表里只有 `(event, ip)`，接口只返回 `COUNT`。**这是有意的**：把 IP 名单暴露到管理端界面，等于给这个系统加了一份"访客日志"。 |
| **不给 `users.email` 加 UNIQUE 约束** | §2.8。 |
| **不动 Spec18 的 `usage` / `user_quota` 双写、不动 Spec21 的充值链路（除审批后发信）** | — |
| **不动 `POST /api/recharge/requests`、`POST /api/auth/recharge-request` 的任何一行业务逻辑** | 只改它们 email 表达式的取值（去掉 `or phone`，§5.5）。 |
| **不给注册页做"验证码倒计时结束前禁用提交"** | 验证码与提交是两件事：用户可以先去填别的字段。倒计时只锁「获取验证码」按钮。 |
| **不清理 `register_requests` 里历史行的 `email` 为空** | 被拒绝的旧申请可能没有邮箱（当时 phone/email 二选一）。**保持可空**：不做 `NOT NULL` 迁移，只在**新写入**时必填（§5.1）。 |

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **⚠️ 零 SMTP 配置 = 三条链路全废。** 不设 `SMTP_PASSWORD` 时：自助注册（卡在"获取验证码"）、邮箱登录、修改密码**全部不可用**，用户看到的是 50302「邮箱服务暂不可用，请联系客服 …」。**仍然可用的**：老用户用密码登录、管理员手工建号（`POST /api/admin/users`，不走邮箱验证）、所有已登录用户的功能。这与 Spec20 §3.3-1 / Spec21 §3.3-1 的"零配置只是不发通知"**性质不同**，是本 Spec 的硬依赖。部署时**必须**配好 `SMTP_PASSWORD`（本机 `Server/.env` 里已经配好了）。
2. **SMTP 配了但发不出去时，接口仍然 200。** 授权码错、被限流、进垃圾箱——用户在界面上看到的是"验证码已发送"，然后等不到信。唯一的自救是 1 分钟后重发；排障看 `notify.email_code_mail_skipped` / `_failed`（§2.5）。**这是同步发送也解决不了的那部分**，本 Spec 不假装它不存在。
3. **任何人知道某个邮箱，都能问出它注册的账号名。** `/api/auth/email-code` 的 `register` 分支会返回「已注册账号{username}…」（§2.4）。这是用户明确要求的文案，代价已记录：**邮箱 → 用户名的枚举**是开放的。
4. **改密码不会踢掉任何已登录的会话。** 本仓从 Spec2 起就没有 token 吊销机制（JWT 无状态、7 天有效期）。用户改了密码之后，之前登录的设备**仍然能用**，直到 token 自然过期。**别对用户承诺"改了密码别人就进不来了"。**
5. **点击统计只有"数量"，没有"名单"。** 表里存了 `(event, ip)`，但接口只回 `COUNT`，日志里没有 IP（§2.9）。反过来说：**它确实在库里存了 IP**（与 Spec19 的 `register_requests.ip` 同一性质）。将来若要做"删除某个 IP 的记录"，得走管理端加一条路由——**当前没有**。
6. **反代没配 `X-Forwarded-For` 时，所有点击的 IP 都是反代的地址。** 后果是"5 个事件各只有 1 个不重复 IP"。`auth.client_ip` 已经优先读 `X-Forwarded-For`（Spec2 起），但**前提是反代真的写了这个头**。部署到公网时先确认这一点，否则这张表毫无意义。
7. **同一个 IP 后面的多个人只算 1 个。** 学校机房、同一个 WiFi 下的宿舍——这是"不重复 IP"这个口径**固有**的偏差，不是 bug。它衡量的是"多少个出口地址来过"，不是"多少个人来过"。
8. **被强制退出/超额的用户会被计一次 `login_page`。** `Login.vue` 在 `auth.token` 变成 null 时挂载（包括被踢回登录页那一次），所以那次也算"打开登录页"。同一个 IP 只计一次，所以影响很小——**已知，不修**。
9. **验证码 TTL 内可重复使用。** 同一个码在 10 分钟内可以被用第二次（§2.2）。前提是它已经在谁手里。
10. **`email_verifications` 表会被"顺手清理"。** 每次发码时删掉过期的行（§2.2）。这意味着**不能**从这张表查询"某人上周申请过几次验证码"——它设计上就不是台账，只有最近 10 分钟。要审计就从日志里找（`email_code.requested`）。
11. **并发提交注册仍然没有唯一约束兜底。** `register_requests` 故意没有 `UNIQUE(username)`/`UNIQUE(email)`（Spec19 §2.2），查重是**业务规则**不是数据库约束。两个人几乎同时用同一个邮箱提交，理论上能产生两条 pending。概率极低（都要先拿到同一个邮箱的验证码），发现即用管理端的「删除」处理。

---

## 4. 技术栈增量

| 项 | 增量 |
|---|---|
| 新依赖（`requirements.txt`） | **0** —— `secrets` / `sqlite3` / `smtplib` 全是标准库 |
| 新 provider / 新模型 / 新上游 API | **0** |
| 新数据库 | 0（仍是 `Server/artcn.db`） |
| 新表 | **2**（`email_verifications` / `click_events`） |
| 删列 | **3**（`users.phone` / `register_requests.phone` / `register_requests.ip`，**不可逆**） |
| 新迁移函数 | **2**（删列 / 邮箱小写化）+ 1 个改造（`_migrate_users_contact`） |
| 新持久目录 | **0** |
| 新错误码 | **5**（40020 / 40021 / 40906 / 40907 / 50302），**删 1 个**（40902） |
| 新环境变量 | **2**（`EMAIL_CODE_TTL_SECONDS` / `EMAIL_CODE_RESEND_SECONDS`），**删 1 个**（`REGISTER_IP_WINDOW_SECONDS`） |
| 新后端文件 | **1**（`verifications.py`） |
| 新前端文件 | **2**（`views/EmailAuthModal.vue` / `utils/track.js`） |
| 新路由 | **6**（5 公开 + 1 管理端） |

**SQLite 版本要求**：`ALTER TABLE … DROP COLUMN` 需要 **3.35.0+**（2021-03）。Python 3.9+ 自带的 `sqlite3` 通常满足，但**必须**在 §13 用例 1 里实测一次，不满足时走 §2.1 的降级分支。

---

## 5. 架构设计（增量）

### 5.1 三列删除 + 三条迁移

**DDL**（`_CREATE_TABLE`，新库用）——只删不加：

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    quota_limit   INTEGER NOT NULL DEFAULT {_QUOTA_DEFAULT},
    email         TEXT           -- Spec22：**唯一**的联系方式（Spec21 加的 phone 已删）
)
```

```sql
CREATE TABLE IF NOT EXISTS register_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,
    password_hash TEXT NOT NULL,             -- bcrypt；同意后置为 ''（Spec19 §2.1）
    email         TEXT,                      -- Spec22：注册必填（旧行可能为 NULL，保持可空）
    wechat        TEXT NOT NULL,             -- 用于支付的微信昵称（管理员对账用）
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at    TEXT NOT NULL,
    reviewed_at   TEXT                       -- NULL = 尚未处理
)
-- Spec22 删掉的三样：phone / email 的并列项 phone、ip 列、以及 idx_register_requests_ip 索引。
```

**删除 `init_db` 里那句建索引**（⚠️ 漏掉它服务起不来，§2.1）：

```python
# Spec22 删除：_CREATE_REGISTER_REQUESTS_IP_INDEX 整个常量 + init_db 里那句 conn.execute(...)
# 原因：ip 列已删。留着的话每次启动都会撞 "no such column: ip"。
```

**新迁移一：删列**（`init_db` 里的位置见 §5.8）：

```python
def _migrate_drop_phone_and_ip(conn: sqlite3.Connection) -> None:
    """删掉 users.phone、register_requests.phone、register_requests.ip（Spec22 §2.1）。

    为什么是真删而不是留着不用：见 §2.1 —— 留一列谁都不读写的死数据，是本仓
    反复记录的那类"看起来还在生效"的陷阱。代价（历史电话数据永久丢失）已确认。

    位置约束：必须排在 _migrate_users_contact **之后**。顺序反了的话，
    一个 Spec21 之前的旧库会先被"无列可删"跳过，然后 _migrate_users_contact
    再把 phone 列加回来 —— 白删一次。

    三列各自独立判存在性：不许共用一个 if。上一次跑了个半截（删了 phone、
    没删 ip）时，共用一个判断会让 ip 永远删不掉。

    SQLite 的 DROP COLUMN 需要 3.35+（2021-03）。老版本上只记一条**显眼**的
    warning 并整段跳过：那几列留着，但没有任何代码读写它们（等于自动降级成
    "保留列"形态），功能零影响。让服务因为一个删列失败而起不来，是拿可用性换洁癖。
    """
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    req_cols = {r["name"] for r in conn.execute("PRAGMA table_info(register_requests)").fetchall()}
    targets = (
        [("users", c) for c in ("phone",) if c in user_cols]
        + [("register_requests", c) for c in ("phone", "ip") if c in req_cols]
    )
    if not targets:
        return
    if sqlite3.sqlite_version_info < (3, 35, 0):
        logger.warning(
            "SQLite 版本过低，跳过删列（users.phone / register_requests.phone|ip）",
            extra={"event": "db.migrate", "reason": "sqlite_too_old"},
        )
        return
    # ip 上有索引，SQLite 拒绝删一个被索引引用的列 —— 必须先删索引。
    # 这不是可选步骤，是 DROP COLUMN 的前置条件（§2.1）。
    conn.execute("DROP INDEX IF EXISTS idx_register_requests_ip")
    for table, col in targets:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")   # 表名/列名来自上面的白名单，非外部输入
    conn.commit()
    logger.info("已删除 phone / ip 列", extra={"event": "db.migrate"})
```

**新迁移二：邮箱小写化**：

```python
def _migrate_lowercase_emails(conn: sqlite3.Connection) -> None:
    """把存量邮箱统一成小写（Spec22 §2.8）。

    不做的话，一个在 Spec21 时代用大写邮箱注册的账号，**邮箱登录永远进不去**
    （而用户完全不知道为什么）。两条 UPDATE 各自幂等：第二次启动影响 0 行。

    注意这边**不碰**空串/NULL：`email <> LOWER(email)` 对 NULL 求值为 NULL，
    行不会被选中，正是我们要的。
    """
    for table in ("users", "register_requests"):
        conn.execute(f"UPDATE {table} SET email = LOWER(email) WHERE email <> LOWER(email)")
    conn.commit()
```

**改造：`_migrate_users_contact`（Spec21 §5.1 的那个）**——只补 `email` 一列：

- 删掉 `if "phone" not in cols: ALTER TABLE users ADD COLUMN phone TEXT` 那两行与 `added = True`。
- 回填 SQL 里删掉两个 `phone = (SELECT r.phone …)` 子查询，只留 `email`。
- **其余不动**（仍是"只在确实补过列的那次跑"、仍只认 `status='approved'`、仍 `ORDER BY r.id DESC LIMIT 1`）。
- docstring 里补一行：Spec22 起这里的 `phone` 那半已删，本函数只负责 email。

**写入路径（去 phone / 去 ip）**：

```python
def create_user(username, password_hash, is_admin=False, email=None) -> dict:
    # INSERT INTO users (username, password_hash, is_admin, created_at, email) VALUES (?,?,?,?,?)
    # Spec22：phone 参数整个删掉，不是留个默认值 —— 留参数就是留一条能写进已删列的路。

def create_register_request(username, password_hash, email, wechat) -> dict:
    # INSERT INTO register_requests (username, password_hash, email, wechat, status, created_at)
    # Spec22：phone / ip 两个参数整个删掉（调用方也不再算 ip）
```

- `db.approve_register_request()` 的 INSERT 去掉 `phone`，只留 `email`（值仍取申请行）。
- **三条邮件的 contact 表达式跟着改**（`main.py`）：`email or phone or "未填写"` → `email or "未填写"`（3 处）。因为注册的邮箱现在是**必填**，所以「未填写」只剩"管理员手工建号"这一种情形（充值通知）。

**读出路径**：`_row_to_dict` 去掉 `"phone"` 一行；`_register_row_to_dict` 去掉 `"phone"` 一行。两者的 docstring 都要改（`_row_to_dict` 那段"PII 检查：流向 5 处"要重写成"只剩 email 一项 PII"，`_register_row_to_dict` 里"任何情况都不带 ip"那条说明随之作废——**列都没了**）。

### 5.2 新表 `email_verifications`

```sql
CREATE TABLE IF NOT EXISTS email_verifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL,   -- 已小写化（§2.8，路由层保证）
    purpose    TEXT NOT NULL,   -- register | login | reset（发码时按场景隔离，§2.2）
    code       TEXT NOT NULL,   -- 4 位数字串，1000~9999（§2.3）
    created_at TEXT NOT NULL    -- 发码时刻（UTC ISO）
)
```

```sql
-- 三个查询都走这条：冷却（最近一条）、校验（TTL 内的全部）、清理（过期的）
CREATE INDEX IF NOT EXISTS idx_email_verifications_lookup
    ON email_verifications(email, purpose, created_at DESC)
```

> **不是台账**：与 `register_requests` / `recharge_requests` 不同，这张表**只装最近 10 分钟的码**，没有 `status`、没有"同意/拒绝"、不保留历史（§3.3-10）。别把它当审计表用。
> **不给 `code` 加索引**：没有任何查询按 code 走。

### 5.3 新表 `click_events`

```sql
CREATE TABLE IF NOT EXISTS click_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event      TEXT NOT NULL,   -- login_page | register | community | gallery | recharge（白名单）
    ip         TEXT NOT NULL,   -- auth.client_ip(request)；只落库、只参与 COUNT（§2.9）
    created_at TEXT NOT NULL,
    UNIQUE(event, ip)           -- 去重就靠它，配 INSERT OR IGNORE
)
```

```sql
-- 统计走这条：SELECT event, COUNT(*) ... GROUP BY event
CREATE INDEX IF NOT EXISTS idx_click_events_event ON click_events(event)
```

> ⚠️ **日志的字段名是 `click_event`，不是 `event`**：`event` 在本仓已经是**每条日志的事件名**（`JsonFormatter._FIELDS` 的第一项，Spec §10 起）。两者同名会让 `grep '"event"'` 一次捞到两种东西——与 Spec19 用 `register_id`、Spec21 用 `recharge_source` 是同一条理由。表里的**列名**叫 `event` 没关系（SQL 与日志不是一回事），但传给 logger 的键必须是 `click_event`。
> **`UNIQUE(event, ip)` 是业务约束，不是数据库洁癖**：它让 `COUNT(*)` 直接等于"不重复 IP 数"，且 `INSERT OR IGNORE` 天然幂等——两个并发请求同时到达也只会记一行（§2.9）。

### 5.4 `Server/verifications.py`（新增）

```python
"""邮箱验证码的生成与场景白名单（Spec22 §5.4）。

只做两件事：生成一个 4 位码、给出合法的 purpose 列表。
**校验**（TTL、冷却、任一命中）全部在 db 层用 SQL 做 —— 它需要读库，
放在这里只会多绕一层。
"""
import secrets

# 场景白名单：发码与校验都按它比对，不拼接外部输入（本仓的既有做法）。
# register = 注册前验证邮箱；login = 邮箱验证码登录；reset = 修改密码前的身份验证。
PURPOSES = ("register", "login", "reset")

# 4 位是**契约**，不是旋钮：邮件正文的措辞、前端 maxlength 都绑死它（§2.3）。
# 想改长度要同时改这三处，所以不做成环境变量。
CODE_LENGTH = 4

# 取值 1000~9999，**刻意不带前导零**：`0042` 这种码用户十有八九会输成 `42`，
# 然后看到"验证码错误"而完全不知道错在哪（§2.3）。熵少 0.15 bit，可以忽略。
_CODE_MIN = 10 ** (CODE_LENGTH - 1)
_CODE_SPAN = 9 * _CODE_MIN


def generate_code() -> str:
    """返回一个 4 位数字串（1000~9999）。用 secrets：验证码是凭据。"""
    return str(_CODE_MIN + secrets.randbelow(_CODE_SPAN))
```

### 5.5 `db.py` 的增删清单

**删除**：

| 对象 | 原因 |
|---|---|
| `_CREATE_REGISTER_REQUESTS_IP_INDEX` 常量 + `init_db` 里的调用 | `ip` 列已删（§2.1，**漏掉服务起不来**） |
| `find_recent_register_by_ip(ip, window_seconds)` | 唯一消费者是 IP 冷却（需求 3 已删） |
| `users.phone` / `register_requests.phone` / `register_requests.ip` 三列 | §5.1 |

**新增**：

| 函数 | 签名 | 说明 |
|---|---|---|
| `get_user_by_email` | `(email) -> dict \| None` | `WHERE email = ? ORDER BY id ASC LIMIT 1`（**确定性口径**：不加 UNIQUE，所以必须指定取哪一条，§2.8）。返回 `_row_to_dict`（默认**不带** `password_hash`）。 |
| `create_email_verification` | `(email, purpose, code, ttl_seconds) -> dict` | **一个事务**：先 `DELETE FROM email_verifications WHERE created_at < ?`（cutoff = now − ttl，顺手清理，§2.2），再 INSERT。返回新行。 |
| `find_recent_email_verification` | `(email, purpose, window_seconds) -> dict \| None` | 重发冷却判据。cutoff 在 **Python 里**算成 `_now_iso()` 字符串再交给 SQL 比大小（照 `find_recent_register_by_ip` 的写法——`_now_iso()` 是 `YYYY-MM-DDTHH:MM:SS.mmmZ`，字典序即时间序；SQLite 的 `datetime('now')` 格式不同，直接比会全错）。 |
| `match_email_verification` | `(email, purpose, code, ttl_seconds) -> bool` | `SELECT 1 … WHERE email=? AND purpose=? AND code=? AND created_at >= ?`（cutoff 同样在 Python 侧算）。**TTL 内任一命中即 True**——这正是用户要的"只要有一个对了都算数"（§2.2）。 |
| `record_click` | `(event, ip) -> bool` | `INSERT OR IGNORE`，返回 `rowcount == 1`（= 这是一个**新的**不重复 IP）。返回值只用于决定要不要打日志（§2.9）。 |
| `get_click_stats` | `() -> dict` | `SELECT event, COUNT(*) … GROUP BY event`，**补齐白名单里所有键**（没有记录的 → 0）。前端不用处理缺键。 |
| `clear_clicks` | `() -> int` | **一个事务**：`DELETE FROM click_events` + `_upsert_meta(conn, CLICKS_CLEARED_KEY, _now_iso())`，返回删行数。照 `clear_usage()` 的样（它是本仓唯一的先例：清零与"上次清零时间"必须同生同死）。 |
| `CLICKS_CLEARED_KEY` | `= "clicks_cleared_at"` | `app_meta` 键，与 `usage_cleared_at` / `feedback_cleared_at` 同款。 |
| `_CLICK_EVENTS` | `= ("login_page", "register", "community", "gallery", "recharge")` | 白名单，路由与 `get_click_stats` 共用（不拼接外部输入）。 |

**改造**：

- `get_cleared_times()` → 返回值多一个 `"clicks_cleared_at"`（`get_meta(CLICKS_CLEARED_KEY)`）。**它已经被 `GET /api/admin/stats` 用 `stats.update(...)` 合并**，所以后端那一行不用改。
- `_row_to_dict` / `_register_row_to_dict`：去 `phone`。
- `create_user` / `create_register_request` / `approve_register_request`：去 `phone` / `ip`。

### 5.6 `mailer.py`：+3 个函数

三个都**必须**是同步 `def`（Spec20 §2.1 的全部理由原样成立：Starlette 对 `BackgroundTasks` 里的 `async def` 是**在事件循环里直接 await**，`smtplib` 的阻塞 IO 会卡死整个循环，而且不报错、只是变慢）——并且**永不抛异常**。

**这三个函数有一个共同点，与既有的三个完全不同：收件人是用户。** 所以它们**都不能带 `to` 进日志**（既有的三个带 `to`，是因为那是你自己固定不变的地址，不是 PII，§10.2）。

```python
def send_email_code(to_email: str, code: str) -> None:
    """把 4 位验证码发给**用户本人**（Spec22 §5.6）。

    与既有两个函数的**关键区别**：收件人是用户，不是 config.REGISTER_NOTIFY_TO。
    所以日志里**不带 `to`** —— 那是用户的邮箱，是 PII（Spec21 §10.2 的规矩）。
    既有两个函数带 `to`，是因为那个地址是你自己的、固定不变的。
    """
    # 未配 SMTP_PASSWORD → warning + return（路由层已经拦过一次，这里是双保险）
    # 主题："ArtiControlNet-邮箱验证"
    # 正文：f"您的邮箱验证码为：{code}。验证码{config.EMAIL_CODE_TTL_SECONDS // 60}分钟内有效。"
    #   ↑ 分钟数由秒数推出来，不写死 "10"（照 RECHARGE_COOLDOWN_MESSAGE 的先例：
    #     改 TTL 时文案自动跟着变，不可能出现"设了 5 分钟、邮件说 10 分钟"）
    # 日志：notify.email_code_mail_sent / _skipped(reason=smtp_not_configured) / _failed(error)


def send_recharge_approved_notification(username: str, to_email: str,
                                        created_at_iso: str, overdue: bool) -> None:
    """充值审批通过 → 通知**该用户**（Spec22 §5.6 / §2.12）。

    两个变体只差标题与正文最后半句，按 recharge_requests.source 分流。
    正文里的时间是**申请时间**（记录的 created_at → 北京时间），不是审批时刻。
    """
    # overdue=True  → 主题 "ArtiControlNet-账号已恢复"
    #                 正文 f"ArtiControlNet的用户您好，您于{beijing_time_text(created_at_iso)}充值的金额已到账，您的账号可以恢复使用啦，感谢您的支持~"
    # overdue=False → 主题 "ArtiControlNet-充值已到账"
    #                 正文 f"ArtiControlNet的用户您好，您于{beijing_time_text(created_at_iso)}充值的金额已到账，感谢您的支持~"
    # 日志：notify.recharge_approved_mail_sent / _skipped(reason=smtp_not_configured|no_email) / _failed(error)


def send_register_approved_notification(username: str, to_email: str,
                                        created_at_iso: str) -> None:
    """注册审批通过 → 通知**该注册者**（Spec22 §5.6 / §2.12）。

    只有**一个**变体（不像充值那封要按 source 分流）——注册审批没有"欠费"这种形态。
    正文里的时间是**申请时间**（申请行的 created_at → 北京时间），不是审批时刻。
    """
    # 主题："ArtiControlNet-注册成功"         ← ⚠️ 注意拼写，见 §0 第 8-a 条
    # 正文：f"您于{beijing_time_text(created_at_iso)}申请的注册已通过，您现在可以开始享用ArtiControlNet啦！"
    #   ↑ 这句话的开头**没有**「ArtiControlNet的用户您好」（充值那两封有）——用户第 8 条
    #     给的原文就是「您于…」，照抄，别顺手补上称呼
    # 日志：notify.register_approved_mail_sent / _skipped(reason=smtp_not_configured|no_email) / _failed(error)
    #   ↑ 字段用 register_id（与既有寄存器命名一致），不用 order_id/request_id
```

> **三封邮件都照抄用户原话**，包括「充值的金额已到账」这句话在充值两封里逐字重复（欠费那封只是**多**了后半句），以及「啦」「~」这些语气词。**别"统一"成一句模板**（Spec21 §2.7 的同一条立场）。
> **`_FROM_NAME` 仍是 `ArtiControlNet`**（Spec20 定的），发件人始终是 `SMTP_USER`。用户收件箱里看到的发件人显示名就是它——这与主题前缀 `ArtiControlNet-` 正好互相印证（也是 §0 第 8-a 条那个拼写要改的理由）。

### 5.7 关键数据流

**A. 注册（改造后）**

```
[前端] 填邮箱 → 点「获取验证码」
   ↓ POST /api/auth/email-code {email, purpose:"register"}
[后端] ① REGISTER_ENABLED?  ② SMTP_PASSWORD 配了吗（否则 50302）
       ③ email 格式  ④ 冷却（1 分钟，40906）
       ⑤ 邮箱在 users？→ 40907「已注册账号X…」
          邮箱有 pending 申请？→ 40907「该邮箱已提交过注册申请…」
       ⑥ verifications.generate_code() → db.create_email_verification(…)
       ⑦ background_tasks.add_task(mailer.send_email_code, email, code)
   ↓ {"sent": true}      ← 绝不回显码
[邮件] 主题「ArtiControlNet-邮箱验证」→ 用户邮箱
[前端] 用户填码 → 提交表单
   ↓ POST /api/auth/register {username, password, email, code, wechat}
[后端] 开关 → 字段 strip+小写 → 用户名(2~32) → 密码(2~72) → wechat(≤64)
       → email 格式 → code 是 4 位数字
       → 邮箱在 users？→ 40907        （提交时再查一遍，§2.4）
       → db.match_email_verification(email,"register",code,TTL) → 否则 40020
       → 用户名占用？→ 40901
       → db.create_register_request(username, hash, email, wechat)
       → background_tasks.add_task(mailer.send_register_notification, …)   ← 发给你自己
   ↓ {"id": N}
```

**B. 邮箱登录**

```
POST /api/auth/login-by-email {email, code}
  → 42901（is_login_blocked）→ 空值 40020 → email 格式 40020
  → code 是 4 位数字 40020
  → db.get_user_by_email(email) 为 None → 40907「还未注册，请宝子前往新用户注册~」
     （注意：这条路**不先发码**也能到达，所以这句话要在这里再给一次）
  → db.match_email_verification(email,"login",code,TTL) → 否则 record_login_failure + 40020
  → 限额判定（照 /api/auth/login：not is_admin and used > quota_limit）→ 40304
  → reset_login_failures → create_token
  ↓ {token, username, is_admin}     ← 与密码登录**完全同形**，前端 auth store 直接复用
```

**C. 修改密码**

```
[前端] 填邮箱 → 获取验证码（purpose:"reset"）   ← 查重：未注册 → 40907「还未注册…」
[前端] 填码 → POST /api/auth/verify-email-code {email, purpose:"reset", code}
        → 通过 {"verified": true} → 前端**这才**展开「新密码 + 二次确认」
          （不通过 → record_login_failure + 40020 红字）
[前端] 两次密码一致（本地判）→ POST /api/auth/reset-password {email, code, password}
        → **再校验一次**码（前端状态不可信，§2.7）
        → db.update_password(user_id, auth.hash_password(password))
        → 日志 auth.password_reset
[前端] 关闭面板 → 登录页绿色提示「密码已修改，请用新密码登录」+ 预填用户名
```

**D. 充值审批通过 → 通知用户**（欠费那一路也多一封，见 §2.12）

```
POST /api/admin/recharge-requests/{id}/approve {amount}
  …（既有校验与前 6 步一字不变）…
  → db.approve_recharge_request(…) 成功
  → background_tasks.add_task(
        mailer.send_recharge_approved_notification,
        user["username"], user["email"] or "", record["created_at"],
        record["source"] == "overdue")
    ↑ user 已在路由里取过（40402 预检那次），**不用再查一遍库**
    ↑ overdue 直接由 record["source"] 推出，**不新增请求字段**
  邮件里没有邮箱可发时，发给 "" → mailer 内部判空即跳过（reason="no_email"）
```

**E. 注册审批通过 → 通知注册者**（与 D 是同一件事，挂在另一张台账上）

```
POST /api/admin/register-requests/{id}/approve {quota_limit}
  …（既有校验与前 5 步一字不变）…
  → db.approve_register_request(…) 成功
  → background_tasks.add_task(
        mailer.send_register_approved_notification,
        record["username"], record["email"] or "", record["created_at"])
    ↑ record 就是这次请求里 with_secret=True 的那次预检结果，**不用再查一遍库**
    ↑ 用**申请行**的 email（被验证码验证过的就是它）；approve_register_request
      会把这个值原样复制进新用户行，所以与 user["email"] 恒等
    ↑ 没有 overdue 参数 —— 注册审批只有一个变体（§2.12）
  邮件里没有邮箱可发时，发给 "" → mailer 内部判空即跳过（reason="no_email"）
```

**F. 点击埋点**

```
[前端] track.js: fetch('/api/click', {method:'POST', body:{event}, keepalive:true})  ← 不 await、异常全吞
   ↓
[后端] 白名单校验（不在 _CLICK_EVENTS → 40021）
       ip = auth.client_ip(request)
       is_new = db.record_click(event, ip)
       is_new 时才 logger.info("click.recorded", extra={"click_event": event})
   ↓ {"ok": true}
[管理端] GET /api/admin/stats → clicks: {login_page:9, register:4, …}
```

### 5.8 `init_db` 的调用顺序（位置约束总表）

本 Spec 引入了 **1 条新的位置约束**，并继承 Spec19/21 的两条。`init_db` 里必须是这个相对顺序：

| 顺序 | 调用 | 约束 |
|---|---|---|
| 1 | `conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)` | — |
| 2 | ~~`conn.execute(_CREATE_REGISTER_REQUESTS_IP_INDEX)`~~ | ⚠️ **Spec22 删除这一行**。`ip` 列已删，留着每次启动都撞 `no such column: ip`（§2.1） |
| 3 | `conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)` | — |
| 4 | `_migrate_users_contact(conn)` | **必须排在 1 之后**（回填要读 `register_requests`，Spec21 §5.1 的原有约束）。Spec22 起它只补/回填 `email` |
| 5 | **`_migrate_drop_phone_and_ip(conn)`** ← **Spec22 新增** | **必须排在 4 之后**：顺序反了，一个 pre-Spec21 的旧库会先被"无列可删"跳过、再被 4 把 `phone` 加回来（§2.1） |
| 6 | **`_migrate_lowercase_emails(conn)`** ← **Spec22 新增** | 排在 5 之后（删列与它无关，但要保证**任何**读 email 的迁移都看到小写后的值） |
| 7 | `conn.execute(_CREATE_EMAIL_VERIFICATIONS_TABLE)` + 索引 + `_CREATE_CLICK_EVENTS_TABLE` + 索引 | 两条新表都是 `CREATE TABLE IF NOT EXISTS`，对新库/存量库行为一致，**不需要迁移函数**（与 Spec21 §2.3 的 `recharge_requests` 同款） |
| 8 | `_migrate_images_wiki_used(conn)` 及其后原有的一串 | 不动 |

**实现完成后必须核对的一件事**：`grep -n "phone\|register_requests_ip" Server/*.py` → **零命中**（`ip` 这个词还会出现在 `auth.client_ip`、登录限速、点击埋点里，那是**别的** IP，不要一起删）。

---

## 6. 接口约定

全部响应仍是 `{code, message, data}`。**新增 6 条路由、变更 2 条**。

### 6.1 变更：`POST /api/auth/register`（公开）

请求体变化（`schemas.RegisterRequestCreate`）：

```diff
-  phone:   Optional[str] = None
-  email:   Optional[str] = None
+  email:   str            # Spec22：**必填**，且注册前必须通过邮箱验证码
+  code:    str            # Spec22：邮箱验证码（4 位数字）
```

**校验顺序（顺序即契约，照 Spec19 §6.2 的写法逐条列全）**：

1. `not config.REGISTER_ENABLED` → `RegisterClosedError` 40305
2. 五个字段 strip（`email` 额外 `.lower()`）
3. `username` 长度 2~32 → 40018「用户名需为 2~32 个字符」
4. **`password` 长度 2~72**（`auth.MIN_PASSWORD_LEN` / `MAX_PASSWORD_LEN`，§2.10）→ 40018「密码需为 2~72 位」
5. `wechat` 非空且 ≤ `RECHARGE_WECHAT_MAX` → 40018「请填写用于支付的微信昵称」
6. `email` 含 `@`、`@` 前后非空、长度 ≤128 → 40018「邮箱格式不正确（需包含 @，且 @ 前后都有内容）」
7. **`code` 是 4 位纯数字** → 40018「请填写 4 位数字验证码」
8. **`db.get_user_by_email(email)` 命中** → `EmailCodeRejectedError` 40907「已注册账号{username}，请前往登录界面。忘记密码请前往登录界面"修改密码"」
9. **`db.match_email_verification(email, "register", code, TTL)` 为假** → `EmailCodeRequestError` 40020「验证码错误或已过期」
10. `db.get_user_by_username(username)` 命中 → `DuplicateUsernameError` 40901
11. `db.create_register_request(username, hash, email, wechat)`（**不再传 ip**）
12. 日志 `auth.register_submitted`（字段：`register_id` / `has_email`，**去掉 `has_phone`**、**不记 IP**）
13. `background_tasks.add_task(mailer.send_register_notification, username, email, wechat, record["created_at"])`
14. `_ok({"id": record["id"]})`

> **删掉的两条**：原来的第 6 条（phone/email 至少一项）、第 7 条（手机号 11 位）、第 10 条（IP 冷却 40902）。
> **顺序上的一处刻意**：第 8 条（查重）排在验证码校验（第 9 条）**之前**。它不泄露任何新东西——`/api/auth/email-code` 那条路本来就会把同一句话说给任何知道这个邮箱的人（§3.3-3）。而它对**填错邮箱的正常用户**给出的提示要有用得多。

### 6.2 新增：`POST /api/auth/email-code`（**公开**）

请求体 `{"email": "zhang@qq.com", "purpose": "register"}` → `{"code":200,"data":{"sent": true}}`

**校验顺序**：

1. `not config.SMTP_PASSWORD` → `EmailServiceUnavailableError` 50302「邮箱服务暂不可用，请联系客服 {SUPPORT_EMAIL}」（**在花钱/落库之前**，§2.5）
2. `email` 格式（同 §6.1 第 6 条）→ 40020「邮箱格式不正确（需包含 @，且 @ 前后都有内容）」
3. `purpose` 不在 `verifications.PURPOSES` → 40020「未知的验证场景」
4. `db.find_recent_email_verification(email, purpose, EMAIL_CODE_RESEND_SECONDS)` 命中 → `EmailCodeRateLimitedError` 40906（文案见 §8）
5. 按 purpose 分流查重（§2.4 的表）→ `EmailCodeRejectedError` 40907
6. `code = verifications.generate_code()` → `db.create_email_verification(email, purpose, code, TTL)`
7. 日志 `email_code.requested`（`purpose`；**不带 email、不带 code**）
8. `background_tasks.add_task(mailer.send_email_code, email, code)`
9. `_ok({"sent": True})`

> **冷却排在查重之前**：一个被拒的邮箱反复点「获取验证码」，会一直撞 40907（查重）——这没问题。但**冷却必须在最前面**，否则连点的人可能因为查重分支不同而看到交替的提示。顺序：**可预知的服务故障 → 格式 → 频率 → 业务规则**。
> **不回显 `code`**，任何情况下（§2.2）。
> **不带 IP、不带 email 进日志**（§10.2）。

### 6.3 新增：`POST /api/auth/verify-email-code`（**公开**）

请求体 `{"email": "...", "purpose": "reset", "code": "4821"}` → `{"code":200,"data":{"verified": true}}`

- 供「修改密码」展开密码栏之前使用（§2.7）。登录与注册**不用**它（各自在自己的提交里校验）。
- 校验顺序：`is_login_blocked` → 42901；字段格式 → 40020；`match_email_verification` → 失败时 `record_login_failure(ip)` + 40020「验证码错误或已过期」。
- 成功时 `reset_login_failures(ip)` + 日志 `email_code.verified`（`purpose`）。
- **这个接口不消费验证码**：它只回答"这个码现在对不对"（§2.2）。真正的授权发生在 `reset-password` 的那次**重新校验**上。

### 6.4 新增：`POST /api/auth/login-by-email`（**公开**）

请求体 `{"email": "...", "code": "4821"}` → `{"code":200,"data":{"token":"...","username":"...","is_admin":false}}`

- 返回值与 `POST /api/auth/login` **完全同形**，前端 `auth.loginByEmail()` 直接复用收尾逻辑。
- **必须**复用登录路由的限额判定（`not is_admin and used > quota_limit` → 40304，Spec21 §5.7 的 `>`）。**这是本 Spec 最容易漏的一处安全缺口**：漏了它，一个已经欠费被拦的用户只要用邮箱登录就能绕过去。
- 先 `is_login_blocked` → 42901；码错 → `record_login_failure` + 40020；成功 → `reset_login_failures` + `create_token`。
- 日志 `auth.email_login`（`username`；**不带 email**）。
- 该用户 `email` 为 NULL（管理员手工建号）时，`get_user_by_email` 不可能命中 → 走 40907「还未注册，请宝子前往新用户注册~」。**这条文案在管理员听来是错的**，但那条路本来就不该有人走（手工建的号没邮箱，无从填起）。已记录，不专门处理。

### 6.5 新增：`POST /api/auth/reset-password`（**公开**）

请求体 `{"email": "...", "code": "4821", "password": "新密码"}` → `{"code":200,"data":{"username":"zhang"}}`

- 校验顺序：`is_login_blocked` → 42901；`email` 格式 → 40020；`code` 4 位数字 → 40020；`password` 长度 2~72（**同一套常量**）→ 40018；`get_user_by_email` → None 则 40907「还未注册…」；`match_email_verification(email,"reset",code,TTL)` → 假则 `record_login_failure` + 40020。
- 通过 → `db.update_password(user_id, auth.hash_password(password))` → `reset_login_failures` → 日志 `auth.password_reset`（`username`）。
- 返回 `username` 供前端预填登录框（§7.2）。
- **不需要旧密码**（用户已经用邮箱证明了自己，§2.7）。
- **不吊销任何 token**（§3.3-4）。

### 6.6 新增：`POST /api/click`（**公开**）

请求体 `{"event": "login_page"}` → `{"code":200,"data":{"ok":true}}`

- `event` 不在 `db._CLICK_EVENTS` → `ClickEventError` 40021「未知的埋点事件」。
- `ip = auth.client_ip(request)` → `db.record_click(event, ip)`。
- **只在 `record_click` 返回 True（新 IP）时**打一行 `click.recorded` 日志（§2.9）。
- 响应**不回传计数**（前端不需要，也没有"实时计数"这个需求）。
- **幂等**：同 IP 重复点击返回同样的 200，库里不新增行。前端不需要区分。

### 6.7 新增：`POST /api/admin/clicks/clear`

无请求体 → `{"code":200,"data":{"cleared": 17}}`

- 中间件保证仅管理员（`/api/admin/*`）。
- `db.clear_clicks()`：**一个事务**里删行 + 写 `app_meta.clicks_cleared_at`。
- 与 Spec18 的 `clear_usage` 同款：**只重置统计区间，不动任何计费口径**（点击本来就不计费）。

### 6.8 变更：`GET /api/admin/stats`

响应**多两个键**（既有键一个都不动）：

```json
{
  "user_count": 12, "total_calls": 340, "totals": {…}, "shares": {…}, "per_user_avg": {…},
  "feedback_totals": {…},
  "usage_cleared_at": "…", "feedback_cleared_at": "…",
  "clicks_cleared_at": "2026-09-19T08:00:00.000Z",
  "clicks": {"login_page": 9, "register": 4, "community": 6, "gallery": 3, "recharge": 1}
}
```

- `clicks` **恒含 5 个键**（没有记录的为 0），前端不用判空。
- 实现：路由里 `stats["clicks"] = db.get_click_stats()`；`db.get_cleared_times()` 已经多返回 `clicks_cleared_at`，而路由那句 `stats.update(db.get_cleared_times())` **一个字都不用改**（§5.5）。

### 6.9 变更：`PUBLIC_AUTH_PATHS`（5 → 10 条）

```python
PUBLIC_AUTH_PATHS = {
    "/api/auth/login",              # Spec2
    "/api/auth/register",           # Spec19（Spec22 起它内部要验证码，但仍公开）
    "/api/auth/register-config",    # Spec19
    "/api/auth/payment-qr",         # Spec19
    "/api/auth/recharge-request",   # Spec21
    # ---- Spec22 新增 5 条 ----
    "/api/auth/email-code",         # 发验证码（用户此刻必然没有 token）
    "/api/auth/verify-email-code",  # 校验验证码（改密码的前置）
    "/api/auth/login-by-email",     # 邮箱登录（就是用来拿 token 的）
    "/api/auth/reset-password",     # 自助改密码（忘了密码的人没有 token）
    "/api/click",                   # 点击埋点（「打开登录页」发生时用户还没 token）
}
```

> 仍是**精确匹配**（不是前缀）。中间件对白名单里的路径**不判限额**——所以 `login-by-email` 必须**自己**判 40304（§6.4），这与 `/api/auth/login` 的处境完全一样（Spec21 §5.7 的四处副本之一就在登录路由里）。

### 6.10 `schemas.py`

```python
# ---- 邮箱验证码与入口统计（Spec22 §6.1~§6.6）----

class RegisterRequestCreate(BaseModel):
    """POST /api/auth/register 请求体（Spec22 §6.1，Spec19 §6.2 的改造版）。
    Pydantic 只负责"字段在不在"，格式/长度/查重全在路由层（40018 / 40907）。"""
    username: str
    password: str
    email: str          # Spec22：必填（原 phone / email 二选一已成历史）
    code: str           # Spec22：邮箱验证码
    wechat: str


class EmailCodeRequest(BaseModel):
    """POST /api/auth/email-code 请求体（Spec22 §6.2）。"""
    email: str
    purpose: str        # register | login | reset，白名单在路由层


class EmailCodeVerifyRequest(BaseModel):
    """POST /api/auth/verify-email-code 请求体（Spec22 §6.3）。"""
    email: str
    purpose: str
    code: str


class EmailLoginRequest(BaseModel):
    """POST /api/auth/login-by-email 请求体（Spec22 §6.4）。"""
    email: str
    code: str


class ResetPasswordRequest(BaseModel):
    """POST /api/auth/reset-password 请求体（Spec22 §6.5）。
    只有一个 password —— **没有** confirm 字段：两次输入是否一致是前端的事，
    后端根本收不到第二个框（§2.10）。"""
    email: str
    code: str
    password: str


class ClickEventRequest(BaseModel):
    """POST /api/click 请求体（Spec22 §6.6）。白名单在路由层（40021）。"""
    event: str
```

> ⚠️ **没有 `RegisterRequestCreate.phone` 了**。删字段**不是**改成 `Optional`：留着一个可选字段，就留了一条能被写进已删列的路（§5.1）。

### 6.11 不变

`POST /api/chat`、`/api/images`、`/api/tasks/{id}`、`/api/gallery/*`、`/api/community/*`、`/api/wiki/*`、`/api/shares/*`、`/api/suggestions/*`、`/api/conversations/*`、`/api/auth/login`、`/api/auth/me`、`/api/auth/payment-qr`、`/api/recharge/info`、`/api/recharge/requests`、`/api/auth/recharge-request`、`PUT /api/admin/users/{id}/quota`、`PUT /api/admin/users/{id}/admin`、`DELETE /api/admin/users/{id}`、`/api/admin/register-requests/*` 三条、`/api/admin/recharge-requests/*` 三条、`POST /api/admin/usage/clear`、`POST /api/admin/feedback/clear` —— **全部一字不动**。

> ⚠️ 上面那串里的两条 `approve` 路由（`register-requests/{id}/approve` 与 `recharge-requests/{id}/approve`）**是"路径与响应一字不动，但不是零改动"**：两条都要加一个 `background_tasks: BackgroundTasks` 参数 + 一次 `add_task`（§2.12 那张表最后两行）。**别因为它们出现在这份清单里就跳过改动。**

**三处例外**（都是"契约不变、行为变了"）：

| 接口 | 变的是什么 |
|---|---|
| `GET /api/auth/register-config` | **少一个键** `daily_notice`（§2.11）。`enabled` / `contact_email` / `qr_url` / `price_notice` 都不动 |
| `POST /api/admin/users` 与 `PUT /api/admin/users/{id}/password` | 密码下限 6 → 2（**校验放宽，请求/响应结构不变**）；前者建的号**没有邮箱**（`create_user` 已无 email 实参） |
| `POST /api/admin/register-requests/{id}/approve` | 多挂一个后台任务给注册者发「注册成功」邮件（§2.12）。**请求体、响应体、状态码、错误码、事务语义、日志事件全部不变**——变的只是"按下去之后多了一封信" |

---

## 7. 前端交互

### 7.1 `RegisterModal.vue`

**表单变化**（从上到下）：

```html
<label class="reg-label">账号 <b class="reg-star">*</b></label>
<input v-model="username" class="login-input" placeholder="2~32 个字符" autocomplete="off" />

<label class="reg-label">密码 <b class="reg-star">*</b></label>
<!-- Spec22 §2.10：placeholder 跟着后端的常量走（6 → 2）。仍然**不做**代码校验：
     长度规则只有一份中文 message，在后端。 -->
<input v-model="password" type="password" class="login-input"
       placeholder="至少 2 位" autocomplete="new-password" />

<!-- Spec22 新增：二次确认。**纯前端**——后端收不到第二个框（§2.10），
     所以这个校验**必须**在前端，而且它不进 schemas、不进后端。 -->
<label class="reg-label">确认密码 <b class="reg-star">*</b></label>
<input v-model="confirmPassword" type="password" class="login-input"
       placeholder="再输入一次" autocomplete="new-password" />

<!-- Spec22：联系方式整段改掉 —— 删掉手机号输入框与那句"至少填一项"的 reg-hint -->
<label class="reg-label">邮箱 <b class="reg-star">*</b></label>
<p class="reg-hint">注册需要邮箱验证，验证码会发到这个邮箱</p>
<div class="reg-code-row">
  <input v-model="email" class="login-input" type="email"
         placeholder="邮箱" autocomplete="off" autocapitalize="off" />
  <button type="button" class="btn-code" :disabled="codeCooldown > 0 || sendingCode"
          @click="sendCode">
    {{ codeCooldown > 0 ? `${codeCooldown}s` : (sendingCode ? '发送中…' : '获取验证码') }}
  </button>
</div>
<input v-model="code" class="login-input" type="text" inputmode="numeric" maxlength="4"
       placeholder="4 位验证码" autocomplete="off" />

<div class="reg-pay">…（收款码那一段不动）…</div>

<label class="reg-label">用于支付的微信昵称（以便后台核对） <b class="reg-star">*</b></label>
<input v-model="wechat" class="login-input" autocomplete="off" />

<!-- Spec22 删除：<p class="reg-note">{{ config.daily_notice }}</p>  ← 规则已不存在（§2.11） -->
<p v-if="error" class="login-error">{{ error }}</p>
<button class="btn-primary reg-submit" type="submit" :disabled="loading">…</button>
```

**脚本变化**：

```js
const code = ref('')
const confirmPassword = ref('')
const sendingCode = ref(false)
const codeCooldown = ref(0)      // 秒，倒计时到 0 才能重发
let cooldownTimer = null

async function sendCode() {
  // 只拦"必填"——邮箱格式规则在后端（40020），前端不复制（Spec19 §7.3 的立场不变）
  if (!email.value.trim()) { error.value = '请先填写邮箱'; return }
  error.value = ''
  sendingCode.value = true
  try {
    await getEmailCode(email.value.trim(), 'register')   // ← api/chatApi.js 新函数
    startCooldown(60)          // 与后端 EMAIL_CODE_RESEND_SECONDS 同值；客户端倒计时只是体验
  } catch (e) {
    // 40907（已注册 / 已提交过申请）与 50302（邮箱服务不可用）的 message 都是**后端给的原文**，
    // 前端零副本：直接显示成红字。这正是 §2.4 那句"已注册账号<用户名>…"的落点。
    error.value = e.message || '验证码发送失败'
  } finally { sendingCode.value = false }
}

async function submit() {
  if (!username.value.trim() || !password.value || !wechat.value.trim()) { … }
  if (password.value !== confirmPassword.value) {
    // Spec22：后端收不到 confirm，这一句只能在前端说（§2.10）
    error.value = '两次输入的密码不一致'
    return
  }
  if (!email.value.trim()) { error.value = '请填写邮箱'; return }
  if (!/^\d{4}$/.test(code.value.trim())) { error.value = '请填写 4 位数字验证码'; return }
  …submitRegisterRequest({ username, password, email, code, wechat })…
}
```

- **倒计时只是体验**：真正的 1 分钟冷却在后端（40906）。前端 `codeCooldown` 不参与任何判定，刷新页面就没了——这是**允许**的（后端才是闸门）。
- **提交成功后那张"申请已提交"面板**：文案不变（「已通知管理员，在30秒内会通过短信/邮件告知您注册结果。」）。⚠️ 那句话里的「短信」现在已经不成立了——**用户没要求改它**，本 Spec **不动**（§14.3 记为待办）。

### 7.2 `Login.vue`

**结构变化**（`login-register` 那一块）：

```html
<!-- Spec19 §7.2 的语义必须保留：REGISTER_ENABLED=false 时注册按钮不渲染，客服行保留。
     Spec22 把 v-if 从"外层 div"下移到了**单个元素**上 —— 因为下面两个新按钮
     不依赖 regCfg（它们用的是邮箱验证码，与 REGISTER_ENABLED 无关）。 -->
<div class="login-register">
  <button v-if="regCfg?.enabled" type="button" class="btn-register" @click="openRegister">
    新用户注册
  </button>

  <!-- Spec22 §7.2：两个新入口。它们与 regCfg 无关，**失败也要在**（regCfg 取不到时
       仍然要能登录/改密码——它们是老用户的逃生通道）。 -->
  <div class="login-alt">
    <button type="button" class="btn-link" @click="emailAuth = 'login'">邮箱登录</button>
    <button type="button" class="btn-link" @click="emailAuth = 'reset'">修改密码</button>
  </div>

  <p v-if="regCfg" class="login-service">有问题请致信官方客服：{{ regCfg.contact_email }}</p>
</div>

<EmailAuthModal v-if="emailAuth" :mode="emailAuth"
                @close="emailAuth = null" @done="onEmailAuthDone" />
```

```js
const emailAuth = ref(null)   // null | 'login' | 'reset'
const okText = ref('')        // Spec22：绿色成功提示行（.login-ok）

function openRegister() {
  trackClick('register')      // Spec22 埋点：点「新用户注册」
  showRegister.value = true
}

function onEmailAuthDone(payload) {
  const mode = emailAuth.value
  emailAuth.value = null
  if (mode === 'reset') {
    // 改密码成功 → 回登录页 + 说一句（什么都不说地回来，用户分不清"成功了"和"没点对"）
    username.value = payload.username || ''
    okText.value = '密码已修改，请用新密码登录'
  }
  // mode === 'login'：token 已进 store，App.vue 的 v-if 会自动切到聊天视图，这里不用做事
}

onMounted(async () => {
  trackClick('login_page')    // Spec22 埋点：打开登录页 = 用户点名的"登录主页"
  …
})
```

```html
<!-- 提示行：红、绿各一条，互不覆盖 -->
<p v-if="error" class="login-error">{{ error }}</p>
<p v-if="okText" class="login-ok">{{ okText }}</p>
```

> **一处刻意**：`trackClick` **不 await、不 try/catch**——`utils/track.js` 内部已经把异常全吞了（§7.5）。调用点写 `trackClick(...)` 一句话，不需要 `await`，也不该让埋点挡住 `showRegister = true`。

### 7.3 `views/EmailAuthModal.vue`（新增，两种模式）

照 `RechargeModal.vue` 的"一个组件两种模式"做法（Spec21 §7.3 的先例）。

```
props: mode: 'login' | 'reset'
emits: close | done({ username })

┌─ 邮箱登录 ────────────────┐   ┌─ 修改密码 ─────────────────┐
│ 邮箱  [____________]      │   │ 邮箱  [____________] [获取验证码] │
│       [获取验证码]        │   │ 验证码 [____]  [验证]      │
│ 验证码 [____]             │   │ ───────────────────────── │
│ [ 登 录 ]                 │   │ 新密码   [__________]      │  ← 验证通过后才展开
│                           │   │ 确认密码 [__________]      │
│                           │   │ [ 完 成 ]                  │
└───────────────────────────┘   └────────────────────────────┘
```

- **`mode='login'`**：邮箱 + 验证码 + 「登录」→ 调 `auth.loginByEmail(email, code)`（store 新动作）。成功 → `emit('done', {})`。
- **`mode='reset'`**：两阶段。
  1. 邮箱 + 「获取验证码」（`purpose='reset'`）+ 验证码 + 「验证」按钮 → 调 `verifyEmailCode(email,'reset',code)`；通过 → `verified = true`，**展开**下面两栏（用户原话："过了也不让单选了，直接弹出新密码+二次确认"）。
  2. 新密码 + 确认密码 + 「完成」→ 前端先判两次一致（不一致 → 红字，不发请求）→ 调 `resetPassword(email, code, password)` → 成功 → `emit('done', { username })`。
- **验证码一旦改动就收起密码栏**（`watch(code, () => { if (password.value || confirmPassword.value) verified.value = false })`）——否则用户改个码再点完成，会拿到一个"看起来填过密码但没验证过"的界面，后端只会回一句 40020。
- 两个模式的红字提示**全部来自后端 `message`**（40907 的「还未注册，请宝子前往新用户注册~」/「已注册账号…」、40020、40906、50302），前端零副本。
- 邮箱输入框 `type="email" autocapitalize="off"`（§2.8 的前端配合，真正的规范化在后端）。

### 7.4 `App.vue`：三个埋点

插在**三个既有 toggle 函数的开头**（不是各加一个 `@click`——保持"所有入口逻辑都在这个函数里"的现状）：

```js
import { trackClick } from '../utils/track'

function toggleGallery()     { trackClick('gallery');   … }   // 我的作品
function toggleCommunity()   { trackClick('community'); … }   // 社区

// 余额与充值：它是 overlay，直接置 true（现有代码），前面加一行
// <button v-if="!auth.isAdmin" class="btn-clear" @click="openRecharge">余额与充值</button>
function openRecharge()      { trackClick('recharge'); showRecharge.value = true }
```

> **只计"打开"**：`toggleGallery` 在"返回聊天"那一次也会被调用。所以**再点一次会把同一个 IP 又报一遍**——而 IP 去重让它在库里不产生任何影响（§2.9），这正是选 IP 去重而不是"计数"的好处。**不需要**在这里判断"是打开还是关闭"。

### 7.5 `utils/track.js`（新增）

```js
// Spec22 §2.9：五个入口点击的不重复 IP 统计。
//
// **刻意不用 api/chatApi.js 的 axios 实例**：
//   那个实例的响应拦截器会在 401 / 40304 时触发 artcn:unauthorized /
//   artcn:quota_exceeded 全局事件 —— 埋点绝不能把用户踢下线。
//   裸 fetch 彻底解耦，也省掉"这条路由必须留在公开白名单里，否则会登出"
//   这种看不见的隐式耦合。
//
// **不 await、异常全吞**：埋点是顺手记一笔，失败不能影响任何主流程。
const EVENTS = ['login_page', 'register', 'community', 'gallery', 'recharge']

export function trackClick(event) {
  if (!EVENTS.includes(event)) return    // 本地白名单，防止手误写出后端会拒的事件名
  try {
    fetch('/api/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event }),
      keepalive: true,                   // 页面正在跳转时也把请求发完
    }).catch(() => {})
  } catch { /* 老浏览器没有 fetch 也照样不报错 */ }
}
```

> **不拼 `VITE_API_BASE`？** 要拼。前端独立部署时（`VITE_API_BASE` 指向远端后端），裸 `'/api/click'` 会打到前端自己的域名上。写 `const base = import.meta.env.VITE_API_BASE || ''` 再拼，与 `api/chatApi.js` 的取值口径一致（读一眼 `chatApi.js` 顶部那行 `baseURL` 的写法，**照抄**）。
> **`keepalive: true`** 是给"点击后立刻离开页面"的场景（比如点了「注册新用户」→ 立刻又点了别的），保证请求在页面卸载时仍能发出。

### 7.6 `store/auth.js`

```js
// Spec22 §6.4：邮箱验证码登录。与 login() 之后的所有收尾完全一致
// （token / username / is_admin 三个 ref 一落，App.vue 的 v-if 自动切换视图）。
async function loginByEmail(email, code) {
  const data = await loginByEmailApi(email, code)   // ← api/chatApi.js 新函数
  token.value = data.token
  username.value = data.username
  isAdmin.value = data.is_admin
  localStorage.setItem('artcn_token', data.token)
  …
}
```

> **`isOverQuota` / 限额判断**：`App.vue` 里没有等价的派生函数（Spec21 §7.2 第 3 处的 `isOverQuota` 在 `AdminPanel.vue`）。邮箱登录被 40304 拦下时，`store` 里那份逻辑与 `auth.login()` 完全一样——**复用 `login()` 现有的 40304 处置**（Spec21 §7.4 的欠费面板），不要另写一套。

### 7.7 `AdminPanel.vue`

1. **用户表删掉联系方式里的电话**（`contactText` 只留 email）：

```js
// Spec22 §7.7：库里已经没有任何电话了（§5.1），所以这一列只可能是邮箱或「无」。
// 「无」= 管理员手工建的号（create_user 不带 email）——**这是允许的形态**（Spec21 §3.3-6）。
function contactText(u) {
  return u.email || '无'
}
```

2. **注册申请表删掉手机号那一行**：`AdminPanel.vue:121` 的 `<span class="reg-row-cell">手机号：{{ r.phone || '—' }}</span>` **整行删除**（不是改成空串——留一个永远显示「—」的格子比删掉更糟）。
3. **两条审批的确认文案各补一句**（`approveRecharge` 与 `approveRegister` 的 `window.prompt` 之前的 `confirm`）：通过后会**给申请者发一封邮件**。让操作者知道这个副作用（用户没要求，但"按一下给用户发一封邮件"是应该被告知的；若不想要，删掉这两句即可）。
   - 注册审批：`确认通过 ${r.username} 的注册申请？通过后会向 ${r.email || '（该申请没有邮箱）'} 发送一封通知邮件。`
   - 充值审批：`确认通过这笔充值（${amount} 次）？通过后会向该用户邮箱发送一封到账通知。`
   - ⚠️ **两条路由的响应与错误码一个字没变**，所以前端这两处**只加一句 confirm 文案**，不要动任何请求逻辑（§6.11 的三处例外表）。

> **「重置密码」按钮不动**，但它现在只能设 ≥2 位的密码（§2.10，后端放宽了）。
> ⚠️ **注册审批那条的 `confirm` 在 `prompt` 之前**：`window.prompt` 是要管理员填额度的那一步，先 confirm 后 prompt，**顺序别反**（反了的话，管理员填完额度再点"取消 confirm"，前面那次输入白填）。

### 7.8 `StatsPanel.vue`

在「AI 服务反馈」区块**之后**新增第三个区块，结构照抄它：

```html
<section class="stats-block">
  <h3 class="stats-subtitle">入口点击（不重复 IP）</h3>
  <p class="stats-cleared">上次清零：{{ clicksClearedText }}</p>
  <button class="btn-mini" @click="clearClicks">清空入口统计</button>

  <table class="stats-table">
    <thead><tr><th>入口</th><th>不重复 IP 数</th></tr></thead>
    <tbody>
      <tr v-for="row in clickRows" :key="row.key">
        <td>{{ row.label }}</td><td>{{ row.count }}</td>
      </tr>
    </tbody>
  </table>
</section>
```

```js
// Spec22 §7.8：5 个入口与后端 db._CLICK_EVENTS 一一对应。
// **不显示"合计"** —— 5 个 IP 集合互相重叠，加起来没有含义（§2.9）。
const CLICK_ROWS = [
  { key: 'login_page', label: '打开登录页' },
  { key: 'register',   label: '点「新用户注册」' },
  { key: 'community',  label: '社区' },
  { key: 'gallery',    label: '我的作品' },
  { key: 'recharge',   label: '余额与充值' },
]
const clickRows = computed(() =>
  CLICK_ROWS.map(r => ({ ...r, count: stats.value.clicks?.[r.key] ?? 0 })))

const clicksClearedText = computed(() => fmtCleared(stats.value.clicks_cleared_at))
// ↑ 复用既有的 fmtCleared（浏览器本地时区，与 usage/feedback 两个"上次清零"同一口径）
```

- `stats` 初始对象里加 `clicks: {}` 与 `clicks_cleared_at: null`。
- `clearClicks()` 照 `clearUsageStats` 写：`confirm` → 调 `clearClicksApi()` → `await load()`。

### 7.9 `api/chatApi.js`

**新增 6 个函数**（拦截器不动）：

| 函数 | 请求 |
|---|---|
| `getEmailCode(email, purpose)` | `POST /api/auth/email-code` |
| `verifyEmailCode(email, purpose, code)` | `POST /api/auth/verify-email-code` |
| `loginByEmailApi(email, code)` | `POST /api/auth/login-by-email` |
| `resetPassword(email, code, password)` | `POST /api/auth/reset-password` |
| `clearClicksApi()` | `POST /api/admin/clicks/clear` |

**改造 1 个**：

```js
// Spec19 §7.6 的签名（Spec22 §6.1 改造）
// 原：submitRegisterRequest({ username, password, phone, email, wechat })
// 新：phone 删除，新增 code（**没有 confirm** —— 它不提交，§2.10）
export function submitRegisterRequest({ username, password, email, code, wechat }) { … }
```

**注释同步**：`listUsers()` / `listRegisterRequests()` 的返回类型注释里的 `phone` 删掉；`api/chatApi.js:156`、`:200`、`:202`、`:209` 四处。

### 7.10 样式（`assets/styles/main.css`）

```css
/* Spec22：改密码成功的绿色提示行。与 .login-error 同排、互不覆盖。
   为什么要有它：改完密码只把人送回登录页、什么都不说，用户分不清"成功了"和"没点对"（§2.7）。 */
.login-ok { color: #86efac; font-size: 13px; margin: 6px 0 0; }

/* Spec22：邮箱 + 「获取验证码」同一行 */
.reg-code-row { display: flex; gap: 8px; align-items: center; }
.reg-code-row .login-input { flex: 1; }
.btn-code { white-space: nowrap; /* 倒计时数字变化时按钮不跳宽 */ }

/* Spec22：登录页两个新入口（并排、弱化，不与「新用户注册」抢主次） */
.login-alt { display: flex; gap: 16px; justify-content: center; margin-top: 10px; }
.btn-link { background: none; border: none; color: var(--acn-text-dim); cursor: pointer; font-size: 13px; }

/* Spec22：EmailAuthModal 的卡片（照 .reg-card 的尺寸与圆角，不重造一套） */
.email-auth-card { /* … */ }
```

- 颜色一律用 `:root` 里既有的变量，**不新增调色板**（Spec19 §7.7 的约定）。
- 紫色主题不动。

---

## 8. 配置 / 环境变量

### 8.1 `config.py`

**删除两行**：

```python
# Spec22 删除：REGISTER_IP_WINDOW_SECONDS
#   唯一消费者是"同一 IP 24 小时一次"的注册冷却，需求 3 已把它整个删掉（§2.11）。
#   留一个"设了也不生效"的变量，正是 CLAUDE.md 为 QUOTA_CONTACT_EMAIL 记过的那类静默失败。

# Spec22 删除：REGISTER_DAILY_NOTICE
#   原文「每人每天只能申请一个账号…」随同一条限制一起消失。
#   连带 GET /api/auth/register-config 不再返回 daily_notice、RegisterModal 删掉那一行（§2.11）。
```

**新增一段**（放在 Spec19 注册块**之后**、Spec20 邮件块**之前**——它与 SMTP 无关，不需要等 SMTP 的变量）：

```python
# ===== 邮箱验证码（Spec22）=====

# 验证码 TTL（秒）。默认 600 = 10 分钟。存进 email_verifications.created_at 的
# cutoff 由它算出来，邮件正文里那句"验证码 N 分钟内有效"也由它推出来
# （照 RECHARGE_COOLDOWN_MESSAGE 的先例：分钟数永远跟着秒数走，改一处就够）。
EMAIL_CODE_TTL_SECONDS = int(os.getenv("EMAIL_CODE_TTL_SECONDS", "600"))

# 同一邮箱、同一场景的重发冷却（秒）。默认 60 = 1 分钟。
EMAIL_CODE_RESEND_SECONDS = int(os.getenv("EMAIL_CODE_RESEND_SECONDS", "60"))

# 四句给用户看的提示语（**唯一来源，前端零副本** —— 与 QUOTA_EXCEEDED_MESSAGE /
# REGISTER_PRICE_NOTICE / RECHARGE_COOLDOWN_MESSAGE 同一原则）。
# 前两句是用户逐字给的原文（含「宝子」与那个弯引号）；第三句是本 Spec 拟的
# （用户只给了"已注册"那句，但"已提交过申请"必须另有一句，理由见 §2.4）。
EMAIL_CODE_REGISTERED_NOTICE = (
    "已注册账号{username}，请前往登录界面。忘记密码请前往登录界面“修改密码”"
)
EMAIL_CODE_PENDING_NOTICE = "该邮箱已提交过注册申请，请等待管理员审批"
EMAIL_CODE_UNREGISTERED_NOTICE = "还未注册，请宝子前往新用户注册~"

# 重发冷却那句告警。**分钟数由秒数推出来**，不是另写一个 "1"
# （CLAUDE.md 已为 RECHARGE_COOLDOWN_MESSAGE 记过同一条：改冷却期文案会自动跟着变）。
EMAIL_CODE_COOLDOWN_MESSAGE = (
    f"验证码发送过于频繁，请 {max(1, EMAIL_CODE_RESEND_SECONDS // 60)} 分钟后重试"
)
```

> ⚠️ **引号那一处**：`EMAIL_CODE_REGISTERED_NOTICE` 里用户写的是 `登录界面'找回/修改密码'`，但按钮已经改名成「修改密码」（§0 第 6-a 条）。所以那句里的引用同步改成 **“修改密码”**（中文弯引号，与「宝子」那句的语感一致）。**这是本 Spec 唯一一处"改了用户原话"**，理由是指着一个不存在的按钮。若要改回单引号或改称呼，只动这一行。

### 8.2 `.env.example` 追加

```bash
# ---- 邮箱验证码（Spec22，全部可留空用默认值）----
# ⚠️ 本功能**依赖 SMTP_PASSWORD**：不配它时注册、邮箱登录、修改密码三条链路全部不可用
#    （接口返回 50302「邮箱服务暂不可用」）。这与 Spec20/21 的"邮件只是通知"性质不同。
# EMAIL_CODE_TTL_SECONDS=600         # 验证码有效期（秒）= 10 分钟
# EMAIL_CODE_RESEND_SECONDS=60       # 同一邮箱的重发冷却（秒）= 1 分钟
```

并在同一文件里**删掉** `REGISTER_IP_WINDOW_SECONDS=86400` 那一行（它在 Spec19 段落里）。

### 8.3 变量总览（本 Spec 触及的）

| 变量 | 值 | 说明 |
|---|---|---|
| ~~`REGISTER_IP_WINDOW_SECONDS`~~ | **删除** | IP 冷却已不存在 |
| `EMAIL_CODE_TTL_SECONDS` | `600` | 验证码 TTL。**新增** |
| `EMAIL_CODE_RESEND_SECONDS` | `60` | 重发冷却。**新增** |
| `SMTP_PASSWORD` | 空 = 关闭 | **语义在本 Spec 变重**：从"只是不发通知"变成"三条链路不可用"（§2.5） |
| `SUPPORT_EMAIL` | `frostyj@qq.com` | 50302 那句提示里的客服邮箱。**不新增变量**（复用 Spec19 的唯一来源） |

### 8.4 `.gitignore` / `requirements.txt`

**都不动。** 无新依赖；无新文件需要排除（`artcn.db` 早已在 `.gitignore` 里）。

---

## 9. 错误码

`errors.py` **追加 5 个类**（排在 Spec21 §9 那一段之后），**删除 1 个类**：

```python
# ---- 邮箱验证码与入口统计（Spec22 §9，追加到 Spec21 §9 之后）----

class EmailCodeRequestError(BadRequestError):
    """验证码链路的字段/校验失败。

    多个不同 message 共用一个码，与 Spec19 的 RegisterRequestError（40018）、
    Spec21 的 RechargeRequestError（40019）同款：
    邮箱格式不对 / 验证场景未知 / 验证码不是 4 位数字 / **验证码错误或已过期**。
    """
    def __init__(self, message: str = "验证码请求非法"):
        super().__init__(message, code=40020)


class ClickEventError(BadRequestError):
    """埋点事件名不在白名单里（只有我们自己的前端会调它，出现即代码写错）。"""
    def __init__(self, message: str = "未知的埋点事件"):
        super().__init__(message, code=40021)


class EmailCodeRateLimitedError(AppError):
    """同一邮箱在同一场景下的重发冷却期内（默认 1 分钟）。

    文案来自 config.EMAIL_CODE_COOLDOWN_MESSAGE（前端零副本）。
    """
    def __init__(self, message: Optional[str] = None):
        super().__init__(40906, message or config.EMAIL_CODE_COOLDOWN_MESSAGE, status_code=409)


class EmailCodeRejectedError(AppError):
    """查重拒绝：邮箱已注册 / 已有待审批申请 / 还未注册。

    三句话共用一个码（用户看到的是 message，不需要知道是哪一种）。
    第一句里要填用户名，所以 message 由**路由**拼好传进来（模板在 config，
    理由见 §2.4：文案的唯一来源是 config，不是这条路由）。
    """
    def __init__(self, message: str = "该邮箱无法申请验证码"):
        super().__init__(40907, message, status_code=409)


class EmailServiceUnavailableError(AppError):
    """未配置 SMTP_PASSWORD —— 验证码发不出去，三条链路都走不通（§2.5）。

    这是**唯一可预知**的失败，所以从"静默降级"改成"明确报错"。
    用 503 而不是 500：这是服务暂时不可用，不是代码错了。
    """
    def __init__(self, message: Optional[str] = None):
        super().__init__(
            50302, message or f"邮箱服务暂不可用，请联系客服 {config.SUPPORT_EMAIL}",
            status_code=503,
        )
```

**删除**：

```python
# Spec22 删除：class RegisterRateLimitedError(AppError)  # 40902
# 它的唯一语义是"同一 IP 24 小时内已提交过注册申请"（Spec19 §2.2）。
# 需求 3 删掉了那个限制 → 这个码没有生产者了 → 整个类删掉。
# **不把它改嫁给"验证码重发冷却"**：重定义既有码会让旧日志里的 40902 变成假话（§2.11）。
```

| 码 | 类 | 何时 | 消息 |
|---|---|---|---|
| `40020` | `EmailCodeRequestError` | 邮箱格式不对；`purpose` 不在白名单；验证码不是 4 位数字；**验证码错误或已过期** | 「邮箱格式不正确（需包含 @，且 @ 前后都有内容）」「未知的验证场景」「请填写 4 位数字验证码」「验证码错误或已过期」 |
| `40021` | `ClickEventError` | `event` 不在 `_CLICK_EVENTS` | 「未知的埋点事件」 |
| `40906` | `EmailCodeRateLimitedError` | 同一邮箱同一场景 1 分钟内重复申请 | `config.EMAIL_CODE_COOLDOWN_MESSAGE` |
| `40907` | `EmailCodeRejectedError` | 邮箱已注册 / 已有待审批申请 / 还未注册 | 见 §2.4 的三句（第 1 句由路由用 `config` 的模板拼） |
| `50302` | `EmailServiceUnavailableError` | 未配置 `SMTP_PASSWORD` | 「邮箱服务暂不可用，请联系客服 {SUPPORT_EMAIL}」 |
| ~~`40902`~~ | ~~`RegisterRateLimitedError`~~ | **删除** | — |
| `42901` | `LoginRateLimitedError`（**复用 Spec2**） | 验证码连错 / 邮箱登录被限速 | 「登录尝试过于频繁，请稍后再试」 |
| `40304` | `QuotaExceededError`（**复用 Spec18**） | 邮箱登录时该用户已超额 | `config.QUOTA_EXCEEDED_MESSAGE` |
| `40018` | `RegisterRequestError`（**复用 Spec19**） | 注册的字段校验（含**新的**密码下限文案与验证码格式） | 「密码需为 2~72 位」等 |
| `40010` | `CredentialsFormatError`（**复用 Spec2**） | 管理员建号 / 重置密码的密码下限（6 → 2） | 「密码至少 2 位」 |

> `42901` 被复用到"验证码猜错"上是**刻意的**（§2.6）：同一个 IP 猜密码和猜验证码是一回事，用同一个码让前端与限速口径只有一份。`errors.py` 里那个类的 docstring 要扩一句。
> `40018` 被复用到"验证码格式"上也是刻意的：注册表单的字段规则本来就都归它（Spec19 的多 message 设计就是为这个）。

---

## 10. 日志约定

沿用 Spec §10 的单行 JSON 格式。

| 事件 | 级别 | 字段 | 何时 |
|---|---|---|---|
| `email_code.requested` | `info` | `purpose` | 码已落库、发信已入队 |
| `email_code.rejected` | `info` | `purpose`, `reason`（`registered` / `pending` / `unregistered`） | 查重拒绝 |
| `email_code.rate_limited` | `info` | `purpose` | 重发冷却命中（40906） |
| `email_code.verified` | `info` | `purpose` | 码校验通过（`verify-email-code` / 登录 / 改密码 / 注册四处之一） |
| `email_code.verify_failed` | `warning` | `purpose` | 码不对或已过期（**每一次都记**，因为这是爆破的指纹） |
| `auth.email_login` | `info` | `username` | 邮箱登录成功 |
| `auth.password_reset` | `info` | `username` | 自助改密码成功 |
| `click.recorded` | `info` | `click_event` | **只在新增一个不重复 IP 时**打（§2.9） |
| `notify.email_code_mail_sent` | `info` | `purpose` | 发码邮件成功（**不带 `to`**） |
| `notify.email_code_mail_skipped` | `warning` | `reason="smtp_not_configured"`, `purpose` | 双保险：路由已拦，这里再兜一次 |
| `notify.email_code_mail_failed` | `warning` | `purpose`, `error`（`类型名: 消息`） | SMTP 报错 |
| `notify.recharge_approved_mail_sent` | `info` | `username`, `recharge_id` | 审批通过通知用户成功（**不带 `to`**） |
| `notify.recharge_approved_mail_skipped` | `warning` | `username`, `recharge_id`, `reason`（`smtp_not_configured` / `no_email`） | 未配 SMTP，或该用户没有邮箱 |
| `notify.recharge_approved_mail_failed` | `warning` | `username`, `recharge_id`, `error` | SMTP 报错 |
| `notify.register_approved_mail_sent` | `info` | `username`, `register_id` | **注册**审批通过通知注册者成功（**不带 `to`**） |
| `notify.register_approved_mail_skipped` | `warning` | `username`, `register_id`, `reason`（`smtp_not_configured` / `no_email`） | 未配 SMTP，或那条申请没有邮箱（Spec22 之前的旧 pending 行） |
| `notify.register_approved_mail_failed` | `warning` | `username`, `register_id`, `error` | SMTP 报错 |

> 这三条的字段（`username` / `register_id` / `reason` / `error`）**全部已在 `_FIELDS` 白名单里**（`register_id` 是 Spec19 加的），所以**不需要再改 `logging_setup.py`**。⚠️ 但**照 `_FIELDS` 的键名逐字传**：路由里那次 `logger.info` 传的 extra 键是 `register_id`，不是 `request_id`（Spec19 定的避让，Spec21 §10.1 记过同一条）。

**删除**：`auth.register_blocked`（IP 冷却那条，事件本身随限制一起消失）。

### 10.1 ⚠️ `logging_setup.py` 的字段白名单（**这是第三次**）

`JsonFormatter._FIELDS` 是一份**白名单，不是"自动带上 extra"**：没登记的键会被**静默丢弃**——不报错、不警告，日志看起来"正常"，只是少了一个字段。Spec20 栽过一次（CLAUDE.md 记了），Spec21 又栽过一次（§10.1 记了）。

**必须新增到 `_FIELDS` 的字段**：

```python
               # Spec22 邮箱验证码与入口统计事件字段
               # purpose：register | login | reset
               # click_event：**不叫 event** —— event 在本仓是每条日志的"事件名"
               #   （_FIELDS 的第一项，Spec §10 起）。同名会让 `grep '"event"'`
               #   一次捞到两种东西，与 Spec19 的 register_id、Spec21 的
               #   recharge_source 是同一条理由（§5.3）。
               "purpose", "click_event")
```

**必须从 `_FIELDS` 删除的字段**：

```python
               # Spec22 删除："has_phone" —— 注册表单已经没有任何电话字段了，
               #   留着它就是一个永远不会被传进来的白名单项。
```

- 已在新日志里用到的**既有**字段：`username` / `reason` / `error` / `recharge_id` / `decision` —— **全都已在白名单**，直接复用。
- `purpose` 与 `click_event` 是全新字段，**必须登记**。

### 10.2 绝不进日志的四样

1. `SMTP_PASSWORD`（凭据，Spec20 起的规矩）。
2. **验证码本身**（`code`）——它是凭据（§2.2）。发码与验码的日志**都只记 `purpose`**，绝不记 `code`。
3. **用户的 `email`**（PII）。⚠️ 注意本 Spec 新增的**四封**邮件收件人都是**用户本人**（验证码 + 三封审批通知），所以它们的日志**一律不带 `to`** —— 与 Spec20/21 那三个函数不同，那时 `to` 是你自己的固定地址（`REGISTER_NOTIFY_TO` / `RECHARGE_NOTIFY_TO`），不构成 PII（§2.12）。
4. `ip`（Spec19 §10 的规矩）。点击埋点**在库里存 IP**，但**日志里没有**；`register_requests.ip` 这个列本身也随需求 3 一起删了。

> **唯一的例外口子**：`notify.*_mail_failed` 的 `error` 字段里可能含收件地址（`smtplib` 的 `SMTPRecipientsRefused` 会把地址写进异常文本）。要严格隐私就得对 `error` 做脱敏，而脱敏会让排障变难——**保留原样**（Spec20/21 也是这样），知悉即可。

---

## 11. 目录结构增量

```
Server/
  verifications.py      ← 新增（本 Spec 唯一的后端新文件）
  db.py                 ← 删 3 列 + 删 2 个迁移产物 + 2 个新迁移 + 8 个新函数 + 6 个改造（§5.5）
  config.py             ← 删 2 个变量、加 2 个变量 + 4 句提示语（§8.1）
  errors.py             ← +5 个类、−1 个类（§9）
  schemas.py            ← RegisterRequestCreate 改造 + 5 个新请求体（§6.10）
  mailer.py             ← +send_email_code、+send_recharge_approved_notification
                          +send_register_approved_notification（§5.6，三个都要同步 def）
  logging_setup.py      ← _FIELDS：−has_phone、+purpose、+click_event（§10.1）
  main.py               ← 注册路由改造、密码下限 ×3、+6 条路由、stats +1 组、
                          PUBLIC_AUTH_PATHS 5→10、3 处 contact 去 phone、
                          两条 approve 路由各加 background_tasks + 一次 add_task
  .env.example          ← +一段（2 变量）、−1 行

frontend/src/
  views/EmailAuthModal.vue   ← 新增（本 Spec 唯一的前端新组件）
  utils/track.js             ← 新增
  views/RegisterModal.vue    ← 删手机号、+验证码、+确认密码、placeholder、删 daily_notice
  views/Login.vue            ← +两个按钮、+EmailAuthModal、+绿色提示行、+2 个埋点
  views/AdminPanel.vue       ← 用户表去电话、注册申请表删手机号行、+审批确认文案
  views/StatsPanel.vue       ← +入口点击区块、+第三个清零按钮、+上次清零
  App.vue                    ← +3 个埋点（社区 / 我的作品 / 余额与充值）
  store/auth.js              ← +loginByEmail
  api/chatApi.js             ← +5 个函数、submitRegisterRequest 改签名、注释去 phone
  assets/styles/main.css     ← .login-ok / .reg-code-row / .btn-code / .login-alt / .btn-link

specs/Spec22.md           ← 本文
CLAUDE.md                 ← 配置段 + 关键注意事项
```

---

## 12. 实施顺序（里程碑）

| # | 动作 | 完成判据 |
|---|---|---|
| 1 | **先量 SQLite 版本**：`python -c "import sqlite3; print(sqlite3.sqlite_version)"` | **≥ 3.35.0**，否则 §2.1 的降级分支会生效（三列留在库里）——这时要先决定是否升级 Python |
| 2 | `db.py`：三列 DDL 删除 + 删 `_CREATE_REGISTER_REQUESTS_IP_INDEX` 及其调用 + `_migrate_users_contact` 改造 + 两个新迁移（§5.1、§5.8） | **用一份 Spec21 时代的旧 `artcn.db` 备份**启动：`sqlite3 artcn.db ".schema users"` 里**没有** `phone`；`.schema register_requests` 里**没有** `phone`/`ip`；`PRAGMA index_list(register_requests)` 里**没有** `idx_register_requests_ip`；**第二次启动不报错** |
| 3 | `db.py`：读/写路径去 phone/ip + 删 `find_recent_register_by_ip` | `grep -n "phone" Server/*.py` → **零命中**；`python -c "import db; db.init_db()"` 通过 |
| 4 | `db.py`：`get_user_by_email` + `email_verifications` 三函数 + `click_events` 四函数 + `get_cleared_times` 改造（§5.5） | `sqlite3 artcn.db ".schema email_verifications"` / `".schema click_events"` 都有那条唯一约束与索引 |
| 5 | `verifications.py` 新建 | `python -c "import verifications; print([verifications.generate_code() for _ in range(5)])"` → 5 个 1000~9999 的 4 位串，**没有前导零** |
| 6 | `config.py`（删 2 加 2 + 4 句）、`errors.py`（+5 −1）、`schemas.py`、`logging_setup.py` | `python -c "import config; print(config.EMAIL_CODE_TTL_SECONDS, config.EMAIL_CODE_UNREGISTERED_NOTICE)"` 不 `NameError`；`python -c "import errors"` 不因 40902 被别处引用而报错 |
| 7 | `mailer.py`：+3 个函数（**三个都是同步 `def`**） | 见 §13 **B / D 组**；`python -c "import mailer; print(mailer.beijing_time_text('2026-09-19T07:33:12.451Z'))"` **仍**输出 `2026-09-19 15:33:12` |
| 8 | `main.py`：密码下限三处（§2.10） | 建一个 2 位密码的账号成功；1 位的报 40018「密码需为 2~72 位」 |
| 9 | `main.py`：注册路由改造（§6.1） | 见 §13 **B 组** |
| 10 | `main.py`：5 条公开路由 + `PUBLIC_AUTH_PATHS` 5→10（§6.2~§6.6、§6.9） | 见 §13 **B / C 组** |
| 11 | `main.py`：**两条 approve 路由**各加 `background_tasks` + 一次 `add_task`（§5.7 D/E、§2.12、§6.11） | 见 §13 **D 组**。⚠️ 两处的参数都插在 `request: Request` 之后、`x_request_id` 之前（否则 `SyntaxError: non-default argument follows default argument`，**服务起不来**） |
| 12 | `main.py`：`clicks` 清零路由 + `stats` 加键（§6.7、§6.8） | 见 §13 **E 组** |
| 13 | 前端：`utils/track.js`、`store/auth.js`、`api/chatApi.js` | `grep -rn "trackClick" frontend/src/` → 6 处（定义 1 + 调用 5） |
| 14 | 前端：`RegisterModal.vue`、`Login.vue`、`EmailAuthModal.vue` | 见 §13 **B / C 组** |
| 15 | 前端：`AdminPanel.vue`、`StatsPanel.vue`、`App.vue`（埋点）、`main.css` | 见 §13 **A / D / E 组** |
| 16 | `CLAUDE.md` 同步（配置段 + 关键注意事项：三条链路依赖 SMTP、删列不可逆、40902 退休、审批两处各发一封信） | — |
| 17 | 走完 §13 全部用例 | 全绿 |

> **判据一栏引用的是 §13 的分组字母，不是用例编号**：本 Spec 的用例编号在讨论过程中变动过，而分组字母（A~H）稳定。要跑哪个用例，直接翻到那一组。

**第 1~5 步可以独立验证**（纯迁移 + 纯函数），**先用一份旧库备份跑通再动路由**——第 2 步是本 Spec 唯一**不可逆**的一步。

---

## 13. 验收用例（端到端 Smoke）

### 前置

1. `Server/.env` 配好 `SMTP_USER` / `SMTP_PASSWORD`（真实授权码），重启后端。
2. 备一份**当前**的 `artcn.db`（第 2 步要用它验删列迁移，**这一步之后不可逆**）。
3. 两个邮箱：一个**没注册过**的（下面叫 `new@qq.com`）、一个**已注册**的（下面叫 `old@qq.com`，用现成账号的邮箱，没有就在管理端给某个账号手工补一个）。
4. 一个管理员 token。

> ⚠️ **本 Spec 的测试会真的把邮件发出去**：`Server/.env` 里的 `SMTP_PASSWORD` 是配好的，所以验证码邮件会真实投递。**请用你能收到的邮箱测**，不要拿陌生人的地址当靶子（那正是 §3.3-3 那个"邮箱→用户名枚举"的滥用形态）。

### A. 迁移与删列（**不可逆，先做**）

```bash
# 1. 版本门槛
python -c "import sqlite3; print(sqlite3.sqlite_version)"     # → 必须 ≥ 3.35.0
#     ✅ 小于 3.35.0 时：启动日志里有一条 db.migrate + sqlite_too_old 的 warning，
#        三列留在库里，但服务照常起、所有功能正常（§2.1 的降级分支）

# 2. 用旧库启动一次（跑的是 §12 第 2 步的代码）
sqlite3 artcn.db "PRAGMA table_info(users)"                   # ✅ 没有 phone 行
sqlite3 artcn.db "PRAGMA table_info(register_requests)"        # ✅ 没有 phone、没有 ip 行
sqlite3 artcn.db "PRAGMA index_list(register_requests)"        # ✅ 没有 idx_register_requests_ip
sqlite3 artcn.db "SELECT COUNT(*) FROM users"                  # ✅ 用户一个都没少（删列不删行）
sqlite3 artcn.db "SELECT username, email FROM users"           # ✅ email 全小写

# 3. 再启动一次
#     ✅ 不报错、不重复执行、日志里没有第二条"已删除 phone / ip 列"
#     ✅ 第一次启动能跑起来（原口径下这里会撞 "no such column: ip"，§2.1）
```

### B. 注册（§6.1、§6.2、§7.1）

```bash
# 4. 发码（未注册邮箱）
curl -X POST localhost:8000/api/auth/email-code -H 'Content-Type: application/json' \
     -d '{"email":"new@qq.com","purpose":"register"}'
#     → {"code":200,"data":{"sent":true}}
#     ✅ 收件箱（new@qq.com）收到：主题「ArtiControlNet-邮箱验证」
#        正文「您的邮箱验证码为：4821。验证码10分钟内有效。」
#     ✅ 响应里**没有** code 字段（没回显）
#     ✅ 日志 email_code.requested, purpose=register
#     ✅ 日志里**没有**邮箱地址、没有验证码、没有 IP

# 5. 1 分钟内重发 → 40906
#     ✅ message 是「验证码发送过于频繁，请 1 分钟后重试」（来自 config，前端零副本）
#     ✅ 日志 email_code.rate_limited
#     ✅ 等 1 分钟后再发 → 200；收件箱**第二封**
#     ✅ 此时库里该邮箱有 2 条记录（`SELECT COUNT(*) FROM email_verifications`）
#        —— TTL 内**两个码都有效**（§2.2）

# 6. 提交注册（用第一封的那个码）
curl -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
     -d '{"username":"spec22a","password":"ab","email":"new@qq.com","code":"4821","wechat":"wx-test"}'
#     → {"code":200,"data":{"id":N}}
#     ✅ 2 位密码**通过**（需求 5）
#     ✅ 收件箱（frostyj@qq.com，你自己）收到 ACN-spec22a-new@qq.com
#     ✅ 管理端「待审批注册用户」出现这条，**没有「手机号：」那一行**，时间是北京时间

# 7. 同一邮箱再发码 → 40907
#     ✅ message 恰好是「该邮箱已提交过注册申请，请等待管理员审批」
#     ✅ 日志 email_code.rejected, reason=pending

# 8. 码错 / 码过期
#     ✅ 提交注册时填 code=1111 → 40020「验证码错误或已过期」
#     ✅ 先删掉 email_verifications 的那两行再提交 → 同样 40020（TTL/命中判据生效）
#     ✅ 日志 email_code.verify_failed （warning）

# 9. 已注册邮箱发码 → 40907
#     ✅ message 恰好是「已注册账号<用户名>，请前往登录界面。忘记密码请前往登录界面“修改密码”」
#     ✅ 用户名是**真的**（这条就是 §3.3-3 那个已知泄露，确认它的形态）
#     ✅ 日志 email_code.rejected, reason=registered
```

### C. 邮箱登录 / 修改密码（§6.3~§6.5、§7.2、§7.3）

```bash
# 10. 未注册邮箱走登录/改密码的验证码
#     ✅ purpose=login 或 reset → 40907「还未注册，请宝子前往新用户注册~」（逐字）
#     ✅ purpose 传 "hack" → 40020「未知的验证场景」

# 11. 邮箱登录（已开通的账号）
#     ✅ 前端点「邮箱登录」→ 填 old@qq.com → 获取验证码 → 收到信 → 填码 → **直接进系统**
#     ✅ 返回 {token, username, is_admin}，与密码登录**同形**（刷新页面仍在登录态）
#     ✅ 日志 auth.email_login, username=<那个账号>
#     ✅ 用**大写**邮箱（OLD@QQ.COM）再走一遍 → 同样成功（§2.8）

# 12. 验证码连错触发限速（§2.6）
#     ✅ 连续 5 次填错码 → 第 6 次开始 42901「登录尝试过于频繁，请稍后再试」
#     ✅ 日志 email_code.verify_failed 记了 5 条
#     ✅ 等 5 分钟（或换 IP）后恢复

# 13. 修改密码全流程
#     ✅ 点「修改密码」→ 填 old@qq.com → 获取验证码 → 填码 → 点「验证」
#     ✅ **验证通过前看不到新密码那两栏**；通过后才展开（用户原话："过了直接弹出"）
#     ✅ 两次密码不一致 → 前端红字「两次输入的密码不一致」，**不发请求**
#     ✅ 填 1 位 → 40018「密码需为 2~72 位」
#     ✅ 合法 + 「完成」→ 回登录页 + **绿色**「密码已修改，请用新密码登录」+ 用户名已预填
#     ✅ 日志 auth.password_reset
#     ✅ 用**新密码**能登录；用**旧密码**登录 → 40102
#     ✅ 改完后**改码再点完成**：密码栏自动收起（§7.3）

# 14. reset-password 的二次校验是真的（§2.7）
#     ✅ 用 curl 直接带一个**假码** POST /api/auth/reset-password → 40020（不靠前端那道）
```

### D. 审批通过 → 用户收到信（§5.6、§5.7 D/E、§2.12）

```bash
# ---- 注册审批（第 8 条要求）----

# 15. 同意一条注册申请 → 注册者收到信
#     ✅ 该申请行的邮箱收到：主题「ArtiControlNet-**注册成功**」
#        （拼写是 ControlNet，不是 ConrtolNet —— §0 第 8-a 条，逐字核对一次）
#        正文「您于<申请时间>申请的注册已通过，您现在可以开始享用ArtiControlNet啦！」
#     ✅ <申请时间> = **申请行** created_at 的北京时间（对照库里 UTC 早 8 小时；
#        与"你刚点了同意"的那一刻**无关**——这句说的是"申请的注册"，不是"审批"）
#     ✅ 正文开头**没有**「ArtiControlNet的用户您好」（充值那两封才有）——照抄原文
#     ✅ 日志 notify.register_approved_mail_sent, register_id=N, username=…（**没有 to**）
#     ✅ 号照建、额度按管理员填的那个数（一切照旧，只多一封信）
#     ✅ 响应体与 Spec19 一字不差（id / username / is_admin / quota_limit）

# 16. 一条 Spec22 之前的旧申请（没有邮箱）
#     ✅ 手工把某条 pending 行的 email 置 NULL（模拟旧数据，§2.12）
#     ✅ 同意它 → **不发信**、**号照建**、日志 notify.register_approved_mail_skipped, reason=no_email
#     ✅ 接口照常 200

# 17. 拒绝 / 删除注册申请 → **不发信**（收件箱零新增）

# ---- 充值审批（第 7 条要求）----

# 18. 同意一条**主动充值**（source='user'）记录 → 用户收到信
#     ✅ 该用户邮箱收到：主题「ArtiControlNet-充值已到账」
#        正文「ArtiControlNet的用户您好，您于<申请时间>充值的金额已到账，感谢您的支持~」
#     ✅ <申请时间> = 该记录 created_at 的**北京时间**（对照库里 UTC 早 8 小时）
#     ✅ 日志 notify.recharge_approved_mail_sent, recharge_id=N, username=…（**没有 to**）
#     ✅ 额度照加（quota_limit 增加、used 不变）

# 19. 欠费充值审批 → 另一个变体
#     ✅ 主题「ArtiControlNet-账号已恢复」
#        正文**多后半句**「您的账号可以恢复使用啦，感谢您的支持~」
#     ✅ 该用户**立刻能登录**（限额已加回）

# 20. 没有邮箱的用户
#     ✅ 管理端手工建一个号（`POST /api/admin/users`，本来就没有邮箱）→ 给他走一遍欠费充值 → 同意
#     ✅ **不发信**、额度照加、日志 notify.recharge_approved_mail_skipped, reason=no_email
#     ✅ 前端不报错

# 21. 拒绝 / 删除充值审批 → **不发信**（收件箱零新增）
```

> ⚠️ **用例 15~21 会真的发出邮件**，收件人是**用户**（不是你自己）。用你能收到的邮箱测——注册那封发给「申请行上的邮箱」，充值那封发给「该用户的邮箱」。

### E. 入口点击统计（§6.6~§6.8、§7.4、§7.8）

```bash
# 22. 五个埋点各自生效
#     ✅ 匿名打开登录页 → 管理端「打开登录页」+1
#     ✅ 点「新用户注册」→「点「新用户注册」」+1
#     ✅ 登录后点「社区」/「我的作品」/「余额与充值」→ 各自 +1
#     ✅ 日志 click.recorded 只在**首次**出现（同 IP 再点不打日志，§2.9）
#     ✅ 库里：SELECT event, COUNT(*) FROM click_events GROUP BY event

# 23. 同一个 IP 只计一次
#     ✅ 刷新登录页 10 次、反复进出社区 → 数字**不变**
#     ✅ `SELECT COUNT(*) FROM click_events` 与面板上的 5 个数字之和一致

# 24. 埋点不影响主流程
#     ✅ 把后端停掉 → 打开登录页、点社区、点注册，**全部照常工作**（不报错、不卡）
#     ✅ 浏览器 console **没有**未捕获的 promise 异常
#     ✅ 埋点**不会**触发登出（切到没有 token 的状态再点，仍然停在登录页）
#     ✅ curl 传一个非法 event → 40021「未知的埋点事件」

# 25. 清零
#     ✅ 点「清空入口统计」→ confirm → 5 个数字全变 0
#     ✅ 「上次清零」显示当前时间（与 usage / feedback 两处格式一致，浏览器本地时区）
#     ✅ 库里的行被删光（`SELECT COUNT(*) FROM click_events` → 0）
#     ✅ `app_meta` 里出现 clicks_cleared_at
#     ✅ **清空调用统计不受影响**：再走一次「清空调用统计」，usage 归零、
#        clicks 那 5 个数字**不动**（两个清零互不干扰）
#     ✅ 清零后**同一 IP 再点**会被重新计入（去重只到清零为止）
```

### F. 零配置与降级

```bash
# 26. 清空 SMTP_PASSWORD 重启
#     ✅ 点「获取验证码」→ 50302「邮箱服务暂不可用，请联系客服 frostyj@qq.com」
#        （**不是**静默 200 让用户傻等 —— 这是本 Spec 与 Spec20/21 立场不同的地方，§2.5）
#     ✅ email_verifications 里**没有**新行（校验在落库之前）
#     ✅ 邮箱登录 / 修改密码 → 同样 50302
#     ✅ **老用户用密码登录照常成功**；管理端手工建号照常成功（§3.3-1）
#     ✅ **两条审批路由照常 200**（第 7、8 条是"通知"，不是"前置条件"）：
#        日志 notify.*_approved_mail_skipped, reason=smtp_not_configured，号/额度照给

# 27. 把 SMTP_HOST 改成 10.255.255.1（黑洞），SMTP_PASSWORD 配回来，重启
#     ✅ 点「获取验证码」→ 200（**不等待**那 10 秒超时）
#     ✅ 码**已经落库**（库里能查到）—— 用户拿不到信，但重发是通的
#     ✅ 约 10 秒后日志 notify.email_code_mail_failed
#     ✅ 这 10 秒期间其它接口**照常响应**（同步 def 走线程池，Spec20 §2.1）
#     ✅ 管理端注册审批 / 充值审批 → 接口照常 200（**不去等那 10 秒**），
#        各记一条 notify.*_approved_mail_failed —— 这一条就是在验"三个函数都是同步 def"
```

### G. 零回归

```bash
# 28. git diff --stat 应只包含 §11 列的文件
#     ✅ 逐字节确认 **requirements.txt 无 diff、.gitignore 无 diff、
#        providers/ 无 diff、agents/ 无 diff、media.py 无 diff**

# 29. Spec19/20/21 回归
#     ✅ 注册申请的全链路仍走通（发码 → 提交 → 管理端 pending → 同意 → 新号能登录）
#     ✅ 审批六条路由（注册/充值 各自的 同意/拒绝/删除）行为不变
#        —— **除两条 approve 各多发一封信**（§2.12），它们的请求体/响应体/错误码**一字不变**
#     ✅ 「清空调用统计」仍只删 usage 行，**`user_quota.used` 纹丝不动**
#     ✅ 四类任务的计数时机一个都没变（成功才计）；风格归纳仍在 await 之前计
#     ✅ `python -c "import mailer; print(mailer.beijing_time_text('2026-09-19T07:33:12.451Z'))"`
#        → 2026-09-19 15:33:12
#     ✅ 充值幂等 / 冷却 / 加额度 / 删记录不收回额度，全部与 Spec21 一致
#     ✅ Spec20 的三封"发给你自己"的邮件**照常**（主题里的 contact 现在是邮箱，不是手机号）

# 30. 用户表三张表都不再有电话
#     ✅ GET /api/admin/users 的每一项**没有** phone 键
#     ✅ GET /api/admin/register-requests 的每一项**没有** phone 键、**没有** ip 键
#     ✅ 前端两处都不再画手机号（用户表显示「邮箱」或「无」）
#     ✅ `grep -rn "phone" frontend/src/ Server/ --include=*.vue --include=*.js --include=*.py` → 零命中
```

### H. **作废的旧验收用例**（不是"没跑"，是"规则本身没了"）

| 出处 | 旧用例 | 为什么不成立 |
|---|---|---|
| Spec19 §13 用例 4、5 | 「紧接着再提交 → 40902 同一 IP 冷却」 | IP 冷却已删（需求 3），40902 这个码已不存在（§2.11） |
| Spec19 §13 用例 5 | 「phone/email 都空 → 40018 请至少填写一项」「手号 10 位 → 40018」「手号含字母 → 40018」 | 注册表单没有电话了，邮箱变成必填 |
| Spec19 §13 用例 5 | 「password 5 位 → 40018」 | 下限已改成 2 位（需求 5） |
| Spec19 §13 用例 5 | 「email "abc" → 40018」 | 仍在，但**前提变了**：现在要先通过验证码，所以这条要在**发码**那一步验（§6.2 第 2 条） |
| Spec20 §13 用例 2、3 | 「只填手机号 → 主题回落到手机号」 | 没有手机号可回落了；注册通知的 contact **恒为邮箱** |
| Spec21 §13 用例 1 | 「联系方式那一列显示「zhang@qq.com / 13800138000」」 | 只剩邮箱（§7.7） |
| Spec21 §13 用例 9 | 「手工建的号（无邮箱无电话）→ 主题里是「未填写」」 | 仍在（只判邮箱），但"无电话"这个前提已无意义 |
| Spec21 §13 用例 14 | 「点「同意」→ 额度增加」 | 仍在，**外加**一封发给用户的邮件（§2.12） |
| Spec19 §13 的注册审批用例 | 「同意注册申请 → 新号能登录」 | 仍在，**外加**一封「注册成功」邮件（§2.12）；响应体与错误码一字不变 |

---

## 14. 补充

### 14.1 与 Spec18 / Spec19 / Spec21 的模型关系

| | Spec18 | Spec19 | Spec21 | **Spec22** |
|---|---|---|---|---|
| 新增表 | `user_quota` | `register_requests` | `recharge_requests` | `email_verifications` / `click_events` |
| 表的性质 | 计费账户（只增） | **台账**（同意/拒绝都留行） | **台账**（同左） | **都不是**：一张是"最近 10 分钟的临时码"，一张是"按 (事件, IP) 去重的计数" |
| 清零 | `usage` 可清（区间统计） | — | — | `click_events` 可清（第三个清零口径） |
| 防刷手段 | 限额 | 同 IP 冷却（**Spec22 删除**） | 幂等 + 冷却 | **邮箱验证码**（可验证的身份凭证） |
| 邮件收件人 | — | 你（Spec20） | 你（Spec21） | **你 + 用户**（Spec22 首次给用户发信；3 封用户邮件：注册成功 / 充值到账 / 账号恢复） |
| 发给用户的那封信 | — | — | — | 挂在**两条 approve 路由**上（第 7、8 条要求），**两条都要加 `BackgroundTasks`** |

**一句话**：Spec19 用"IP 冷却"当门槛，Spec21 用"必须是一个真的欠费账号"当门槛，Spec22 把门槛换成了**"这个邮箱是真的"**——它是三者里唯一**可验证**的。

### 14.2 为什么验证码不放在 `auth.py`

`auth.py` 现在的职责是"密码哈希 + JWT + 登录限速"，全是**不依赖库**的纯函数与内存状态。验证码不一样：它的三条规则（TTL、重发冷却、任一命中）**必须查库**（§2.2）。放进 `auth.py` 就要让那个文件 import `db`，把"纯函数模块"变成"要读库的模块"——而这个文件被 `main.py` 和 `db.py` 两边都碰，加了库依赖之后循环引用的风险立刻出现。所以：**生成码的纯逻辑进新文件 `verifications.py`，要读库的校验留 `db.py`，路由负责把两边串起来。** 这也是 `timefmt.py`（Spec21）的同一种切法。

### 14.3 将来若要改的地方（写入本文档，供实际用起来之后回头改）

1. **注册成功面板那句「在30秒内会通过短信/邮件告知您注册结果」。** 「短信」这个通道**从来没有过**，本 Spec 又把邮件变成了唯一的联系通道。用户没要求改这句话，所以**一个字没动**。要改的话，它在前端硬编码（`RegisterModal.vue` 的成功面板），**不是** config 里的常量——顺手的话应该搬到 `config` 去（与其他四句提示语同一个原则）。
2. **`email_verifications` 的清理是"顺手"的。** 只在有人发码时才删过期行（§2.2）。若哪天有人写脚本猛发码（每个邮箱 1 分钟一次），表会长到"最近 10 分钟的码数"——那仍然是有界的，但值得知道它没有独立的清理任务。
3. **验证码的尝试次数没有**每个码**的上限。** 限速是按 IP 的（§2.6）。要更严就得给每个码加一个 `attempts` 列——但那样和"TTL 内任一命中都算数"这句话的交互要想清楚。
4. **`users.email` 没有唯一约束。** 两条同邮箱的存量账号，邮箱登录会进**先注册的那个**（§2.8）。要根治得先清数据再加 `UNIQUE`——等真的遇到再说。
5. **点击统计没有"删除某个 IP"的路。** 真要删就得手动 `DELETE FROM click_events WHERE ip = '…'`（§3.3-5）。
6. **「修改密码」只在登录页。** 已登录的人想改密码要走"退出 → 修改密码 → 重新登录"（§3.2）。若哪天用户抱怨这一步，入口应该加在**顶部按钮区**（与「余额与充值」同排），而不是再做一个面板。
7. **`POST /api/click` 接受任何人的 POST。** 一个人若有很多出口 IP（手机流量切飞行模式就能换），可以把数字刷上去。它与 Spec21 §3.3-2 那条"公开欠费端点"同级：**能被影响的只是你自己看的一张报表**，不会改变任何业务状态。已记录，不修。

---

**完。**
