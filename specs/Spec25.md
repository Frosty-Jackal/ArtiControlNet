# ArtiControlNet Spec 25：管理端建号限制与注册对齐 + 两处过时文案

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：**把「管理员手工建号」的限制与「用户自助注册」的限制收口成同一份规则**（用户名 2~32、密码 2~72），并删掉管理端「用户管理」页那两处还停留在 Spec19「申请 → 审批」时代的文案。
> 本 Spec 是 **Spec.md / Spec2~24 的增量补充**，**不推翻任何既有 Spec**，只 **订正 Spec19 §7.5a 与 Spec22 §9 表格里的两处措辞**（§1.3 逐个点名）。
> **后端改动面 = 3 个文件、5 处**：`auth.py`（+2 个常量）、`main.py`（3 处校验）、`errors.py`（1 处 docstring）。
> **前端改动面 = 1 个文件**：`views/AdminPanel.vue`（2 处文案 + 3 处字面量）。
> **0 个新增接口、0 个新增环境变量、0 个新增依赖、0 个新增文件、0 个新增错误码、0 个新增日志字段、0 处 DB 改动。**
> 硬约束仍遵守：无本地推理、只有前后端两层、所有凭据只在后端环境变量、除 `artcn.db` 外无其他数据库。
> ⚠️ 本 Spec **不实现任何新功能**——它是一次"把已经存在的两条路对齐"的收口，外加两行文案。如果实现过程中发现需要新增接口或改表结构，那说明理解错了范围。

---

## 0. 三件事一览（用户原话 → 落点）

| # | 用户原话 | 本 Spec 的落点 |
|---|---|---|
| 1 | 「管理员-用户管理界面中，"待审批注册申请 条"应当删掉」 | §2.1、§5.4、§7.1 |
| 2 | 「"，或由用户申请后审批开通"应该为"或由用户自由注册"」 | §5.4、§7.1 |
| 3 | 「管理员创建账号的限制应该跟普通用户注册的限制保持一致（与普通用户相同），例如"初始密码>=6位的限制"应该改」 | §2.2~§2.5、§5.2、§5.3、§5.4、§6.1、§6.2、§7.2、§7.3 |

### 用户在答复里改的口径（**实现时按这一列**）

本 Spec 就两个会改变实现范围的问题问过用户，下面两行是用户明确点过的选项，不是本 Spec 的推断。

| # | 问题 | 用户选定 | 落点 |
|---|---|---|---|
| A | 管理员建号要不要也**必填邮箱**（自助注册是必填 + 验证码）？ | **不加，邮箱仍可空** | §2.2、§3.3-1 |
| B | `AdminPanel.vue` 里写死的「至少 6 位」（placeholder + `create()` + `resetPassword()` 三处）怎么处理？ | **字面量降到 2**（保留前端即时校验，不是删掉校验） | §2.3、§7.2、§7.3 |

---

## 1. 功能目的

### 1.1 为什么现在做

Spec23 把注册从「提交申请 → 管理员审批」改成「验证码一过直接建号」之后，系统里**设定一个账号**的路只剩两条：

| | 自助注册 `POST /api/auth/register` | 管理员建号 `POST /api/admin/users` |
|---|---|---|
| 用户名 | 2~32（`main.py:1318` 写死） | **只有下限 ≥2**（`main.py:1764`，无上限） |
| 密码 | 2~72（`auth.MIN_PASSWORD_LEN` / `MAX_PASSWORD_LEN`） | 2~72（**后端已对齐**，Spec22 §2.10） |
| 邮箱 | 必填 + 验证码 | 无（落 NULL）——**用户选定保持不变** |
| 初始额度 | `config.QUOTA_DEFAULT_LIMIT` = 10 | 同一个 `db.create_user` → 10 ✅ |
| 前端提示 | `RegisterModal.vue`：「2~32 个字符」「至少 2 位」 | `AdminPanel.vue`：**「≥6 位」「密码至少 6 位」** |

**后端密码那一栏 Spec22 §2.10 已经收口了，前端没有。** 于是现状是：

- **管理端 UI 实际拒绝 2~5 位的密码**（`AdminPanel.vue:215` 与 `:238` 各写死一个 `6`），而后端接受。用户在管理端设一个 2 位密码，界面上根本发不出去。
- 这条不一致 **CLAUDE.md 已经记过**（"已知不一致"那段），Spec22 §7.7 当时明说「重置密码按钮不动」，所以它是有意留下的尾巴。本 Spec 就是来收它的。

同时，那两处 `6` 是**跨语言同值副本**——前端拿不到 `auth.MIN_PASSWORD_LEN`（Python 常量），只能同值复制。本仓对同值副本的既定做法是"留下 + 写明改要一起改"（§2.3）。

### 1.2 一句话架构

不改架构。改的是**两条路共用的那组数字**放在哪、以及管理端页面上那句话说的是不是真的。

### 1.3 与既有 Spec 的关系（**本 Spec 订正的东西**）

| 既有记录 | 本 Spec 怎么处理 |
|---|---|
| **Spec19 §7.5a**：管理端顶部提示行的原文案与「待审批注册申请 `{{ pendingCount }}` 条」 | **订正**。`pendingCount` 这个变量在 **Spec23 §7.6 就从 `AdminPanel.vue` 的 script 里删掉了**（连同 `requests` / `busyRegId` / `loadRequests()`），但**模板里那一行没删**。Spec23 的删除清单（§5.1 表、§7.6）只列了 script 侧的 state，模板那一行漏了。⚠️ 所以这不是"过时文案"，是一个**活着的 bug**（§2.1）。 |
| **Spec22 §9 错误码表**里 `40010` 的 message 一栏：`「密码至少 2 位」` | **订正措辞**——`40010` 这个**码**不变，只是它的 message 与注册那条（`40018` 的「密码需为 2~72 位」）对齐。理由见 §2.5。 |
| **Spec22 §2.10** 的「设定密码的路一共三条，三处都引用常量」 | **沿用并扩展**：同一个做法（一份规则、一个地方）这次用到**用户名**上（§2.4）。 |
| **CLAUDE.md** 的「⚠️ 已知不一致：`AdminPanel.vue` 的两处仍写死至少 6 位」 | **本 Spec 消除它**。§15 列出 CLAUDE.md 要改的段落。 |
| Spec19 / Spec20 / Spec21 / Spec23 里其余提到「注册申请」「注册申请与审批」的地方 | **不动**。那些是代码注释里的 tombstone（`# Spec23 删除：…`）或历史 Spec 正文，按本仓惯例保留（§2.7）。 |

---

## 2. 决策记录（为什么这么选）

### 2.1 「待审批注册申请 N 条」不只是过时文案，是一个活着的 `undefined`

模板第 12 行是：

```html
· <b class="tip-pending">待审批注册申请 {{ pendingCount }} 条</b>
```

而 `pendingCount` 在 `<script setup>` 里**已经不存在了**（Spec23 §7.6 删掉了 `requests` ref 与它的 `computed`）。用户看到的就是渲染出来的 **「待审批注册申请  条」**——两个空格之间什么都没有。

为什么它没让页面崩：在 `<script setup>` 里，模板引用的标识符若不在 setup 绑定里，编译器会把它编成 `_ctx.pendingCount`，取到 `undefined`，插值成空串。**开发模式下 Vue 会额外在控制台打一条 `Property "pendingCount" was accessed during render but is not defined on instance`**——所以这个 bug 一直是可见的，只是没人往控制台看。

**结论**：这一行**整行删除**，不是把它改成一个新的计数。注册改成自助之后没有"申请"可审，也没有"待审批"这个状态（Spec23 §2.1）。

⚠️ **`.tip-pending` 这条 CSS 不许删**：正下方那行「待审批充值 `{{ pendingRechargeCount }}` 条」还在用它。这与 Spec23 §14 陷阱 1（删注册 UI 时 `.reg-*` 一行 CSS 都不许删）是**同一条陷阱的第二次出现**——删元素前先 `grep tip-pending`。

### 2.2 邮箱：管理员建的号**仍然可以没有邮箱**（用户选定）

自助注册必填邮箱且要过验证码；管理员建号没有邮箱，落 NULL，管理端「联系方式」列显示「无」。**本 Spec 不改这一点**（用户在 §0 表格 A 行选定了）。

代价必须写清楚，它是本 Spec 最大的一处遗留（§3.3-1）：**一个没有邮箱的账号，永远用不了邮箱登录、也用不了自助改密**（Spec22 把邮箱定成了唯一身份凭证），而**全仓没有任何接口能给一个已存在的账号补邮箱**——`db.create_user` 有 `email` 参数，但只有注册路由传，且没有 `update_email` 这一类函数（已 `grep` 确认）。忘了密码就只能找管理员重置。

这条不是本 Spec 引入的，本 Spec 只是**选择不修它**，因此把它原样记录在 §3.3，不放进"范围内"。

### 2.3 前端保留长度校验，字面量 `6` → `2`（同值副本的处理）

用户在 §0 表格 B 行选了"字面量降到 2"，而不是"删掉前端校验"。

因此 `AdminPanel.vue` 里那三处会变成这样：

- placeholder：`初始密码（≥6 位）` → `初始密码（≥2 位）`
- `create()`：`pass.length < 6` → `pass.length < 2`，同时 message `'用户名至少 2 个字符，密码至少 6 位'` → `'用户名至少 2 个字符，密码至少 2 位'`
- `resetPassword()`：prompt 里的`（至少 6 位）` → `（至少 2 位）`，`pass.length < 6` → `pass.length < 2`，message `'密码至少 6 位'` → `'密码至少 2 位'`

**这三处是 `auth.MIN_PASSWORD_LEN` 的同值副本**（跨语言，import 不到）。按本仓对同值副本的既定做法（Spec23 §14 陷阱 1、`CommunityPanel.vue` 的 `COMMENT_MAX`），**留一份 + 注释写明"同值副本，改要一起改"**，不引入构建期共享机制（那要动 Vite 配置，为一个数字不值当）。

⚠️ **上限（32 / 72）不在这三处判**。规则只有一个地方，在后端；前端只做一个"下限"的即时反馈，超过上限时由后端的 message 落到下面那行 `error` 里（§6.1、§6.2 给了确切文案）。这样前端不会多出两个会漂移的副本。

### 2.4 用户名上限 32：为什么引入两个常量，而不是再写一个 32

用户的要求是"**限制保持一致**"，而现状是注册那条路有上限 32、管理员那条路只有下限 ≥2——**同一个系统里"用户名最长多少"有两个答案**。管理员现在能建出一个 500 字符的用户名，用户表格与顶栏当场散架。

实现方式有两种：

| 方案 | 做法 | 取舍 |
|---|---|---|
| **① 引入常量（选它）** | `auth.MIN_USERNAME_LEN = 2` / `MAX_USERNAME_LEN = 32`，注册路由与管理端建号路由都引用它 | 两条路**共用同一份规则**，且 message 由 f-string 拼出、抄不了错。代价：多改一个 `main.py:1318`（注册路由） |
| ② 各写一个 32 | `main.py:1764` 补上 `len(username) > 32`，字面量再写一遍 | 改动更小，但从此"用户名上限"有两个地方各写一个 32——正是 Spec22 §2.10 花力气消灭的那类副本 |

选 ①。理由与 Spec22 §2.10 对密码的处理**逐字相同**：既然这次要动同一个数字，就顺手让它只有一个来源。`auth.py` 里那两个密码常量的注释已经把这条原则写在文件里了，新常量紧挨着它们放。

⚠️ **改 `main.py:1318` 是"零行为变更"**：改前 `2 <= len(username) <= 32`、message「用户名需为 2~32 个字符」；改后 `auth.MIN_USERNAME_LEN <= len(username) <= auth.MAX_USERNAME_LEN`、message 由 f-string 拼出**同一句话**。§13-A 有一条专门验它逐字不变。

### 2.5 `40010` 的 message 与 `40018` 对齐（**这条订正 Spec22 §9 表格的措辞**）

管理端两条路由现在的 message 是 `f"密码至少 {auth.MIN_PASSWORD_LEN} 位"` → **「密码至少 2 位」**。这句话在密码**过长**（>72）时是**反的**：用户填了 100 个字符，系统回他"密码至少 2 位"。用户没法从这句话里知道问题出在哪。

注册那条路的 message 是对的：「密码需为 2~72 位」（`main.py:1322`），因为它是 `f"密码需为 {MIN}~{MAX} 位"`。

既然本 Spec 的目标就是"管理端与注册保持一致"，这里就**对齐成同一句话**：

```python
raise CredentialsFormatError(
    f"密码需为 {auth.MIN_PASSWORD_LEN}~{auth.MAX_PASSWORD_LEN} 位")
```

**明确记录**：这会让 **Spec22 §9 错误码表里 `40010` 那一行的 message 栏过期**（它写的是「密码至少 2 位」）。`40010` 这个**码本身、它的 status_code、它的类都不动**——同样的 400，同样的 `CredentialsFormatError`，只换 message 字符串。这与 Spec23 订正 Spec19 段落是同一种做法：后来的 Spec 点名作废前者的措辞。

⚠️ `main.py:1192` 的「用户名和密码不能为空」（登录路由）**不动**——那不是长度规则，是"字段是空的"，本来就不该跟长度规则长一个样。

### 2.6 `db.create_initial_admin` 的两道闸（≥2 / ≥6）**不动**

`db.py:927` 的 `len(username) < 2` 与 `:929` 的 `len(password) < 6` 是**部署者写在 `.env` 里的初始管理员口令**的防呆线，不是终端用户输入。Spec22 §2.10 已经为此留了注释（"那道 ≥6 **故意不跟着改**"），本 Spec 沿用同一条判断：

- 那个 `≥6` **不引用** `auth.MIN_PASSWORD_LEN`（引用了就等于把防呆线降到 2）。
- 那个 `≥2` **也不引用** 新的 `auth.MAX_USERNAME_LEN`（同理，而且不需要上限）。
- 技术上它也**引用不了**：`db.py` 只 import `config` 与 `errors`，对 `auth` 是**函数内延迟 import**（`from auth import hash_password  # 延迟导入，避免与 auth.py 循环依赖`）。谁要是"顺手统一"给它加上 `auth.` 前缀，要么造出一个循环引用，要么只好把 import 提到模块顶层——两条路都是错的。

### 2.7 注释面：只改会误导的那一条，其余 tombstone 一律保留

Spec23 删注册审批链路时，在 `Server/` 与 `frontend/src/` 里留下了大量形如 `# Spec23 §7.6 删除：…` 的**墓碑注释**（`chatApi.js`、`main.py:1228`、`schemas.py:163`、`config.py:77`、`db.py:232` 等）。**这是本仓有意的惯例**（Spec2 §7.5a 的注释也以同样方式保留），本 Spec **不清理它们**——清理会让"某段代码为什么是这样"的线索消失。

**唯一要改的是 `AdminPanel.vue:7-8` 那条**：

```html
<!-- Spec19 §7.5a：原文案"无公开注册"不再成立——注册申请与审批已上线。
     待审批条数写进这一行，免得管理员每次都要滚过用户表才知道有没有活干。 -->
```

它**两句话都在描述它正下方那三行**，而其中两行这次要被改/删。留着它，下一个读代码的人会以为"待审批注册申请"还在。改成 Spec25 的墓碑（§5.4 给了逐字内容）。

另外 `Server/errors.py` 的 `CredentialsFormatError` docstring 里那句 `（用户名 <2 字符 / 密码 <auth.MIN_PASSWORD_LEN 位）` 在本次改动后**不再完整**（用户名有上限了、管理端不再抛"<2 字符"那句了），一并刷新为不枚举具体文案的写法（§5.3）。

---

## 3. 需求边界

### 3.1 范围内

1. `views/AdminPanel.vue`：
   - 删掉模板第 12 行「待审批注册申请 `{{ pendingCount }}` 条」整行（§2.1）。
   - 第 11 行「或由用户申请后审批开通」→「**或由用户自由注册**」。
   - 重写第 7~8 行的注释（§2.7）。
   - `初始密码（≥6 位）` → `初始密码（≥2 位）`。
   - `新用户名（≥2 字符）` → `新用户名（2~32 字符）`（与 `RegisterModal.vue` 的「2~32 个字符」同一个口径；后端这次真的会拒 33 字符的名字了，提示语必须跟上）。
   - `create()` 与 `resetPassword()` 里的 `6` → `2`（含 message）。
2. `Server/auth.py`：新增 `MIN_USERNAME_LEN = 2` / `MAX_USERNAME_LEN = 32`。
3. `Server/main.py`：三处长度校验改为引用常量（注册用户名、管理端建号用户名、管理端建号/重置密码的 message 对齐）。
4. `Server/errors.py`：`CredentialsFormatError` 的 docstring 刷新。
5. `CLAUDE.md`：按 §15 改段落。

### 3.2 不在范围内（明确不做）

| 不做的事 | 为什么 |
|---|---|
| **给管理员建号加邮箱输入框** | 用户在 §0 表格 A 行明确选了"不加，邮箱仍可空"。代价记在 §3.3-1。 |
| **新增「给已有账号补邮箱」的接口/函数** | 用户没要；这是 Spec22 遗留的独立议题，见 §3.3-1。它要动 `users` 表语义（`email` 没有 UNIQUE 约束、`get_user_by_email` 用 `LIMIT 1`），不是一次文案收口能顺带做的。 |
| **把前端那三处 `6` 换成"从后端拿"** | 要走一条新的公开配置接口或在构建期注入，为一个数字不值当（§2.3）。 |
| **清理由 Spec23 留下的墓碑注释** | 本仓惯例，见 §2.7。 |
| **改 `db.create_initial_admin` 的 ≥2 / ≥6** | §2.6。 |
| **改 `main.py:1192` 的「用户名和密码不能为空」** | §2.5 末。 |
| **给注册路由的 `40018` 与管理端的 `40010` 合并成一个码** | 两个码早就在各自的 Spec 里被写死了（Spec19 §9 / Spec2 §9），合并会连带改前端的拦截器判断。本 Spec 只统一**message 的文字**，不统一码。 |
| **给用户名加字符集规则**（纯字母数字等） | 两条路现在都只看长度。这是一条**新**需求，不是"对齐"。 |
| **任何 DB 改动**（表、列、迁移） | 本 Spec 不碰 `artcn.db` 的结构（§11）。 |

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **管理员建的号仍然是"二等公民"**（用户明知并选定）：没有邮箱 → 用不了邮箱登录、用不了自助改密、忘了密码只能由管理员重置，而且**没有任何接口能补邮箱**。存量 11 个老账号（Spec22 之前建的）同样如此。这条在 Spec22 那次就已经存在，本 Spec 只是**没有消除它**——不要读成"本 Spec 解决了邮箱问题"。
   - 一个附带的安全侧证：`users.email` **没有 UNIQUE 约束**，查重只发生在发码/注册那一层（`_reject_duplicate_email`），而 `db.get_user_by_email` 用的是 `ORDER BY u.id ASC LIMIT 1`。所以**将来若真要开"补邮箱"这个口子，必须同时补查重**，否则重复邮箱会让后建的那个号永远登不进去（旧号赢，静默失效）。本 Spec 不开这个口子，故不涉及。
2. **前端那三处 `2` 是副本，会漂移**（§2.3）。它们与 `auth.MIN_PASSWORD_LEN` 一旦不一致，症状是"界面报的错与后端规则不同"——不报错、只是说法不同。§15 要求把这条写进 CLAUDE.md。
3. **`AdminPanel.vue` 的用户名下限是 `name.length < 2`，用的是 JS 的 `.length`（UTF-16 码元）**，而后端是 Python 的 `len()`（码点）。含 emoji / 代理对的用户名在两边的"长度"不同。**这是既有行为，本 Spec 不修**；由于前端只判下限、上限在后端，最坏结果是前端放过、后端按码点拒掉并给出正确 message。记在这里是为了避免被当成新引入的 bug。
4. **`create()` 里 `name` 已经 `trim()` 过，`pass` 没有**（密码里的空格是有效字符，不能 trim）。这一条不要"顺手统一"。

---

## 4. 技术栈增量

**零。** 不动 `requirements.txt`、不动 `package.json`、不引任何新库、不用任何新浏览器 API。

---

## 5. 架构设计（增量）

### 5.1 改动面总表（**一张表看全，逐项打勾用**）

| 文件 | 动作 | 处数 | 章节 |
|---|---|---|---|
| `Server/auth.py` | 新增 2 个常量 | 1 个代码块 | §5.2 |
| `Server/main.py` | 注册路由用户名校验改常量 | 1 | §5.3 |
| `Server/main.py` | 管理端建号：用户名改常量（**加 ≤32**）、密码 message 对齐 | 2 | §5.3 |
| `Server/main.py` | 管理端重置密码：message 对齐 | 1 | §5.3 |
| `Server/errors.py` | `CredentialsFormatError` docstring | 1 | §5.3 |
| `frontend/src/views/AdminPanel.vue` | 模板：注释重写 + 删 1 行 + 改 1 行 + 2 个 placeholder | 5 | §5.4 |
| `frontend/src/views/AdminPanel.vue` | 脚本：`create()` + `resetPassword()` | 2 | §5.4 |
| `CLAUDE.md` | 按 §15 | — | §15 |

**不动的文件（点名，免得"顺手"改）**：`Server/db.py` 的任何一行、`Server/config.py`、`Server/schemas.py`（`AdminCreateUserRequest` 仍是 `username` + `password` 两个字段）、`Server/logging_setup.py`（`_FIELDS` 零增删）、`Server/task_queue.py`、`Server/agents/*`、`frontend/src/api/chatApi.js`、`frontend/src/views/RegisterModal.vue`、`frontend/src/assets/styles/main.css`、`frontend/src/store/auth.js`。

⚠️ `frontend/src/assets/styles/main.css` 一行不改：`.tip-pending` 仍被「待审批充值」那行用着（§2.1）。

### 5.2 `Server/auth.py`

在 `MAX_PASSWORD_LEN = 72` 那两行**正下方**追加（紧挨着放，是为了让"长度规则都在这里"一眼可见）：

```python
# 用户名长度规则（**全仓唯一来源**）。Spec25 §2.4：设定用户名的路有两条
# （自助注册 / 管理员建号），Spec23 之前只有注册那条有上限 32，管理员那条
# 只有下限——同一个系统里"用户名最长多少"有两个答案，管理员能建出一个
# 500 字符的名字。两个常量一次收口，两处 message 都由 f-string 拼出。
# ⚠️ db.create_initial_admin 那道 ≥2（`db.py:927`）**故意不引用它**，理由与
#    MAX_PASSWORD_LEN 上面那条同款：那是部署者写在 .env 里的值，不是用户输入；
#    而且 db.py 对 auth 是函数内延迟 import，引用不了也不会去引用（§2.6）。
MIN_USERNAME_LEN = 2

MAX_USERNAME_LEN = 32
```

**没有别的改动。** 不要动 `MIN_PASSWORD_LEN` / `MAX_PASSWORD_LEN` 的值（Spec22 §2.10 定的是 2 / 72），也不要动那两个常量上面已有的注释。

### 5.3 `Server/main.py` + `Server/errors.py`

#### (a) 注册路由的用户名校验（`main.py:1318-1319`）——**零行为变更**

```python
# 改前
    if not 2 <= len(username) <= 32:
        raise RegisterRequestError("用户名需为 2~32 个字符")

# 改后
    if not auth.MIN_USERNAME_LEN <= len(username) <= auth.MAX_USERNAME_LEN:
        raise RegisterRequestError(
            f"用户名需为 {auth.MIN_USERNAME_LEN}~{auth.MAX_USERNAME_LEN} 个字符"
        )
```

**这是本次唯一的"改起来吓人、其实没变"的一处**：拼出来的 message 与原来逐字相同（`用户名需为 2~32 个字符`），判据也相同。§13-A 专验它。这一处是 Spec23/24 之后**第一次**动注册路由，实现时要格外确认没有连带改动（该路由这次的 diff 应该**只有这 4 行**）。

#### (b) 管理端建号（`main.py:1764-1770`）

```python
# 改前
    if len(username) < 2:
        raise CredentialsFormatError("用户名至少 2 个字符")
    # Spec22 §2.10：下限从写死的 6 降成 auth.MIN_PASSWORD_LEN。设定密码的路一共
    # 三条（注册 / 建号 / 重置），**同一份规则**——别在这里再写一个 6。
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise CredentialsFormatError(
            f"密码至少 {auth.MIN_PASSWORD_LEN} 位")

# 改后
    # Spec25 §2.4：与自助注册**同一份规则**（2~32）。改前这里只有下限，
    # 管理员能建出任意长的用户名——用户表格与顶栏当场散架。
    if not auth.MIN_USERNAME_LEN <= len(username) <= auth.MAX_USERNAME_LEN:
        raise CredentialsFormatError(
            f"用户名需为 {auth.MIN_USERNAME_LEN}~{auth.MAX_USERNAME_LEN} 个字符")
    # Spec22 §2.10：下限从写死的 6 降成 auth.MIN_PASSWORD_LEN。设定密码的路一共
    # 三条（注册 / 建号 / 重置），**同一份规则**——别在这里再写一个 6。
    # Spec25 §2.5：message 与注册那条（40018）对齐成同一句话。原来那句是
    #   "密码至少 2 位"，在密码**过长**（>72）时是反的——用户填 100 个字符，
    #   系统回他"至少 2 位"，从这句话里看不出问题在哪。
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise CredentialsFormatError(
            f"密码需为 {auth.MIN_PASSWORD_LEN}~{auth.MAX_PASSWORD_LEN} 位")
```

**响应体不变**：仍是 `{"id": …, "username": …, "is_admin": false}`。**错误码不变**：仍是 `40010` / 400。

#### (c) 管理端重置密码（`main.py:1836-1838`）

```python
# 改前
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise CredentialsFormatError(
            f"密码至少 {auth.MIN_PASSWORD_LEN} 位")

# 改后
    # Spec25 §2.5：与建号那处同一句话（两处 message 必须逐字相同——
    # 它们是同一条规则的两个出口）。
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise CredentialsFormatError(
            f"密码需为 {auth.MIN_PASSWORD_LEN}~{auth.MAX_PASSWORD_LEN} 位")
```

#### (d) `Server/errors.py` 的 `CredentialsFormatError` docstring

```python
# 改前
    """用户名或密码格式非法（用户名 <2 字符 / 密码 <auth.MIN_PASSWORD_LEN 位）。

    Spec22 §2.10：密码下限从 6 降到 2，所以"<6 位"这个说法不再成立——
    下限由 `auth.MIN_PASSWORD_LEN` 定义，本类只负责抛，不定义规则。
    """

# 改后
    """用户名或密码格式非法。

    长度规则由 `auth.MIN_USERNAME_LEN` / `MAX_USERNAME_LEN` /
    `MIN_PASSWORD_LEN` / `MAX_PASSWORD_LEN` 定义，**本类只负责抛，不定义规则**，
    也不枚举具体文案——原来那句"用户名 <2 字符 / 密码 <N 位"在 Spec25 之后
    就不完整了（用户名有上限了、管理端也不再抛"<2 字符"那句）。

    ⚠️ 40010 的 message 有三处消费者（登录路由、管理端建号、管理端重置密码），
    其中后两处的密码 message 在 Spec25 §2.5 对齐成了注册那条的
    「密码需为 2~72 位」。Spec22 §9 错误码表里 40010 那一行的 message 措辞
    由此作废；**码与 status_code 一个字没变**。
    """
```

### 5.4 `frontend/src/views/AdminPanel.vue`

**只有这一个前端文件改动。** 逐处：

#### (a) 模板第 7~14 行（注释重写 + 删 1 行 + 改 1 行）

```html
<!-- 改后 -->
    <!-- Spec25 §2.1：Spec19 §7.5a 的「注册申请与审批已上线 + 待审批条数」整段作废。
         注册早就是自助的（Spec23），没有"申请"可审、也没有"待审批"这个状态。
         ⚠️ 被删的那行不只是过时文案——它引用的 pendingCount 在 Spec23 §7.6 就
         从 script 里删掉了，渲染出来一直是「待审批注册申请  条」（dev 控制台
         还有一条 property not defined 告警）。
         ⚠️ .tip-pending 这条 CSS **不许删**：下面「待审批充值」那行还在用它。 -->
    <p class="admin-tip">
      当前登录：{{ auth.username }}（{{ auth.isAdmin ? '管理员' : '普通用户' }}）
      · 账号可由管理员创建，或由用户自由注册
      · <b class="tip-pending">待审批充值 {{ pendingRechargeCount }} 条</b>
    </p>
```

对照改前的第 11~12 行：

```html
      · 账号可由管理员创建，或由用户申请后审批开通          ← 改成「或由用户自由注册」
      · <b class="tip-pending">待审批注册申请 {{ pendingCount }} 条</b>   ← 整行删除
```

第 10 行的「当前登录：…」与第 13 行的「待审批充值…」**不动**。

#### (b) 两个 placeholder（第 21、28 行）

```html
<!-- 改前 -->
        placeholder="新用户名（≥2 字符）"
        placeholder="初始密码（≥6 位）"

<!-- 改后 -->
        placeholder="新用户名（2~32 字符）"
        placeholder="初始密码（≥2 位）"
```

用户名那处改成 `2~32 字符`，是因为后端这次真的会拒 33 字符的名字了——提示语必须跟上（与 `RegisterModal.vue:21` 的「2~32 个字符」同一个口径）。密码那处只动数字，保持 `≥` 这半边的写法不变。

#### (c) `create()`（第 212~232 行）

```js
// Spec25 §7.2：下限 6 → 2，与后端 auth.MIN_PASSWORD_LEN 同值（跨语言，前端
//   import 不到那个 Python 常量，只能同值副本——**改要一起改**）。
//   上限（用户名 32 / 密码 72）**不在这里判**：规则只有一个地方，在后端；
//   超上限时后端 40010 的 message 会落到下面那行 error 里（§5.3）。
//   ⚠️ pass 不能 trim（密码里的空格是有效字符），name 已经 trim 过——别统一。
async function create() {
  const name = newName.value.trim()
  const pass = newPass.value
  if (name.length < 2 || pass.length < 2) {
    error.value = '用户名至少 2 个字符，密码至少 2 位'
    return
  }
  // ……以下一个字不改
}
```

#### (d) `resetPassword()`（第 234~251 行）

```js
// Spec25 §7.3：与 create() 同一条同值副本（下限 6 → 2）。上限同样交给后端。
async function resetPassword(u) {
  const pass = window.prompt(`为「${u.username}」设置新密码（至少 2 位）：`)
  if (!pass) return
  if (pass.length < 2) {
    error.value = '密码至少 2 位'
    return
  }
  // ……以下一个字不改
}
```

#### (e) 不动的部分

- `contactText()`、`isOverQuota()`、`editQuota()`、`toggleAdmin()`、`remove()`、三个充值处理函数：**一个字不改**。
- `onMounted` 里的 `load()` + `loadRecharges()`：不改（两张表照旧）。
- 第 112~114 行、第 173~174 行、第 326 行、第 333~335 行的墓碑注释：**保留**（§2.7）。
- 文件里**没有** `pendingCount` 的任何残留引用（script 侧早在 Spec23 就删干净了），所以 (a) 删掉模板那行之后，全文件 `grep pendingCount` 应返回**零**。

---

## 6. 接口约定

### 6.1 行为变更：`POST /api/admin/users`（管理端，需管理员）

请求体**不变**（`schemas.AdminCreateUserRequest`：`username` + `password`）。响应体**不变**。错误码**不变**。变的是校验判据与 message：

| 输入 | 改前 | 改后 |
|---|---|---|
| `username` 长度 1 | 40010「用户名至少 2 个字符」 | 40010「用户名需为 2~32 个字符」 |
| `username` 长度 33 | **通过**（建出 33 字符的号） | **40010「用户名需为 2~32 个字符」** |
| `password` 长度 1 | 40010「密码至少 2 位」 | 40010「密码需为 2~72 位」 |
| `password` 长度 73 | 40010「密码至少 2 位」（**误导**） | 40010「密码需为 2~72 位」 |
| `username` 32 / `password` 72 | 通过 | 通过 |
| 用户名重名 | 40901（`DuplicateUsernameError`） | 40901（**不变**） |
| 非管理员调用 | 40301（中间件） | 40301（**不变**） |

### 6.2 行为变更：`PUT /api/admin/users/{id}/password`（管理端，需管理员）

请求体、响应体、错误码均**不变**；只有密码超限时的 message 变了：

| 输入 | 改前 | 改后 |
|---|---|---|
| `password` 长度 1 | 40010「密码至少 2 位」 | 40010「密码需为 2~72 位」 |
| `password` 长度 73 | 40010「密码至少 2 位」（**误导**） | 40010「密码需为 2~72 位」 |
| `password` 长度 2~72 | 通过 | 通过 |
| 用户不存在 | 40408（`UserNotFoundError`） | 40408（**不变**） |

### 6.3 零行为变更：`POST /api/auth/register`（公开）

判据（2~32 / 2~72）与**全部 message**逐字不变。唯一变化是 `main.py:1318` 从字面量改成引用 `auth.MIN_USERNAME_LEN` / `MAX_USERNAME_LEN`——**这是一次纯重构**（§5.3a），§13-A 逐字验它。

### 6.4 不变：其余全部接口

`GET /api/admin/users`、`PUT /api/admin/users/{id}/quota`、`PUT /api/admin/users/{id}/admin`、`DELETE /api/admin/users/{id}`、四条充值管理端路由、以及所有非管理端接口：**零改动**。

---

## 7. 前端交互

### 7.1 顶部提示行（`.admin-tip`）

**改前**（管理员视角）：

```
当前登录：FJ（管理员） · 账号可由管理员创建，或由用户申请后审批开通 · 待审批注册申请  条 · 待审批充值 2 条
```

**改后**：

```
当前登录：FJ（管理员） · 账号可由管理员创建，或由用户自由注册 · 待审批充值 2 条
```

注意改前的「待审批注册申请  条」中间是**空的**（`pendingCount` 是 `undefined`）——这正是用户报告的那个现象。改后**这一整段消失**，同时开发模式控制台里那条 `pendingCount` 的告警也一起消失。

`待审批充值 N 条` 的行为**完全不变**（`pendingRechargeCount` 是活的 `computed`，正常显示数字）。

### 7.2 创建账号表单

- `新用户名（2~32 字符）`、`初始密码（≥2 位）`。
- 点「创建账号」时前端先判：用户名 <2 或 密码 <2 → `error` 行显示「用户名至少 2 个字符，密码至少 2 位」，**不发请求**。
- 前端放过、后端拒绝的情况（用户名 >32 或密码 >72）→ 请求发出，后端 40010 的 message 原文落到 `error` 行（`catch (e) { error.value = e.message … }` 已经就是这么做的，**不用改**）。
- 成功后行为不变：清空两个输入框、`flash` 提示、重新拉用户表。

### 7.3 重置密码

- prompt 文案 `为「x」设置新密码（至少 2 位）：`
- 输入 <2 位 → `error` 行「密码至少 2 位」，不发请求。
- 输入 >72 位 → 后端拒绝，message 落到 `error` 行。
- 取消（prompt 返回 `null`）→ `if (!pass) return` 照旧（`null` 与空串都走这条）。

### 7.4 界面上一句话都不新增

本 Spec 在前端**不新增任何元素**，只删一行、改两行字、改两个 placeholder、改三处数字。没有新的按钮、没有新的面板、没有新的弹窗。

---

## 8. 配置 / 环境变量

**0 个新增、0 个删除、0 个改名。** 本 Spec 不碰 `Server/config.py`（一个字都不改）、不碰 `Server/.env.example`。

⚠️ 特别确认：这次**不新增**任何形如 `USERNAME_MAX_LEN` 的环境变量。32 这个数字是**规则**不是**部署参数**——让它可配置会造出"同一个系统两套规则"，正是 §2.4 要消灭的东西。

---

## 9. 错误码

**0 个新增、0 个删除、0 个改动码值。** 唯一的变化是一句 message 的文字：

| 码 | 类 | 触发 | message（改前 → 改后） |
|---|---|---|---|
| `40010` | `CredentialsFormatError` | 管理端建号 / 重置密码的**密码**超限 | 「密码至少 2 位」→「**密码需为 2~72 位**」（§2.5） |
| `40010` | `CredentialsFormatError` | 管理端建号的**用户名**超限 | 「用户名至少 2 个字符」→「**用户名需为 2~32 个字符**」 |
| `40010` | `CredentialsFormatError` | 登录路由「用户名和密码不能为空」 | **不变**（§2.5 末） |
| `40010` | `CredentialsFormatError` | 管理端建号**新增**触发：用户名 33 字符 | 「用户名需为 2~32 个字符」 |
| `40018` | `RegisterRequestError` | 注册路由 | **不变**（含 §5.3a 那次纯重构之后） |
| `40901` | `DuplicateUsernameError` | 用户名重名 | 不变 |

⚠️ **Spec22 §9 错误码表里 `40010` 那一行的 message 措辞由本 Spec 作废**（§2.5）。实现时不要"为了跟旧表一致"把 message 改回去。

---

## 10. 日志约定

**0 个新增字段。** `logging_setup.py` 的 `JsonFormatter._FIELDS` **零增删**。

两条被改动的路由的既有日志事件与字段一个字不变：

- `POST /api/admin/users` → `auth.admin.create_user`，字段 `request_id` / `username`（操作者）/ `target_user`。
- `PUT /api/admin/users/{id}/password` → `auth.admin.reset_password`，字段 `request_id` / `username`（操作者）/ `target_user`（被重置者的 id）。

失败路径的日志**不新增**：校验失败走 `AppError` 处理器，行为与现在完全一致。

---

## 11. 目录结构增量

**0 个新增文件、0 个删除文件、0 个改名。**

```
Server/
  auth.py            ← 改：+2 个常量（§5.2）
  main.py            ← 改：3 处校验（§5.3a/b/c）
  errors.py          ← 改：1 处 docstring（§5.3d）
  db.py              ← 不改（§2.6、§5.1）
  config.py          ← 不改
  schemas.py         ← 不改
  logging_setup.py   ← 不改
frontend/src/
  views/AdminPanel.vue   ← 改：模板 5 处 + 脚本 2 处（§5.4）
  assets/styles/main.css ← 不改（.tip-pending 仍被用着）
  views/RegisterModal.vue ← 不改
  api/chatApi.js          ← 不改
CLAUDE.md            ← 改：按 §15
specs/Spec25.md      ← 本文件
```

⚠️ **`Server/artcn.db` 零改动**：不新增列、不新增表、不跑任何迁移。本 Spec 是**纯代码**收口。

⚠️ `Server/static/` 是构建产物：按本仓惯例，前端改动之后要 `npm run build` 并**把新版一起 `git add -A` 提交**（旧哈希文件被删、新哈希文件是 untracked，`Server/static/index.html` 已指向新哈希——只 `git commit -am` 会留下一对不存在的 JS/CSS，单端口跑法直接白页）。

---

## 12. 实施顺序（里程碑）

1. **`Server/auth.py`** 加两个常量（§5.2）。
2. **`Server/main.py`** 三处校验（§5.3a → b → c）。**先跑一次后端**，确认服务能起、注册与登录照常（这一步能立刻抓到循环引用 / 名字写错这类硬错误）。
3. **`Server/errors.py`** docstring（§5.3d）。
4. **跑 §13-A / §13-B**（后端行为）。这两组**不依赖前端构建**，先过掉。
5. **`frontend/src/views/AdminPanel.vue`** 七处（§5.4）。
6. `cd frontend && npm run dev` → 跑 §13-C（界面）。
7. `cd frontend && npm run build` → **`git add -A`**（含 `Server/static/` 的新哈希产物）。
8. 按 §15 改 `CLAUDE.md`。

---

## 13. 验收用例（端到端 Smoke）

### 前置

- 本 Spec **不改 DB 结构**，但**会真的建号、真的改密码**——所以**必须拿库副本跑**，不要拿 `Server/artcn.db` 真库跑（建出来的 `spec25_*` 测试号会永远留在用户列表里）。
- 复用本仓既有的烟测骨架（`%TEMP%` 里那套 `acn_smoke*.py`：复制库副本 + 把 `mailer.send_*` 换成桩）。**本 Spec 全链路不发任何邮件**（建号与重置密码都不发信），所以 `SMTP_PASSWORD` 配没配都无所谓——但**别拿真库跑**这条仍然成立。
- 浏览器/curl 一律用 **`127.0.0.1`，不要用 `localhost`**（本机 `localhost` 先解析到 `::1`，每个请求白等约 2 秒；它不会让断言失败，只会让"响应够快"这类用例变成假阴性）。
- 管理员 token：脚本自己给**库副本**里的管理员换一个临时口令（用仓库自己的 `auth.hash_password`），**不要**去读 `Server/.env` 的 `ADMIN_PASSWORD`——那只在 users 表为空时用来建初始号。
- ⚠️ **限速用例排最后**：登录限速按 IP 计、窗口 300 秒。本 Spec 的用例**不含**限速用例，所以别在它前面跑任何"连错 5 次"的东西。

```bash
BASE=http://127.0.0.1:8000
TOKEN=...   # 库副本管理员的 JWT，见上
AUTH="Authorization: Bearer $TOKEN"
JSON="Content-Type: application/json"
```

### A. `POST /api/auth/register` 逐字不变（**纯重构的回归，先跑这条**）

这是本次唯一动了注册路由的地方，必须先证明它没变。

```bash
# A-1 用户名 33 字符 → 40018，message 逐字
curl -s -X POST $BASE/api/auth/register -H "$JSON" \
  -d "{\"username\":\"$(python -c 'print("a"*33)')\",\"password\":\"12\",\"email\":\"a@b.c\",\"code\":\"1234\"}"
# 期望 {"code":40018,"message":"用户名需为 2~32 个字符","data":null}

# A-2 用户名 1 字符 → 40018，同一句话
curl -s -X POST $BASE/api/auth/register -H "$JSON" \
  -d '{"username":"a","password":"12","email":"a@b.c","code":"1234"}'
# 期望 {"code":40018,"message":"用户名需为 2~32 个字符","data":null}

# A-3 密码 1 位 → 40018「密码需为 2~72 位」
curl -s -X POST $BASE/api/auth/register -H "$JSON" \
  -d '{"username":"spec25_reg","password":"1","email":"a@b.c","code":"1234"}'
# 期望 {"code":40018,"message":"密码需为 2~72 位","data":null}

# A-4 密码 73 位 → 40018「密码需为 2~72 位」（同一句，方向正确）
curl -s -X POST $BASE/api/auth/register -H "$JSON" \
  -d "{\"username\":\"spec25_reg\",\"password\":\"$(python -c 'print("a"*73)')\",\"email\":\"a@b.c\",\"code\":\"1234\"}"
# 期望 {"code":40018,"message":"密码需为 2~72 位","data":null}

# A-5 git diff 只该有 4 行
git diff Server/main.py | grep -A6 -B2 "MIN_USERNAME_LEN"
# 期望：注册路由那处只有 if 与 raise 两行变了；该路由**没有别的改动**
```

### B. 管理端建号 / 重置密码的新判据

```bash
# B-1 密码 2 位 → 成功（改前前端根本发不出去，后端本来就接受）
curl -s -X POST $BASE/api/admin/users -H "$AUTH" -H "$JSON" \
  -d '{"username":"spec25_u2","password":"12"}'
# 期望 {"code":200,...,"data":{"id":N,"username":"spec25_u2","is_admin":false}}

# B-2 密码 1 位 → 40010，且 message 是**新**那句
curl -s -X POST $BASE/api/admin/users -H "$AUTH" -H "$JSON" \
  -d '{"username":"spec25_u1","password":"1"}'
# 期望 {"code":40010,"message":"密码需为 2~72 位","data":null}

# B-3 密码 73 位 → 40010，**同一句话**（改前是误导的"密码至少 2 位"）
curl -s -X POST $BASE/api/admin/users -H "$AUTH" -H "$JSON" \
  -d "{\"username\":\"spec25_u73\",\"password\":\"$(python -c 'print("a"*73)')\"}"
# 期望 {"code":40010,"message":"密码需为 2~72 位","data":null}

# B-4 用户名 32 字符 → 成功
curl -s -X POST $BASE/api/admin/users -H "$AUTH" -H "$JSON" \
  -d "{\"username\":\"$(python -c 'print("u"*32)')\",\"password\":\"12\"}"
# 期望 code 200，data.username 是那 32 个字符

# B-5 ⚠️ 用户名 33 字符 → **改前会成功、改后必须 40010**（本 Spec 的核心行为变更）
curl -s -X POST $BASE/api/admin/users -H "$AUTH" -H "$JSON" \
  -d "{\"username\":\"$(python -c 'print("u"*33)')\",\"password\":\"12\"}"
# 期望 {"code":40010,"message":"用户名需为 2~32 个字符","data":null}

# B-6 用户名 1 字符 → 40010，message 与 B-5 相同
curl -s -X POST $BASE/api/admin/users -H "$AUTH" -H "$JSON" \
  -d '{"username":"u","password":"12"}'
# 期望 {"code":40010,"message":"用户名需为 2~32 个字符","data":null}

# B-7 重置密码：2 位成功，1 位 40010，73 位 40010 同一句
UID=...   # B-1 建出来的那个 id
curl -s -X PUT $BASE/api/admin/users/$UID/password -H "$AUTH" -H "$JSON" -d '{"password":"34"}'
# 期望 {"code":200,...}
curl -s -X PUT $BASE/api/admin/users/$UID/password -H "$AUTH" -H "$JSON" -d '{"password":"3"}'
# 期望 {"code":40010,"message":"密码需为 2~72 位","data":null}

# B-8 用 B-7 设的新密码登录 → 成功（证明 2 位密码真的可用，不只是"接口收了"）
curl -s -X POST $BASE/api/auth/login -H "$JSON" \
  -d '{"username":"spec25_u2","password":"34"}'
# 期望 code 200，data 里有 token

# B-9 建出来的号**没有邮箱**（用户选定的口径，§0 表格 A 行 / §3.3-1）
curl -s $BASE/api/admin/users -H "$AUTH" | python -c "import sys,json;print([u for u in json.load(sys.stdin)['data'] if u['username']=='spec25_u2'][0])"
# 期望 email 是 None（管理端显示「无」）
```

### C. 管理端界面

```bash
cd frontend && npm run dev     # 浏览器用 127.0.0.1:5173
```

1. 管理员登录 → 打开「用户管理」面板。
2. **顶部提示行**：`grep -c 'tip-pending">待审批注册申请' frontend/src/views/AdminPanel.vue` → **0**。
   - ⚠️ **不能**用裸的 `grep -c "待审批注册申请"`——那个会数到 **1**，命中的是本 Spec 自己写进 `AdminPanel.vue` 的那条墓碑注释（§5.4a 的注释里逐字引了这句文案）。判据必须落在**模板绑定**上，不能落在"文件里有没有这几个字"：§2.7 说了墓碑注释要保留，两条要求放在一起，裸 grep 就必然不是 0。**这是实现时实测发现的**，原始判据写松了。
   - 界面上那句是 `当前登录：FJ（管理员） · 账号可由管理员创建，或由用户自由注册 · 待审批充值 N 条`。
   - `待审批充值 N 条` **仍然正常显示数字**：`grep -c '{{ pendingRechargeCount }}' frontend/src/views/AdminPanel.vue` → **1**（它必须还在——这条同时证明模板没被删过头）。
3. **控制台零告警**：打开面板，DevTools Console 里**没有** `pendingCount` 相关的 `property ... was accessed during render but is not defined` 告警。
   - 对照：改之前这条告警**一定在**。
   - **不开浏览器也能验**（等价判据，两步一起看）：告警的成因是编译后的渲染函数里留下了 `_ctx.pendingCount` 这个属性访问（§2.1）。所以判据落在**编译产物**上，不落在"文件里有没有这几个字"上：
     - **(a) 编译侧（主判据，自证不空转）**：对模板做一次 `compileTemplate`，数渲染函数里 `_ctx.pendingCount` 的出现次数 → **0**；把被删那行加回去再编译一次 → **1**。判据会翻转，说明它测的是真东西，不是一条恒真的 grep。
       ```bash
       cd frontend && node -e "
       const fs=require('fs');const {parse,compileTemplate}=require('vue/compiler-sfc');
       const c=s=>compileTemplate({source:parse(s).descriptor.template.content,filename:'a.vue',id:'x'}).code;
       const src=fs.readFileSync('src/views/AdminPanel.vue','utf8');
       const n=(s,re)=>(c(s).match(re)||[]).length;
       console.log('_ctx.pendingCount =', n(src,/_ctx\.pendingCount/g));                                    // 期望 0
       console.log('反证：加回那行 =', n(src.replace('或由用户自由注册','待审批注册申请 {{ pendingCount }} 条'),/_ctx\.pendingCount/g));  // 期望 1
       "
       ```
     - ⚠️ **正则必须是 `_ctx\.pendingCount`，不能是裸的 `pendingCount`**：`compileTemplate` **默认保留 HTML 注释**，所以裸数 `/pendingCount/g` 会数到 **1**——命中的是本 Spec 自己写进模板的那条墓碑注释（§5.4a 逐字引了 `pendingCount`），**不是**插值。这与第 2 条那个裸 grep 的坑是同一个坑的第二次出现：墓碑注释按 §2.7 必须留，判据就必须避开注释文本。
     - **(b) 构建产物（旁证）**：`grep -c pendingCount Server/static/assets/index-*.js` → **0**。这条**是**有效证据（理由见下），但**不够**当主判据——它是"事后看不见"，而不是"编译器不会生成"。
     - ⚠️ **产物 grep 不能配一条"且 `pendingRechargeCount` ≥1"的反向校验**——那是**错的**，**这是实现时实测发现的**：`<script setup>` 的绑定在压缩时会被**改名**，`pendingRechargeCount` 在产物里是 **0**；而 `pendingCount` 当年是**未绑定标识符**，编出来的是 `_ctx.pendingCount` 这个**属性名**，属性名不参与改名。**同一条 grep 对两者含义不同**，拿后者给前者当上界校验，等于把"改了名"误读成"被删了"。原文写的"（且 `pendingRechargeCount` ≥1）"期望值本身就是错的，已删。
4. `grep -c '{{ pendingCount }}' frontend/src/views/AdminPanel.vue` → **0**（活的绑定没了）。
   - ⚠️ 同样**不能**用裸的 `grep -rn "pendingCount" frontend/src/`——那个会数到 **2**：一条是 Spec23 §7.6 留下的墓碑注释（`requests / busyRegId / pendingCount`），一条是本 Spec §5.4a 新写的那条。两条都按 §2.7 有意保留。
5. **创建账号**：
   - placeholder 是 `新用户名（2~32 字符）` 与 `初始密码（≥2 位）`。
   - 用户名 `ab` + 密码 `12` → **创建成功**（改前前端会拦下并显示"密码至少 6 位"）。
   - 用户名 `ab` + 密码 `1` → error 行显示「用户名至少 2 个字符，密码至少 2 位」，且**没有网络请求**（DevTools Network 面板无 `POST /api/admin/users`）。
   - 用户名 33 字符 + 密码 `12` → 请求发出，error 行显示后端回的那句「**用户名需为 2~32 个字符**」。
6. **重置密码**：点「重置密码」→ prompt 文案是 `为「x」设置新密码（至少 2 位）：`；输入 `12` → 成功；输入 `1` → error 行「密码至少 2 位」，无请求。
7. **回归**：充值台账那一块的「同意 / 拒绝 / 删除」三个动作**照常可用**；`.tip-pending` 的紫色样式仍在（说明 CSS 没被连带删掉）。

### D. 回归（**别把没要求改的改坏了**）

```bash
# D-1 后端改动面只有 3 个文件
git diff --stat Server/
# 期望恰好：Server/auth.py、Server/main.py、Server/errors.py（+ Server/static/ 的构建产物）
# 出现 db.py / config.py / schemas.py / logging_setup.py 的任何改动都是做错了
# ⚠️ 输出里**还会**多一行 `Server/agents/prompts.py | 2 +-`——那是 **Spec24 的**
#    一行文案（CLAUDE.md 已记），不是本 Spec 的。本 Spec 的判据是：
#    用 `grep -rl "Spec25"` 枚举实际改动面 → 恰好这 3 个 .py + 1 个 .vue + specs/Spec25.md + CLAUDE.md。

# D-2 _FIELDS 零增删
git diff --stat Server/logging_setup.py
# 期望：空

# D-3 config.py 一个字没动（尤其没有新环境变量）
git diff --stat Server/config.py
# 期望：空

# D-4 CSS 没被连带删
git diff --stat frontend/src/assets/styles/main.css
# 期望：**没有 Spec25 的改动**（判据见下）。
# ⚠️ 字面期望「空」在**当前工作区不成立**：Spec24 尚未提交，main.css 里躺着它的
#    .btn-login-entry / .login-overlay / .login-state / .login-back（39 insertions / 1 deletion）。
#    所以判据只能是"逐字搜 Spec25"——**这是实现时实测发现的**，原始判据写松了。
#    与 CLAUDE.md 里 Spec24 §13-A-1 那条「验收命令要按意图读」是同一类问题。
git diff -- frontend/src/assets/styles/main.css | grep -c "Spec25"
# 期望 0（我把 Spec25 的说明写进了 .vue 的注释，没写进 CSS）
grep -c "tip-pending" frontend/src/assets/styles/main.css
# 期望 ≥1（下面那行还在用）

# D-5 管理端其余动作不受影响
curl -s -X PUT $BASE/api/admin/users/$UID/quota -H "$AUTH" -H "$JSON" -d '{"quota_limit":10}'
# 期望 code 200
curl -s $BASE/api/admin/users -H "$AUTH" | head -c 120
# 期望 code 200，用户表正常返回（email / created_at_beijing 都在）

# D-6 初始管理员的闸没被"顺手统一"
grep -n "len(password) < 6" Server/db.py
# 期望仍存在（§2.6）
grep -n "MIN_USERNAME_LEN\|MAX_USERNAME_LEN" Server/db.py
# 期望：0 命中（db.py 不引用 auth 的常量）
```

### E. 构建产物

```bash
cd frontend && npm run build
cd .. && git status --short Server/static/
# 期望：两个新哈希的 assets/* 是 ??（untracked）、index.html 是 M
# 提交时必须 git add -A，否则单端口跑法白页（§11）
```

---

## 14. 陷阱清单（**实现时逐条对照**）

1. **⚠️ `.tip-pending` 的 CSS 一行都不许删。** 「待审批注册申请」那行删掉之后，正下方的「待审批充值」还在用同一个类名。删任何 CSS 之前先 `grep tip-pending frontend/src/assets/styles/main.css`。这与 Spec23 §14 陷阱 1 是同一条陷阱的第二次出现。
2. **⚠️ 删模板那行之前，先确认 script 侧真的没有 `pendingCount` 了。** 现在的状态是"script 删了、模板漏了"——反过来的情况（两个都在）会让删除变成"删了一个还在用的变量"。落刀前 `grep -n pendingCount frontend/src/views/AdminPanel.vue` 应当**只有模板那一行**。
3. **⚠️ `main.py:1318`（注册路由）是本次唯一"改了但行为必须不变"的地方。** 它是 Spec23/24 之后第一次被动。该路由的 diff 应该**只有 `if` 与 `raise` 那 4 行**——多出任何一行都要停下来问为什么。
4. **⚠️ 两处密码 message 必须逐字相同**（建号 `main.py:1769` 与重置 `main.py:1837`）。它们是同一条规则的两个出口，抄错一个就会出现"同样是密码超限，两个接口说法不同"。
5. **⚠️ 不要给 `db.create_initial_admin` 的 ≥2 / ≥6 加 `auth.` 前缀。** 那两道是部署者口令的防呆线（Spec22 §2.10 已记），而且 `db.py` 对 `auth` 是**函数内延迟 import**——加了要么循环引用，要么被"顺手"提成顶层 import，两条都是错的（§2.6）。
6. **⚠️ 不要新增 `USERNAME_MAX_LEN` 之类的环境变量。** 32 是规则不是部署参数（§8）。
7. **⚠️ 不要把前端的 `2` 改成"从后端拿"。** 那要走一条新的公开配置接口或在构建期注入，为一个数字不值当；本仓对跨语言同值副本的既定做法是"留一份 + 注释写明"（§2.3）。
8. **⚠️ `pass` 不能 trim。** `create()` 里 `name` 已经 `.trim()`，`pass` 没有也不许有——密码里的空格是有效字符（§3.3-4）。
9. **⚠️ 别去清理 Spec23 留下的墓碑注释。** `# Spec23 §7.6 删除：…` 这类注释是有意保留的（§2.7）。本 Spec 只重写 `AdminPanel.vue:7-8` 那一条，因为它描述的是它正下方那三行。
10. **⚠️ 别把 `40010` 的 message 改回「密码至少 2 位」以求"跟 Spec22 §9 一致"。** 那张表的那一行**由本 Spec 作废**（§2.5、§9）。
11. **⚠️ 验收必须用库副本。** 本 Spec 会真的建号、真的改密码；拿 `Server/artcn.db` 真库跑，测试号会永远留在用户列表里，而且会真的改掉某个账号的密码。
12. **⚠️ 改完前端记得重建 `Server/static/` 并 `git add -A`。** 新哈希文件是 untracked，漏了它单端口跑法白页（§11）。

---

## 15. 收尾：`CLAUDE.md` 要改的段落

| 位置 | 怎么改 |
|---|---|
| 「重要陷阱」里那条 **⚠️ 已知不一致：`AdminPanel.vue` 的「创建账号」与「重置密码」两处前端校验/提示仍写死「至少 6 位」…** | **整条替换**。它记的是本 Spec 消除的问题。换成：管理端三处字面量已跟 `auth.MIN_PASSWORD_LEN` 对齐（Spec25），并注明**那三处是跨语言同值副本，改 `MIN_PASSWORD_LEN` 要一起改**。 |
| 「配置」段或「重要陷阱」段（`auth.MIN_PASSWORD_LEN` 那条附近） | **补一句**：用户名长度的唯一来源是 `auth.MIN_USERNAME_LEN = 2` / `MAX_USERNAME_LEN = 32`，注册路由与管理端建号路由**都引用它**（Spec25 §2.4）；`db.create_initial_admin` 的 ≥2 与 ≥6 **故意不跟着走**（部署者口令的防呆线，且 `db.py` 对 `auth` 是延迟 import）。 |
| 「后端 (`Server/`)」的 `main.py` 条目 | 补一句：管理端建号 / 重置密码的密码 message 在 Spec25 与注册那条对齐成「密码需为 2~72 位」——**Spec22 §9 错误码表里 40010 那一行的措辞由此作废**，码本身没变。 |
| 「前端」条目里 `AdminPanel.vue` 的描述 | 若提到顶部提示行，更新为「账号可由管理员创建，或由用户自由注册」；并记一条：**「待审批注册申请 N 条」那行在 Spec25 删除**——它是 Spec23 删 script 侧 state 时漏掉的模板引用（`pendingCount` 一直是 `undefined`）。 |
| 「模型权重已删除」「API's Usage」「storage/」等段 | 不动。 |
| 「Commands」「Deployment」 | 不动。 |
