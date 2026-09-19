# ArtiControlNet Spec 21：余额与充值（自助充值 + 审批台账 + 联系方式）

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：**把"续费"从一个只在管理端存在的动作，变成用户自己就能发起、邮件提醒你审批的闭环**——顶部「余额与充值」按钮、登录页的欠费充值面板、管理端的「待审批充值记录」块，三处共用一张台账 `recharge_requests`。
> 本 Spec 是 **Spec.md / Spec2~20 的增量补充**，不推翻原有架构。
> **新增 1 张表**（`recharge_requests`）+ **给 users 补 2 列**（`phone` / `email`，含存量回填）。
> **无新依赖**（仍是标准库 `sqlite3` / `smtplib`）、**无新持久目录**、**无新 provider / 新模型**。
> 新增 **1 个后端文件**（`timefmt.py`）+ **1 个前端组件**（`RechargeModal.vue`）+ **3 个环境变量**（全部有默认值）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有凭据只在后端环境变量、除 `artcn.db` 外无其他数据库。
> **`RegisterModal.vue` 零改动**（注册页文案来自后端 `REGISTER_PRICE_NOTICE`）。

---

## 0. 六件事一览（用户原话 → 落点）

| # | 用户原话 | 本 Spec 的落点 |
|---|---|---|
| 1 | 用户管理页每条目展示**电话-邮箱**（没有就「无」）；**创建时间展示北京时间** | §5.1（users 补两列）+ §5.2（时间格式化）+ §7.2 |
| 2 | 「更新会逐张分析个人作品…」**不要恒定展示**，点了「基于我的新作品更新风格」才展示 | §7.6（一个 `v-if`） |
| 3 | 帮助页删两句、改成「每个用户预充值后会获得对应次数」 | §7.5（纯文案） |
| 4 | 普通用户顶部加「余额与充值」→ 弹窗（余额 / 收款码 / 参考价 / 微信昵称 / 我已完成充值）→ 落一张**充值表** + 发邮件 + 管理端「待审批充值记录」三按钮 | §5.3~§5.6、§6.2、§6.5、§7.1、§7.3 |
| 5 | 强制退出阈值 `>= 限额` 改成 `>= 限额+1`；被强制退出或登录被拒时登录页弹收款码 + 「我已完成充值」→ 发「ACN欠费充值-」邮件，同样进充值表 | §5.7、§6.3、§7.4 |
| 6 | 注册页「1 元起充 / 1 元约 10 次」改成「0.9 元起充 / 0.9 元约 10 次」 | §8.1（改 `REGISTER_PRICE_NOTICE`，前端零改动） |
| 7 | 注册申请邮件正文**前面加**「微信充值账号是<微信昵称>，」 | §5.5（`send_register_notification` 加一个参数） |

> **关于第 6、7 条的一处订正**：用户记忆里的注册邮件正文是「申请时间是<申请时间>，请立即审批」。实际线上代码（Spec20 §5.1）是「**注册时间**是<北京时间>，请立即审批**！**」。已确认**保留「注册时间是」**，只在前面加微信昵称那一句。所以三封邮件的措辞并不完全一致，这是**有意照抄用户原话**的结果，见 §2.7。

---

## 1. 功能目的

### 1.1 为什么现在做

- **Spec18/19 把「付费」做成了半截。** Spec18 定了"限额用满即锁"，Spec19 定了"注册要先预充值"，但**唯一的续费通道是线下**：用户被锁 → 看到一句"请联系管理员续费" → 加微信 → 你手工改限额。中间没有一条路能把"我付了钱"这件事**结构化地**送到你面前。
- **微信昵称是唯一的对账键。** Spec19 §1.1 已经说过这句话，Spec20 §1.1 又说了一遍——转账记录里只有昵称能把钱和账号对上。所以充值入口也必须收集它，且必须**落库**（邮件会丢、会被淹没，台账不会）。
- **被锁的用户在登录页，而登录页当时什么都没有。** Spec18 的处理是弹一句 `window.alert` 让他去找管理员。用户此刻**最想干的事就是付钱**，本 Spec 让他在原地就能扫码、留昵称、按「我已完成充值」。
- **阈值差 1 次是个真实的体验伤。** 原口径 `used >= limit` 意味着**第 25 次调用一成功就被踢**——用户看不到那次的结果（对话的回复、生成的那张图），而这一次的钱**已经花了**（`record_call` 在成功后才计，所以账是准的，但结果没拿到）。改成 `used >= limit + 1` 后，用户总能看满自己付过的每一次。

### 1.2 一句话架构

**一张台账表 + 四个用户侧入口（余额弹窗 / 欠费面板 / 管理端三按钮 / 邮件提醒），全部复用 Spec19 的「申请 → 审批 → 台账」模型。**

### 1.3 与既有 Spec 的关系

| 既有件 | 本 Spec 怎么动它 |
|---|---|
| `users` 表 | **加两列** `phone` / `email`（可空）。这是 Spec21 唯一的结构性改动，理由见 §2.2。 |
| `register_requests` | **只读**。存量回填时按 `username` 取它的 `phone`/`email`（§5.1）。 |
| `mailer.py` | 加 `send_recharge_notification()`；`send_register_notification()` **加一个参数**（§5.5）。两者共用的时间函数抽到新文件 `timefmt.py`。 |
| Spec18 的限额判定 | 阈值由 `>= limit` 改成 `> limit`（§5.7）。**这是本 Spec 唯一改动既有业务规则的地方**，四处副本必须同步。 |
| Spec19 的注册链路 | 表单、校验、冷却、四条路由**一行不改**。只有「落库之后的那次 `add_task`」多传一个 `wechat`（§5.5）。 |
| Spec20 的邮件机制 | **原样复用**：`BackgroundTasks` + 同步 `def` + 永不抛异常 + `SMTP_PASSWORD` 空则静默跳过。 |
| `RegisterModal.vue` | **零改动**（注册页文案来自 `GET /api/auth/register-config`）。 |

---

## 2. 决策记录（为什么这么选）

### 2.1 联系方式存哪：`users` 表加两列

| 决策 | 选择 | 理由 |
|---|---|---|
| 存哪 | `users` 加 `phone` / `email` | **需求 4/5 的邮件主题是 `ACN充值-<账号>-<邮箱/电话>`，"当前登录用户"的联系方式必须能被后端直接读到。** 而"当前用户"是 `users` 的一行——联系方式不在这张表上，就得靠 username 去 `register_requests` 现查，见下一行。 |
| 为什么不现查 `register_requests` | 不现查 | 三个具体的坏处：① 用户被删后重建同名账号会**串到前一个人的联系方式**；② 管理员手工建的号（`POST /api/admin/users`）**没有任何申请行**，永远查不到；③ 列表接口要为每个用户做一次子查询，而 `users` 表本来就有这一行——把联系方式放在它旁边是零成本的。 |
| 列可空吗 | **可空** | 管理员手工建的号没有联系方式。需求 1 已经为此定了显示口径：「无」。 |
| 存量用户怎么办 | 迁移时**按 username 从已通过的申请回填**（§5.1） | 不回填的话，Spec19 上线以来开通的所有用户在你眼里都是「无」——而他们的联系方式**就在库里**，只是躺在另一张表。回填是这条迁移唯一有价值的副产品，成本是一条 UPDATE。 |
| 回填的边界 | 只认 `status='approved'` 的行 | 被拒绝的申请里的联系方式**不属于任何账号**（那个人从来没被开通），拿它填进去等于凭空捏造一条联系方式。 |
| 为什么不用 `register_requests.user_id` | 不加这一列 | 那要给 Spec19 的表补列 + 回填 + 改三处写入，动的是**已经跑通的审批链路**。而 Spec21 需要的信息（`users.phone/email`）用一个 username 关联就能一次性搬完，搬完就再也不需要关联了。 |

### 2.2 时间格式化：抽出 `Server/timefmt.py`

| 决策 | 选择 | 理由 |
|---|---|---|
| 为什么不把 `beijing_time_text` 留在 `mailer.py` | 抽到新文件 | Spec20 时它只有一个消费者（发信）；Spec21 之后 `main.py` 要用它给**三个管理端列表**各算一个 `created_at_beijing`。让路由层写 `mailer.beijing_time_text(...)` 是**语义错位**——一个叫 mailer 的模块不该拥有通用的时间格式化。 |
| 破坏 Spec20 的验收命令吗 | **不破坏** | `mailer.py` 改成 `from timefmt import beijing_time_text`，`mailer.beijing_time_text` 依然可调用。Spec20 §13 第 2 步的命令（`python -c "import mailer; print(mailer.beijing_time_text(...))"`）**逐字照旧可用**。 |
| 实现细节变了吗 | **一个字都没变** | 固定 `+08:00`，不用 `zoneinfo`（Windows 没有系统 tz 数据库）。Spec20 §2.2 的全部理由原样成立，见 §5.2。 |
| 为什么不在前端转 | 后端转 | 前端的 `toLocaleString()` 给的是**浏览器所在时区**。你在国外打开管理端会看到当地时间。用户要的是**北京时间**这个绝对量，那么它就不该取决于谁在看。 |
| 字段名叫什么 | `created_at_beijing` | 自解释。**不覆盖原有的 `created_at`**——UTC ISO 仍是它本来的值，排序/排障/将来别的消费者都用得上；展示串是"多出来的一个"。 |

### 2.3 充值台账：`recharge_requests`

| 决策 | 选择 | 理由 |
|---|---|---|
| 表名 | `recharge_requests` | 与 `register_requests` 同构同构词，一眼看出是同一类东西（申请台账）。 |
| 是不是台账 | **是**（照抄 Spec19 §2.4） | 同意 / 拒绝都**保留记录**，只有「删除」真删行。理由一样：你需要能回答"上周那个人说他付了钱，到底批没批"。 |
| 存 `user_id` 还是 `username` | **两个都存** | `user_id` 决定**给谁加额度**（唯一可靠的键）；`username` 是**提交时刻的快照**——台账要能脱离 `users` 表被读懂，而 Spec19 的 `register_requests` 整体就是这个立场。两者不会漂移（系统没有改名功能）。 |
| `source` 列 | 有：`'user'` / `'overdue'` | 两条入口的**业务含义不同**（主动充值 vs 欠费被拦），邮件主题也不同（`ACN充值-` vs `ACN欠费充值-`）。它同时是**排障时第一个要看的字段**："这个人是从哪进来的"。 |
| `amount` 列 | 有，可空 | 同意时管理员当场填的加次数。**台账要能回答"我给他加了多少"**，否则记录只有"批准了"，而批准的数字凭空消失。`NULL` = 尚未处理。 |
| **不存 `ip`** | 不加这一列 | Spec19 存 ip 是因为它需要**同 IP 冷却**；本表的防刷手段是**幂等**（见 §2.4），不需要 IP。于是本表**全表不含任何多余 PII**——`wechat` 是对账必需，`username` 是台账必需，仅此而已。 |
| 为什么没有 `UNIQUE(user_id, status)` | 不加 | 与 Spec19 §2.2「`register_requests` 故意没有 `UNIQUE(username)`」同一条理由：**被拒绝之后必须能再申请**。唯一性靠 `status='pending'` 的幂等查询兜（§2.4），那是**业务规则**，不是数据库约束。 |
| 表在 `init_db` 的建表清单里 | **在** | 与 `register_requests` 一样是全新空表，`CREATE TABLE IF NOT EXISTS` 对新库/存量库行为一致，**不需要**迁移函数（与 Spec18 的 `_backfill_user_quota` 不同——那个要给**已存在的数据**补一份派生账本）。 |

### 2.4 防刷：**幂等**，不是冷却

| 决策 | 选择 | 理由 |
|---|---|---|
| 重复提交怎么处理 | 同一用户已有 `pending` 记录 → **不落库、不发信**，照常返回 200 + 那条的 id | 这是"我已经点过了"的正常行为，不是攻击。给它一个错误码只会让前端多一个分支、让你多一个要判断的码。 |
| 前端要不要区分 | **不区分** | 成功面板永远说同一句话（「已提交，等待管理员审批」）。**零分支**：用户不需要知道"这是第一次还是第二次"，你也不需要。 |
| 那公开端点（欠费）不会被刷吗 | 刷不动 | 公开端点额外要求「**账号存在**且**确实已超额**」（§6.3）。所以能被刷的集合 = **已经欠费的账号**，而其中每个最多产生 1 条 pending。上限是你自己的欠费用户数，**不是攻击者的资源数**。 |
| 为什么不加同 IP 冷却 | 不加 | Spec19 加冷却是因为注册是**任何人**都能触发的（无门槛），而欠费充值有"必须是一个真的欠费账号"这个门槛。为一个人为门槛已经很高的动作再引入一套冷却表 + 409 错误码 + 前端提示，是复杂度换不到安全。 |
| 拒绝之后能不能再提交 | **能** | 幂等只认 `pending`。被拒绝（比如昵称填错了）之后重新提交是**正常且必要**的路径——否则用户被拒一次就再也点不动了。 |
| 已同意的呢 | 也不拦 | 加完额度后用户可能还想再充。`pending` 之外的任何状态都不参与幂等判定。 |

### 2.5 「同意」加多少：管理员当场填

| 决策 | 选择 | 理由 |
|---|---|---|
| 谁决定次数 | **管理员当场填**（`window.prompt`，与注册审批逐字同款交互） | 与 Spec19 §6.5 同一个理由：弹窗上写着「0.9 元约 10 次」，但**实收金额是你在微信里看到的**，只有你知道。写死 `+10` 会在有人付了 2 元时变成一个你改不了的错。 |
| 前端给默认值吗 | **不给** | Spec19 §7.5c 已经为「同意注册申请」定了这条：前端拿不到 `QUOTA_DEFAULT_LIMIT`，写死任何数字都是复制一个会漂移的常量。充值同理。 |
| 取值范围 | 整数 **≥ 1**，且加完不得超 `QUOTA_LIMIT_MAX` | 下界 1：加 0 次是一次无意义的点击，几乎必然是手滑——宁可报错让管理员看清。上界复用 Spec18 的 `QuotaLimitError`（40017），因为**超上限的后果与「改限额」超上限完全一样**（一个天文数字进库）。 |
| 加在哪一列 | `users.quota_limit += amount` | **`user_quota.used` 一个字都不动。** used 是历史事实（Spec18 §2.2），充值改变的是"你还能用多少次"，不是"你已经用了多少次"。 |
| 事务边界 | **一个事务**：置 `approved` + 记 `amount` + `quota_limit += amount` | 与 Spec19 §5.2B「建号 + 改状态必须同生同死」完全同类。否则会开出"记录已批准，但额度没到账"的窗口——用户拿着批准记录来找你，而系统显示他没充过。**并发判据仍是 `UPDATE ... WHERE status='pending'` 的 rowcount**。 |
| 用户已被删除呢 | 路由预检 → 40402 | 管理员删号之后，那条 pending 记录仍在台账里（台账不级联，见 §2.6），但**加不上去**。让 `UPDATE users` 影响 0 行然后静默提交，是最坏的结果（记录显示已批准，钱没到账）。所以**预检**：目标用户不存在 → 40402，整条操作不做。 |

### 2.6 删用户时，充值记录怎么办

| 决策 | 选择 | 理由 |
|---|---|---|
| 删用户 | **一并删该用户的 `recharge_requests` 行**（任意状态） | `delete_user` 已经在级联删 `usage` / `user_quota` / `images` / 帖子 / 评论 / 建议 / 分享 / wiki / 对话（Spec18 §5.1h 的清单）。充值记录是**该用户的业务数据**，与它们同类——留一堆 `user_id` 指向不存在用户的挂账记录，只会让列表里出现点不动的行。 |
| 那 `register_requests` 为什么不删 | 不删（维持 Spec19 原样） | 它是**审批台账**且**没有 user_id**（Spec19 §1.3：申请阶段还没有用户）。删除一个已开通的账号，不影响"当初谁申请过"这条历史。两者结论不同是因为**它们回答的问题不同**，不是不一致。 |
| 「删除」按钮删的是什么 | 只删这条充值记录 | 与 Spec19 §6.7 同款：**不触碰 `users`**。删除一条已同意的记录**不会**把加过的额度收回来（那要走「改限额」）。这个副作用必须写进确认文案，见 §7.3。 |

### 2.7 三封邮件的措辞：**照抄用户原话，即使不一致**

| 邮件 | 主题 | 正文 |
|---|---|---|
| 注册申请（Spec20，本次改） | `ACN-<账号>-<邮箱/电话>` | `微信充值账号是<昵称>，注册时间是<北京时间>，请立即审批！` |
| 主动充值 | `ACN充值-<账号>-<邮箱/电话>` | `微信充值账号是<昵称>，申请时间是<北京时间>，请立即审批` |
| 欠费充值 | `ACN欠费充值-<账号>-<邮箱/电话>` | `微信充值账号是<昵称>，申请时间是<北京时间>，请立即审批` |

| 决策 | 选择 | 理由 |
|---|---|---|
| 注册那封的时间措辞 | **保留「注册时间是」**（已确认） | 用户只要求"前面加一句"。改一个没被要求的词，会让 Spec20 的验收用例与邮件历史对不上。 |
| 充值两封要不要 `！` | **不要** | 用户原话两次都是「请立即审批」，没有感叹号。**照抄**。 |
| 三种措辞不一致要紧吗 | 不要紧 | 正文只有一句话，收件人是你自己。**为"统一句式"去改用户逐字给的文案，是拿你的审美覆盖他的需求。** |
| `<邮箱/电话>` 取哪个 | 邮箱优先，没有才电话，都没有 → `未填写` | 与 Spec20 §2.3 同一口径（邮箱在邮件客户端里可点击、可复制）。`未填写` 是纯防御：管理员手工建的号两个都没有（§2.1）。 |
| 从哪取 | 库里的 `users.phone` / `users.email` | 与注册链路不同，这里**必须回读库**：登录态里只有 id/username/is_admin（`main.py:374`），联系方式不在其中。 |

### 2.8 阈值改成 `limit + 1`

| 决策 | 选择 | 理由 |
|---|---|---|
| 判据写成什么 | `user["used"] > user["quota_limit"]` | 整数下与 `>= limit + 1` 完全等价，但**少一次加法、也不会有人把 `+1` 写在括号外**。 |
| 用户体验上到底变了什么 | 限额 25 的用户能做完**第 26 次**调用 | 原口径下第 25 次调用**一成功就被踢**，用户看不到那次的结果——而这次的钱已经花了（`record_call` 在任务成功后才计 +1，所以账没算错，是**结果没拿到**）。改完阈值后，用户总能看满自己付过的每一次。 |
| 为什么不是别的大数字 | 只放宽 1 | 用户要的就是"把最后那一次用完"。放宽 2 或更多等于白送次数，与"预充值"模型矛盾。 |
| 有哪几处副本 | **4 处**（见 §5.7） | Spec18 那套判据在本仓有 4 个副本：中间件、登录路由、`AdminPanel.vue` 的 `isOverQuota`、`admin_list_users` 的 docstring。**改漏一处就会出现"管理端标着已超额、用户却还能用"**——CLAUDE.md 已经为这类同值副本记过一次教训（`COMMENT_TEXT_MAX`、`GALLERY_NOTE_MAX`）。 |
| 已经欠费的存量用户会怎样 | **会被多放一次** | 一个 `used == limit + 1` 的用户升级后仍然被锁（判据没变），但一个 `used == limit` 的用户从"被锁"变成"还能用一次"。这正是本次要的效果。 |

### 2.9 余额：后端算，且**照用户给的公式**

| 决策 | 选择 | 理由 |
|---|---|---|
| 公式 | `余额 = (quota_limit − used) / 10`（元），保留 1 位小数 | 用户原话：「（该用户调用次数限额-已使用次数）/10\*1元」。 |
| 谁算 | **后端**（`GET /api/recharge/info`） | 前端**根本拿不到** `quota_limit` / `used`（`/api/auth/me` 只返回 username/is_admin），而且与"文案唯一来源在后端"是同一条原则（Spec18 的 `QUOTA_EXCEEDED_MESSAGE`）。 |
| 精度 | `round(..., 1)` | 除以 10 只会产生 1 位小数，但浮点会给 `2.2000000000000002`。 |
| 负数怎么办 | **照原样显示** | 超额的用户余额是 `−0.1`，这是**正确的**（他欠你 1 次）。抹成 0 是撒谎。 |
| 余额与参考价的口径不一致 | **照用户公式，不改** | 余额按 **1 元 = 10 次** 的名义价算，而参考价是 **0.9 元 ≈ 10 次**。所以余额会**略高于实付**（新用户限额 25 → 余额 2.5 元，而他实际付了约 2.25 元）。这是用户明确给定的公式，**已当面确认知悉**；真要改只需改 §6.1 里 `balance` 那一行的除数与 §8.1 的文案。 |
| 管理员看得到吗 | **不显示按钮** | 用户原话是"普通用户的顶部"。管理员 `used`/`quota_limit` 照常累计（Spec18 §5.1a）但**不参与判定**，给他显示一个无业务含义的余额是误导。前端 `v-if="!auth.isAdmin"`；**后端照常返回**（不额外拦）——少一个分支，也少一个"接口和按钮不一致"的坑。 |
| 要不要顺便显示剩余次数 | **不显示** | 用户只要了余额。`quota_limit` / `used` 仍照常返回（排障与将来都用得上），但 UI 不画。 |

### 2.10 欠费面板的数据来源：复用 `GET /api/auth/register-config`

| 决策 | 选择 | 理由 |
|---|---|---|
| 收款码地址从哪来 | `getRegisterConfig().qr_url` | 它是**公开**接口（在 `PUBLIC_AUTH_PATHS` 里），且**永远返回 200**——即使 `REGISTER_ENABLED=false`（Spec19 §6.1 的 docstring 明说了"前端要读 contact_email，所以永远 200"）。超额用户此刻没有 token，正好能调。 |
| 为什么不写死 `/api/auth/payment-qr` | 不写死 | 那个地址是**相对的**，而 `register-config` 用 `_public_base(request)` 拼的是**绝对**地址。前端独立部署（`VITE_API_BASE` 指向远端后端）时，写死的相对路径会请求到前端自己的域名上——一张裂图。Spec19 §6.1 已经为这个坑写过一次。 |
| 为什么不新加一个公开的 `GET /api/auth/recharge-config` | 不加 | 它要返回的东西（`qr_url` + 一句参考价）**`register-config` 全都已经有了**。加一条公开路由就多一个要维护、要考虑限流、要在 §6 里占一行的东西——而收益是零。Spec19 的注册页与本 Spec 的欠费面板，本来就是同一个"还没进门的人"要看的同一个二维码。 |
| 参考价要不要也用它那句 | **要** | 见 §7.3 的说明：两句话的价格口径一致、句式不同，而 `register-config` 那句（「请先预充值，0.9 元起充，…」）在被锁门的场景里更贴切。 |

---

## 3. 需求边界

### 3.1 范围内

**后端**

- **新增** `Server/timefmt.py`：`beijing_time_text()`（§5.2）。
- `Server/mailer.py`：改成从 `timefmt` 导入；`send_register_notification()` 加 `wechat` 参数；**新增** `send_recharge_notification()`（§5.5）。
- `Server/db.py`：users DDL 加两列 + `_migrate_users_contact()`（含回填）；`create_user()` / `approve_register_request()` 写入联系方式；`_row_to_dict()` 带出联系方式；`recharge_requests` 建表 + 索引 + 8 个函数（§5.1、§5.3、§5.4）。
- `Server/config.py`：改 `REGISTER_PRICE_NOTICE`；新增 3 个变量（§8.1）。
- `Server/schemas.py`：3 个新请求体（§6.4）。
- `Server/errors.py`：3 个新码（§9）。
- `Server/main.py`：**阈值两处**（§5.7）+ **7 条新路由**（§6）+ 三个管理端列表加 `created_at_beijing` + `register_request()` 的 `add_task` 多传 `wechat`。
- `Server/.env.example`：一段占位。

**前端**

- **新增** `frontend/src/views/RechargeModal.vue`（两种模式共用，§7.3/§7.4）。
- `App.vue`：顶部按钮 + 挂载弹窗 + `artcn:quota_exceeded` 监听里补一行账号。
- `AdminPanel.vue`：联系方式列、北京时间、`isOverQuota` 阈值、注册申请行的时间、**新增「待审批充值记录」块**、顶部 tip 行加待办数。
- `Login.vue`：欠费时自动弹充值面板。
- `HelpModal.vue`：文案。
- `GalleryPanel.vue`：提示语一个 `v-if`。
- `api/chatApi.js`：7 个新函数。
- `utils/quotaNotice.js`：多带一个 username。

**文档**：`specs/Spec21.md`（本文）、`CLAUDE.md`。

### 3.2 不在范围内（明确不做）

| 不做的事 | 为什么不 |
|---|---|
| **不接在线支付** | 没有商户号、没有回调、没有对账——那是一个独立项目。本 Spec 的模型仍是「转账 + 人工核验 + 人工批准」，只是把它**结构化**了。 |
| **不做用户侧"充值记录"查询** | 用户要知道进度，问你就行（弹窗里那句「等待管理员审批」已经管理了预期）。加一个 `GET /api/recharge/my` 就要加一个列表 UI、一个空态、一个分页口径——为一个"最多几条"的列表不值得。 |
| **不在充值弹窗里显示剩余次数** | §2.9。用户只要了余额。 |
| **不给管理员显示余额按钮** | §2.9。 |
| **不做余额自动扣减 / 按次计费** | 余额是**展示用的派生值**，不是账本。真正的账本是 `user_quota.used`（只增不减，Spec18 §2.2）。别把它变成一个能被扣的字段。 |
| **不做充值审批的 CSV 导出 / 统计** | Spec11 的统计页不碰。台账在管理端页面上看得见就够了。 |
| **不做邮件里的链接** | Spec20 §14.2 的理由原样成立：管理端是 SPA 内的一个视图状态，没有可直接跳转的 URL。 |
| **不动 `register_requests` 的任何一格** | §1.3。本 Spec 只在迁移时**读**它一次。 |
| **不动注册表单 / 校验 / 冷却 / 四条注册路由** | 唯一的变化是 `add_task` 多传一个参数（§5.5）。 |
| **不动 Spec18 的 `usage` / `user_quota` 双写** | `record_call` 一个字不改。 |
| **不做「撤销已批准的充值」** | 批错了走「改限额」（`PUT /api/admin/users/{id}/quota`）——那条路已经存在，且是**幂等的绝对值设置**，比"反向加负数"安全得多。 |

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **零配置 = 只有邮件不发。** 不设 `SMTP_PASSWORD` 时，本 Spec 的邮件部分完全静默（每次充值多一条 `notify.recharge_mail_skipped` 日志），**充值接口、台账、管理端三按钮全部照常工作**。这与 Spec20 §3.3-1 是同一条性质。
2. **欠费充值端点是公开的。** 它要求「账号存在 + 确实已超额」，所以能被刷的上限 = 你的欠费账号数（§2.4）。**它不校验密码**——任何人知道一个欠费账号的用户名，就能替它提交一条充值申请。后果是什么？**只是你收件箱里多一封邮件、台账里多一条待审批记录**，你点「拒绝」即可。它**不能**给任何人加额度（加额度只发生在你点「同意」的那一刻）。这个上限是可接受的。
3. **充值不会自动解封。** 用户提交 ≠ 到账 ≠ 能用。必须等你点「同意」。用户点完「我已完成充值」之后**仍然登不进去**，这是**正确**的——弹窗里那句「已提交，等待管理员审批」就是这个意思。
4. **余额是名义价，不是实收。** 见 §2.9。
5. **`get_recharge_info` 对管理员照常返回数字**（前端不画入口）。若将来给管理员也画上按钮，那个数字没有业务含义。
6. **邮箱/电话可能为空。** 管理员手工建的号 → 用户表显示「无」、充值邮件主题里是 `未填写`（§2.7）。**这是允许的形态**，不是 bug。
7. **存量回填只覆盖"用户名唯一匹配到一条已通过申请"的用户。** 用户被删后重建同名账号，回填会在新账号上填出**前一个人的**联系方式——本 Spec 无法区分（那是同名的两个人）。概率极低，且管理员在用户表上看得见（显示的是"无"还是"某个陌生邮箱"），发现即用「改限额」旁边那条路手工纠正。**已记录，不修。**
8. **并发同意仍然由 rowcount 兜底。** 两个管理员同时点「同意」，后到的那个拿到 `40904`（该记录已处理），**额度只加一次**。

---

## 4. 技术栈增量

| 项 | 增量 |
|---|---|
| 新依赖（`requirements.txt`） | **0** —— `sqlite3` / `smtplib` / `datetime` 全是标准库 |
| 新 provider / 新模型 / 新上游 API | **0** |
| 新数据库 | 0（仍是 `Server/artcn.db`） |
| 新表 | **1**（`recharge_requests`） |
| 补列迁移 | **1 次**（users 加 `phone` / `email`，含回填） |
| 新持久目录 | **0** |
| 新错误码 | **3**（40019 / 40411 / 40904），另复用 40017 / 40402 |
| 新环境变量 | **3**（§8） |
| 新后端文件 | **1**（`timefmt.py`） |
| 新前端组件 | **1**（`RechargeModal.vue`） |

---

## 5. 架构设计（增量）

### 5.1 users 补两列 + 存量回填

**DDL**（`_CREATE_TABLE`，新库用）：

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    quota_limit   INTEGER NOT NULL DEFAULT {_QUOTA_DEFAULT},
    phone         TEXT,          -- Spec21：手机号（可空——管理员手工建的号没有）
    email         TEXT           -- Spec21：邮箱（同上）
)
```

**迁移**（`init_db` 里调用，位置见 §5.8）：

```python
def _migrate_users_contact(conn: sqlite3.Connection) -> None:
    """存量库补 users.phone / users.email（Spec21 §5.1），并把已开通用户的联系方式回填一次。

    两列**独立**判存在性，不共用一个 if：万一上一次跑了个半截（phone 加了、email 没加），
    共用一个判断会让 email 永远补不上。
    回填只在"确实补过列"的那次跑：库里的 register_requests 是唯一来源，
    它不会变（Spec19 的申请行只增不隐），所以回填天然一次性。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    added = False
    if "phone" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        added = True
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        added = True
    if not added:
        return
    # 只认 approved：被拒绝的申请里的联系方式不属于任何账号（§2.1）
    conn.execute(
        "UPDATE users SET "
        "  phone = (SELECT r.phone FROM register_requests r "
        "           WHERE r.username = users.username AND r.status = 'approved' "
        "           ORDER BY r.id DESC LIMIT 1), "
        "  email = (SELECT r.email FROM register_requests r "
        "           WHERE r.username = users.username AND r.status = 'approved' "
        "           ORDER BY r.id DESC LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM register_requests r "
        "              WHERE r.username = users.username AND r.status = 'approved')"
    )
    logger.info("users.phone / users.email 列已补齐并回填", extra={"event": "db.migrate"})
```

> ⚠️ **位置约束（本 Spec 第一处）**：这个函数**必须排在 `_CREATE_REGISTER_REQUESTS_TABLE` 之后**——回填要读 `register_requests`。放在 `init_db` 里 `conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)` 那两行之后、`_migrate_images_wiki_used` 之前。
> `ORDER BY r.id DESC LIMIT 1` 是**纯防御**：`users.username` 有 UNIQUE，所以同一个用户名最多只会有一条 approved 申请（第二条会在建号时撞 40001）。写明它只是为了让"取哪一条"有一个确定的答案。

**写入路径两处**：

```python
def create_user(username, password_hash, is_admin=False, phone=None, email=None) -> dict:
    # INSERT INTO users (username, password_hash, is_admin, created_at, phone, email)
    # VALUES (?, ?, ?, ?, ?, ?)
```
- `POST /api/admin/users`（手工建号）→ **不传** phone/email → NULL → 前端显示「无」。
- `db.approve_register_request()` 的 INSERT 补两列，值直接取申请行：`req["phone"]` / `req["email"]`（`get_register_request(..., with_secret=True)` 已经把它们带出来了）。

**读出路径一处**：`_row_to_dict()` 加两个键：

```python
        "quota_limit": int(row["quota_limit"]),
        "used": int(row["used"]),
        "phone": row["phone"],        # Spec21：可能为 None
        "email": row["email"],        # Spec21：可能为 None
```

> ⚠️ **PII 检查（实现时逐条核对）**：`_row_to_dict` 的返回值会流向 5 个地方，其中**只有第 1 个是接口响应**，其余都是路由内部取字段后**手写**一个小 dict 返回：
> 1. `db.list_users()` → `GET /api/admin/users`（**仅管理员**，正是我们要的）✅
> 2. `db.get_user_by_id()` → 中间件只取 id/username/is_admin 放进 `request.state.user`；`admin_delete_user` 只取 username ✅
> 3. `db.get_user_by_username()` → 登录路由只取 password_hash/is_admin/used/quota_limit ✅
> 4. `db.set_user_quota()` → `admin_set_quota` 手写 `{id, quota_limit, used}` ✅
> 5. `db.approve_register_request()` → `admin_approve_register` 手写 `{id, username, is_admin, quota_limit}` ✅
>
> **结论：`phone` / `email` 只会从 `GET /api/admin/users` 出去。** 实现完成后要 `grep -n "_row_to_dict\|list_users\|get_user_by_id" main.py` 逐个确认没有哪条路由把整个 dict 直接 `_ok(...)` 了。

### 5.2 `Server/timefmt.py`（新增）

**把 Spec20 §5.1 的 `beijing_time_text` 原样搬过来**，一个字不改：

```python
"""UTC ISO ↔ 北京时间展示串（Spec21 §5.2，Spec20 §2.2 的实现搬家）。

唯一职责：把库里存的 UTC ISO 串转成给人看的北京时间。
搬出 mailer.py 的原因：Spec21 之后 main.py 的三个管理端列表也要用它
（Spec21 §2.2），而一个叫 mailer 的模块不该拥有通用的时间格式化。
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("timefmt")

# 中国全境单一时区、无夏令时，所以固定 +08:00 偏移是**正确**的，不只是权宜。
# 刻意不用 zoneinfo("Asia/Shanghai")：Windows 没有系统 tz 数据库，
# 未安装 tzdata 包时 ZoneInfo 会抛 ZoneInfoNotFoundError，而部署机正是 Windows。
_BEIJING = timezone(timedelta(hours=8))


def beijing_time_text(created_at_iso: str) -> str:
    """库里的 UTC ISO 串（2026-09-19T07:33:12.451Z）→ '2026-09-19 15:33:12'。

    解析失败时**原样返回**：宁可显示得难懂，也不让调用方（发信 / 列表接口）出错。
    """
    try:
        dt = datetime.strptime(created_at_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, TypeError):
        return str(created_at_iso)
    return dt.replace(tzinfo=timezone.utc).astimezone(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")
```

`mailer.py` 顶部改成 `from timefmt import beijing_time_text`（**`mailer.beijing_time_text` 依然可调用**，Spec20 §13 的验收命令逐字照旧）。`mailer.py` 里 `_BEIJING` 与那个函数的定义**整体删除**（避免两份实现）。

三个管理端列表各加一个字段（`main.py`）：

```python
@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """...（docstring 里的判据同步改成 `u.used > u.quota_limit`，§5.7）"""
    items = db.list_users()
    for u in items:
        u["created_at_beijing"] = timefmt.beijing_time_text(u["created_at"])
    return _ok(items)
```

- `GET /api/admin/register-requests` 同样处理（`r["created_at_beijing"]`）。
- `GET /api/admin/recharge-requests` 在建路由时一并算（**两个**：`created_at_beijing` 与 `reviewed_at_beijing`——`reviewed_at` 可能为 `None`，此时**不加这个键**，前端 `v-if` 判空）。

**为什么不覆盖 `created_at`**：它是 UTC ISO，排序、排障、将来别的消费者都用得上（§2.2）。展示串是**多出来的一个键**。

### 5.3 `recharge_requests` 表

```python
# 充值台账（Spec21 §5.3）：一行 = 一条待处理/已处理的充值申请。
# 「台账」语义与 Spec19 的 register_requests 完全相同：同意/拒绝都保留记录（status），
# 只有「删除」才真删行（§2.3）。刻意**没有** UNIQUE(user_id, status)——
# 被拒绝之后必须能再申请，唯一性靠 status='pending' 的幂等查询兜（§2.4）。
# 刻意**没有** ip 列：防刷靠幂等而不是冷却，于是本表不含任何多余 PII（§2.3）。
_CREATE_RECHARGE_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS recharge_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,             -- 加额度的目标（users.id）
    username    TEXT NOT NULL,                -- 提交时刻的账号名快照（台账要能脱离 users 读）
    wechat      TEXT NOT NULL,                -- 充值用的微信昵称（唯一的对账键）
    source      TEXT NOT NULL DEFAULT 'user', -- 'user'（系统内主动充值）| 'overdue'（欠费被拦时提交）
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    amount      INTEGER,                      -- 同意时管理员填的加次数（NULL = 尚未处理）
    created_at  TEXT NOT NULL,                -- 提交时刻（UTC ISO）
    reviewed_at TEXT                          -- 同意/拒绝的时刻（NULL = 尚未处理）
)
"""

# 幂等查询走这条：WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1
_CREATE_RECHARGE_REQUESTS_USER_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_recharge_requests_user "
    "ON recharge_requests(user_id, status, id DESC)"
)

# 列表查询走这条：pending 优先 + 组内 id 倒序（与 Spec19 §6.4 同款）
_CREATE_RECHARGE_REQUESTS_STATUS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_recharge_requests_status "
    "ON recharge_requests(status, id DESC)"
)

# 来源 / 状态白名单（校验用，不拼接外部输入）
_RECHARGE_SOURCES = ("user", "overdue")
_RECHARGE_STATUSES = ("pending", "approved", "rejected")
```

### 5.4 `db.py` 新增的 8 个函数

```python
def _recharge_row_to_dict(row) -> dict | None:
    """充值行 → dict。**不带出 ip**（本表根本没有这一列，§2.3）。"""
    # id / user_id / username / wechat / source / status / amount / created_at / reviewed_at

def create_recharge_request(user_id: int, username: str, wechat: str, source: str) -> dict:
    """落一条充值申请。source 必须已在路由层过白名单（本函数不判）。"""

def find_pending_recharge(user_id: int) -> dict | None:
    """该用户是否已有一条待审批的充值申请（幂等判据，§2.4）。"""

def get_recharge_request(request_id: int) -> dict | None:
    """取一条（路由预检用）。**没有 with_secret**——本表没有密码。"""

def list_recharge_requests() -> list[dict]:
    """台账列表：pending 优先，组内 id 倒序。
    ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, id DESC
    （与 Spec19 的 list_register_requests 同款写法）。"""

def approve_recharge_request(request_id: int, amount: int) -> dict | None:
    """同意：**单事务**内 置 approved + 记 amount + users.quota_limit += amount。
    返回加完额度后的用户 dict；该行已不是 pending（并发抢跑）时返回 None（调用方转 40904）。

    为什么必须一个事务：先改状态再单独加额度，中间会开出"记录已批准，但额度没到账"
    的窗口——用户拿着批准记录来找你，而系统显示他没充过。这与 Spec19 §5.2B
    「建号 + 改状态必须同生同死」是同一类错误。

    **不动 user_quota.used**：它是历史事实（Spec18 §2.2），充值改变的是"还能用多少次"。

    并发判据用 `WHERE ... AND status='pending'` 的 rowcount，而不是"先查后写"：
    两个管理员同时点同意时，后到的那个 UPDATE 影响 0 行 → rollback，额度只加一次。
    ⚠️ UPDATE recharge 必须排在 UPDATE users **之前**：rowcount 是回滚的判据，
    而回滚要能撤销已经发生的加额度。
    """
    req = get_recharge_request(request_id)
    if req is None:
        return None
    now = _now_iso()
    with _connect() as conn:
        marked = conn.execute(
            "UPDATE recharge_requests SET status = 'approved', reviewed_at = ?, amount = ? "
            "WHERE id = ? AND status = 'pending'",
            (now, amount, request_id),
        )
        if marked.rowcount == 0:
            conn.rollback()
            return None
        credited = conn.execute(
            "UPDATE users SET quota_limit = quota_limit + ? WHERE id = ?",
            (amount, req["user_id"]),
        )
        # 第二道 rowcount 检查。正常路径下**到不了这里**：delete_user 会在同一个事务里
        # 删掉该用户的 recharge_requests 行（§2.6），所以"用户没了但充值行还在"这个
        # 状态不存在——那时上面的 marked.rowcount 已经是 0。留着它是为了万一将来
        # 有人改了 delete_user 的级联清单：宁可这次点不动（40904），也绝不能留下
        # 一条"记录已批准、额度没到账"的挂账（§2.5）。
        if credited.rowcount == 0:
            conn.rollback()
            return None
        conn.commit()
    return get_user_by_id(req["user_id"])

def reject_recharge_request(request_id: int) -> dict | None:
    """拒绝：只改状态。该行已不是 pending 时返回 None。**不加额度、不删记录**。"""

def delete_recharge_request(request_id: int) -> bool:
    """删掉一条充值记录（任意状态）。**不触碰 users**（§2.6）。"""
```

**`delete_user()` 补一行**（放在 `DELETE FROM user_quota` 那一组里，§2.6）：

```python
        conn.execute("DELETE FROM recharge_requests WHERE user_id = ?", (user_id,))
```

### 5.5 `mailer.py`：改一处 + 加一个函数

```python
from timefmt import beijing_time_text          # ← 定义已搬走（§5.2）
# （删掉本文件里的 _BEIJING 与 beijing_time_text 定义）


def send_register_notification(username: str, contact: str, wechat: str,
                               created_at_iso: str) -> None:
    """（Spec20 原样，只多一个 wechat 参数与正文前缀——§2.7）

    ⚠️ 本函数必须保持为**同步 def**。改成 async def 会让 Starlette 在事件循环里
    直接 await 它，smtplib 的阻塞 IO 会卡死整个循环（Spec20 §2.1）。
    """
    ...
    msg["Subject"] = f"ACN-{username}-{contact}"
    msg.set_content(
        f"微信充值账号是{wechat}，注册时间是{beijing_time_text(created_at_iso)}，请立即审批！"
    )
    ...


def send_recharge_notification(username: str, contact: str, wechat: str,
                               created_at_iso: str, overdue: bool) -> None:
    """发一封"有人提交了充值申请"的提醒（Spec21 §5.5）。**同步阻塞**，调用方丢线程池。

    overdue=True  → 主题 ACN欠费充值-<账号>-<联系方式>（登录页那条路）
    overdue=False → 主题 ACN充值-<账号>-<联系方式>

    四种结局，全部静默（与 Spec20 §2.4 逐字同款）：
      未配置 SMTP_PASSWORD → warning 日志，直接返回
      发送成功             → info 日志
      发送失败             → warning 日志（异常被吞掉，绝不冒泡到充值请求上）

    ⚠️ 与 send_register_notification 一样必须保持为**同步 def**（理由同上）。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("充值通知未发送：SMTP 未配置", extra={
            "event": "notify.recharge_mail_skipped",
            "reason": "smtp_not_configured", "username": username,
        })
        return

    prefix = "ACN欠费充值" if overdue else "ACN充值"
    msg = EmailMessage()
    msg["Subject"] = f"{prefix}-{username}-{contact}"
    msg["From"] = formataddr((_FROM_NAME, config.SMTP_USER))
    msg["To"] = config.RECHARGE_NOTIFY_TO
    # 正文照抄用户原话：没有感叹号（§2.7）
    msg.set_content(
        f"微信充值账号是{wechat}，申请时间是{beijing_time_text(created_at_iso)}，请立即审批"
    )
    try:
        with smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS
        ) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as exc:  # 故意吞掉一切（Spec20 §2.4）
        logger.warning("充值通知发送失败", extra={
            "event": "notify.recharge_mail_failed",
            "username": username, "error": f"{type(exc).__name__}: {exc}",
        })
        return

    logger.info("充值通知已发送", extra={
        "event": "notify.recharge_mail_sent",
        "username": username, "to": config.RECHARGE_NOTIFY_TO,
    })
```

**`main.py` 里注册链路的唯一改动**（`register_request()`，Spec20 那行 `add_task`）：

```python
    background_tasks.add_task(
        mailer.send_register_notification,
        username,
        email or phone or "未填写",
        wechat,                      # ← Spec21 新增：正文前缀（§2.7）
        record["created_at"],
    )
```

### 5.6 关键数据流

```
① 系统内主动充值（普通用户点顶部「余额与充值」）
   GET /api/recharge/info        → {balance, quota_limit, used, qr_url, price_notice}
   用户扫码转账 → 填微信昵称 → 点「我已完成充值」
   POST /api/recharge/requests   {wechat}
     │
     ├─ 白名单/长度校验（40019）
     ├─ ★ 幂等：db.find_pending_recharge(user_id) 命中 → 直接返回 200 {id: 那条的 id}
     │                                            （不落库、不发信，§2.4）
     ├─ user = db.get_user_by_id(request.state.user["id"])   ← 回读库拿 phone/email（§2.7）
     ├─ record = db.create_recharge_request(user_id, user["username"], wechat, "user")
     │     logger.info("recharge.submitted")
     ├─ background_tasks.add_task(mailer.send_recharge_notification,
     │       user["username"], user["email"] or user["phone"] or "未填写",
     │       wechat, record["created_at"], False)     ← 在 return 之前注册
     └─ return _ok({"id": record["id"]})              ← 立刻返回，不等 SMTP

② 欠费充值（被锁的用户在登录页）
   POST /api/auth/login → 40304（§5.7 的新阈值）→ 前端清 token 回登录页
   → Login.vue 弹 RechargeModal(mode="overdue")：账号（预填）+ 微信昵称 + 收款码
   POST /api/auth/recharge-request  {username, wechat}      ← 公开，无 token
     │
     ├─ 白名单/长度校验（40019）
     ├─ user = db.get_user_by_username(username)
     │     不存在 → 40019「账号不存在」
     │     is_admin 或 used <= quota_limit → 40904「当前账号无需充值」
     ├─ ★ 幂等（同上）
     ├─ record = db.create_recharge_request(user["id"], user["username"], wechat, "overdue")
     ├─ add_task(mailer.send_recharge_notification, ..., overdue=True)
     └─ return _ok({"id": record["id"]})

③ 管理员审批（用户管理页「待审批充值记录」块）
   GET  /api/admin/recharge-requests                → pending 优先的台账
   同意 → window.prompt 填次数 n（≥1 的整数）
        → POST /api/admin/recharge-requests/{id}/approve  {amount: n}
          ├─ 40017 若 n < 1 或 目标用户当前限额 + n > QUOTA_LIMIT_MAX
          ├─ 40411 若记录不存在 ／ 40402 若目标用户已被删除（§2.5）
          ├─ 40904 若该记录已不是 pending
          └─ db.approve_recharge_request（单事务：置 approved + 记 amount + 加额度）
   拒绝 → POST .../reject  → 只改状态
   删除 → DELETE .../{id}  → 真删行（不动 users、不收回额度）
```

### 5.7 阈值：`>= limit` → `> limit`（**四处副本，一处都不能漏**）

| # | 文件:行 | 现在 | 改成 |
|---|---|---|---|
| 1 | `main.py:384`（鉴权中间件） | `user["used"] >= user["quota_limit"]` | `user["used"] > user["quota_limit"]` |
| 2 | `main.py:1060`（登录路由） | `user["used"] >= user["quota_limit"]` | `user["used"] > user["quota_limit"]` |
| 3 | `AdminPanel.vue:238`（`isOverQuota`） | `u.used >= u.quota_limit` | `u.used > u.quota_limit` |
| 4 | `main.py:1224`（`admin_list_users` 的 docstring） | 「前端用 `!u.is_admin && u.used >= u.quota_limit` 现算」 | 同上改成 `>`，并把「为什么是 `>`」写进注释 |

**三处代码 + 一处文档**。第 3 处漏改的后果最明显：管理端会给一个还能用的用户打上「已超额」红标。第 1、2 处漏改任意一处，就会出现"能登录但一进去就被踢"或反之。

**欠费充值端点的"确实已超额"判据也用同一个 `user["used"] > user["quota_limit"]`**（§6.3）——它是第 5 处使用，但不在"改动既有副本"的清单里（那是新增代码）。

### 5.8 `init_db` 的调用位置（§5.1 那条位置约束的落点）

```python
        conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)
        conn.execute(_CREATE_REGISTER_REQUESTS_IP_INDEX)
        conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)
        # Spec21 §5.3：充值台账。与 register_requests 同类——全新空表，
        # CREATE TABLE IF NOT EXISTS 对新库/存量库行为一致，不需要迁移函数。
        conn.execute(_CREATE_RECHARGE_REQUESTS_TABLE)
        conn.execute(_CREATE_RECHARGE_REQUESTS_USER_INDEX)
        conn.execute(_CREATE_RECHARGE_REQUESTS_STATUS_INDEX)
        # Spec21 §5.1：users 补 phone/email 并回填。
        # ⚠️ 位置约束：必须排在 _CREATE_REGISTER_REQUESTS_TABLE **之后**（回填要读它）。
        _migrate_users_contact(conn)
        # Spec10：建议状态收敛…
        conn.execute("UPDATE suggestions SET status = 'pending' WHERE status = 'read'")
```

---

## 6. 接口约定

全部响应仍是 `{code, message, data}`。新增 7 条路由。

### 6.1 `GET /api/recharge/info`（需登录）

```json
{"code":200,"message":"ok","data":{
  "balance": 2.2,
  "quota_limit": 25,
  "used": 3,
  "qr_url": "http://host/api/auth/payment-qr",
  "price_notice": "充值参考：0.9元约10次设计服务"
}}
```

- `balance = round((quota_limit − used) / 10, 1)`，**可为负**（§2.9）。
- `qr_url` 用 `_public_base(request)` 拼**绝对地址**（与 `GET /api/auth/register-config` 完全同款），前端直接塞进 `<img src>`，不做任何拼接。
- `price_notice` 来自 `config.RECHARGE_PRICE_NOTICE`，**前端零副本**。
- **管理员也照常返回**（前端不画入口，§2.9）。
- 收款码文件缺失时**本接口不报错**（它只返回 URL；`<img>` 裂图由 `payment_qr` 的 40410 决定，与 Spec19 §5.3 同款行为）。

### 6.2 `POST /api/recharge/requests`（需登录）

请求体 `{"wechat": "微信昵称"}` → `{"code":200,"data":{"id": 7}}`

- 身份取自 token（`request.state.user["id"]`），**不接受客户端传 username**。
- `source` 恒为 `"user"`。
- 幂等：命中 pending 时返回**那条的 id**，不落新行、不发信（§2.4）。
- 校验：`wechat` strip 后非空且 ≤ `RECHARGE_WECHAT_MAX`，否则 40019。

### 6.3 `POST /api/auth/recharge-request`（**公开**）

请求体 `{"username": "...", "wechat": "..."}` → `{"code":200,"data":{"id": 7}}`

- **进 `PUBLIC_AUTH_PATHS`（4 → 5 条）**：用户此时被 40304 拦住，手里没有 token。收款码本身已是公开的（Spec19 §3.3-6），这条路由的暴露面与它同级——它**只能产生一条待审批记录**，不能给任何人加额度（§3.3-2）。
- `source` 恒为 `"overdue"`。
- 校验顺序（顺序即契约，与 Spec19 §6.2 同一个写法）：
  1. `username` strip 后非空 → 否则 40019「请填写账号」
  2. `wechat` 非空且 ≤ MAX → 否则 40019「请填写用于支付的微信昵称」
  3. `db.get_user_by_username(username)` 为 None → 40019「账号不存在」
  4. `user["is_admin"] or user["used"] <= user["quota_limit"]` → 40904「当前账号无需充值」
  5. 幂等（`find_pending_recharge`）→ 返回既有 id
  6. 落库 + `add_task` + `_ok({"id": ...})`
- **不校验密码**（已确认）。理由与代价见 §3.3-2。
- 日志里**不带 IP**（Spec19 §10 的规矩）。

### 6.4 `schemas.py` 新增

```python
# ---- 余额与充值（Spec21 §6.2~§6.5）----

class RechargeRequestCreate(BaseModel):
    """POST /api/recharge/requests 请求体（Spec21 §6.2）。
    长度/空值校验在路由层（40019），Pydantic 只负责"字段在不在"。"""
    wechat: str


class RechargeOverdueCreate(BaseModel):
    """POST /api/auth/recharge-request 请求体（Spec21 §6.3）。同上。"""
    username: str
    wechat: str


class RechargeApproveRequest(BaseModel):
    """POST /api/admin/recharge-requests/{id}/approve 请求体（Spec21 §6.5）。
    非整数由 Pydantic 拦下 → 40001；取值范围（≥1 且不超 QUOTA_LIMIT_MAX）在路由层判。"""
    amount: int
```

### 6.5 管理端三条（`/api/admin/*`，中间件保证仅管理员）

| 方法 | 路径 | 请求体 | 返回 |
|---|---|---|---|
| `GET` | `/api/admin/recharge-requests` | — | `[{id, user_id, username, wechat, source, status, amount, created_at, created_at_beijing, reviewed_at, reviewed_at_beijing?}]` |
| `POST` | `/api/admin/recharge-requests/{id}/approve` | `{amount}` | `{id, username, quota_limit, used}` |
| `POST` | `/api/admin/recharge-requests/{id}/reject` | — | `{id}` |
| `DELETE` | `/api/admin/recharge-requests/{id}` | — | `{id}` |

- `reviewed_at` 为 `None` 时**不加** `reviewed_at_beijing` 这个键（前端 `v-if` 判空）。
- `approve` 的校验顺序：
  1. `amount < 1` → 40017（消息见 §9）
  2. 记录不存在 → 40411
  3. 记录已不是 pending → 40904
  4. 目标用户不存在（被删过）→ 40402「用户已被删除，无法充值」
  5. 目标用户当前 `quota_limit + amount > QUOTA_LIMIT_MAX` → 40017
  6. `db.approve_recharge_request()` 返回 None（并发抢跑）→ 40904
- `reject` 不校验任何东西，只把 pending → rejected。
- `DELETE` **不触碰 users**（§2.6）。

### 6.6 不变

`POST /api/chat`、`/api/images`、`/api/tasks/{id}`、`/api/gallery/*`、`/api/community/*`、`/api/wiki/*`、`/api/shares/*`、`/api/suggestions/*`、`/api/conversations/*`、`/api/auth/login`、`/api/auth/me`、`/api/auth/register`、`/api/auth/register-config`、`/api/auth/payment-qr`、`/api/admin/users`（**响应多两个键，契约不变**）、`/api/admin/register-requests/*`、`/api/admin/stats` —— **全部一字不动**（除 §6.1 明说的两个新增键）。

---

## 7. 前端交互

### 7.1 `App.vue`：顶部按钮（仅普通用户）

在「帮助」按钮**之前**插一个，与其它 header 按钮同排：

```html
<button v-if="!auth.isAdmin" class="btn-clear" @click="showRecharge = true">余额与充值</button>
```

弹窗挂在 `HelpModal` 旁边（顶层，任何面板视图下都可用）：

```html
<RechargeModal v-if="showRecharge" @close="showRecharge = false" />
```

`artcn:quota_exceeded` 的监听里补一行（**必须在 `auth.logout()` 之前**，`username` 那时还在）：

```js
window.addEventListener('artcn:quota_exceeded', () => {
  setQuotaUsername(auth.username)   // ← Spec21：供登录页的欠费面板预填账号
  auth.logout()
  closeAllPanels()
})
```

### 7.2 `AdminPanel.vue`

1. **用户表加一列「联系方式」**（放在「角色」之后、「服务总调用次数」之前）：

```html
<td class="cell-contact">{{ contactText(u) }}</td>
```

```js
// Spec21 §7.2：邮箱与电话都显示（有哪个显示哪个），都没有 → 「无」。
// 顺序固定「邮箱 / 电话」——邮箱是邮件主题里优先取的那个（Spec21 §2.7）。
function contactText(u) {
  const parts = [u.email, u.phone].filter(Boolean)
  return parts.length ? parts.join(' / ') : '无'
}
```

2. **创建时间改北京时间**：`{{ u.created_at }}` → `{{ u.created_at_beijing }}`。注册申请行的 `{{ r.created_at }}` → `{{ r.created_at_beijing }}` 同样处理（**同一页两种时区比不改更糟**）。

3. **`isOverQuota` 阈值同步**（§5.7 第 3 处）：

```js
// Spec21 §5.7：判据与后端一致（used > quota_limit），管理员恒不超额。
// 注意是 `>` 不是 `>=`：限额用满（used == limit）还能再用一次（Spec21 §2.8）。
function isOverQuota(u) {
  return !u.is_admin && u.used > u.quota_limit
}
```

4. **顶部 tip 行**加待办数：

```html
· <b class="tip-pending">待审批注册申请 {{ pendingCount }} 条</b>
· <b class="tip-pending">待审批充值 {{ pendingRechargeCount }} 条</b>
```

5. **新增「待审批充值记录」块**（放在注册申请块**之后**，结构照抄它）：

```html
<section class="reg-admin">
  <h3 class="reg-admin-title">待审批充值记录</h3>
  <p v-if="recharges.length === 0" class="reg-admin-empty">暂无充值申请</p>

  <div v-for="c in recharges" :key="c.id" class="reg-row">
    <div class="reg-row-info">
      <span class="reg-row-user">{{ c.username }}</span>
      <span class="reg-row-cell">微信昵称：{{ c.wechat }}</span>
      <span class="reg-row-cell">{{ c.source === 'overdue' ? '欠费充值' : '主动充值' }}</span>
      <span v-if="c.amount !== null" class="reg-row-cell">加 {{ c.amount }} 次</span>
      <span class="reg-row-cell reg-row-time">{{ c.created_at_beijing }}</span>
    </div>
    <div class="reg-row-actions">
      <template v-if="c.status === 'pending'">
        <button class="btn-mini" :disabled="busyRechargeId === c.id" @click="approveRecharge(c)">同意</button>
        <button class="btn-mini" :disabled="busyRechargeId === c.id" @click="rejectRecharge(c)">拒绝</button>
      </template>
      <span v-else class="reg-row-done">{{ c.status === 'approved' ? '已同意' : '已拒绝' }}</span>
      <button class="btn-mini danger" :disabled="busyRechargeId === c.id" @click="removeRecharge(c)">删除</button>
    </div>
  </div>
</section>
```

```js
// 同意 = 弹框填次数（与「同意注册申请」逐字同款交互）。
// **不传第二个参数**（不给默认值）：次数该由管理员按实收金额决定，
// 写死任何数字都是复制一个会漂移的常量（与 Spec19 §7.5c 同款理由）。
async function approveRecharge(c) {
  const input = window.prompt(
    `同意「${c.username}」的充值申请，并填写加多少次服务额度：`
  )
  if (input === null) return
  const raw = input.trim()
  const n = Number(raw)
  // 同样的三个坑（Spec19 §7.5c）：raw 为空单独拦（Number('') === 0 是整数）；
  // Number.isInteger 而非 parseInt（'10abc' 会静默变 10）；上限交给后端 40017 报。
  // 下界是 1 不是 0：加 0 次是一次无意义的点击，几乎必然是手滑（Spec21 §2.5）。
  if (!raw || !Number.isInteger(n) || n < 1) {
    error.value = '充值次数需为不小于 1 的整数'
    return
  }
  ...
  await approveRechargeRequest(c.id, n)
  flash(`已为「${c.username}」充值 ${n} 次`)
  await loadRecharges()
  await load()          // 额度变了，用户表那一行也要刷新
}

async function removeRecharge(c) {
  // 确认文案必须点明"不收回额度"——删记录 ≠ 撤销充值（Spec21 §2.6）
  if (!window.confirm('确定删除这条充值记录？此操作不可撤销，且不会收回已加的服务额度。')) return
  ...
}
```

`onMounted` 里并行拉第三张表：`load(); loadRequests(); loadRecharges()`。

### 7.3 `RechargeModal.vue`（新组件，两种模式共用）

`props: { mode: 'user' | 'overdue' (默认 'user'), username: String (默认 '') }`

> **`mode="overdue"` 的数据从哪来**：它调**已有的** `getRegisterConfig()`（`GET /api/auth/register-config`，公开），拿 `qr_url` 与 `price_notice`。这样就**不需要**写死 `/api/auth/payment-qr` 这个路径、也不需要抄一份文案——而且 `register-config` 是**永远返回 200** 的（即使 `enabled=false`，Spec19 §6.1 的 docstring 明说了），超额用户拿得到。`getRegisterConfig` 已在 `chatApi.js` 里、`Login.vue`/`RegisterModal.vue` 都在用，直接复用。
>
> 两个模式显示的参考价**措辞不同**（「充值参考：…」/「请先预充值，0.9 元起充，参考价格：…」），这是**有意的**：前者出自需求 4 的原话，后者出自需求 6 的原话，而后者在"你已经被锁在门外"这个场景里正好是把"先充值"说清楚的那一句。两句话的**价格口径一致**（都是 0.9 元约 10 次），只是句式不同。想统一只需让其中一处改读另一个常量。

| 区块 | `mode="user"` | `mode="overdue"` |
|---|---|---|
| 余额行 | **显示**（来自 `GET /api/recharge/info`） | 不显示（拿不到） |
| 账号输入框 | 不显示 | **显示 + 必填**，`:value` 预填传入的 `username` |
| 收款码 | 显示（`GET /api/recharge/info` 的 `qr_url`） | 显示（`getRegisterConfig().qr_url`） |
| 参考价备注 | 显示 `RECHARGE_PRICE_NOTICE`（「充值参考：0.9元约10次设计服务」） | 显示 `getRegisterConfig().price_notice`（「请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务」） |
| 微信昵称 | **必填** | **必填** |
| 提交 | `POST /api/recharge/requests` | `POST /api/auth/recharge-request` |
| 成功后 | 整卡换成结果面板 | 同左 |

结构照抄 `RegisterModal.vue` 的 `done` 模式（提交成功 → 整卡换成结果面板，用户自己关，不自动关）：

```
标题「余额与充值」
当前余额 2.2 元              ← 数值由后端给，前端只拼「元」这个单位
[收款码 img，max-height 220px]
充值参考：0.9元约10次设计服务
[账号]（仅 overdue）
[充值用的微信昵称（以便核验）*]
[我已完成充值]
```

提交成功后的面板：`已提交，等待管理员审批。审批通过后服务次数会立即到账。`

- **零分支**：第一次提交与重复提交（幂等命中）显示同一句话（§2.4）。前端**不区分**。
- 收款码裂图（40410，部署时忘了放 `payment.jpg`）：与 Spec19 §7.3 同款——`<img>` 直接裂，不额外处理。用户可以照常提交申请，线下联系时再收款。
- `mode="overdue"` 且两个输入框都空时，按钮禁用/本地提示「请填写账号与微信昵称」（只拦必填，不复制长度规则——那些在后端 40019 有中文 message）。

### 7.4 `Login.vue`：欠费时自动弹充值面板

```js
const notice = takeQuotaNotice()          // 现在是 { message, username }（§7.7）
if (notice.message) {
  error.value = notice.message
  window.alert(notice.message)            // Spec18 §7.4 原样保留（用户要求"弹出提示警告"）
  overdraft.value = notice                // ← Spec21：额外把充值面板弹出来
}
```

```html
<!-- Spec21 §7.4：被强制退出 / 登录被拒时，二维码直接弹在登录页上 -->
<RechargeModal
  v-if="overdraft"
  mode="overdue"
  :username="overdraft.username"
  @close="overdraft = null"
/>
```

`window.alert` **与**面板**同时保留**——前者是 Spec18 §7.4 记录的"用户要求弹出提示警告"，后者是本 Spec 新加的动作入口。两个不冲突（alert 是阻断式的，点掉「确定」之后面板就在后面）。

### 7.5 `HelpModal.vue`：文案

「📊 服务次数」那一段，**两句删、一句换**：

```html
<p class="help-item-desc">
  每个用户预充值后会获得对应次数。次数用满后需要联系管理员续费才能继续使用。
</p>
```

- 删掉：「每个账号有一定的服务调用额度（默认 25 次，含对话、文生图、图文生图、图像 QA、风格归纳）。」→ 换成「每个用户预充值后会获得对应次数。」
- 删掉：「管理员不受额度限制。」
- **保留**中间那句「次数用满后需要联系管理员续费才能继续使用。」（用户没提它）。

> 已知的过时点：加完本 Spec 的「余额与充值」按钮后，用户其实可以**自助**提交充值申请。这句话仍然成立（最终确实要管理员点头），但少了"在哪儿点"。**留着不动**是刻意的——用户逐字给了替换文本，不该由实现者顺手改写（§2.7 同一条原则）。要改只需改这一行。

### 7.6 `GalleryPanel.vue`：提示语条件展示

```html
<!-- Spec21 §7.6：这句话是"分析中"的说明，与按钮上的「分析中…」同一个生命周期。
     常驻展示是噪音；分析结束（成功或失败）后它还留着就是死字。 -->
<p v-if="wikiBusy" class="wiki-hint">
  更新会逐张分析个人作品（之前已分析过则不会分析），请耐心等待
</p>
```

**只有这一个改动。** `refreshStyle()` 一个字不动（`wikiBusy` 由它自己置位与复位）。

### 7.7 `utils/quotaNotice.js`：多带一个 username

```js
// Spec21 §7.7：多带一个"是谁被锁了"。
// 为什么需要：auth.logout() 会清掉 store 里的 username，而登录页的欠费充值面板
// 要把账号预填进去。写入方仍是 2 处，但分工变了：
//   api/chatApi.js 的 40304 分支 → 只写 message（拦截器里拿不到 store）
//   App.vue 的 artcn:quota_exceeded 监听 → 补写 username（此刻 auth.username 还在）
// 读取方仍是 1 处：views/Login.vue 挂载时取走。
export const quotaNotice = ref('')
export const quotaUsername = ref('')

export function setQuotaNotice(message) { if (message) quotaNotice.value = message }
export function setQuotaUsername(name) { quotaUsername.value = name || '' }

// 返回值从 string 变成对象——**两处写入方、一处读取方**都要跟着改（§12 第 9 步）
export function takeQuotaNotice() {
  const payload = { message: quotaNotice.value, username: quotaUsername.value }
  quotaNotice.value = ''
  quotaUsername.value = ''
  return payload
}
```

> ⚠️ **这是本 Spec 唯一一处破坏性签名变更**（`takeQuotaNotice` 从返回 string 变成返回对象）。全仓只有 `Login.vue:68` 一个读取方，`store/auth.js` 与 `chatApi.js` 两个写入方——改完要 `grep -rn "quotaNotice\|takeQuotaNotice\|setQuotaNotice" frontend/src/` 确认没有第四处。

### 7.8 `api/chatApi.js`：7 个新函数

```js
// ---- 余额与充值（Spec21 §6）----
export async function getRechargeInfo()        // GET  /api/recharge/info
export async function submitRecharge(wechat)   // POST /api/recharge/requests {wechat}
export async function submitOverdueRecharge(username, wechat)
                                               // POST /api/auth/recharge-request
export async function listRechargeRequests()   // GET  /api/admin/recharge-requests
export async function approveRechargeRequest(id, amount)
                                               // POST /api/admin/recharge-requests/{id}/approve
export async function rejectRechargeRequest(id)
export async function deleteRechargeRequest(id)
```

**拦截器不用改**：`/api/auth/recharge-request` 是公开端点，它的失败码是 40019/40904，既不是 401 也不是 40304，不会误触发登出分支（与 Spec19 §6.8 对 40305 的处理同一个判断）。

---

## 8. 配置 / 环境变量

### 8.1 `config.py`

**改一行**（Spec19 注册块里）：

```python
REGISTER_PRICE_NOTICE = "请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务"
```

**新增一段**（追加在 **Spec20 段之后**、`# ===== 服务限额（Spec18）=====` 之前）：

```python
# ===== 余额与充值（Spec21）=====
# 本段必须排在 Spec19 注册块**之后**：RECHARGE_NOTIFY_TO 的默认值取 SUPPORT_EMAIL，
# 而 Python 是从上往下执行的（与本文件里前两段同一个理，Spec21 §8.1）。
#
# 充值弹窗里那句参考价（唯一来源，前端零副本——与 REGISTER_PRICE_NOTICE 同一原则）。
# 注意它与余额公式的口径**故意不同**：余额按 1 元 = 10 次的名义价算（用户给定，
# Spec21 §2.9），而这句说的是实收价（0.9 元约 10 次）。两者不一致是有意的，别"统一"。
RECHARGE_PRICE_NOTICE = "充值参考：0.9元约10次设计服务"

# 微信昵称的长度上限（前后端同值？**不是**——前端只拦必填，长度由后端 40019 报，
# 与 Spec19 对手机号/邮箱的处理同一个立场：规则只有一份中文 message，在后端）。
RECHARGE_WECHAT_MAX = int(os.getenv("RECHARGE_WECHAT_MAX", "64"))

# 充值提醒的收件人。默认跟随 SUPPORT_EMAIL，但**单独一个变量**：
# SUPPORT_EMAIL 是给用户看的客服邮箱，哪天换成对外公开邮箱，充值提醒不该跟着寄到别处
# （与 Spec20 的 REGISTER_NOTIFY_TO 同一个取舍）。
RECHARGE_NOTIFY_TO = os.getenv("RECHARGE_NOTIFY_TO", SUPPORT_EMAIL).strip()
```

> ⚠️ **位置约束（本 Spec 第二处；第一处是 §5.1 的 `init_db` 顺序）**：这一段若挪到 `SUPPORT_EMAIL`（第 83 行）之上，`RECHARGE_NOTIFY_TO` 会直接 `NameError`。CLAUDE.md 里已为 Spec19、Spec20 各记过一次同类约束，Spec21 是第三例。

### 8.2 `.env.example` 追加

```bash
# ---- 余额与充值（Spec21，全部可留空/可省）----
# 充值提醒邮件的收件人。默认跟随 SUPPORT_EMAIL，单个变量是为了将来能分开。
# 发信机制与 Spec20 完全共用：唯一的开关仍是 SMTP_PASSWORD（留空 = 完全不发信）。
# RECHARGE_NOTIFY_TO=frostyj@qq.com
# RECHARGE_WECHAT_MAX=64
```

### 8.3 变量总览

| 变量 | 默认值 | 说明 |
|---|---|---|
| `REGISTER_PRICE_NOTICE` | **（改文案）** `请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务` | 注册弹窗（Spec19 §8）。**不是环境变量**，是常量。 |
| `RECHARGE_PRICE_NOTICE` | `充值参考：0.9元约10次设计服务` | 充值弹窗的参考价备注。常量。 |
| `RECHARGE_WECHAT_MAX` | `64` | 微信昵称长度上限 |
| `RECHARGE_NOTIFY_TO` | 跟随 `SUPPORT_EMAIL` | 充值提醒收件人 |

### 8.4 `.gitignore` / `requirements.txt`

**都不动。** 无新依赖；收款码 `Server/payment.jpg` 早已在 `.gitignore` 里（Spec19 §2.6），本 Spec 只是多了一个消费它的地方。

---

## 9. 错误码

`errors.py` **追加 3 个类**（排在 Spec19 §9 那一段之后）：

```python
# ---- 余额与充值（Spec21 §9，追加到 Spec19 §9 之后）----

class RechargeRequestError(BadRequestError):
    """充值申请字段非法 / 账号不存在 / 账号无需充值。

    多个不同 message 共用一个码，与 Spec19 的 RegisterRequestError（40018）同款。
    """
    def __init__(self, message: str = "充值申请信息非法"):
        super().__init__(message, code=40019)


class RechargeNotFoundError(NotFoundError):
    """充值记录不存在。"""
    def __init__(self, message: str = "充值记录不存在"):
        super().__init__(message, code=40411)


class RechargeAlreadyReviewedError(AppError):
    """该充值记录已被处理（或两个管理员同时点了同意，后到的那个）。"""
    def __init__(self, message: str = "该充值记录已处理"):
        super().__init__(40904, message, status_code=409)
```

| 码 | 类 | 何时 | 消息 |
|---|---|---|---|
| `40019` | `RechargeRequestError` | 微信昵称为空/超长；账号为空；账号不存在 | 「请填写用于支付的微信昵称」「请填写账号」「账号不存在」 |
| `40411` | `RechargeNotFoundError` | approve/reject/delete 的记录 id 不存在 | 「充值记录不存在」 |
| `40904` | `RechargeAlreadyReviewedError` | 记录已不是 pending（含并发抢跑）；欠费端点遇到"无需充值"的账号 | 「该充值记录已处理」「当前账号无需充值」 |
| `40017` | `QuotaLimitError`（**复用 Spec18**） | `amount < 1`，或加完超 `QUOTA_LIMIT_MAX` | 「充值次数需为不小于 1 的整数」「服务限额需为 0~{MAX} 之间的整数」（前者给一条新 message） |
| `40402` | `UserNotFoundError`（**复用 Spec2**） | 同意的目标用户已被删除 | 「用户已被删除，无法充值」 |

> `40017` 复用是**刻意的**：超上限的后果与「改限额」超上限完全一样（一个天文数字进库），给两个码会让前端为同一件事写两条提示分支（§2.5）。
> `40904` 复用两个语义（记录已处理 / 账号无需充值）也是刻意的：两者都是"这个动作现在不该发生"，且**不会出现在同一条路由上**（前者在管理端三条，后者在公开欠费端点）。

---

## 10. 日志约定

沿用 Spec §10 的单行 JSON 格式。

| 事件 | 级别 | 字段 | 何时 |
|---|---|---|---|
| `recharge.submitted` | `info` | `username`, `recharge_id`, `recharge_source` | 落库成功 |
| `recharge.submitted_duplicate` | `info` | `username`, `recharge_id`, `recharge_source` | 幂等命中（未落库、未发信） |
| `recharge.reviewed` | `info` | `recharge_id`, `operator`, `target_user`, `decision`, `amount` | 同意 / 拒绝 |
| `recharge.deleted` | `info` | `recharge_id`, `operator`, `target_user`, `was_status` | 删除 |
| `notify.recharge_mail_sent` | `info` | `username`, `to` | 充值提醒发送成功 |
| `notify.recharge_mail_skipped` | `warning` | `reason="smtp_not_configured"`, `username` | `SMTP_PASSWORD` 为空 |
| `notify.recharge_mail_failed` | `warning` | `username`, `error`（`类型名: 消息`） | SMTP 报错 |

### 10.1 ⚠️ `logging_setup.py` 的字段白名单（Spec20 栽过一次，**这是第二次**）

`JsonFormatter._FIELDS` 是一份**白名单，不是"自动带上 extra"**：没登记的键会被**静默丢弃**——不报错、不警告，日志看起来"正常"，只是少了一个字段（CLAUDE.md 已为 Spec20 记过这一条）。

**必须新增到 `_FIELDS` 的字段**：

```python
               "to", "error",
               # Spec21 余额与充值事件字段（recharge.submitted / recharge.reviewed / …）
               # 注意用 recharge_source 而不是 source：后者在本仓已是
               # Spec12 wiki 事件的"作品来源"（generate|edit|upload），
               # 两者同名会让 `grep '"source"'` 一次捞到两种含义的东西。
               # 这与 Spec19 用 register_id 而不是 request_id 是同一条理由。
               "recharge_id", "recharge_source", "amount")
```

- `username` / `target_user` / `operator` / `decision` / `was_status` / `reason` / `to` / `error` **已在白名单**（Spec18~20 加的），直接复用。
- `amount` 是全新字段，**必须登记**。
- **`recharge_id` 而不是 `request_id`**：`request_id` 在本仓是"HTTP X-Request-Id"的固定含义（每个路由的每行日志都带它），两者同名会让排查时一搜就串味（Spec19 §10 为 `register_id` 记过同一条）。

### 10.2 绝不进日志的三样

`SMTP_PASSWORD`（凭据）、用户的 `phone` / `email`（PII，且已在邮件主题里，无需日志再抄一份）、`ip`（Spec19 §10 的规矩；本 Spec 的路由**根本不取 IP**）。

---

## 11. 目录结构增量

```
Server/
  timefmt.py         ← 新增（本 Spec 唯一的后端新文件）
  mailer.py          ← 时间函数搬走；send_register_notification 加参数；+send_recharge_notification
  db.py              ← users +2 列 + 迁移回填；+recharge_requests 建表/索引/8 函数；delete_user +1 行
  config.py          ← REGISTER_PRICE_NOTICE 改文案；+3 个变量（位置约束见 §8.1）
  schemas.py         ← +3 个请求体
  errors.py          ← +3 个错误类
  main.py            ← 阈值 ×2；+7 条路由；三个管理端列表 +created_at_beijing；
                       register_request 的 add_task 多传 wechat
  logging_setup.py   ← _FIELDS +3 个字段（§10.1）
  .env.example       ← +一段占位

frontend/src/
  views/RechargeModal.vue   ← 新增（本 Spec 唯一的前端新组件）
  App.vue                   ← +按钮、+挂载弹窗、quota 监听 +1 行
  views/AdminPanel.vue      ← 联系方式列、北京时间、阈值、+充值台账块、+待办数
  views/Login.vue           ← takeQuotaNotice 返回值变了 + 弹欠费面板
  views/HelpModal.vue       ← 文案
  views/GalleryPanel.vue    ← wiki-hint 加 v-if
  views/RegisterModal.vue   ← **零改动**
  api/chatApi.js            ← +7 个函数（拦截器不动）
  utils/quotaNotice.js      ← 多带 username（破坏性签名变更，§7.7）
```

---

## 12. 实施顺序（里程碑）

| # | 动作 | 完成判据 |
|---|---|---|
| 1 | `timefmt.py` 新建；`mailer.py` 改为从它导入 | `python -c "import mailer; print(mailer.beijing_time_text('2026-09-19T07:33:12.451Z'))"` → `2026-09-19 15:33:12`（**Spec20 §13 的原命令，必须仍然通过**） |
| 2 | `db.py`：users DDL +2 列、`_migrate_users_contact`、`create_user`/`approve_register_request`/`_row_to_dict`、`init_db` 调用（§5.8） | 用一份**含存量用户**的旧 `artcn.db` 启动，`SELECT username, phone, email FROM users` 显示出已开通用户的联系方式；重启第二次不报错、不覆盖 |
| 3 | `db.py`：`recharge_requests` 建表 + 8 个函数 + `delete_user` 补一行 | `python -c "import db; db.init_db()"` 通过；`sqlite3 artcn.db ".schema recharge_requests"` 有那两列索引 |
| 4 | `config.py`（改文案 + 3 变量）、`errors.py`（+3 类）、`schemas.py`（+3 模型）、`logging_setup.py`（+3 字段） | 服务能起来；`python -c "import config; print(config.RECHARGE_NOTIFY_TO)"` → `frostyj@qq.com`（不 `NameError`） |
| 5 | `mailer.send_recharge_notification` + `send_register_notification` 加参数 | 见 §13 用例 6~9 |
| 6 | `main.py`：**阈值两处** + docstring（§5.7） | 见 §13 用例 10 |
| 7 | `main.py`：三个管理端列表 +`created_at_beijing` | 见 §13 用例 3 |
| 8 | `main.py`：7 条新路由 + `register_request` 的 `add_task` 多传 `wechat` | 见 §13 用例 7~9、11~21 |
| 9 | 前端：`quotaNotice.js`（破坏性）、`App.vue`、`api/chatApi.js` | 登录页不报错；`grep -rn "takeQuotaNotice" frontend/src/` 只有 2 处（定义 + Login.vue） |
| 10 | 前端：`RechargeModal.vue`（两种模式）、`Login.vue` | 见 §13 用例 11、12、17、18 |
| 11 | 前端：`AdminPanel.vue`（4 项）、`HelpModal.vue`、`GalleryPanel.vue` | 见 §13 用例 1~5、13~16 |
| 12 | `CLAUDE.md` 同步（配置段 + 关键注意事项） | — |
| 13 | 走完 §13 全部用例 | 全绿 |

**第 1、2 步可以独立验证**（纯函数 + 迁移），建议先跑通再动路由。

---

## 13. 验收用例（端到端 Smoke）

### 前置

`Server/.env` 配好 `SMTP_USER` / `SMTP_PASSWORD`（真实授权码）/ `REGISTER_NOTIFY_TO` / `RECHARGE_NOTIFY_TO`，重启后端。另需一个**普通用户 token** 与一个**管理员 token**。

### A. 用户管理页（§7.2）

```bash
# 1. 联系方式：走完整注册流程开通一个账号（邮箱+电话都填），再手工建一个
#    ✅ GET /api/admin/users 里，申请开通的那个有 email/phone；手工建的两个都是 null
#    ✅ 前端那一列显示「zhang@qq.com / 13800138000」与「无」

# 2. 存量回填：用 Spec19 时代的老库（已开通若干账号）启动一次
#    ✅ 那些账号的 phone/email 被填上了（来源是它们当初的 approved 申请）
#    ✅ 第二次启动不重复回填、不改任何值

# 3. 北京时间：对照库里的 UTC
sqlite3 artcn.db "SELECT username, created_at FROM users LIMIT 3"
#    ✅ 接口里 created_at_beijing 恰好比 created_at 早 8 小时（例：库里 07:33:12.451Z → 15:33:12）
#    ✅ created_at 本身**没有**被改动（仍是 UTC ISO）
#    ✅ 注册申请块与充值台账块的 time 字段同样如此
```

### B. 提示语与文案（§7.5、§7.6）

```bash
# 4. 打开「我的作品」
#    ✅ **看不到**「更新会逐张分析个人作品…」
#    ✅ 点「基于我的新作品更新风格」→ 这句话出现，按钮变「分析中…」
#    ✅ 分析结束（成功或失败）→ 这句话消失

# 5. 打开「帮助」
#    ✅ 「服务次数」段是「每个用户预充值后会获得对应次数。次数用满后需要联系管理员续费才能继续使用。」
#    ✅ 全文没有「默认 25 次」，也没有「管理员不受额度限制」

# 6. 打开注册弹窗
#    ✅ 「请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务」
#    ✅ **RegisterModal.vue 零 diff**（git diff --stat 里没有它）
```

### C. 邮件（§5.5）

```bash
# 7. 注册申请邮件的正文
#    ✅ 收件箱：主题 ACN-<账号>-<邮箱>（邮箱优先）
#       正文：微信充值账号是<微信昵称>，注册时间是<北京时间>，请立即审批！
#       ← 「微信充值账号是…，」在前，「注册时间是」措辞保留（§2.7）

# 8. 主动充值邮件
#    ✅ 主题 ACN充值-<账号>-<邮箱>（没有邮箱就用手机号）
#       正文：微信充值账号是<微信昵称>，申请时间是<北京时间>，请立即审批    ← **没有感叹号**
#    ✅ 日志 notify.recharge_mail_sent

# 9. 欠费充值邮件
#    ✅ 主题 ACN欠费充值-<账号>-<邮箱>
#       正文同上
#    ✅ 手工建的号（无邮箱无电话）→ 主题里是「未填写」（§2.7）
```

### D. 阈值（§5.7）

```bash
# 10. 把一个普通用户的限额设成 3，used 也做成 2（用两三次），然后：
#     ✅ 第 3 次调用**成功**，且 used 变成 3 之后**用户还在系统里**（原口径下这一步已被踢）
#     ✅ 第 4 次调用被拦 → 403 (40304)
#     ✅ 前端清 token 回登录页 → alert 一句 + **登录页上出现收款码面板**（§7.4）
#     ✅ GET /api/admin/users 里这个用户的「已超额」标记出现
#     ✅ 登录被拒（POST /api/auth/login → 40304）
#     ✅ 改回限额 25 之后立刻能登录（判据每请求实时查库）
```

### E. 充值主链路（§6.2、§6.5）

```bash
# 11. 普通用户点顶部「余额与充值」
#     ✅ **管理员看不到这个按钮**（§7.1）
#     ✅ 余额 = (25 - 3) / 10 = 2.2 元
#     ✅ 收款码显示、备注「充值参考：0.9元约10次设计服务」
#     ✅ 微信昵称留空 → 本地拦（不发请求）；填了 → 200 + {id}
#     ✅ 收件箱收到 ACN充值-… 邮件（用例 8）
#     ✅ 成功面板「已提交，等待管理员审批。」

# 12. 幂等：**再点一次「我已完成充值」**
#     ✅ 仍然 200，返回**同一个 id**
#     ✅ 库里只有一条 pending、收件箱**没有**第二封
#     ✅ 日志是 recharge.submitted_duplicate（不是 recharge.submitted）

# 13. 管理端「待审批充值记录」
#     ✅ 出现一条：账号 / 微信昵称 / 主动充值 / 时间（北京时间）/ 三个按钮
#     ✅ 顶部 tip 行「待审批充值 1 条」

# 14. 点「同意」→ 弹框填 10
#     ✅ 用户表里该用户 quota_limit 从 25 变成 35，**used 不变（仍是 3）**
#     ✅ 记录变「已同意 · 加 10 次」
#     ✅ 该用户**立刻**能继续用（不用重新登录也行——判据每请求实时查库）
#     ✅ 日志 recharge.reviewed, decision=approved, amount=10
#     ✅ 前端「拒绝」「删除」都点不动了（已处理行只剩「删除」）

# 15. 加额度的上界
#     ✅ 填 0 → 前端拦「充值次数需为不小于 1 的整数」
#     ✅ 把该用户限额设成 QUOTA_LIMIT_MAX - 5 再同意一条 +10 → 40017（服务限额需为 0~MAX…）
#     ✅ 该记录**仍是 pending**（校验在事务之前，没有半截状态）

# 16. 「拒绝」与「删除」
#     ✅ 拒绝 → 状态变 rejected，**quota_limit 不变**，记录保留
#     ✅ 删除一条**已同意**的记录 → 记录消失，但**该用户的额度仍然是加过的**（§2.6）
#     ✅ 删除用户 → 他的充值记录全部消失（§2.6）
```

### F. 欠费充值链路（§6.3）

```bash
# 17. 一个 used > quota_limit 的用户在登录页点「我已完成充值」
#     ✅ 面板上账号可预填（从系统内被踢的场景：#10 里 auth.username 被带过来了）
#     ✅ 在一个全新浏览器直接打开登录页（无预填）→ 手工填账号也能提交
#     ✅ 提交 → 200 + 收件箱 ACN欠费充值-… 邮件（用例 9）

# 18. 公开端点的三条边界
curl -X POST localhost:8000/api/auth/recharge-request -H 'Content-Type: application/json' \
  -d '{"username":"不存在的账号","wechat":"张三"}'          # → 40019「账号不存在」
#     ✅ 一个**没欠费**的账号 → 40904「当前账号无需充值」
#     ✅ 管理员账号 → 40904（管理员不受限额，没有"欠费"这回事）
#     ✅ **不带 token 也能调**（它在 PUBLIC_AUTH_PATHS 里，§6.3）
#     ✅ 反复提交只有一条 pending、一封邮件（幂等）
#     ✅ 同意它 → 该用户额度增加 → **立刻能登录**
```

### G. 降级与零回归

```bash
# 19. 清空 .env 的 SMTP_PASSWORD，重启
#     ✅ 充值接口仍然 200 + id
#     ✅ 没有邮件，日志 notify.recharge_mail_skipped (reason=smtp_not_configured)
#     ✅ **台账、管理端三按钮、加额度全部照常工作**（邮件只是通知，§3.3-1）

# 20. 把 SMTP_HOST 改成 10.255.255.1（黑洞），重启，提交一条充值
#     ✅ 接口仍然 200（响应**不等待**那 10 秒超时）
#     ✅ 这 10 秒期间其它接口**照常响应**（验证同步 def 走线程池，§5.5）
#     ✅ 约 10 秒后日志 notify.recharge_mail_failed

# 21. 收款码缺失
#     ✅ 临时把 Server/payment.jpg 改名 → 两个弹窗都是裂图，但**照常能提交**（§7.3）
#     ✅ GET /api/auth/payment-qr → 40410

# 22. git diff --stat 应只包含 §11 列的文件
#     ✅ 逐字节确认 **frontend/src/views/RegisterModal.vue 无 diff**
#     ✅ **requirements.txt 无 diff、.gitignore 无 diff、providers/ 无 diff、agents/ 无 diff**

# 23. Spec20 回归
#     ✅ `python -c "import mailer; print(mailer.beijing_time_text('2026-09-19T07:33:12.451Z'))"`
#        仍输出 2026-09-19 15:33:12（搬运没有改变行为，§5.2）
#     ✅ Spec19 全链路（注册 → 管理端 pending → 同意 → 新号能登录）行为与之前一致

# 24. Spec18 回归
#     ✅ 四类任务的计数时机一个都没变（成功才计）
#     ✅ 风格归纳仍在上游调用**发出前**计数
#     ✅ 「清空调用统计」仍然只删 usage 行，`user_quota.used` 纹丝不动
```

---

## 14. 补充

### 14.1 与 Spec18 / Spec19 的模型关系

三者是三层：

| Spec | 回答的问题 | 载体 |
|---|---|---|
| Spec18 | **用了多少、还能用多少** | `usage`（区间统计）+ `user_quota`（终身账本）+ `users.quota_limit` |
| Spec19 | **谁可以有一个账号** | `register_requests` |
| **Spec21** | **钱是怎么进来的** | `recharge_requests` |

**本 Spec 一个字都没有改 Spec18 的记账语义**：`record_call` 的双写不动，`used` 的"只增不减"不动，`usage` 的可清零不动。充值改的是 `users.quota_limit` 这一个**阈值**字段——它本来就是"管理员可改"的（Spec18 §6.2 的 `PUT /api/admin/users/{id}/quota`），本 Spec 只是给这个动作加了一条**有台账、有邮件提醒、能自助发起**的通道。

### 14.2 为什么余额不改成一个真正的"钱包"

因为它会立刻引出三个必须回答的问题：**退款怎么办**（微信转账退不退？退多少？）、**部分扣减的精度**（一次对话扣 0.1 元？那余额是 2.2 还是 2.19？）、**与 `used` 谁是权威**。而现在的模型一个都不用回答：`used` 是唯一的账本，`quota_limit` 是唯一的阈值，余额是它俩的一个**纯展示函数**（§2.9）。

**把它做成钱包，是把一个"展示"问题升级成一个"资金"问题。** 本 Spec 明确不做（§3.2）。

### 14.3 将来若要改的地方（写入本文档，供实际用起来之后回头改）

| 想改什么 | 改哪 | 成本 |
|---|---|---|
| 改参考价文案 | `config.RECHARGE_PRICE_NOTICE` / `REGISTER_PRICE_NOTICE` | 零代码 |
| 改余额的换算率（比如改成 0.9 元 = 10 次） | `main.py` 里 `GET /api/recharge/info` 的那一行除以 9 | 1 行。**注意与 §8.1 的文案要一起改**，否则两个口径又会不一致 |
| 让管理员也看到余额按钮 | `App.vue` 去掉 `v-if="!isAdmin"` | 1 行。但那个数字对管理员没有业务含义（§3.3-5） |
| 换充值提醒的收件人 | `.env` 设 `RECHARGE_NOTIFY_TO` | 零代码 |
| 临时关掉全部邮件 | 清空 `SMTP_PASSWORD` 并重启 | 零代码（注册与充值一起关，因为共用一个开关） |
| 给用户看自己的充值记录 | 需要加 `GET /api/recharge/my` + 一个列表 UI | 中。当前判断是不值得（§3.2） |
| 加"充值满 N 次自动通过" | 在 `create_recharge_request` 之后加一条阈值判断 | 中。**不建议**：自动加额度意味着一个能被公开端点触发的写操作，那就必须重新做一整套防刷 |
| 帮助页那句改成"可在顶部『余额与充值』里自助提交" | `HelpModal.vue` 一行 | 零代码。**当前刻意没改**，理由见 §7.5 |
