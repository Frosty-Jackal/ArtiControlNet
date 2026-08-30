# ArtiControlNet Spec 6：追问选项清单 + 画廊提示词溯源（不打磨）

> 目标读者：Claude Code（用于后续 Spec Coding）与项目作者（FJ）。
> 一句话：Spec5 上线后作者的两个反馈修订——①**追问不给选项**：澄清文案要让用户一眼知道"要补哪些参数、每个参数有哪些选项"；②**画廊提示词被打磨 + 看不了全文**：作品里显示的 prompt 不是用户原文（是 DeepSeek 主 Agent 按 Spec.md §6 指示改写的），且过长时后半截看不到、复制不了。
> 本 Spec 是 Spec5 的增量修订，不推翻 Spec5 架构（pending 内存、images 表、ask_clarification 工具均保留）。作者已拍板两项关键决策：**删除独立 style 参数**、**彻底透传原文给 API（方案 B）**，本版按定稿执行。

---

## 1. 问题陈述（用户反馈原文要点）

### 1.1 追问选项不清晰

- 用户被问"想用什么风格？画幅多大？比如：赛博朋克风、16:9。"时无法作答：
  - 只给了 16:9 一个例子，不知道还有哪些画幅可选；
  - "填风格"不知所云——为什么文生图还要单独填风格，风格不该写在描述里吗？
- 当前实现：`ask_clarification(intent, missing, question)` 的 `question` 由 LLM 自由生成（≤100 字），系统提示词只给弱示例；`missing` 只作结构化数据，**不渲染给用户**；`supervisor.tool_node` 拦截时甚至把 `missing` 丢弃，未写入 pending。

### 1.2 画廊提示词：被"打磨"且看不了全文

- 用户发现：作品库里显示的 prompt 不是自己输入的原文，像是被"打磨"过。
- 当前实现：`generation.py` / `editing.py` 把 Supervisor 传入的 `args["prompt"]`（截断 ≤256/≤200）+ `_merge_prompt` 合并风格后存为 `images.prompt`；而 `args["prompt"]` 是 DeepSeek 主 Agent 按系统提示词"综合对话历史补全成独立、可执行的中文描述"改写出的版本。**打磨方 = 主 Agent（路由模型），依据 = Spec.md §6 的原始指示 + Spec5 §5.4 的风格合并**。
- 前端 `GalleryPanel.vue` 用 CSS `-webkit-line-clamp: 2` 截断为 2 行，仅 hover 有 `title` 悬浮，**看不了全文、也复制不了**。

---

## 2. 根因分析

| 现象 | 根因 | 位置 |
|---|---|---|
| 追问不给选项 | 文案由 LLM 自由生成，提示词无选项枚举、无结构化约束；`missing` 字段未透传/未渲染 | `agents/prompts.py` 提示词、`agents/supervisor.py` tool_node、`main.py` handle_task |
| 文生图被问风格 | Spec5 §1 引入独立 `style` 创作参数，语义与"描述含风格"重叠 → **作者拍板删除** | Spec5 §1 / §5.4 |
| 画廊 prompt 非原文 | 主 Agent 按 Spec.md §6 指示"综合历史补全/改写" + `_merge_prompt` 追加"风格：" → **改为透传原文** | `agents/prompts.py`、`generation.py`/`editing.py` `_merge_prompt`、`gallery.save_gallery_image` 入参 |
| 全文看不了/复制不了 | 前端只做 2 行截断 + hover tooltip | `frontend/src/views/GalleryPanel.vue` |

---

## 3. 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 追问文案来源 | **后端按 `missing` + 选项菜单统一格式化**，LLM 只决定 `intent` 与 `missing`（选哪些参数缺失），不再自由写文案 | 选项清单是确定性的，写死在代码里不会漏、不会乱；用户体验稳定 |
| `style` 参数 | **删除独立 `style` 参数**（作者拍板）。风格并入 prompt 描述；`generate_image`/`edit_image` 工具签名去掉 `style`；`generation.py`/`editing.py` 删除 `_merge_prompt` 与"风格："合并逻辑；系统提示词/追问清单不再出现"风格"项 | 文生图场景下独立 style 语义与描述重叠；用户明确困惑 |
| `size` 选项 | **固定清单 + 自定义范围说明**：1:1（1024x1024）/ 16:9（1024x576）/ 9:16（576x1024）/ 4:3（1024x768）/ 3:4（768x1024），或自定义 `宽x高`（宽高 512~2048、面积 ≤1024²） | 选项可穷举，直接展示；TokenHub 限制即合法范围 |
| 主 Agent 是否改写 | **彻底透传原文给 API（方案 B，作者拍板）**：一轮输入若已是完整描述，**原样透传**，不要润色、不要加料；仅在用户表达依赖历史上下文（如"再亮一点""换个红色"）时才做最小组合补全，且尽量保留原文用词 | 尊重用户原文；作品 prompt = 用户原话 |
| 画廊存储 | **不新增 `user_prompt` 列**。透传后 `prompt` 字段本身即用户原文（最小组合时含原文用词），画廊直接存它、前端直接展示 | 方案 B 下 prompt 与原文一致，独立列冗余 |
| 前端全文 | **弹窗（overlay）查看全文 + 「复制」按钮**；卡片 2 行截断保留，截断文本可点击打开弹窗 | 与 Spec5 大图 overlay 交互一致；长 prompt 可看全文、可复制 |

---

## 4. 需求边界

### 范围内

- 删除独立 `style` 参数：工具签名、系统提示词、`_merge_prompt`、风格合并逻辑、追问清单中的"风格"项全部移除。
- 追问文案：缺失参数逐条列出 + 每个参数的可选项（含"不指定/默认"选项）。
- `ask_clarification` 返回结构化信息（`intent` / `missing`），后端据此生成文案；`missing` 透传进 pending。
- `size` 合法选项清单与校验规则写入提示词与后端，两处口径一致。
- 主 Agent：一轮完整输入原样透传；多轮补全尽量保留原文用词。
- 画廊：`prompt` 存透传后的原文；前端"查看全文 + 复制"。

### 范围外（本 Spec 不做）

- 不改 Spec5 已定架构：pending 仍内存、images 表结构不变（不加列）、ask_clarification 工具仍存在。
- 不做"保存多版 prompt"（用户原文 + 改写 + 发送）的版本管理。
- 不做追问的富交互控件（下拉/按钮）——本版仍以文本气泡呈现选项清单，后续 v2 再议。
- 不实测 TokenHub 对超长 prompt 的实际容忍上限——`MAX_PROMPT_LEN` 防御性截断保留（仅限 API 发送），画廊存储存完整原文。若后续实测上限远超 256，可再放宽。

---

## 5. 方案设计（增量）

### 5.1 追问选项结构化 + 删除 style

**工具签名**（`prompts.py` TOOL_DEFINITIONS）：

```
ask_clarification(intent, missing, question?)
  intent    : 计划执行的真实工具（generate_image / edit_image / qa_image）
  missing   : 缺失参数名数组，如 ["size"] / ["question"] / ["prompt"] / ["image_url"]
  question  : 可选。LLM 不再自由写文案；改为由后端依据 missing 生成（保留字段用于兜底）
```

`generate_image`/`edit_image` 参数从 `(prompt, style?, size?)` 改为 `(prompt, size?)`——删除 `style`。

**后端格式化**（新增 `agents/clarify.py` 或并入 `supervisor.py`）：

- 输入 `missing`，输出固定文案，例如：
  - 缺 `size`：画幅想用哪种？可选：1:1（1024x1024）/ 16:9（1024x576）/ 9:16（576x1024）/ 4:3（1024x768）/ 3:4（768x1024）；也可以直接说"宽x高"自定义（宽高 512~2048、面积 ≤1024²）。或回复"随便"用默认画幅。
  - 缺 `question`（QA）：想了解这张图的什么？比如：画面内容 / 构图 / 色彩 / 风格 / 光线。回复"看你"则自动描述画面内容。
  - 缺 `prompt`：请描述你想要什么样的画面（主体 / 场景 / 配色等）。
  - 缺 `image_url`：请上传参考图（或给出已上传图片的说明）。
- `supervisor.tool_node` 把 `missing` 一并放入 `{kind:"clarify", intent, missing, image_url}`；`main.py` handle_task 写入 pending 时保留 `missing`；`_build_messages` 的挂起上下文带上 `missing`，让下一轮主 Agent 知道还缺哪些。

### 5.2 提示词透传（不准打磨）

**主 Agent 提示词修订**（`prompts.py` SUPERVISOR_SYSTEM_PROMPT）：

- 把"综合历史补全成独立描述"改为："一轮输入若已是完整描述，**原样透传**，不要润色、不要加料；仅在用户表达依赖历史上下文（如'再亮一点''换个红色'）时才做最小组合补全，且尽量保留原文用词。"
- 删除风格相关句段（工具 1/2 描述、创作参数确认规则里的"风格"）。

**子 Agent 入库链路**（`generation.py` / `editing.py`）：

- 删除 `_merge_prompt`；`prompt` 直接使用主 Agent 透传的原文（多轮最小组合后的版本）。
- API 发送：保留 `MAX_PROMPT_LEN`（256 / 200）防御性截断——仅影响发送，不影响画廊存储。
- 画廊入库：`gallery.save_gallery_image(image_bytes, user_id, source, prompt)`，存**截断前完整原文**，作品 prompt = 用户原话。

### 5.3 前端画廊全文查看/复制

- `GalleryPanel.vue`：
  - 卡片 prompt 区域：2 行截断保留，截断文本改为可点击（`title` 提示"点击查看全文"），点击打开全文弹窗。
  - overlay：复用大图弹窗（或独立 prompt 弹窗）展示完整 `prompt`，带「复制」按钮（`navigator.clipboard.writeText`，失败回退 `execCommand`）。

---

## 6. 接口/交互改动

| 项 | 改动 |
|---|---|
| `generate_image` / `edit_image` 工具定义 | 删除 `style` 属性 |
| `ask_clarification` 工具 | `question` 变可选；后端按 `missing` 生成文案（见 §5.1） |
| 追问任务终态 | 仍是 `{kind:"text", text:...}`，前端零改动；文案内容变为"选项清单"形式 |
| `GET /api/gallery` 响应 `items[]` | 字段不变；`prompt` 语义从"发送的完整描述"变为"用户原文（透传）"，无新增字段 |
| `GalleryPanel.vue` | 全文弹窗 + 复制按钮 |

---

## 7. 实施顺序

1. **S6-1 删 style + 追问选项**：`prompts.py` 工具定义删 `style`、改 `ask_clarification` 签名 + 系统提示词（删风格、改透传）；新增后端文案格式化（§5.1）；`supervisor.tool_node` / `main.py` handle_task / `_build_messages` 透传 `missing`。
2. **S6-2 子 Agent 透传**：`generation.py`/`editing.py` 删 `_merge_prompt`，画廊存完整原文。
3. **S6-3 前端全文**：`GalleryPanel.vue` 全文弹窗 + 复制。
4. **S6-4 验收**：按 §8 Smoke。

---

## 8. 验收用例（Smoke）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 上传线稿 + "把它上色"（缺画幅） | 追问文案列出全部画幅选项（含"随便"默认项），不是裸的"16:9" |
| 2 | 追问中回复"随便" | 用默认画幅直接出图，不再追问 |
| 3 | 文生图描述里含风格（如"赛博朋克风海报"） | 不再追问风格；作品 prompt = 用户原文，未被改写 |
| 4 | 我的作品里点开一张生成图 | 能看到完整原文 prompt，且可一键复制 |
| 5 | 文生图不加风格、不加画幅 | 只有画幅缺失时追问画幅一次；用户直接说"做一张海报"而没提画幅 → 追问画幅（含全部选项） |
| 6 | 多轮"再亮一点" | 最小组合补全但仍保留"再亮一点"原文用词；作品 prompt 可见原话 |
