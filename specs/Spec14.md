# ArtiControlNet Spec 14：产品口径统一（标语改为「赋能设计的 AIGC 系统」）

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：全项目的**产品标语**从「多智能体 AI 创意工作台 / 辅助设计的 AI 工作台 / AI 创意工作台」统一为 **「赋能设计的 AIGC 系统」**——涉及**用户可见界面（A）、后端提示词（B）、文档与脚本（D）**三组共 **10 处**。
> 本 Spec 是 **Spec.md / Spec2~13 的增量补充**，且性质特殊：**它是纯口径修订，不含任何功能变更**——不加接口、不改数据结构、不改交互、不改样式、不加错误码/日志/配置/依赖。**唯一有行为面的一处**是 `Server/agents/prompts.py:8`（进模型上下文的 Supervisor 系统提示词），故验收里含一轮路由冒烟。
> 硬约束仍遵守：无本地推理、只有前后端两层、无新数据库、无新 pip/npm 依赖。

---

## 1. 功能目的

- **一个产品，一个名字**：目前同一件事在三处被叫成三种样子——登录后左上角叫「多智能体 AI 创意工作台」，登录页叫「多智能体 AI 创意工作台」，帮助弹窗叫「辅助设计的 AI 工作台」，浏览器标签页叫「AI 创意工作台」。用户每换一个界面就要重新理解一次"这是什么产品"。本 Spec 收敛成一句。
- **把"做什么"说清楚**：旧标语的主语是**技术形态**（多智能体 / 工作台），新标语的主语是**产品价值**（赋能设计）——面向设计师这个受众，后者才是他们关心的问题。
- **顺手修正一处口径错误**：旧标语里的「多智能体」在项目自己的材料里就是被标注为**容易误导**的说法（`产品面经.txt` 开篇即写明"项目的技术实质是 Single Agent + 多工具编排，不是 Multi-Agent"）。新标语不再背负这个词，等于把一个已知的表述风险去掉。
- **改动可穷尽、可复核**：本 Spec 的价值主要在**清单的完整性**——把"产品名/定位"的每一处露出都钉死在文里，改完可以靠一条命令复检（§11 用例 5）。

---

## 2. 口径定稿

**新标语（唯一写法）**：

```
赋能设计的 AIGC 系统
```

| 规则 | 内容 |
|---|---|
| 排版 | **`AIGC` 两侧各留一个半角空格**（与项目既有「AI 创意工作台」「图文生图 / 图像问答」的排版习惯一致）。作者原话写作「赋能设计的AIGC系统」，本 Spec 明确按**加空格**版本落库 |
| 品牌名 | **`ArtiControlNet` 原样保留**，标语只替换它后面那句描述；两者组合如 `ArtiControlNet - 赋能设计的 AIGC 系统` |
| 英文口径 | `design-empowering AIGC system`（**不**用 `AIGC system that empowers design` 这类直译长句）；`一键启动.bat` 保持纯 ASCII 英文 |
| 「多智能体」 | 从**标语**中退役；**不作为架构术语被全局禁用**——历史 spec 与 `产品面经.txt` 正文里讨论架构时仍在用（见 §4 范围外） |

---

## 3. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 空格 | **加**：`赋能设计的 AIGC 系统` | 作者拍板。既符合项目既有中英混排习惯（旧标语就是「AI 创意工作台」），也避免小字号下 `的AIGC系统` 挤成一坨 |
| 品牌名 | **不动** | 作者只要求改"产品名描述"。`ArtiControlNet` 出现在 logo、FastAPI title、分享页、下载文件名前缀等**十几处**，动它是另一件事（且会牵出 `artcn_` 命名前缀这类内部标识） |
| A 类（用户可见） | **全改**：App 头部 / 登录页 / 帮助弹窗 / 标签页标题 | 这四处是**同一个标语的四种露出**，改一半等于没统一 |
| B 类（LLM 提示词） | **改**，且只改**开头那一句的身份定义** | `prompts.py:8` 会进 Supervisor 的上下文；它写着「你是 ArtiControlNet 多智能体对话工作台的主 Agent」——本项目自己的材料都认为「多智能体」是误导性说法，让模型也照着这个自我认知走，没有好处 |
| B 类的具体改法 | `你是 ArtiControlNet（赋能设计的 AIGC 系统）的主 Agent（Supervisor）。` | **保留品牌名 + 用括号挂定位**，一句话内读完；不写成「你是赋能设计的 AIGC 系统的主 Agent」——那会把品牌名从提示词里抹掉，而品牌名是模型自我指称时唯一稳定的锚点 |
| B 类的改动边界 | **只动第 8 行那一句**，该提示词其余全部内容（职责说明、四个工具定义、路由规则）**一字不改** | 提示词的职责描述是**功能**、标语是**身份**；顺手"优化"职责措辞会引入无法归因的路由行为变化。本 Spec 要的是**可归因**的最小改动 |
| D 类（文档/脚本） | **改**：`README.md`、`CLAUDE.md`、`一键启动.bat`、`产品面经.txt` | 作者拍板 ABD 全改。README 是仓库门面、CLAUDE.md 是后续 AI 协作者的必读前言、bat 是交付给外部演示者的第一个窗口、面经是作者本人的对外叙述——四处口径不一致时，最可信的是其中最新的那份，等于没标准 |
| `README.md:44`「完整的工作台」 | **改**为「完整的系统」 | 这是一个**泛指**用法（指"这一整套东西"），不是标语；但「工作台」正是本次退役的词，留着会在同一份文档里和标语打架。一句同义词替换，零风险 |
| `CLAUDE.md:7` 的英文 | `a **design-empowering AIGC system** for designers` | 同句后半段（Supervisor 单跳路由 + 子 Agent + 云端 API + 结果直返）**原样保留**——那是机制描述，不是标语 |
| `产品面经.txt` 改几处 | **只改「项目一句话」那 1 处**（全文共 12 处「多智能体」） | 另外 11 处出现在问题解答的**架构讨论**里（"我用了什么模型""Agent 怎么编排"），是**术语**不是**标语**；且该文件自己的「术语约定」段说明"本文件沿用项目文档里的叫法"——项目 spec 不改（见下条），故那句仍然成立。连带改 11 处等于重写全套问答，超出"统一标语"的范围 |
| 历史 spec（`Spec.md:5`、`Spec8.md:116` 等） | **不改** | 它们是"当时怎么定的"**存档**。`Spec8.md:116` 里的帮助文案是**当时**的定稿，改了它反而让 Spec 与"当时交付的东西"对不上。历史口径的唯一正确处理方式是**由本 Spec 记录变更**，而不是回改旧档 |
| `main.css:130` 注释、`artcn_*` 变量/键名、`Server/main.py:251` FastAPI title、`shares.py` 分享页品牌行、logo `<h1>` | **全部不动**（C/E 类） | 要么是**代码内部标识**（不面向用户，改了徒增 diff 与回归面），要么**只有品牌名没有标语**（本 Spec 不涉及） |
| 分享页要不要加标语 | **本 Spec 不加**（仅记录） | `Server/shares.py` 的分享页是**唯一站外露出**（发链接给外部人免登录看），加标语属于**新增曝光位**而非"统一既有口径"。留作后续单独决定（一行改动） |
| 构建产物 | `npm run build` + 同步 `Server/static/`（**不手改**） | `Server/static/index.html` 与 `assets/*.js` 里各有一份旧标语副本；它们是产物，手改会被下次构建覆盖。同步后 JS 的文件名 hash 会变（旧的删除、新的新增） |

---

## 4. 需求边界

### 范围内（A / B / D 三组，共 10 处）

| 组 | 文件 | 处数 |
|---|---|---|
| **A** 用户可见 | `frontend/src/App.vue`、`frontend/src/views/Login.vue`、`frontend/src/views/HelpModal.vue`、`frontend/index.html` | 4 |
| **B** 提示词 | `Server/agents/prompts.py` | 1 |
| **D** 文档/脚本 | `README.md`（2 处）、`CLAUDE.md`、`一键启动.bat`（2 处）、`产品面经.txt` | 6 |
| **产物** | `Server/static/`（build 自动生成） | — |

### 范围外（本 Spec 不做）

- **品牌名 `ArtiControlNet` 的任何改名**：logo、FastAPI title、分享页品牌行、下载文件名前缀 `artcn_`、localStorage 键 `artcn_*`、`artcn.db`——一律不动。
- **给"只有品牌名"的位置补标语**：`HelpModal.vue:6`「认识 ArtiControlNet」、`shares.py` 分享页、`App.vue:13` / `Login.vue:6` 的 `<h1>`、`Server/main.py:251`——**不新增曝光位**。
- **历史 spec 回改**：`specs/Spec.md`、`Spec2`、`Spec5`、`Spec8`（含 `:116` 帮助文案定稿）等一律留档。
- **`产品面经.txt` 其余 11 处「多智能体」**：属架构术语讨论，不改。
- **代码内部注释与标识**：`main.css:130`「对话工作台布局」注释、变量名、localStorage 键名、日志事件名。
- **任何功能 / 接口 / 数据结构 / 样式 / 交互变更**；不新增错误码、日志事件、配置项、依赖。
- **`CLAUDE.md` 里除第 7 行以外的内容**：架构说明、硬约束、命令等全部原样。

### 已知限制（写入本文档，避免误读）

- **仓库内仍会残留「多智能体」**：`specs/*.md` 与 `产品面经.txt` 正文合计十余处。这是**刻意**的（历史留档 + 架构术语），不是漏改。**复检命令必须排除 `specs/`**，否则会误报（见 §11 用例 5）。
- **「工作台」这个词仍会出现在历史 spec 与代码注释里**：同上，刻意保留。
- **英文口径不是逐字直译**：`design-empowering AIGC system` 是「赋能设计的 AIGC 系统」的**英文惯用表达**，语序与中文不同，属正常。
- **`产品面经.txt` 是本地自用稿且已 gitignore**：本 Spec 的改动**不会进版本库**，只在作者本机生效。

---

## 5. 技术栈增量

| 层 | 新增 |
|---|---|
| 后端 | **无**（只改 `prompts.py` 一行字符串字面量，无新模块/依赖/配置） |
| 前端 | **无**（只改模板里的字符串字面量，无新组件/依赖/样式） |
| 文档 | 无新文件 |

> 无新 pip / npm 依赖；无新环境变量；`.gitignore` / `requirements.txt` / `package.json` / 数据库 schema **全部不变**。

---

## 6. 改动清单（逐条 before → after）

### A 组：用户可见（4 处）

| # | 文件:行 | before | after |
|---|---|---|---|
| A1 | `frontend/src/App.vue:16` | `多智能体 AI 创意工作台 · {{ auth.username }}` | `赋能设计的 AIGC 系统 · {{ auth.username }}` |
| A2 | `frontend/src/views/Login.vue:8` | `多智能体 AI 创意工作台 · 登录后使用` | `赋能设计的 AIGC 系统 · 登录后使用` |
| A3 | `frontend/src/views/HelpModal.vue:7` | `辅助设计的 AI 工作台——你说想法，它出图。三种玩法，照着说就行。` | `赋能设计的 AIGC 系统——你说想法，它出图。三种玩法，照着说就行。` |
| A4 | `frontend/index.html:7` | `<title>ArtiControlNet - AI 创意工作台</title>` | `<title>ArtiControlNet - 赋能设计的 AIGC 系统</title>` |

> **A1 是"所有页面"的那一处**：它在登录后共用的 `<header>` 里，聊天 / 我的作品 / 社区 / 建议 / 用户管理 / 数据统计**六个视图共用**，改一处即全覆盖。
> **A3 只换破折号前面的半句**：`——你说想法，它出图。三种玩法，照着说就行。` 与下面三张能力卡片（🎨 文生图 / 🖌 图文生图 / 🔍 图片问答）**一字不动**。
> **A4 同时是 PWA/收藏夹/浏览器历史里的名字**，改完需要重新构建才会生效（§7）。

### B 组：LLM 提示词（1 处）

| # | 文件:行 | before | after |
|---|---|---|---|
| B1 | `Server/agents/prompts.py:8` | `SUPERVISOR_SYSTEM_PROMPT = """你是 ArtiControlNet 多智能体对话工作台的主 Agent（Supervisor）。` | `SUPERVISOR_SYSTEM_PROMPT = """你是 ArtiControlNet（赋能设计的 AIGC 系统）的主 Agent（Supervisor）。` |

> **只改第 8 行这一句**。该提示词第 9 行起（职责说明 / 四个工具定义 / 路由规则 / 输出格式）**全部原样**——见 §3 决策。

### D 组：文档与脚本（6 处）

| # | 文件:行 | before | after |
|---|---|---|---|
| D1 | `README.md:5` | `ArtiControlNet 是一款依托 AI 能力辅助设计师创作的定制化 AIGC 产品：用自然语言（可带参考图）提出需求，…` | `ArtiControlNet 是一款赋能设计的 AIGC 系统：用自然语言（可带参考图）提出需求，…` |
| D2 | `README.md:44` | `启动后打开 **http://localhost:8000** 就是完整的工作台——…` | `启动后打开 **http://localhost:8000** 就是完整的系统——…` |
| D3 | `CLAUDE.md:7` | `ArtiControlNet is a **multi-agent AIGC chat workbench** for designers ("基于进化算法…"). Users describe what they want in natural language (optionally attaching a reference image); a Supervisor agent does a single intent-routing pass, and child agents complete "text-to-image / sketch-to-image / image QA" via **external cloud model APIs**, returning results **directly to the user**.` | `ArtiControlNet is a **design-empowering AIGC system** for designers ("基于进化算法…"). Users describe what they want in natural language (optionally attaching a reference image); a Supervisor agent does a single intent-routing pass, and child agents complete "text-to-image / sketch-to-image / image QA" via **external cloud model APIs**, returning results **directly to the user**.` |
| D4 | `一键启动.bat:2` | `title ArtiControlNet AIGC Workbench` | `title ArtiControlNet (Design-Empowering AIGC System)` |
| D5 | `一键启动.bat:6` | `echo   ArtiControlNet AIGC Workbench - One-click launcher` | `echo   ArtiControlNet (Design-Empowering AIGC System) - One-click launcher` |
| D6 | `产品面经.txt:12` | `项目一句话：为设计师做的多智能体 AIGC 对话工作台。用户用自然语言（可带参考图）` | `项目一句话：赋能设计的 AIGC 系统。用户用自然语言（可带参考图）` |

> **D1 只换加粗短语的定语部分**，冒号后那句机制描述（主 Agent 分发 / 子 Agent 经云端 API / 三个能力）原样保留。
> **D3 只换句子前半段的定位短语**，`Users describe…` 之后的机制描述原样保留（与 D1 同一原则）。
> **D4 / D5 保持纯 ASCII**：bat 是 Windows 启动器，中文窗口标题在部分终端的编码下会乱码，故英文表达。
> **D6 只换第一个分句**，`用户用自然语言（可带参考图）提需求，主 Agent（Supervisor）做一次意图分发…` 原样保留；该文件里其余 11 处「多智能体」按 §3 决策**不动**。

---

## 7. 构建产物同步（A 组的落地前置）

A1~A4 改完后**必须**：

```bash
cd frontend && npm run build          # 生成 dist/（含新标语 + 新文件 hash）
# 同步 dist → Server/static（与既有提交口径一致：删旧 assets、拷新 assets + index.html）
```

- `Server/static/index.html:7` 的 `<title>` 与 `Server/static/assets/*.js` 里打包的标语文本，**由构建覆盖**，绝不手改。
- 同步后：旧 hash 的 `assets/index-*.js|css` **删除**，新增新 hash 文件（`Server/static/index.html` 内的引用同步更新）。
- `Server/static/favicon.svg` 不随标语变化（品牌未动），可原样覆盖。

---

## 8. 接口约定 / 配置 / 错误码 / 日志

**全部无变更。**

- 接口：不新增、不修改任何端点，响应壳与鉴权口径（Spec2/Spec12）不变。
- 配置：不新增环境变量与 `config.py` 常量。
- 错误码：不新增、不修改；`errors.py` 不动。
- 日志：不新增事件；日志字段与格式（Spec.md §10）不变。
- 数据库：`.py` 里除 `prompts.py` 那一行外零改动，`artcn.db` schema 不变。

---

## 9. 目录结构增量

```
frontend/
  index.html                    # A4 标签页标题
  src/App.vue                   # A1 共用 header 标语
  src/views/Login.vue           # A2 登录页副标题
  src/views/HelpModal.vue       # A3 帮助弹窗首段
Server/
  agents/prompts.py             # B1 Supervisor 身份定义（第 8 行，唯一有行为面的一处）
  static/                       # 构建产物（§7 同步，非手改）
README.md                       # D1 / D2
CLAUDE.md                       # D3
一键启动.bat                     # D4 / D5
产品面经.txt                     # D6（本地自用、已 gitignore，不进版本库）
specs/Spec14.md                 # 本文件（变更的权威记录）
```

> **无新文件、无新依赖、无删除文件**（唯一"删除"是 `Server/static/assets/` 里的旧 hash 构建产物）。

---

## 10. 实施顺序（里程碑）

1. **W1 前端文案（A）**：A1~A4 逐条替换。
2. **W2 构建与同步**：`cd frontend && npm run build` → 同步 `frontend/dist` → `Server/static/`（§7）。
3. **W3 提示词（B）**：`prompts.py:8` 一句替换。
4. **W4 文档与脚本（D）**：D1~D6 逐条替换。
5. **W5 复检**：§11 全量走查（含一条命令的口径复检 + 一轮路由冒烟）。

> W1/W2 与 W3 无依赖，可并行；**W5 必须在 W2 之后**（否则检的是旧产物）。

---

## 11. 验收用例

| # | 操作 | 期望 |
|---|---|---|
| 1 | 登录后依次进聊天 / 我的作品 / 社区 / 建议 / 用户管理 / 数据统计 | 六个视图左上角**统一**为 `赋能设计的 AIGC 系统 · <用户名>`，无一处残留旧标语 |
| 2 | 打开登录页（未登录 / 退出登录后） | 副标题为 `赋能设计的 AIGC 系统 · 登录后使用` |
| 3 | 点顶部「帮助」 | 首段为 `赋能设计的 AIGC 系统——你说想法，它出图。三种玩法，照着说就行。`；三张能力卡片与底部提示**文案未变**；标题仍为「认识 ArtiControlNet」 |
| 4 | 看浏览器标签页 / 收藏夹标题 | `ArtiControlNet - 赋能设计的 AIGC 系统`（**构建并同步后**才生效） |
| 5 | 仓库口径复检（一条命令） | 源文件与构建产物中 **0 命中**旧标语；`specs/` 与 `产品面经.txt` 正文的「多智能体」**允许命中**（§4 已知限制）<br>`grep -rn --exclude-dir={.venv,node_modules,__pycache__} --exclude-dir=specs -e "多智能体 AI 创意工作台" -e "辅助设计的 AI 工作台" -e "AI 创意工作台" .`<br>**改前基线（已实测）= 8 命中**：`frontend/src/App.vue:16`、`Login.vue:8`、`HelpModal.vue:7`、`frontend/index.html:7`、`frontend/dist/index.html:7` + `dist/assets/*.js`、`Server/static/index.html:7` + `static/assets/*.js`。改完 + 重新构建同步后应为 **0**（`dist/` 与 `static/` 一并覆盖，故该命令顺带验证了构建产物是新鲜的） |
| 6 | **路由冒烟**（B1 的回归验证）：分别发「做一张赛博朋克风的新年海报」/ 上传线稿 +「按这张线稿上色，日系动漫风」/ 上传照片 +「这张图怎么样？帮我打个分」 | 三次都正确选中 `generate_image` / `edit_image` / `qa_image`，出图与回答正常，表现与改前一致 |
| 7 | 追问链路冒烟：只说「帮我画一张图」（缺 prompt） | 仍走 `ask_clarification` 追问，追问文案与改前一致 |
| 8 | 打开一个已生成的分享链接（免登录） | 页面标题 `作品分享 · ArtiControlNet`、品牌行 `ArtiControlNet · 作品分享`——**不含标语**（本 Spec 不改），功能正常 |
| 9 | 访问 `/docs` | FastAPI title 仍为 `ArtiControlNet`（C 类不改） |
| 10 | 看 `README.md` / `CLAUDE.md` / `一键启动.bat` | 三处均为新口径；bat 双击后窗口标题为 `ArtiControlNet (Design-Empowering AIGC System)`，中文不乱码（纯 ASCII） |
| 11 | 数据与接口回归 | 生成 / 上传 / 作品库 / 分享 / 建议箱 / 用户管理 / 统计**行为与改前完全一致**；`git diff` 只含文案行 + 构建产物，`Server/` 下除 `prompts.py` 一行外零改动 |
| 12 | 重启后端 | `prompts.py` 为模块级常量，重启即生效；无需重建数据库、无需迁移 |

> 用例 6/7 通过标准：Supervisor 仍能正确选中 `generate_image` / `edit_image` / `qa_image` / `ask_clarification`，且**行为与改前一致**（提示词只有身份那半句变了）。若出现选择退化，回退 B1 并记录——即"标语统一不值得牺牲路由质量"。
> 验收时明确排除：品牌名改名 / 给只有品牌名的位置补标语 / 历史 spec 与面经正文的「多智能体」/ 代码内部注释与标识 / 分享页加标语。
