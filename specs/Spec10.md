# ArtiControlNet Spec 10：建议箱重做 + 共享样式上移（去白底）+ 拖拽上传

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：针对 Spec9 落地后的三处反馈做收尾——①**建议箱重做**：管理员**不能写建议、只能审批**（回复弹窗 + 状态二选一，发送自动标记「已处理」），普通用户端改弹窗只读查看「状态 + 管理员回复」，去掉"待用户处理/已读"两态；②**去白底**：修复 `.gallery-tab/.gallery-lightbox/.gallery-empty` 等类因**只在 GalleryPanel 的 `<style scoped>` 里定义、跨组件复用失效**导致标签按钮退化成原生白底的问题，统一提升到全局 `main.css` 并加 `color-scheme: dark`；③**拖拽上传**：主聊天输入区与社区发帖弹窗的上传区都支持把图片拖进去。
> 本 Spec 是 **Spec.md / Spec2~9 的增量补充**，不推翻原有架构。无新数据表、无新依赖、无新环境变量。唯一数据库语义变化：`suggestions.status` 取值由 `pending|read|resolved` **收敛为 `pending|resolved`**（老数据 `read` 启动时迁移为 `pending`）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量。数据库例外沿用 Spec2：仅本地单文件 SQLite。

---

## 1. 功能目的

- **建议箱（重做）**：普通用户仍写信给管理员（发送前 `confirm` 警告一次）；管理员在「管理建议」里**只能审批**——点开**回复弹窗**（状态二选一 + 写回复 + 发送，一次性落库），或删除建议；**管理员没有写信入口**（前端隐藏 + 后端拦截）。普通用户在「我的建议」里点开自己的建议 → **弹窗**只读展示全文、状态、管理员回复；普通用户**不具备回复权限**（后端本无用户回复接口，前端也不渲染回复框）。
- **状态语义（收敛为两态）**：`pending` = 待管理员处理（新建议初始态）；`resolved` = 已处理。**不设"待用户处理/已读"**——用户无法回复，这两个状态没有存在意义。管理员发送回复时**自动标记为 `resolved`**，弹窗内也可手动在 `pending` / `resolved` 之间切换。
- **去白底（共享样式上移）**：消灭"就那一小坨文字是白底、其余都是深紫"的现象。根因是 scoped CSS 跨组件复用失效（见 §2.3），把共享类上移到全局 `main.css` + `:root { color-scheme: dark }`，让标签按钮、弹窗遮罩、空态、原生 select 弹层全部统一深紫主题。
- **拖拽上传**：主聊天输入区和社区发帖弹窗的「上传新图」都支持把图片文件直接拖进区域（带拖入高亮反馈，松手即拾取），点击选择仍保留。

---

## 2. 决策记录（为什么这么选）

### 2.1 建议状态收敛

| 决策 | 选择 | 理由 |
|---|---|---|
| 状态取值 | 两态：`pending`（待管理员处理）/ `resolved`（已处理） | 作者拍板：**去掉"待用户处理"**（用户压根无法回复，没有"等用户"这回事）；`read`（已读）也无实际价值，一并去掉 |
| 初始态 | 新建议 `status='pending'`（待管理员处理） | 新建议自然等管理员处理 |
| 回复后自动态 | 管理员在回复弹窗点「发送」→ **自动置 `resolved`** | 作者拍板「已处理就是管理员发送回复可以自动标记」 |
| 手动改状态 | 回复弹窗内提供 `pending / resolved` **二选一**（默认 `resolved`） | 作者拍板「也可以弹窗里手动二选一」——管理员可把回复过的建议挂回 `pending` 继续跟进 |
| 老数据 | 启动时把 `status='read'` 迁移为 `'pending'` | 收敛词汇表，避免老值悬空；量级小，一条 UPDATE |
| 状态权限 | 只有管理员能改状态 / 写回复 | 普通用户端纯只读（Spec10 保持 Spec9 口径：后端无用户侧回复接口） |

### 2.2 管理员不写建议

| 决策 | 选择 | 理由 |
|---|---|---|
| 管理员可否写信 | **否** | 作者拍板「管理员肯定不能写建议，管理员只能审批建议」 |
| 前端 | 管理员端不显示写信区，只显示「管理建议」视图（按 `auth.isAdmin` 分支，不再用 Tab） | 无入口即无诱惑 |
| 后端 | `POST /api/suggestions` 对 `is_admin` 用户返回 `403`（复用 `40301` ForbiddenError） | 双保险，防绕过前端直接调接口 |

### 2.3 白底根因与修复（关键决策）

| 决策 | 选择 | 理由 |
|---|---|---|
| 现象 | 「就那一小坨文字是白底，其余都是深紫」 | 出现在建议页标签按钮与社区发帖弹窗标签按钮 |
| 根因 | `.gallery-tab / .gallery-tabs / .gallery-empty / .gallery-lightbox*` **只在 `GalleryPanel.vue` 的 `<style scoped>` 里定义**，却被 `SuggestionPanel.vue`、`CommunityPanel.vue` 复用。Vue scoped 样式给选择器打上 `[data-v-组件hash]`，其他组件元素匹配不到 → 标签按钮退化为**浏览器原生 button 的浅灰/白底**，弹窗遮罩（`position:fixed` + 半透明底）也失效 | 代码审查确认：这些类在三个组件里被使用，却只在一处 scoped 定义；原生 `<button>` 默认 `buttonface` 浅灰底即"白底小坨" |
| 修复 1 | 把共享类提升到**全局 `main.css`**：`.gallery-tabs/.gallery-tab(+:hover/.active)/.gallery-empty/.gallery-lightbox(+inner/bar)/.community-time`，并从 `GalleryPanel.vue`、`CommunityPanel.vue` 的 scoped 中移除（单一事实源） | 全局类天然跨组件生效；`GalleryPanel.vue` 自身同名元素同样命中，不受影响 |
| 修复 2 | `:root { color-scheme: dark }` | 让原生控件（`<select>` 展开的选项弹层、滚动条、`<input>` 等）跟随深色主题，杜绝系统浅色弹层 |
| 修复 3 | 全局为 `select / option` 补深色兜底样式（`--bg-input` 底 + `--text-primary` 字） | 二次保险：即便某个 select 没写类，也不再出白底 |

### 2.4 回复 / 查看弹窗

| 决策 | 选择 | 理由 |
|---|---|---|
| 管理员交互 | 每行建议一个「回复 / 审批」按钮 → 打开**弹窗**：状态二选一 + 回复 `<textarea>` + 「发送」/「取消」；发送 = 一次 `PUT {status, reply}` 落库 | 作者拍板「写回复信息并发送的弹窗（发送就是存到建议回复同一表的数据库里去）」；替代 Spec9 的行内 `<select>` + `<input>` |
| 删除 | 仍为行内「删除」按钮（`confirm` 后 `DELETE`） | Spec9 已有，保留；弹窗不承载删除 |
| 普通用户交互 | 建议**卡片**列表；点卡片 → 弹窗只读显示全文 + 状态徽标 + 管理员回复 + 时间 | 作者拍板「普通用户端设计弹窗，显示自己写的建议的管理员回复和该建议的状态」；无回复框 |

---

## 3. 需求边界

**范围内**

- 建议箱：用户写信（≤2000 字，发送前 `confirm`）；用户弹窗只读查看（状态 + 回复）；管理员回复弹窗（状态二选一 + 回复 + 发送，自动 `resolved`）+ 行内删除；管理员无写信入口（前后端双重拦截）；老 `read` 状态迁移为 `pending`。
- 去白底：共享 `.gallery-*` 类提升全局；`color-scheme: dark`；`select/option` 深色兜底。
- 拖拽上传：主聊天输入区 + 社区发帖「上传新图」区，拖入即拾取（格式/大小校验与点击选择一致）。

**范围外（本 Spec 不做）**

- 建议**多轮来回会话**（一条提交 = 一条建议，回复即终态，维持 Spec9 §3.4）；用户回复权限（明确无）。
- 状态超过两态（不引入"待用户处理/待管理员处理/已处理/已读"等更多词汇）。
- 建议通知 / 未读红点 / 自动回复 / 分类 / 附件。
- 主聊天之外其他面板（作品库 / 社区发帖外的图片选择）的拖拽上传；批量拖拽多图（本 Spec 只支持单图，与发帖单图约束一致）。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | 无新依赖 | 仅 `db.py`（状态白名单 + 迁移）与 `main.py`（管理员禁写拦截 + 白名单）微调 |
| 前端 | 无新依赖 / 无新框架 | `main.css` 共享类上移；`SuggestionPanel.vue` 重写；`CommunityPanel.vue` / `ChatInput.vue` / `GalleryPanel.vue` 增量 |

> 无新 pip / npm 依赖；无新环境变量；`config.py` 不变。

---

## 5. 架构设计（增量）

### 5.1 数据变更

`artcn.db` 的 `suggestions` 表结构**不变**（字段照旧），仅**语义**变化：

```
suggestions.status:  'pending'（待管理员处理）| 'resolved'（已处理）
   - 新建议  → 'pending'
   - 管理员发送回复 → 'resolved'（弹窗内可手动改回 'pending'）
   - 老数据 'read' → 启动迁移为 'pending'
```

启动迁移（`init_db` 内，幂等）：

```sql
UPDATE suggestions SET status = 'pending', updated_at = updated_at WHERE status = 'read';
```

> 只收敛取值词汇，不动表结构，不需要改表 / 删表。

### 5.2 关键数据流

- **管理员禁写**：`POST /api/suggestions` → `request.state.user["is_admin"]` 为真 → 抛 `ForbiddenError("管理员不能提交建议")`（`40301`）。
- **管理员审批**：`PUT /api/admin/suggestions/{id}` 请求体 `{status?, reply?}`，`status` 白名单收敛为 `{pending, resolved}`（`db.py` 的 `_SUGGESTION_STATUSES` 同步）；回复与状态**一次落库**（同一条 UPDATE，`updated_at` 刷新）。
- **前端自动置已处理**：回复弹窗默认把状态选为 `resolved`，管理员直接点发送即得到"回复后自动已处理"；改回 `pending` 则继续挂起。
- **普通用户只读**：`GET /api/suggestions/mine` 返回自身建议（含 `status/reply`），前端弹窗渲染，无任何写回控件。

---

## 6. 接口约定

### 6.1 变更

| 端点 | 变更 |
|---|---|
| `POST /api/suggestions` | 新增：`is_admin` 用户 → `403`（`40301`，message「管理员不能提交建议」）。普通用户行为不变 |
| `GET /api/admin/suggestions` | `?status=` 白名单由 `pending\|read\|resolved` 收敛为 `pending\|resolved`（非法 → `40013`） |
| `PUT /api/admin/suggestions/{id}` | `status` 白名单同上收敛为两态；`{status, reply}` 一次落库（Spec9 已支持），语义不变 |
| 其余全部接口 | **不变** |

### 6.2 鉴权约定

与 Spec9 §6.2 一致；唯一新增：`POST /api/suggestions` 对管理员额外拒绝（`40301`）。

---

## 7. 前端交互

- **`main.css`（去白底核心）**：
  - `:root` 增加 `color-scheme: dark;`。
  - 新增全局 `.gallery-tabs` / `.gallery-tab`（+ `:hover` / `.active`）/ `.gallery-empty` / `.gallery-lightbox`（+ `.gallery-lightbox-inner` / `.gallery-lightbox-inner img` / `.gallery-lightbox-bar`）/ `.community-time`；同时从 `GalleryPanel.vue`、`CommunityPanel.vue` 的 scoped 中删除同名定义（避免双源）。
  - 新增全局 `select / option` 深色兜底（`--bg-input` 底、`--text-primary` 字、`--border-color` 边）。
- **`SuggestionPanel.vue`（重写）**：去掉 Tab，按 `auth.isAdmin` 分支：
  - **普通用户**「我的建议」：顶部写信区（textarea ≤2000 + 「发送」，`confirm` 一次）；下方建议**卡片**列表（状态徽标 `pending→待管理员处理` / `resolved→已处理` + 时间 + 文字摘要），点卡片 → **只读弹窗**（全文 + 状态 + 管理员回复 + 时间 + 关闭）。
  - **管理员**「管理建议」：全部建议表格（发送者 / 建议 / 状态 / 回复预览 / 时间 / 操作）；每行「回复 / 审批」按钮 → **回复弹窗**（状态二选一默认 `resolved` + 回复 textarea 预填当前回复 + 「发送」「取消」，发送 = 一次 `PUT`）+「删除」按钮（`confirm`）。**无写信区**。
- **`CommunityPanel.vue`**：发帖弹窗两个 Tab（从作品库选择 / 上传新图）改用全局 `.gallery-tab`（深紫胶囊）；「上传新图」区支持**拖拽**：`dragover` 高亮（紫色虚线边框）+ `drop` 拾取（复用现有 `onPickFile` 校验逻辑），点击选择仍保留。
- **`ChatInput.vue`**：主聊天输入区支持**拖拽**：拖入显示浮层提示「松开以添加参考图」并高亮，`drop` 拾取图片 → 复用现有 `onFile` 的格式/大小校验（抽成 `acceptFile(f)` 供点击与拖拽共用）。
- `GalleryPanel.vue`：仅删除已上移的 scoped 类定义，行为不变。

---

## 8. 配置 / 环境变量 / .gitignore

无新增。`config.py`、`.env`、`.gitignore` 均不变（`artcn.db` 数据迁移在 `init_db` 启动时自动完成）。

---

## 9. 错误码

无新增错误码。管理员提交建议复用 `40301 ForbiddenError`（message「管理员不能提交建议」）；状态白名单非法仍为 `40013`。

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON 与 Spec9 §10 事件。新增一条：
- `suggestion.rejected`（管理员尝试写建议被拒，附 user_id / event，不记正文）。

其余 `suggestion.created / updated / deleted` 语义不变。

---

## 11. 目录结构增量

```
Server/
  db.py         # _SUGGESTION_STATUSES = ("pending","resolved")；init_db 加 read→pending 迁移
  main.py       # POST /api/suggestions 管理员拦截；admin 建议状态白名单收敛两态
frontend/src/
  assets/styles/main.css        # 共享 .gallery-* / .community-time 上移 + color-scheme:dark + select/option 兜底
  views/SuggestionPanel.vue     # 重写：用户只读弹窗 / 管理员回复弹窗
  views/CommunityPanel.vue      # 发帖 Tab 复用全局样式 + 上传区拖拽；scoped 移除已上移类
  views/GalleryPanel.vue        # scoped 移除已上移类
  components/ChatInput.vue      # 主聊天拖拽上传
```

---

## 12. 实施顺序（里程碑）

1. **B1 后端**：`db.py` 状态白名单收敛 + `init_db` 迁移；`main.py` 管理员禁写拦截 + admin 白名单收敛。
2. **F1 共享样式上移**：`main.css` 全局类 + `color-scheme:dark` + `select/option` 兜底；`GalleryPanel.vue` / `CommunityPanel.vue` scoped 清理。
3. **F2 建议面板重写**：`SuggestionPanel.vue`（用户弹窗 + 管理员回复弹窗）。
4. **F3 拖拽上传**：`ChatInput.vue` + `CommunityPanel.vue` 上传区。
5. **A3 验收**：`npm run build` + 后端冒烟。

---

## 13. 验收用例

### 建议箱

| # | 操作 | 期望 |
|---|---|---|
| 1 | 普通用户写建议 → 点发送 | 先 `confirm` 警告；确认后提交成功，状态=`pending`（待管理员处理） |
| 2 | 普通用户「我的建议」点开该条 | **弹窗**显示全文 + 状态徽标（待管理员处理）+ 时间；无回复框 |
| 3 | 管理员打开「管理建议」 | **无写信区**；表格里看到该条（含发送者） |
| 4 | 管理员点「回复/审批」→ 弹窗填回复 → 发送 | 弹窗关闭；该条状态自动变 `resolved`（已处理），回复落库 |
| 5 | 管理员再点「回复/审批」→ 状态手动改回 `pending` → 发送（回复可空） | 状态变 `pending`，回复保留 |
| 6 | 普通用户刷新「我的建议」→ 点开 | 弹窗显示状态 + 管理员回复 |
| 7 | 管理员直接 `curl -X POST /api/suggestions` | `403`（`40301`），message「管理员不能提交建议」 |
| 8 | 管理员 `PUT` 状态传 `read` | `400`（`40013`） |
| 9 | 管理员删除该建议 | 普通用户列表同步消失 |
| 10 | 空建议提交 / 普通用户访问 `/api/admin/suggestions` | `40013` / `40301`（同 Spec9） |

### 去白底（视觉）

| # | 检查点 | 期望 |
|---|---|---|
| 11 | 建议面板标签 / 社区发帖 Tab（若仍有 Tab 形态） | 深紫胶囊、选中高亮，**无原生白底按钮** |
| 12 | 社区发帖弹窗 / 帖子弹窗遮罩 | 全屏固定遮罩 + 居中弹窗（`position:fixed` 生效），不再内联平铺 |
| 13 | 任意 `<select>` 展开选项 / 滚动条 | 跟随深色主题，**无系统白底弹层** |
| 14 | 全局回归 | 我的作品面板样式与 Spec9 前一致（共享类上移后不破坏） |

### 拖拽上传

| # | 操作 | 期望 |
|---|---|---|
| 15 | 把 jpg/png 拖到主聊天输入区 | 输入区出现高亮浮层「松开以添加参考图」；松手后出现缩略图附件；可随消息发送 |
| 16 | 把非图片文件拖到主聊天输入区 | 提示「仅支持 jpg / png / webp / gif 图片」，不产生附件 |
| 17 | 社区发帖弹窗切到「上传新图」→ 拖图进上传区 | 区域高亮，松手后出现本地预览，可发布 |
| 18 | 社区发帖「上传新图」仍可点击选择 | 文件选择器正常打开 |

> 验收时明确排除：建议多轮会话 / 用户回复 / 三态以上状态 / 其它面板的拖拽上传 / 社区评论等 Spec9 §3 已排除项。
