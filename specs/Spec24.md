# ArtiControlNet Spec 24：登录后置、未登录暂存与顶部横条改版

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：**把"没登录就整页登录页"改成"游客先看到界面，碰到会落后端的动作才弹登录"**；被拦下的内容（文字 + 图片）暂存 3 分钟，登录成功或从登录层返回时回填进输入框；顺带把顶栏那句带用户名的副标题换成恒定文案，并加一行登录状态。
> 本 Spec 是 **Spec.md / Spec2~23 的增量补充**，**不推翻任何既有 Spec**。
> **`Server/` 目录一个字节不改**——不加公开接口、不动 `PUBLIC_AUTH_PATHS`（仍是 10 条）、不动 `artcn.db`、不动日志字段白名单。
> **新增 1 个前端文件**（`utils/pendingRequest.js`）、**新增 1 个前端组件**（`components/LoginGate.vue`）。
> **0 个新增环境变量**、**0 个新增依赖**、**0 个新增后端文件**、**0 个新增错误码**。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有凭据只在后端环境变量、除 `artcn.db` 外无其他数据库。
> ⚠️ 唯一一处**引入新浏览器 API**：图片暂存用 IndexedDB（§2.4 说明为什么 `localStorage` 不行）。

---

## 0. 两件事一览（用户原话 → 落点）

| # | 用户原话 | 本 Spec 的落点 |
|---|---|---|
| 1 | 「登录界面后置……用户一进来，可以先看到 主聊天、社区、我跑的作品、建议等全部普通用户页面（如果用户试图打开管理员界面 url，必须立马跳登录界面）」 | §2.1~§2.3、§2.10、§5.2、§5.3、§5.5、§7.1、§7.4 |
| 2 | 「未登录用户点击『新对话、发送需求』等内容，先用 localstorage 等技术把未登录用户发送的需求（以及上传的图片）暂存下来（……大概 3 分钟吧），然后跳登录界面」 | §2.4~§2.7、§5.4、§5.6、§5.7、§5.9、§7.5、§7.6 |
| 3 | 「只有登录用户，才可以发送聊天需求、社区发帖、看到自己的作品、以及提建议、发送充值等」 | §3.1 门禁清单（§7.1 逐条落点） |
| 4 | 「不要在『赋能设计的 AIGC 系统 · admin』显示用户名字了，这句话直接全删，改成恒定『AI辅助设计的系统』」 | §7.2、§7.7 |
| 5 | 「然后在上面大横条设计一个登录状态提示。登录状态只显示『目前登录：未登录/<用户名>』」 | §7.2 |

### 用户在答复里改的口径（**实现时按这一列，不要按上面那列的字面**）

用户在两轮澄清里逐条选了口径。**下表每一行都是用户明确点过的选项**，不是本 Spec 的推断。

| # | 原话的字面 | 改成 | 为什么 |
|---|---|---|---|
| 1-a | 「先看到……全部普通用户页面」 | 页面**外壳**可见，**内容不可见**：社区/我的作品/建议三个面板对游客**整个不挂载**，原位换成一块登录门 | 用户在四选一里选了「只看得到空页 + 登录提示（后端零改动）」。原字面也可以读成"社区内容对人类游客只读开放"，但那样要新增 2 条公开读接口、把匿名可访问他人上传的图片这件事坐实，用户没选那条。 |
| 1-b | 「管理员界面 url」 | **不引 URL 路由**，只保证管理员入口对非管理员/游客一律不渲染、任何管理动作前都过登录 | 全站**没有 vue-router**，六个面板全靠 `v-if` 切状态（唯一的 URL 消费者是 `Login.vue` 的 `?register=1`）。用户在有 URL 路由与无 URL 路由之间选了「不引路由」。§1.3 记了这条推翻的是什么。 |
| 2-a | 「暂存大概 3 分钟」 | 暂存**有效期 3 分钟**，从被拦下那一刻起算 | 字面。过期后 `takeRequest()` 返回 `null`，内容不再回填（§2.5）。 |
| 2-b | 「先用 localstorage 等技术」 | 文本 + 元数据进 `localStorage`；**图片进 IndexedDB** | 用户在两选一里选了「图片走 IndexedDB」。`localStorage` 的配额（约 5MB）装不下输入框允许的 10MB 图，转 base64 还要再涨 33%——**大部分真实照片会静默写失败**（§2.4）。 |
| 2-c | 「（以及上传的图片）暂存下来」 | 点输入框的 🖼 **不拦**；统一在点「发送」时拦，此时文字与图片一起暂存 | 用户在两选一里选了「允许先选图，点发送时统一拦」。好处是不会出现"只存了图"这种半截状态。 |
| 2-d | 「然后跳登录界面」→ 登录之后呢 | **回填到输入框**，用户自己再点一次「发送」 | 用户在两选一里选了「回填到输入框」（**不是**自动发出）。所以本 Spec **不实现任何自动重放**——这条很容易被"顺手优化"掉，§14 列了它。 |
| 2-e | 「新对话」也是拦截点 | `ConversationSidebar` 加 `guest` prop，游客时「＋ 新对话」**可点**且点了弹登录 | 该按钮现在是 `:disabled="currentId === null"`（`ConversationSidebar.vue:7`），而游客的 `currentConvId` **恒为 null** → 按钮是灰的、**点不动** → 用户点名的这条根本触发不了。必须一起改（§5.7、§14 陷阱 4）。 |
| 4-a | 「这句话直接全删，改成恒定『AI辅助设计的系统』」 | `App.vue` 的 `.brand-sub` 变成常量字符串，**不再插值 `auth.username`** | 字面。「全删」删的是那句话里的用户名插值。 |
| 4-b | 同一个短语在别处还有 4 处 | **五处一起改**（`App.vue` / `Login.vue` / `index.html` / `README.md` / `Server/agents/prompts.py`） | 我在设计稿里把 5 处列出来问了范围，用户答「按你的来」= 按我给的推荐（统一改）。§7.7 有逐处清单；`GithubPage/assets/hero-banner.jpg` 是**图片**、改不了，§3.3 记了。 |
| 5-a | 「登录状态只显示『目前登录：未登录/<用户名>』」 | 文案照抄；游客时**额外**给一个「登录」按钮 | 「只显示」管的是那句状态文案的字面，不是"整个横条只许有一个元素"——不给游客主动登录入口，他就只能靠被拦下才能登录。§7.2 画了横条布局。 |

---

## 1. 功能目的

### 1.1 为什么现在做

- **现在这个漏斗的第一屏是一堵墙。** `App.vue:6` 是 `v-else-if="!auth.token"` → 整页 `<Login/>`。任何人打开站点，在他看到这个产品长什么样、能干什么之前，先被要求"交出用户名密码"——**而他对这个产品的全部认知只有一张登录卡**。
- **这个产品的说服力全在"看得见的东西"上**：文生图、线稿上色、社区里别人做出来的图。让游客先看到这些（哪怕社区对他们只是一个空壳），比在登录页上写十行介绍有用。
- **被拦下时机的选择，决定流失发生在哪一步。** 现在的拦法是在"进门"那一刻；改成在"他真的想做点什么"那一刻之后，**用户至少已经知道自己在放弃什么**。这不是转化率话术，是"让人知道自己错过了什么"的基本尊重。
- **游客会有"打了一半被弹走"的挫败**，所以暂存是这次改造的必配项而不是加分项：用户打了一段字、点了发送、看到登录页、**点返回**——如果字没了，那次交互就是纯损失。§5.9 的两条恢复路径里，**第二条（返回也回填）比第一条更重要**。
- **顶栏那句 `赋能设计的 AIGC 系统 · {{ auth.username }}` 是个设计失误**：它把"品牌定位"和"当前身份"塞进同一个位置，于是两个人看到的是两句不同的话，而**访客看到的是「· 」后面空着**（未登录时 `auth.username` 是空串，屏幕上只剩一个孤零零的分隔点）。拆成"恒定品牌句 + 独立状态位"两件事之后，两句话各自都能被独立地改、独立地读。

### 1.2 一句话架构

**`App.vue` 的 `!auth.token → 整页 Login` 这一支删掉；游客照常进 `.app` 外壳，六个面板由一个新的 `activePanel` 计算属性分发（游客一律落到 `<LoginGate>` 而不是任何一个面板组件）；登录层变成外壳的兄弟节点 `<Login v-if="showLogin" class="login-overlay" />`，被拦下的内容经 `utils/pendingRequest.js`（文本 → localStorage，图片 → IndexedDB）在登录层关闭或登录成功时回填进 `ChatInput`。**

### 1.3 与既有 Spec 的关系（**本 Spec 推翻的东西**）

| 既有件 | 本 Spec 怎么动它 |
|---|---|
| **`App.vue` 的「未登录 → 整页登录页」**（Spec2 起） | **推翻**。登录页从"唯一入口"降级成"一个可开关的覆盖层"。`App.vue:6` 那一行 `v-else-if="!auth.token"` 删除。 |
| **Spec21 §7.4「被踢出时自动弹充值面板」** | **保留，但必须补一行**（§2.8）。原来"被踢 → 登出 → 自动落到整页登录页 → Login.vue 挂载 → 弹面板"这条链，靠的是"登出即回登录页"这个副作用。登录页不再是唯一去处之后，**必须显式地 `showLogin = true`**，否则整条链断掉、面板永不出现、提示语变成空头支票。 |
| **Spec21 §7.4 那句「若您单击登录键则会跳出充值面板」** | **文案不改**，行为也不改（被踢仍自动弹）。这条与用户既有的"明知不完全对应仍选择如此"（见 CLAUDE.md gotcha）一致——本 Spec 不动它，只是**保证它仍然成立**。 |
| **Spec22 §2.9 的 `login_page` 埋点** | **语义漂移，但实现不动**。它原来只在"落地到登录页"时触发一次；现在每次打开登录层都触发。`click_events` 有 `UNIQUE(event, ip)`，所以**库里同一个 IP 仍然只有第一行、只打第一条日志**（Spec22 §2.9），统计口径一个数字都不会变。 |
| **Spec17 §7.3 的 `resetForUser(null)` 早退分支** | **保留，而且变得更关键**。游客每进一次站点都会走它；它那句 `if (!this.username) return` 是"游客不调任何列表接口"的唯一保险（§14 陷阱 13）。 |
| **Spec2 的鉴权中间件 / `PUBLIC_AUTH_PATHS`** | **一个字不动**。仍 10 条，仍精确匹配。**本 Spec 没有新增任何公开接口。** |

---

## 2. 决策记录（为什么这么选）

### 2.1 登录页从"整页替换"变成"覆盖层"（外壳 DOM 必须继续挂载）

`App.vue` 现在的模板是个三分支链，其中第二支 `v-else-if="!auth.token"` 会把整个 `.app` **换成** `<Login/>`。改成覆盖层，有三个各不相同的理由，缺一个都不行：

1. **回填需要一个还活着的落点。** 回填的终点是 `ChatInput` 组件里的局部 `text`/`file` ref（§5.6）。如果登录时 `.app` 被卸载、登录成功后再重建，那么"回填"就变成了"跨挂载周期传值"，得额外做一套状态提升；而 **`ChatInput` 挂着的时候，一切都是一次 prop 赋值**。
2. **五个面板的开关状态不该被打断。** 游客点「社区」→ 登录门 → 点「登录」→ 登录成功，期望是**落在社区里**。`showCommunity` 这个 ref 在 `.app` 里；`.app` 被卸载一次，它就没了。
3. **对话 store 不该被无谓地重置一次。** `store.resetForUser()` 会清 `clearAuthedImageCache()`、重拉对话列表；游客态下它本来就是空跑，没必要在登录前后被触发两次。

实现上只需要给 `Login.vue` 的根元素加一个类（Vue 会把 `class` 合并到只有一个根节点的子组件上）：

```html
<Login v-if="showLogin" class="login-overlay" @close="onLoginClose" />
```

`main.css` 加三条规则（§7.7）。`.login-page` 原本是 `height: 100%` + flex 居中——它原本的语境是"整个 body 里只有它"，套上 `position: fixed; inset: 0` 之后，`height: 100%` 仍然成立（定位元素的包含块是视口），**`.login-card` 一个字节不用动**。

### 2.2 门禁是前端的，后端一个字节不改

本 Spec **不改 `Server/` 的任何文件**。这不是省事，是这次需求的形状决定的：

- 用户要的是"**页面看得见、动作做不了**"。页面归前端管；后端本来就对游客返 40103，它的行为已经是对的。
- 一旦为了让游客"读到点东西"而把 `/api/community` 之类加进 `PUBLIC_AUTH_PATHS`，就等于**把匿名可访问他人上传的图片**这件事坐实（社区图片走 `/api/community/{id}/image`）。用户明确没选那条。
- 反过来，"什么算敏感动作"是**产品决策**，它会变（下次可能就想让游客只看得到社区了）。把它放在前端 = 下次改一个 `activePanel` 计算属性；放在后端 = 改中间件白名单 + 重新部署。

**所以本 Spec 的验收里有一条硬判据：`git diff --stat Server/` 必须为空**（§13-A）。

### 2.3 面板"不挂载"而不是"挡住内容"

这是本次最容易写错的一处。直觉做法是"面板照常挂载，只是内容区显示登录提示"，**那样每个游客一进页面就会触发一次全局登出**：

```
游客点「社区」→ CommunityPanel 挂载 → onMounted → load() → GET /api/community
             → 中间件无 token → 40103
             → chatApi.js 响应拦截器：resp.status === 401 && !url.includes('/api/auth/login')
             → clearToken() + window.dispatchEvent(new Event('artcn:unauthorized'))
             → App.vue 的监听器：auth.logout() + closeAllPanels()
             → 面板当场关掉，游客看到的是"点了没反应"
```

五个面板的 `onMounted` **全部**会立刻发请求（`GalleryPanel.vue:723`、`CommunityPanel.vue:503`、`SuggestionPanel.vue:262`、`AdminPanel`/`StatsPanel` 同理）。所以门禁必须做在**挂载之前**。

实现：不再用五个并列的 `v-if`，改成**一个计算属性分发**（§5.2）。这比"给每个 `v-if` 补一个 `&& !isGuest`"更好，因为它是**穷尽且互斥**的——`activePanel` 的返回值恰好命中一个分支，不存在"所有分支都不匹配导致空白"这种状态。

### 2.4 暂存介质：文本 → `localStorage`，图片 → IndexedDB

用户说"用 localstorage 等技术"，并给了自由度（"等"）。**图片不能进 `localStorage`**，这不是洁癖，是会静默错的：

| | 数字 |
|---|---|
| `localStorage` 配额（Chrome / Safari 同源） | 约 **5MB**（字符数，UTF-16 下还要翻倍算） |
| `ChatInput` 允许的单图上限 | **10MB**（`ChatInput.vue` 的 `acceptFile`） |
| 10MB 图转 base64 后 | 约 **13.3MB** |
| 结论 | **超过 5M 的图必然 `QuotaExceededError`**，而 `setItem` 抛异常时如果被 `try{}catch{}` 吞掉，用户看到的是"登录后什么都没回来"——**和"没暂存过"一模一样**，无法区分 |

`IndexedDB` 原生支持直接存 `Blob`（不需要 base64、不需要转码、容量按磁盘配额走），代价是异步 API。**本 Spec 只在这一个地方引入它**，并且：IDB 不可用（隐私模式、被策略禁用、`onblocked`）时**降级为"只暂存文字"**，而不是整体失败。

两处存储的分工是**故意的**：文本走 `localStorage` 是**同步**的，所以它先落盘——即使 IDB 那一半挂了，用户打完的字也已经安全了。

### 2.5 3 分钟 TTL 只在 `takeRequest()` 里判一次

`TTL_MS = 3 * 60 * 1000` 定义在 `utils/pendingRequest.js`，**只在 `takeRequest()` 里读一次 `Date.now() - meta.ts`**。两条恢复路径（登录成功 / 从登录层返回）共用同一个函数，所以判据只有一处。

**这条 TTL 的实际效果要说清楚**（它是用户"大概 3 分钟吧"的字面结果）：

- 正常路径（点发送 → 登录 → 几秒内完成）永远碰不到它。
- 它真正拦的是**跨页面生命周期**的僵尸暂存：游客打了字 → 关了标签页 → 3 分钟后同一个人（或同一台机器的下一个人）打开站点并登录 → 不判过期的话，一段三天前的文字会莫名其妙出现在输入框里。
- **代价（要认）**：登录层开着超过 3 分钟再关掉/再登录，暂存已过期 → 内容不回填。§3.3 记了这条。

### 2.6 回填走 prop + 事件，`ChatInput` 保持哑组件

`ChatInput.vue` 现在是个纯展示组件：只有 `disabled` 一个 prop、只 emit `send`、**不 import 任何 store**。回填有两条路可走：

- **在 `ChatInput` 里 import `useChatStore`**——破坏它的哑组件性质，而且回填这个动作与"对话"无关（游客根本还没有对话）。
- **prop 进、事件出**（本 Spec 选的）：`draft` prop（`{text, file}` 或 `null`）+ `draft-consumed` 事件。父组件持有 `draft` ref，子组件消费完通知父组件清空。

**`watch` 必须带 `{ immediate: true }`**，这一条不能省：游客从**面板那一路**登录成功时（点「社区」→ 登录门 → 登录），`main-col` 里占位的是 `CommunityPanel`，**`ChatInput` 根本没挂载**；`draft` 先落进 `App.vue` 的 ref 里待着，等用户切回聊天视图、`ChatInput` 挂载那一刻才消费。没有 `immediate`，这一份就永远填不进去（§14 陷阱 7）。

### 2.7 登录后**不自动发送**，回填到输入框

用户在两选一里明确选了"回填到输入框，用户自己再点一次"。这条值得单独写一节，因为**它是最容易被"顺手优化"掉的一处**：

- 自动发送会**立刻消耗一次额度**（Spec18 的 `record_call`）。用户还没看清自己发的是什么，钱已经花了——而这一整套改动的出发点恰恰是"别在用户没准备好之前就要东西"。
- 自动发送还要处理"图片先上传再发送"的时序，以及上传失败/额度不足时的半截状态。回填方案把这些全部推给用户手里的那一次点击，**失败路径复用现有的**（`store.send()` 里那条 `图片上传失败` 气泡）。
- 所以本 Spec **不实现任何形式的自动重放**。§14 陷阱 10 是它的守卫。

### 2.8 被踢（401 / 40304）必须顺手打开登录层

`App.vue` 现在有两个全局监听器（`App.vue:207` 与 `App.vue:216`），两个都只做 `auth.logout() + closeAllPanels()`。在旧结构里，`auth.logout()` 之后 `!auth.token` 成立 → 模板自动切到整页 `<Login/>`——**登录页是 `logout` 的副作用**。

新结构里没有那个副作用了：登出之后只是一个游客态外壳。所以两处**都必须补 `showLogin.value = true`**。

**40304 那条尤其要命**：`Login.vue` 的 `onMounted` 会 `takeQuotaNotice()` 并把欠费充值面板挂出来——Spec21 §7.4 那句「若您单击登录键则会跳出充值面板」的落点就在那儿。不打开登录层 → 用户被踢到游客界面、看不到任何解释、也看不到充值面板，**那句提示语当场变成空头支票**。§14 陷阱 3 是它的守卫。

### 2.9 埋点位置：门禁在 `trackClick` 之后

`trackClick` 保持在各 `toggleXxx` 函数的**第一行**，门禁逻辑加在它之后（§5.3）。

即：**游客点「社区」也计一次 `community`**。理由是这个埋点叫「入口点击」，定义是"用户点了这个入口"——游客的点击是真实点击。把它挪到门禁之后，这个指标会**悄悄变成"登录用户专属"**，而且从代码上看不出来（这正是一族静默失败）。何况游客点完之后确实看到了一个新的界面（登录门）。

后端零影响：`POST /api/click` 本来就在公开白名单里，`UNIQUE(event, ip)` 让同一 IP 的重复点击不产生任何新行（Spec22 §2.9）。

### 2.10 不引 URL 路由

用户原话里有"打开管理员界面 url"，但**这个前端没有 URL 可言**：`package.json` 里没有 `vue-router`，六个面板是 `App.vue` 里的六个 boolean，唯一的 URL 消费者是 `Login.vue:132` 那行 `?register=1`。

引入路由要动的东西：新增依赖、给六个面板定路径、处理 GitHub Pages 的 `VITE_BASE` 子路径与 History 模式的 404 回退、把 `?register=1` 的现有语义并进去。**这是一次与本 Spec 无关的重构**，用户在有/无之间选了"不引"。

本 Spec 对"管理员界面"的保证是**两级**的，且都成立：

1. **入口不渲染**：`App.vue:38-43` 的两个按钮是 `v-if="auth.isAdmin"`，游客与非管理员都看不到。
2. **动作前过登录**：§5.2 的 `activePanel` 分发里，`gallery/admin/stats/community/suggestions` 五个分支**只有已登录才可达**——游客无论怎么点，`activePanel` 只会返回 `'gate'` 或 `null`。

第 2 级是防"将来有人手滑给游客打开了 `showAdmin`"的：那时落到的是登录门，不是管理面板。

---

## 3. 需求边界

### 3.1 范围内

**A. 游客态**

| 动作 | 位置 | 游客点它会怎样 |
|---|---|---|
| 发送消息（文字和/或图） | `ChatInput` → `App.onSend` | **暂存 + 弹登录层** |
| 「＋ 新对话」 | `ConversationSidebar` `@new` | 弹登录层（无内容可暂存） |
| 打开「我的作品」 | header 按钮 | 面板不挂载 → 原位 <b>LoginGate</b> |
| 打开「社区」 | header 按钮 | 同上 |
| 打开「建议」 | header 按钮 | 同上 |
| 「余额与充值」 | header 按钮 | 直接弹登录层（它是 overlay，不是面板） |
| 「用户管理」「数据统计」 | header 按钮 | **按钮不渲染**（`v-if="auth.isAdmin"`），够不着 |
| 「帮助」 | header 按钮 | **无门禁**，照常可用（`HelpModal` 不发任何请求） |
| 主动登录 | header 新增「登录」按钮 | 弹登录层 |
| 「退出」 | header 按钮 | 游客态下换成「登录」按钮 |
| 从登录层返回 | Login 新增按钮 | 收起登录层，**并把暂存放回输入框** |
| 从 `?register=1` 深链接进来 | `App.vue` 启动时 | 自动打开登录层（注册弹窗由 `Login.vue` 原有逻辑挂出） |

**B. 未登录暂存 / 回填**

- 暂存内容：文字 + 可选的一张图（`ChatInput` 一次只允许一个附件）。
- 暂存有效期 3 分钟。
- 恢复路径两条：**登录成功**、**从登录层返回**。两条都回填到输入框，都不自动发送。
- 降级：IndexedDB 不可用时只暂存文字。

**C. 顶部横条**

- `.brand-sub` 由 `赋能设计的 AIGC 系统 · {{ auth.username }}` 改成常量 `AI辅助设计的系统`。
- 新增 `.login-state`：`目前登录：未登录` / `目前登录：<用户名>`。
- 游客态新增「登录」按钮，「退出」按钮仅登录态渲染。
- 同一短语的另外 4 处一并改（§7.7）。

### 3.2 不在范围内（明确不做）

1. **不做 URL 路由**（§2.10）。没有 `#/admin`、`?panel=community` 这类可直达地址。
2. **不给游客开放任何后端读接口**。`PUBLIC_AUTH_PATHS` 仍是 10 条（§2.2）。
3. **不做"登录后自动发出"**（§2.7）。
4. **不实现"未登录也能看到社区帖子"**。社区对游客是一个登录门，不是只读列表。
5. **不改 `QUOTA_DEFAULT_LIMIT` / 不动 `artcn.db` 结构 / 不加迁移**。
6. **不改 `RechargeModal` 的 `mode="overdue"`**。它挂在 `Login.vue` 里，被踢时照旧弹出。
7. **不改 `HelpModal`**。它对新用户仍然照旧自动弹一次（`artcn_help_seen:<username>` 机制不变）。
8. **不给游客做"注册引导"之外的任何营销位**。
9. **不动 `GithubPage/`**（README 的 alt 文本除外，见 §7.7）。

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **⚠️ 3 分钟过期会让"登录层开着很久"的用户丢掉内容**（§2.5）。这是"暂存大概 3 分钟"的字面结果。要改就是 `TTL_MS` 一个常量，但改之前想清楚僵尸暂存的问题。
2. **⚠️ 暂存是"按浏览器"的，不是"按用户"的。** 同一台机器上 A 暂存、B 登录，B 会看到 A 的那段文字。窗口只有 3 分钟，且这两条恢复路径都会**立刻消费掉**它（`takeRequest()` 读完即清），所以实际撞上的概率很低。**不为此加用户维度**——游客态下没有用户可言。
3. **⚠️ `login_page` 埋点的触发次数变多了，但库里的数字不变**（§1.3）。不要因为"日志变多"就去动 `click_events`。
4. **⚠️ 游客态下 header 的「余额与充值」按钮仍然渲染**（`v-if="!auth.isAdmin"` 对游客为真）。它点了弹登录层。**没有把它藏起来**，理由是它同时是"这产品怎么收费"的入口，游客有知情权。若要藏，改 `App.vue:46` 那一行的条件即可。
5. **⚠️ `GithubPage/assets/hero-banner.jpg` 里可能画着「赋能设计的 AIGC 系统」这几个字，本 Spec 改不了它**（它是位图）。§7.7 列了能改的 5 处源码；那张图要换得重新导出。
6. **⚠️ 游客态下「我的作品」是一个登录门，不是一个空作品库。** 这是用户选的（1-a），别看到"空了"就顺手接上 `GET /api/gallery`。

---

## 4. 技术栈增量

| 项 | 增量 |
|---|---|
| Python 依赖 | **无** |
| npm 依赖 | **无**（IndexedDB 是浏览器原生 API；没装 `idb` 之类的封装库） |
| 后端文件 | **无**（`Server/` 一个字节不改） |
| 前端新文件 | `src/utils/pendingRequest.js`、`src/components/LoginGate.vue` |
| 前端改文件 | `App.vue`、`views/Login.vue`、`components/ChatInput.vue`、`components/ConversationSidebar.vue`、`assets/styles/main.css`、`index.html` |
| 非代码 | `README.md`、`Server/agents/prompts.py`（各一行文案）、`CLAUDE.md`（§15） |
| 环境变量 | **0 个新增，0 个删除** |
| 数据库 | **不动**（`artcn.db` 无迁移、无新表、无新列） |

---

## 5. 架构设计（增量）

### 5.1 游客态判定

```js
// App.vue
const auth = useAuthStore()
const isGuest = computed(() => !auth.token)
```

**判据用 `auth.token`，不是 `auth.username`。** 理由：`store/auth.js` 的 `init()` 里，token 是**同步**从 localStorage 读出来的（`state: () => ({ token: getToken() })`），而 `username` 要等 `GET /api/auth/me` 回来才有值。用 `username` 判会在启动那一瞬把一个已登录用户误判成游客。

**`!auth.loaded` 的启动分支保持不变**（`App.vue:3`），它保证了上面那句"启动那一瞬"根本轮不到渲染——`loaded` 为假时整棵树被 `加载中…` 挡住。所以 `isGuest` 只在 `loaded === true` 之后被读。

### 5.2 `App.vue` 模板新结构

**核心改动：五个面板的并列 `v-if` 换成 `activePanel` 计算属性分发。** 这个计算属性是**穷尽且互斥**的，所以不存在"所有分支都不匹配 → 空白"的状态。

```js
// App.vue
const PANEL_LABELS = {
  gallery: '我的作品', admin: '用户管理', stats: '数据统计',
  community: '社区', suggestions: '建议'
}

// 游客态下"他想开的是哪个面板"——只用来给登录门选一句文案。
// 顺序与下面 activePanel 里的顺序一致。
const guestPanel = computed(() => {
  if (showGallery.value) return 'gallery'
  if (showCommunity.value) return 'community'
  if (showSuggestions.value) return 'suggestions'
  if (showStats.value) return 'stats'
  if (showAdmin.value) return 'admin'
  return null
})

// Spec24 §2.3：**唯一**决定 main-col 里渲染什么的东西。
// 互斥、穷尽，且游客永远拿不到任何面板分支（§2.10 的第 2 级保证）。
const activePanel = computed(() => {
  if (isGuest.value) return guestPanel.value ? 'gate' : null
  if (showGallery.value) return 'gallery'
  if (showAdmin.value) return 'admin'
  if (showStats.value) return 'stats'
  if (showCommunity.value) return 'community'
  if (showSuggestions.value) return 'suggestions'
  return null
})

// 登录门上那句「🔒 XXX 需要登录后查看」里的 XXX（§5.5）
const guestPanelLabel = computed(() => PANEL_LABELS[guestPanel.value] || '该页面')

// 原来的 isChatView 就是"没有面板开着"，语义不变，改成从 activePanel 推
const isChatView = computed(() => activePanel.value === null)
```

模板（`main-col` 内部，`header` 之后）：

```html
<!-- Spec24 §2.3：面板组件对游客**整个不挂载**（它们的 onMounted 会立刻发请求 → 401
     → artcn:unauthorized → 全局登出）。分发权交给 activePanel，见 script。 -->
<GalleryPanel    v-if="activePanel === 'gallery'"          @close="showGallery = false" />
<AdminPanel      v-else-if="activePanel === 'admin'"       @close="showAdmin = false" />
<StatsPanel      v-else-if="activePanel === 'stats'"       @close="showStats = false" />
<CommunityPanel  v-else-if="activePanel === 'community'"   @close="showCommunity = false" />
<SuggestionPanel v-else-if="activePanel === 'suggestions'" @close="showSuggestions = false" />

<!-- Spec24 §5.5：游客的落点。:label 是"他想开的那个面板"的名字（guestPanelLabel）。 -->
<LoginGate
  v-else-if="activePanel === 'gate'"
  :label="guestPanelLabel"
  @login="openLogin"
  @close="closeAllPanels"
/>

<!-- 聊天区（原样不动） -->
<template v-else>
  <main class="chat-scroll" ref="scrollRef"> … </main>
  <ChatInput :disabled="store.sending" :draft="draft" @send="onSend" @draft-consumed="draft = null" />
</template>
```

**注意 `ChatInput` 那一行多了两个绑定**（`draft` 与 `draft-consumed`），其余原样。

### 5.3 门禁函数与各动作的落点（**五个不改，三个加门禁**）

```js
// App.vue
const showLogin = ref(false)
const draft = ref(null) // Spec24 §2.6：待回填的暂存内容 { text, file }；null = 没有

function openLogin() {
  showLogin.value = true
}

// Spec24 §2.6：两条恢复路径（登录成功 / 从登录层返回）共用它。
// takeRequest() 内部判 3 分钟 TTL，过期返回 null（§2.5）。
async function restorePending() {
  const pending = await takeRequest()
  if (pending) draft.value = pending
}
```

**五个 `toggleXxx` 全部不加门禁。** 让面板的 boolean 照常翻转，由 `activePanel`（§5.2）把游客分流到登录门。
`trackClick` 保持在第一行（§2.9）：

```js
function toggleGallery() {
  trackClick('gallery')                          // ← 位置不变（§2.9）
  showGallery.value = !showGallery.value         // ← 一个字不改
  if (showGallery.value) closeOtherPanels('gallery')
}
// toggleCommunity / toggleSuggestions / toggleAdmin / toggleStats 同款，全部不动
```

> **为什么这里不该加 `if (isGuest) { openLogin(); return }`**（这是本 Spec 最容易写错的一处）：
> 加上去的话，游客点「社区」会被**直接糊一脸登录卡**——而用户选的口径是
> "**先看到页面**，只有登录用户才能看到**内容**"（§0 的 1-a）。登录门就是那个"页面"。
> 分流交给 `activePanel` 之后，`activePanel === 'gate'` 是**游客态下的常态**，不是边角情况。

`openRecharge` 与 `onNewConversation` 是**例外**——它们没有"页面"可给（一个是 overlay，一个是列表里的动作），所以**直接弹登录层**：

```js
function openRecharge() {
  trackClick('recharge')                       // ← 位置不变（§2.9）
  if (isGuest.value) { openLogin(); return }   // ← 唯一新增
  showRecharge.value = true
}

function onNewConversation() {
  if (isGuest.value) { openLogin(); return }   // ← 唯一新增（§0 的 2-e）
  store.newConversation()
  scrollToBottom()
}
```

`onSend` 是唯一一个**带暂存**的门禁点：

```js
async function onSend(payload) {
  if (isGuest.value) {
    // Spec24 §2.4/§5.4：先落盘再弹登录——**顺序不能反**。
    // 反过来的话，"弹登录"与"写暂存"会并发，用户秒点返回时可能读到空暂存。
    // stashRequest 内部把文本同步写进 localStorage，所以 await 它不等于"等 IDB"。
    await stashRequest(payload.text, payload.file)
    openLogin()
    return
  }
  store.send(payload.text, payload.file)
}
```

**`ChatInput.submit()` 在 emit 之后就清空自己的 `text`/`file`**（`ChatInput.vue` 的 submit），所以游客点发送那一刻，输入框会先空掉——这正是回填要存在的原因（§5.9 路径 2）。

`onOpenConversation` / `onDeleteConversation` 加一行防御（游客的列表恒为空，正常够不着）：

```js
async function onOpenConversation(id) {
  if (isGuest.value) { openLogin(); return }
  await store.openConversation(id)
  scrollToBottom()
}
```

### 5.4 新增 `frontend/src/utils/pendingRequest.js`（逐行）

```js
// Spec24 §2.4：未登录游客被拦下时，把他"正要发出的东西"暂存下来，
// 登录成功（或从登录层返回）后由 App.vue 回填进输入框。
//
// 两处存储，各存各的、各失败各的：
//   localStorage → 文本 + 元数据（同步、快；配额约 5MB，只放字符串）
//   IndexedDB    → 图片 Blob（localStorage 装不下：输入框收 ≤10MB 的图，
//                  转 base64 还要涨 33%，而配额只有约 5MB —— 大部分真实照片会静默写失败）
//
// **任何一步失败都降级，绝不抛**：拿不到图就只回填文字；两处都拿不到就当作没暂存过。
// 私有模式 / 禁用存储的浏览器里这两个 API 都可能直接抛，所以每一步都包了 try/catch。

const TEXT_KEY = 'artcn_pending_request'
const TTL_MS = 3 * 60 * 1000 // Spec24 §2.5：暂存有效期 3 分钟

const DB_NAME = 'artcn_drafts'
const DB_VERSION = 1
const STORE = 'blobs'
const BLOB_KEY = 'pending'

// ---------- localStorage：文本 + 元数据 ----------

function readMeta() {
  try {
    const raw = localStorage.getItem(TEXT_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null // 隐私模式下 getItem 也可能抛
  }
}

function writeMeta(meta) {
  try {
    localStorage.setItem(TEXT_KEY, JSON.stringify(meta))
    return true
  } catch {
    return false // 配额满 / 隐私模式
  }
}

function clearMeta() {
  try {
    localStorage.removeItem(TEXT_KEY)
  } catch {
    /* 同上 */
  }
}

// ---------- IndexedDB：图片 Blob ----------

// 连接缓存：一次失败就永久降级（IDB 不可用时重试也不会成功）。
// 不主动 close —— 页面卸载时浏览器自己收。
let dbPromise = null

function openDbOnce() {
  return new Promise((resolve) => {
    let req
    try {
      req = indexedDB.open(DB_NAME, DB_VERSION)
    } catch {
      return resolve(null)
    }
    if (!req) return resolve(null)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
    req.onsuccess = () => resolve(req.result)
    // 配额满 / 被策略禁用 / 被另一个标签页占着旧版本 → 一律当作"没有 IDB"
    req.onerror = () => resolve(null)
    req.onblocked = () => resolve(null)
  })
}

function openDb() {
  if (!dbPromise) dbPromise = openDbOnce()
  return dbPromise
}

function idbWrite(mode, fn) {
  return openDb().then((db) => new Promise((resolve) => {
    if (!db) return resolve(null)
    try {
      const tx = db.transaction(STORE, mode)
      const req = fn(tx.objectStore(STORE))
      tx.oncomplete = () => resolve(req ? req.result ?? true : true)
      tx.onerror = () => resolve(null)
      tx.onabort = () => resolve(null)
    } catch {
      resolve(null)
    }
  }))
}

const idbPut = (blob) => idbWrite('readwrite', (s) => s.put(blob, BLOB_KEY))
const idbTake = () => idbWrite('readonly', (s) => s.get(BLOB_KEY))
const idbDrop = () => idbWrite('readwrite', (s) => s.delete(BLOB_KEY))

// ---------- 对外三个函数 ----------

/** 暂存一条待发送内容。返回 true 表示"至少文字存下了"。 */
export async function stashRequest(text, file) {
  await clearRequest() // 同一次暂存只该有一份

  const meta = { text: text || '', ts: Date.now(), file: null }
  if (file) meta.file = { name: file.name || 'image', type: file.type || 'image/png' }

  if (!writeMeta(meta)) {
    await clearRequest() // 文字都没落盘 → 不留半截状态
    return false
  }

  if (file) {
    const ok = await idbPut(file)
    // ⚠️ Spec24 §14 陷阱 6：图没存下时必须把 meta.file **抹掉**，
    // 否则 takeRequest 会去 IDB 找一个不存在的 Blob（拿到 null → file 为 null，
    // 看起来"没坏"，但那条 meta.file 是个永远兑现不了的承诺）。
    if (!ok) writeMeta({ ...meta, file: null })
  }
  return true
}

/**
 * 取出暂存内容并清空（读完即清）。
 * 过期 / 不存在 / 解析失败 → 一律返回 null。
 * @returns {Promise<{text: string, file: File|null}|null>}
 */
export async function takeRequest() {
  const meta = readMeta()
  if (!meta) return null

  if (typeof meta.ts !== 'number' || Date.now() - meta.ts > TTL_MS) {
    await clearRequest() // Spec24 §2.5：过期即清，不给下一次机会
    return null
  }

  let file = null
  if (meta.file) {
    const blob = await idbTake()
    if (blob) {
      try {
        file = new File([blob], meta.file.name, { type: meta.file.type })
      } catch {
        file = null // 老浏览器没有 File 构造器 → 降级成只回填文字
      }
    }
  }

  await clearRequest()
  return { text: meta.text || '', file }
}

/** 清空暂存（两处都清）。任何失败都吞掉。 */
export async function clearRequest() {
  clearMeta()
  await idbDrop()
}
```

### 5.5 新增 `frontend/src/components/LoginGate.vue`

游客点开面板时占位的那一块。它**不发任何请求**——这是它存在的全部意义（§2.3）。

```html
<template>
  <!-- Spec24 §2.3：面板组件对游客整个不挂载，由它占位。
       它必须**不发任何请求** —— 一挂载就发请求的话，游客会立刻吃一个 401，
       chatApi.js 的拦截器会派发 artcn:unauthorized，全局登出（§2.3）。 -->
  <div class="login-gate">
    <p class="gate-title">🔒 {{ label }}需要登录后查看</p>
    <p class="gate-hint">登录后可以发送设计需求、保存自己的作品、在社区发帖与提建议。</p>
    <div class="gate-actions">
      <button class="gate-login" @click="emit('login')">登录 / 注册</button>
      <button class="gate-back" @click="emit('close')">返回聊天</button>
    </div>
  </div>
</template>

<script setup>
// Spec24 §5.5：纯展示组件，零 API、零 store。文案里的 label 由 App.vue 给。
defineProps({
  label: { type: String, default: '该页面' } // '我的作品' / '社区' / '建议' …
})
const emit = defineEmits(['login', 'close'])
</script>

<style scoped>
.login-gate {
  flex: 1;                    /* 顶满 main-col 的剩余高度，和面板同款 */
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 24px;
  text-align: center;
}
.gate-title { font-size: 16px; color: var(--text-secondary); }
.gate-hint { font-size: 13px; color: var(--text-muted); max-width: 320px; line-height: 1.7; }
.gate-actions { display: flex; gap: 10px; margin-top: 8px; }
.gate-login {
  padding: 8px 20px;
  font-size: 13px;
  color: #fff;
  background: var(--purple-500);
  border-radius: var(--radius-full);
  transition: background var(--transition-fast);
}
.gate-login:hover { background: var(--purple-600); }
.gate-back {
  padding: 8px 20px;
  font-size: 13px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-full);
  transition: all var(--transition-fast);
}
</style>
```

> ⚠️ 色板变量以 `main.css` 的 `:root` 为准。上面用到的 `--purple-500` / `--purple-600` / `--radius-full` / `--text-secondary` / `--text-muted` / `--border-color` / `--transition-fast` 都是**该文件里已有的**；若某个名字对不上，**按现有名字改，不要新增变量**（main.css 的 `:root` 是既有主题，Spec.md 有"preserve"的要求）。

### 5.6 `ChatInput.vue` 的 `draft` prop

```js
const props = defineProps({
  disabled: { type: Boolean, default: false },
  // Spec24 §2.6：登录后要回填的暂存内容 { text, file }；null = 没有。
  // 父组件持有它，子组件消费完 emit('draft-consumed') 通知父组件清空。
  draft: { type: Object, default: null }
})
const emit = defineEmits(['send', 'draft-consumed'])

// Spec24 §2.6：回填。
// ⚠️ **immediate: true 不能省**：游客从"点面板 → 登录门 → 登录"那一路进来时，
//    main-col 里占位的是 LoginGate/面板，ChatInput **还没挂载**；draft 先落进
//    App.vue 的 ref，等用户切回聊天视图、ChatInput 挂载那一刻才消费。
//    没有 immediate，这一份就永远填不进去（§14 陷阱 7）。
watch(() => props.draft, (d) => {
  if (!d) return
  text.value = d.text || ''
  if (d.file) setFile(d.file) // setFile 会自己 revoke 上一份 objectURL 并生成新预览
  nextTick(autoResize)        // textarea 高度按新内容重算
  emit('draft-consumed')      // → App.vue 把 draft 置回 null（watch 收到 null 即早退）
}, { immediate: true })
```

需要新增的 import：`nextTick` 加进现有的 `import { computed, ref } from 'vue'`。

**不动的地方**：`submit()` 里 emit 之后那三行清空照旧（§5.3 说明了为什么这不成问题——回填就是为了接住这次清空）；`acceptFile` / `setFile` / 拖拽三个入口全部照旧，**游客选图与拖图都不拦**（用户选的 2-c）。

### 5.7 `ConversationSidebar.vue` 的 `guest` prop

**必须改的理由**（§0 的 2-e）：该按钮现在是 `:disabled="currentId === null"`，而游客的 `currentConvId` 恒为 `null` → 按钮是灰的 → 用户点名的"点新对话跳登录"**根本触发不了**。

```js
defineProps({
  conversations: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
  // Spec24 §5.7：游客态。游客没有对话列表，但「＋ 新对话」必须**可点**
  // ——它是用户点名的拦截点之一（点它 → 弹登录层）。
  guest: { type: Boolean, default: false }
})
```

模板里三处随之变化：

```html
<button
  class="conv-sidebar-new"
  :disabled="!guest && currentId === null"
  :title="guest
    ? '登录后开始新对话'
    : (currentId === null ? '已经在空对话里了' : '开始一段新对话')"
  @click="emit('new')"
>
  ＋ 新对话
</button>

<div class="conv-list">
  <p v-if="!conversations.length" class="conv-empty">
    {{ guest ? '登录后可保存并查看对话历史' : '还没有对话，点「新对话」开始' }}
  </p>
  …
</div>
```

### 5.8 `views/Login.vue` 的「返回继续浏览」

`Login.vue` 现在**没有任何 prop/emit**。新增一个 emit 与一个按钮：

```js
const emit = defineEmits(['close'])
```

按钮放在 `.login-register` 那一块的最后（客服行之后），复用现有的 `.btn-link` 样式：

```html
<div class="login-register">
  …（注册按钮 / 邮箱登录 / 修改密码 / 客服行，全部原样）…

  <!-- Spec24 §5.8：登录层现在是覆盖层，用户必须有一条退路回到游客界面。
       少了它，点开登录就等于"只能登录或关标签页"。 -->
  <button type="button" class="btn-link login-back" @click="emit('close')">← 返回继续浏览</button>
</div>
```

**另外一处必须补的**：`Login.vue` 的 `?register=1` 深链接逻辑（`Login.vue:132`）原本假设"挂到 Login.vue 就等于用户已经在登录页上"。现在还得有人在**外壳那一层**把登录层打开：

```js
// App.vue —— 与 auth.init() 同一段启动逻辑里
// Spec24 §3.1：?register=1 深链接进来时，游客要先看到登录层（注册弹窗由
// Login.vue 的 onMounted 照旧挂出）。**不清理 URL**（Spec19 §7.4 的既定行为）。
if (!auth.token && new URLSearchParams(window.location.search).get('register') === '1') {
  showLogin.value = true
}
```

### 5.9 关键数据流（三条时序）

**路径 1 —— 游客点「发送」（带暂存 → 登录 → 回填）**

```
游客在 ChatInput 打字（可能还附了图）
  → submit() → emit('send', {text, file}) → 清空自己的 text/file
  → App.onSend: isGuest → await stashRequest(text, file)   [localStorage 同步落盘, 图进 IDB]
  → openLogin() → showLogin = true → 登录层盖上来（外壳仍挂载）
  → 用户登录成功 → auth.token / username 变化
  → App 的 watcher([auth.loaded, auth.username]) 触发：
        showLogin = false
        await store.resetForUser(username)
        await restorePending() → takeRequest() → draft.value = {text, file}
  → ChatInput 的 watch(props.draft) 触发（已挂载）→ 填回 text / setFile(file)
  → emit('draft-consumed') → App: draft = null
  → 用户点「发送」→ 这次 isGuest 为假 → store.send(...)
```

**路径 2 —— 游客点「发送」→ 点「返回继续浏览」（**这条比路径 1 更重要**）**

```
  … 同上，直到 showLogin = true
  → 用户点「← 返回继续浏览」→ emit('close') → onLoginClose()
        showLogin = false
        await restorePending() → 未过期 → draft.value = {text, file}
  → ChatInput 填回 → 用户看到自己刚才打的字还在
```

> 没有这条路径的话，用户打完字、点发送、看到登录页、点返回——**字没了**。
> 这是整套改造里唯一一处"用户会明确感到被坑"的地方。

**路径 3 —— 游客点「社区」（面板门禁，不走暂存）**

```
  → toggleCommunity() → trackClick('community') → showCommunity = true
  → activePanel: isGuest → guestPanel='community' → 'gate'
  → <LoginGate label="社区"> 渲染在社区那块位置上（**CommunityPanel 不挂载**）
  → 用户点「登录 / 注册」→ openLogin() → 登录层
  → 登录成功 → isGuest 变假 → activePanel 重新计算 → 'community'
  → CommunityPanel 挂载（此刻有 token，它的 load() 正常成功）
  → 用户**落在社区里**，不是被弹回聊天
```

> 路径 3 里 `showCommunity` **全程为真**——登录层不碰面板的 boolean，登录成功也不调
> `closeAllPanels()`（那个只在 401/40304 两个监听器里调）。这是"落在自己想去的地方"的实现方式。

---

## 6. 接口约定

### 6.1 后端：零改动

| 项 | 状态 |
|---|---|
| `PUBLIC_AUTH_PATHS` | **仍 10 条**，精确匹配，一条不加一条不减 |
| 新增/变更/删除的路由 | **无** |
| 请求/响应体 | **无变化** |
| 错误码 | **无新增**（40103 / 40301 / 40304 的触发条件一字不变） |
| `Server/` 下的文件 | **全部零改动**（验收判据 §13-A） |

游客发起的任何请求都不存在——这正是 §2.3 那条"面板不挂载"的设计目标。唯一两个游客会打到后端的请求是：

- `POST /api/click`（埋点，公开白名单，裸 `fetch`，异常全吞）
- `GET /api/auth/register-config`（**只有打开登录层时才发**，`Login.vue` 的 `onMounted`，公开白名单）

### 6.2 前端内部接口（新增部分）

| 模块 | 导出 / 契约 |
|---|---|
| `utils/pendingRequest.js` | `stashRequest(text: string, file: File\|null) => Promise<boolean>`<br>`takeRequest() => Promise<{text, file: File\|null} \| null>`（**读完即清**）<br>`clearRequest() => Promise<void>` |
| `components/LoginGate.vue` | props `label: String`；emits `login`、`close` |
| `components/ChatInput.vue` | **新增** prop `draft: Object\|null`；**新增** emit `draft-consumed` |
| `components/ConversationSidebar.vue` | **新增** prop `guest: Boolean`（默认 `false`） |
| `views/Login.vue` | **新增** emit `close` |

---

## 7. 前端交互

### 7.1 `App.vue`（逐处清单）

| 行（改动前） | 改动 |
|---|---|
| `3` `v-if="!auth.loaded"` | **不动** |
| `6` `v-else-if="!auth.token"` → `<Login v-else-if="!auth.token" />` | **删除这一支**（§2.1） |
| `9` `<div v-else class="app">` | **文本不变，但它挂的链变了**：原来是 `v-else`（挂在 `!auth.loaded` 与 `!auth.token` 两个分支之后），现在只挂在 `!auth.loaded` 之后 |
| `11-18` `ConversationSidebar` | **加 `:guest="isGuest"`** |
| `26-28` `.brand-sub` | 换常量文案（§7.2） |
| `29-49` 六个 header 按钮 | `toggleGallery / toggleCommunity / toggleSuggestions / toggleAdmin / toggleStats` **一个字不改**（§5.3：门禁不在它们里面，交给 `activePanel`）；`openRecharge` **加门禁** |
| `—`（新增） | `.login-state` 状态提示 + 「登录」按钮（§7.2） |
| `53-57` 五个面板的 `v-if` 链 | **换成 `activePanel` 分发** + `LoginGate`（§5.2） |
| `59-78` 聊天区 `<template v-else>` | `ChatInput` 加 `:draft` / `@draft-consumed`，其余不动 |
| `81-84` `HelpModal` / `RechargeModal` | **不动** |
| `—`（模板末尾，`.app` 的**兄弟**） | 新增 `<Login v-if="showLogin" class="login-overlay" @close="onLoginClose" />` |
| `108-111` store / refs | 新增 `isGuest` / `activePanel` / `guestPanel` / `PANEL_LABELS` / `draft` / `showLogin` |
| `119-134` 登录态 watcher | 改成 `async`；补 `showLogin = false` 与 `await restorePending()`（§2.8、§5.9 路径 1） |
| `190-193` `isChatView` | 改成 `computed(() => activePanel.value === null)` |
| `207-210` `artcn:unauthorized` 监听器 | **补 `showLogin.value = true`**（§2.8） |
| `216-223` `artcn:quota_exceeded` 监听器 | **补 `showLogin.value = true`**（§2.8，**这条漏了欠费面板就永不出现**） |
| `240-245` `onSend` / `onRetry` | `onSend` 改成 async + 门禁（§5.3）；`onRetry` 不动（游客没有消息可重试） |
| `252-259` 三个侧边栏动作 | `onNewConversation` 加门禁；`onOpenConversation` 加防御 |

**启动逻辑新增的一段**（与 `auth.init()` 同一处，§5.8）：

```js
const auth = useAuthStore()
auth.init()

// Spec24 §5.8：?register=1 深链接 → 游客也要先看到登录层（注册弹窗由 Login.vue 挂）
// ⚠️ 这段要排在 showLogin 的 ref 声明**之后**；auth.token 是同步从 localStorage 读的
//（store/auth.js 的 state 初始化），所以这里判得到，不用等 init() 的 Promise。
if (!auth.token && new URLSearchParams(window.location.search).get('register') === '1') {
  showLogin.value = true
}
```

### 7.2 顶部横条

**文案**（用户原话第 4、5 条）：

```html
<!-- Spec24 §7.2：恒定文案。原句「赋能设计的 AIGC 系统 · {{ auth.username }}」整行删除
     —— 它把"品牌定位"和"当前身份"塞进一个位置，而未登录时 auth.username 是空串，
     屏幕上只剩一个孤零零的「· 」。品牌句与身份位现在是两个元素。 -->
<span class="brand-sub">AI辅助设计的系统</span>
…
<!-- Spec24 §7.2：登录状态。**两个条件一起判** —— token 是同步从 localStorage 读的，
     username 要等 GET /api/auth/me 回来；只判 token 会闪一下「目前登录：」（§14 陷阱 8）。 -->
<span class="login-state">
  目前登录：{{ auth.token && auth.username ? auth.username : '未登录' }}
</span>
<button v-if="isGuest" class="btn-login-entry" @click="openLogin">登录</button>
<button v-else class="btn-logout" title="退出登录" @click="onLogout">退出</button>
```

**布局**（`.brand-sub` 的 `flex: 1` 保持不动——它是把按钮推到右边的弹簧）：

```
登录态：
[● ArtiControlNet] AI辅助设计的系统 ······· [我的作品][社区][建议][余额与充值][帮助] 目前登录：admin [退出]

游客态：
[● ArtiControlNet] AI辅助设计的系统 ······· [我的作品][社区][建议][余额与充值][帮助] 目前登录：未登录 [登录]

管理员：
[● ArtiControlNet] AI辅助设计的系统 · [我的作品][社区][建议][用户管理][数据统计][帮助] 目前登录：admin [退出]
```

> 管理员没有「余额与充值」（`v-if="!auth.isAdmin"`，Spec21 §7.1），所以那一行反而更松。最挤的是
> 普通用户那一行：7 个按钮 ≈ 530px + 品牌 ≈ 150px + 状态 ≈ 110px，在 `.app` 的 `max-width: 900px`
> 里刚好放得下。**状态文字用 12px + `white-space: nowrap`**（§7.7），别让它换行。

> ⚠️ 如果实测仍然挤：**第一顺位是缩短按钮文案，不是删掉状态提示**（用户点名要的就是那个提示）。

### 7.3 `views/Login.vue`

只加两样东西（§5.8）：`defineEmits(['close'])` + 一个「← 返回继续浏览」按钮。
**其余全部不动**：logo、品牌标题、副标题（只改那半句短语，§7.7）、登录表单、注册按钮、两个邮箱入口、客服行、`RegisterModal` / `EmailAuthModal` / `RechargeModal` 三个内嵌弹窗、`onMounted` 里那整段（`trackClick('login_page')` / `takeQuotaNotice()` / `getRegisterConfig()` / `?register=1`）。

### 7.4 `components/LoginGate.vue`（新增）

见 §5.5 的完整代码。三条硬约束：

1. **不发任何请求**（不 import `chatApi`、不 import store）——这是它存在的全部意义。
2. `label` 由 `App.vue` 给（`PANEL_LABELS[guestPanel]`），组件自己不猜。
3. `flex: 1` 顶满 `main-col` 剩余高度，视觉上与面板同级。

### 7.5 `components/ChatInput.vue`

见 §5.6。除 `draft` prop / `draft-consumed` / 那个 `watch` 外**一字不动**；
`acceptFile` / `setFile` / `onFile` / `onDragEnter|Leave|Drop` / `clearFile` / `autoResize` / `submit` 全部保持原样。

### 7.6 `components/ConversationSidebar.vue`

见 §5.7。三处变化：props 加 `guest`、按钮的 `:disabled` 与 `:title`、空态文案。

### 7.7 样式与文案（`assets/styles/main.css`、`index.html`、其余两处）

**`main.css` 新增**（放在 `.login-page` 规则附近）：

```css
/* Spec24 §2.1：登录页从"整页"降级成"覆盖层"——它现在是 .app 的兄弟节点。
   .login-page 原本是 height:100% + flex 居中，套上 fixed/inset 后
   height:100% 仍然成立（定位元素的包含块是视口），.login-card 一个字节不用改。 */
.login-page.login-overlay {
  position: fixed;
  inset: 0;
  z-index: 900;                 /* 与 .reg-overlay 的 1000 错开：登录层在下，注册/邮箱/充值弹窗在上 */
  background: var(--bg-primary);/* 不透明：背后的游客界面不该从缝里透出来 */
}

/* Spec24 §7.2：顶栏登录状态。12px + nowrap —— 横条已经很挤，它不能换行。 */
.login-state {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Spec24 §7.2：登录页底部的「← 返回继续浏览」。复用已有的 .btn-link（Login.vue 的
   「邮箱登录 / 修改密码」就是它），只补一点上边距。 */
.login-back { margin-top: 4px; }
```

**`main.css` 修改一条既有规则**（不是新增）：

```css
/* 原来只有 .btn-logout。游客态的「登录」按钮是同一个位置、同一种视觉的另一个形态
   （§7.2 的两行横条布局），所以合并选择器 —— **不要**复制一份声明，那会变成两份会漂移的副本。 */
.btn-logout,
.btn-login-entry {
  …（原有声明全部不动）…
}
```

> ⚠️ 别忘了 `.login-state` 的 `flex-shrink: 0`（横条是 flex row，不加它状态文字会被压缩换行）；
> 也别忘了 `.login-page.login-overlay` 用**两个类**做选择器——只写 `.login-overlay` 会连带影响
> 别的元素，只写 `.login-page` 会把**非覆盖层**的登录页也固定住（现在虽然没有非覆盖层的用法，但选择器要表达出意图）。

**文案五处**（同一个短语「赋能设计的 AIGC 系统」→「AI辅助设计的系统」）：

| 文件 | 改动前 | 改动后 |
|---|---|---|
| `frontend/src/App.vue:27` | `赋能设计的 AIGC 系统 · {{ auth.username }}` | `AI辅助设计的系统`（§7.2） |
| `frontend/src/views/Login.vue:11` | `赋能设计的 AIGC 系统 · 登录后使用` | `AI辅助设计的系统 · 登录后使用` |
| `frontend/index.html:7` | `<title>ArtiControlNet - 赋能设计的 AIGC 系统</title>` | `<title>ArtiControlNet - AI辅助设计的系统</title>` |
| `README.md:2` | `alt="ArtiControlNet —— 赋能设计的 AIGC 系统"` | `alt="ArtiControlNet —— AI辅助设计的系统"` |
| `Server/agents/prompts.py:8` | `你是 ArtiControlNet（赋能设计的 AIGC 系统）的主 Agent（Supervisor）。` | `你是 ArtiControlNet（AI辅助设计的系统）的主 Agent（Supervisor）。` |

改完扫一遍：`grep -rn "赋能设计的" frontend/src frontend/index.html README.md Server/agents`——**应该输出为空**。
（`Server/static/` 里的旧构建产物也含这句话，但它不在上面那条命令的范围内；重新 `npm run build` 之后它自然消失，§12 第 9 步。）

> ⚠️ `GithubPage/assets/hero-banner.jpg` 是**位图**，里面若画着这句话本 Spec 改不了（§3.3-5）。

---

## 8. 配置 / 环境变量

**无新增、无删除、无默认值变更。** `Server/config.py` 不动，`Server/.env.example` 不动。

`TTL_MS = 3 * 60 * 1000` 是**前端常量**，不是环境变量——它没有任何部署相关的取值理由，进 `.env` 只会多一个"配了但没人看"的旋钮。

---

## 9. 错误码

**无新增、无删除、无语义变更。**

| 码 | 本 Spec 下的行为 |
|---|---|
| `40103` | 游客**不会**碰到它——所有会发请求的面板都不挂载（§2.3）。已登录用户 token 失效时行为不变（登出 + `showLogin = true`，§2.8）。 |
| `40304` | 行为不变（登出 + 弹登录层 + 欠费面板）。§2.8 那一行 `showLogin = true` 是保证它**仍然可见**的关键。 |
| `40301` | 不变（非管理员访问 `/api/admin/*`）。 |

---

## 10. 日志约定

**`logging_setup.py` 的 `_FIELDS` 白名单一个字不动。** 本 Spec 不新增任何日志字段，也不删。

唯一要记的是**语义漂移**（§1.3）：`POST /api/click` 的 `login_page` 事件现在每次打开登录层都会发一次（游客点任何门禁点都会经过它）。库里**不会有任何变化**——`click_events` 的 `UNIQUE(event, ip)` 让同一 IP 只落第一行、只打第一条 `click.recorded` 日志（Spec22 §2.9）。§14 陷阱 11 是它的守卫。

---

## 11. 目录结构增量

```
frontend/src/
├── components/
│   ├── ChatInput.vue              ← 改（+draft prop / +draft-consumed / +watch）
│   ├── ConversationSidebar.vue    ← 改（+guest prop，三处文案）
│   └── LoginGate.vue              ← 新建（§5.5，零 API 零 store）
├── utils/
│   └── pendingRequest.js          ← 新建（§5.4，localStorage + IndexedDB）
├── views/
│   └── Login.vue                  ← 改（+emit('close') / +「返回继续浏览」/ 副标题半句）
├── App.vue                        ← 改（改动最大：§7.1 逐处清单）
└── assets/styles/main.css         ← 改（+.login-overlay / +.login-state / 合并 .btn-logout 选择器）

frontend/index.html                ← 改（<title>）
README.md                          ← 改（alt 一行）
Server/agents/prompts.py           ← 改（Supervisor 提示词里那句话）
CLAUDE.md                          ← 改（§15）
```

**`Server/` 下除 `agents/prompts.py` 那一行文案外，其余文件零改动**（§13-A 的判据要相应放宽成
"`git diff --stat Server/` 只有 `agents/prompts.py` 一行"）。

---

## 12. 实施顺序（里程碑）

1. **`utils/pendingRequest.js`**（§5.4）。独立文件、无依赖，先写完可以先在浏览器控制台单独验它。
2. **`components/LoginGate.vue`**（§5.5）。同样是独立文件。
3. **`components/ChatInput.vue`**（§5.6）。加 prop + watch，此时父组件还没传，行为不变。
4. **`components/ConversationSidebar.vue`**（§5.7）。加 `guest` prop，默认 `false` → 现有行为不变。
5. **`views/Login.vue`**（§5.8、§7.3）。加 emit + 返回按钮 + 那半句副标题。
6. **`App.vue`**（§5.2、§5.3、§7.1、§7.2）。**改动最大的一步**，把前五步接起来。
7. **`main.css`**（§7.7）。登录层覆盖、登录状态、按钮选择器合并。
8. **其余文案四处**（`index.html` / `README.md` / `Server/agents/prompts.py`）。
9. **`npm run build` → 重新构建静态产物**（`Server/static/`）。仓库既有惯例（"build: 重新构建前端静态产物"）。
10. **按 §13 逐条验收**，最后改 `CLAUDE.md`（§15）。

> 第 9 步不要省。`Server/static/` 是进了仓库的构建产物，不重建的话，用
> "后端单端口托管 dist" 那种跑法（CLAUDE.md 的 Commands 最后一节）看到的还是旧界面。

---

## 13. 验收用例（端到端 Smoke）

### 前置

- 后端与前端都跑起来（`uvicorn main:app --reload --port 8000` + `npm run dev`）。
- 浏览器地址栏**用 `127.0.0.1:5173`，不要用 `localhost`**（本机环境下 `localhost` 每个请求会白等约 2 秒，见 CLAUDE.md 的验收约定）。
- **准备一个"干净的浏览器上下文"**：无痕窗口最省事（`localStorage` 与 IndexedDB 都是空的）。每条用例开头都从无痕窗口重新开始。
- 本 Spec **不改后端**，所以**不需要**动 `SMTP_PASSWORD`、不需要库副本、不会发任何真实邮件。

### A. 后端零改动（**先跑这条**）

1. `git diff --stat Server/` → **只有 `agents/prompts.py` 一行**（§11）。出现任何 `.py` 的功能改动都是**做错了**。
2. `git diff Server/main.py` → **空**。尤其确认 `PUBLIC_AUTH_PATHS` 仍是 10 条。
3. 无 token 打一条业务接口，确认后端行为不变：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/community
# 期望 401
curl -s http://127.0.0.1:8000/api/community | head -c 200
# 期望 {"code":40103,"message":"缺少登录态","data":null}
```

### B. 游客态：看得见页面，做不了动作

4. **无痕窗口打开 `http://127.0.0.1:5173/`** →
   - **不再**是登录页；看到的是聊天外壳（侧边栏 + 顶栏 + 空态提示 + 输入框）。
   - 顶栏副标题恒为 **`AI辅助设计的系统`**，**后面没有 `·`，没有用户名**。
   - 顶栏右侧：**`目前登录：未登录`** + 一个「登录」按钮。
   - 打开 DevTools → Network，**过滤 `/api/`**：除了 `POST /api/click`（进站埋点），**不应有任何请求**。有任何一条 401 都是做错了。
5. 点「社区」→ 社区那块位置出现 **登录门**（「🔒 社区需要登录后查看」+ 两个按钮），**Network 里没有 `GET /api/community`**。
6. 点「我的作品」→ 同上，`label` 是「我的作品」；**Network 里没有 `GET /api/gallery`**。
7. 点「建议」→ 同上，`label` 是「建议」。
8. 点「帮助」→ **帮助弹窗正常打开**（无门禁）。
9. 点「余额与充值」→ **直接弹登录层**（不是登录门）。
10. 确认顶栏**没有**「用户管理」「数据统计」两个按钮。
11. **游客控制台不应出现 `artcn:unauthorized` 的连锁**：检查顶栏仍是「目前登录：未登录」（若被派发过全局登出，面板会被 `closeAllPanels()` 关掉——第 5~7 条点完门禁还在，就说明没有）。

### C. 暂存 → 登录 → 回填（**本 Spec 的核心**）

12. 游客在输入框打「画一只戴帽子的猫」，点「发送」→
    - 立刻弹**登录层**（全屏）；输入框空了（`ChatInput` 的既有行为）。
    - DevTools → Application → Local Storage：`artcn_pending_request` 有值，形如 `{"text":"画一只戴帽子的猫","ts":…,"file":null}`。
13. 在登录层点 **「← 返回继续浏览」** →
    - 登录层收起，**回到游客外壳**。
    - **输入框里是「画一只戴帽子的猫」**（回填生效，§5.9 路径 2）。
    - `localStorage` 里 `artcn_pending_request` **已被清掉**（读完即清）。
14. 重复第 12 步，然后**正常登录**（admin / 你在 `.env` 里设的密码）→
    - 登录层收起，进入已登录界面。
    - **输入框里是「画一只戴帽子的猫」**（路径 1）。
    - 顶栏变成 **`目前登录：admin`**，按钮从「登录」变成「退出」。
15. 在输入框点「发送」（这次真的发出去）→ 正常出图。**这一步证明回填没被写成自动发送**（第 14 步没自动发）。

### D. 带图的暂存

16. 游客点 🖼 选一张图 → **不弹登录**，预览正常出现（用户选的 2-c）。
17. 再打几个字，点「发送」→ 弹登录层。
18. 点「← 返回继续浏览」→ **文字回来了，图片预览也回来了**（说明 IndexedDB 那一半通了）。
19. 无痕窗口打开 DevTools → Application → IndexedDB → `artcn_drafts` → `blobs`：暂存期间能看到 `pending` 这一条；第 18 步之后它应该没了。
20. **降级路径**：DevTools → Application → 把 IndexedDB 整体禁用（或在 Firefox 隐私窗口里跑）→ 重复 16~18 → **文字仍然回填**，只是图没了。**不能报错、不能白屏。**

### E. 3 分钟 TTL

21. 游客打字 → 点发送 → 弹登录层。
22. **手动改小时间戳**（比等 3 分钟快）：`localStorage.setItem('artcn_pending_request', JSON.stringify({text:'x', ts: Date.now() - 4*60*1000, file:null}))`，然后点「返回继续浏览」→ **输入框不回填**，且 `artcn_pending_request` 被清掉（§2.5 过期即清）。

### F. 面板门禁与登录后的落点

23. 无痕窗口 → 点「社区」→ 登录门 → 点门上的「登录 / 注册」→ 登录 → **落在社区里**（CommunityPanel 正常加载），不是被弹回聊天（§5.9 路径 3）。
24. 退出登录 → 回到游客外壳（**不是**登录页），顶栏显示「目前登录：未登录」。

### G. 被踢的两条链（**回归，别改坏**）

25. **40304**：把某个测试账号的 `used` 改成大于 `quota_limit`（走管理端「改限额」把上限调成 0 即可），用它登录 →
    - 弹出**欠费充值面板**（Spec21 §7.4）。
    - 这就是 §2.8 那行 `showLogin = true` 的作用。**故意把它注释掉再跑一次**，应当看到面板不再出现——确认自己理解了这条链，然后改回来。
26. **401**：登录后手动把 `localStorage.artcn_token` 改成一个乱码 → 刷新 → 被登出到**游客外壳**，且**登录层自动打开**。

### H. 文案

27. `grep -rn "赋能设计的" frontend/src frontend/index.html README.md Server/agents` → **无输出**。
28. `grep -rn "· {{ auth.username }}\|auth.username }}" frontend/src/App.vue` → **无输出**。
29. 浏览器标签页标题是 `ArtiControlNet - AI辅助设计的系统`。
30. 顶栏那句状态在三种身份下分别是：游客 `目前登录：未登录` / 普通用户 `目前登录：<用户名>` / 管理员 `目前登录：admin`。

### I. 回归（**别把没要求改的改坏了**）

31. 已登录用户：五个面板照常开合、互斥正常；对话侧边栏的「＋ 新对话」在空对话里**仍然是灰的**（`guest=false`，`:disabled` 条件没变）。
32. 已登录用户发文字 / 发图 / 重试失败气泡 / 👍👎 反馈 —— 全部照常。
33. `?register=1` 深链接（无痕窗口）→ 直接看到**登录层 + 注册弹窗**。
34. 帮助弹窗的"首次登录自动弹一次"照旧（换一个新账号验）。

---

## 14. 陷阱清单（**实现时逐条对照**）

1. **⚠️ 登录层必须是 `.app` 的兄弟节点，不能是 `v-else` 替换物。** 替换掉的话，`ChatInput` 被卸载 → 登录成功后回填**无处可去**（§2.1）。验收 C-13/C-14 是它的守卫。

2. **⚠️ 五个面板对游客必须"不挂载"，不是"挡住内容"。** 它们的 `onMounted` 全部立刻发请求 → 401 → `chatApi.js` 拦截器派发 `artcn:unauthorized` → 全局登出（§2.3）。验收 B-5~B-7 检查的是 Network 面板。

3. **⚠️ 401 与 40304 两个监听器都要补 `showLogin.value = true`。** 旧结构里登录页是 `auth.logout()` 的副作用；新结构里没有了。**40304 那条漏了，Spec21 §7.4 那句「若您单击登录键则会跳出充值面板」当场变成空头支票**（§2.8）。验收 G-25 是它的守卫。

4. **⚠️ `ConversationSidebar` 的「＋ 新对话」现在是 `:disabled="currentId === null"`，游客恒 disabled。** 不加 `guest` prop 的话，用户点名的"点新对话跳登录"**根本触发不了**——而且**看起来像没做**（按钮在，就是点不动）。§0 的 2-e。

5. **⚠️ 图片别塞 `localStorage`。** 配额约 5MB，输入框收 ≤10MB 的图，base64 还要涨 33%。`setItem` 抛 `QuotaExceededError` 时如果被吞掉，用户看到的是"登录后什么都没回来"——**和"没暂存过"一模一样**（§2.4）。

6. **⚠️ IDB 写图失败时，必须把 `meta.file` 抹掉。** 否则 `takeRequest()` 会去 IDB 找一个不存在的 Blob，拿到 `null` → `file` 最终是 `null`，**看起来"没坏"，实际是那条 meta 里的 `file` 键永远兑现不了**（§5.4 里那行 `if (!ok) writeMeta({ ...meta, file: null })`）。

7. **⚠️ `watch(() => props.draft, …, { immediate: true })` 的 `immediate` 不能省。** 游客从"点面板 → 登录门 → 登录"那一路进来时 `ChatInput` 还没挂载，`draft` 先在 `App.vue` 里待着，等挂载那一刻才消费（§2.6、验收 F-23）。

8. **⚠️ 登录状态文案要两个条件一起判。** `auth.token` 是同步从 localStorage 读的，`username` 要等 `GET /api/auth/me`。写成 `auth.token ? auth.username : '未登录'` 会在启动那一瞬闪一下「目前登录：」。

9. **⚠️ `trackClick` 保持在门禁之前**（§2.9）。挪到后面会让 `community` / `gallery` / `recharge` 三个指标**悄悄变成"登录用户专属"**，而且从代码上看不出来。

10. **⚠️ 不要实现"登录后自动发送"。** 用户在两选一里明确选了"回填到输入框"。自动发出会**立刻消耗一次额度**（`record_call`），而这一整套改动的出发点恰恰是"别在用户没准备好之前就要东西"（§2.7）。验收 C-15 是它的守卫——**它同时证明了第 14 步没有自动发**。

11. **⚠️ `login_page` 埋点会发得更勤，但库里的数字不变。** `click_events` 有 `UNIQUE(event, ip)`（Spec22 §2.9）。**不要**因为"日志变多"去动 `click_events` 或埋点代码（§10）。

12. **⚠️ `.btn-login-entry` 不要复制一份 `.btn-logout` 的声明。** 合并选择器（`.btn-logout, .btn-login-entry { … }`），否则两份会漂移（§7.7）。同理别忘 `.login-state` 的 `flex-shrink: 0`——横条是 flex row，不加它状态文字会被压扁换行。

13. **⚠️ `store.resetForUser(null)` 的早退分支（`chat.js` 的 `if (!this.username) return`）一个字都不能改。** 它是"游客不调任何列表接口"的唯一保险；删掉的话游客一进站就会 `listConversations()` → 401 → 全局登出事件（§1.3）。

14. **⚠️ 别给游客态接上任何 `GET /api/...`。** 「我的作品」对游客是一个登录门，不是一个空作品库（§3.3-6）。看到"空了"就顺手接数据，等于把 B-5~B-7 的验收全破坏掉。

15. **⚠️ 文案五处一起改，改完 `grep` 扫一遍。** 同一个短语散在 `App.vue` / `Login.vue` / `index.html` / `README.md` / `prompts.py`（§7.7）。`Server/static/` 里的旧构建产物要在第 9 步重建后才会消失——**别把构建产物也算进"没改干净"**。

16. **⚠️ 验收用 `127.0.0.1`，别用 `localhost`**（本机环境下 `localhost` 每请求白等约 2 秒，会把"回填慢"误判成代码问题）。每条用例从**无痕窗口**开始——`localStorage` 与 IndexedDB 都是跨用例污染的。

---

## 15. 收尾：`CLAUDE.md` 要改的段落

| 段落 | 怎么改 |
|---|---|
| 项目概述的 Frontend 那一行 | 「登录页 `views/Login.vue` 是未登录时的唯一入口」→ 改成「**Spec24 起登录页降级成覆盖层**：游客先看到聊天外壳，碰到会落后端的动作（发送 / 新对话 / 开面板 / 充值）才把登录层盖上来；被拦下的内容暂存 3 分钟后回填」 |
| **新增一条 gotcha** | 「**登录层是 `.app` 的兄弟节点，不是 `v-else` 替换物**（Spec24 §2.1）。外壳必须继续挂载——回填的落点 `ChatInput` 在里面，五个面板的 boolean 也在里面。改成替换式的话回填就无处可去。」 |
| **新增一条 gotcha** | 「**五个面板对游客必须"不挂载"而不是"挡住内容"**（Spec24 §2.3）。它们的 `onMounted` 全都立刻发请求，挂载了就是一条 401 → `artcn:unauthorized` → 全局登出。守卫是 `App.vue` 的 `activePanel` 计算属性（互斥且穷尽，游客永远拿不到面板分支）。」 |
| **新增一条 gotcha** | 「**401 / 40304 两个监听器都补了 `showLogin = true`**（Spec24 §2.8）。旧结构里"登出即回登录页"是 `auth.logout()` 的副作用，新结构里没有那个副作用了——40304 那条漏了，Spec21 §7.4 的欠费充值面板就永不出现，提示语变成空头支票。」 |
| **新增一条 gotcha** | 「**未登录暂存：文本进 `localStorage`，图片进 IndexedDB**（Spec24 §2.4）。图片**不能**进 `localStorage`——配额约 5MB 而输入框收 ≤10MB 的图，`QuotaExceededError` 被吞掉之后用户看到的是"登录后什么都没回来"，与"没暂存过"无法区分。3 分钟 TTL 只在 `takeRequest()` 里判一次。」 |
| **新增一条 gotcha** | 「**`ChatInput` 的 `draft` watch 必须带 `immediate: true`**（Spec24 §2.6）。游客从面板那一路登录成功时 `ChatInput` 还没挂载，`draft` 先在 `App.vue` 里待着，等挂载那一刻才消费。」 |
| **新增一条 gotcha** | 「**登录后是回填输入框，不是自动发送**（Spec24 §2.7）。自动发会立刻消耗一次 `record_call`，而用户明确选了回填。**别顺手优化成自动发出。**」 |
| **新增一条 gotcha** | 「**`ConversationSidebar` 的「＋ 新对话」有 `guest` prop**（Spec24 §5.7）。它的 `:disabled="currentId === null"` 会让游客**点不动**那个按钮（游客的 `currentConvId` 恒为 null）——用户点名的"点新对话跳登录"就靠这个 prop 才成立。」 |
| 配置段 | **不动**（本 Spec 0 个新环境变量） |
| `logging_setup.py` 那一行 | **不动**（`_FIELDS` 无增删）；但可补一句「`login_page` 埋点 Spec24 起触发更频繁，`UNIQUE(event, ip)` 保证库里不变」 |
| 「Important notes」新增一条 | 「**`Server/` 自 Spec24 起仍然是"除 `agents/prompts.py` 一行文案外零改动"**——门禁全在前端，`PUBLIC_AUTH_PATHS` 仍是 10 条。」 |
| Spec 索引 | 加一行 `specs/Spec24.md` |
