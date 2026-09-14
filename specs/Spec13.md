# ArtiControlNet Spec 13：「上次更新前的作品风格」全文弹窗

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：Spec12 的「个人作品风格」Block 里，**「上次更新前：…」那一行是 `-webkit-line-clamp: 2` 截断的**——风格一旦偏长，作者在页面上只能看到开头两行，**看不到上一版全文**。本 Spec 给这一行加上**点击 → 小弹窗看全文（+ 复制全文）**，与 Spec6 §5.3 为「作品 prompt 看不了全文」给出的解法同构。
> 本 Spec 是 **Spec.md / Spec2~12 的增量补充**：**纯前端改动，零后端改动**——不加表、不加列、不加接口、不加错误码、不加日志、不加配置、不加依赖。`wiki.prev_style` 的存法（Spec12 §5.1）与写入口径（Spec12 §5.2 B/C）**完全不变**，本 Spec 只动它的**展示**。
> 硬约束仍遵守：无本地推理、只有前后端两层、无新数据库、无新 pip/npm 依赖。

---

## 1. 功能目的

- **让「上次更新前」从"提示"变成"可读"**：Spec12 把上一版风格留在小块里，本意是给作者一条回退视线。但 2 行 clamp 之下，偏长的风格**只能看到开头**，那条视线其实是断的——作者知道"改过"，却看不到"改成什么样之前"。
- **`prev_style` 是本项目里最"只有一份"的数据**：Spec12 明确不建历史表、不做 N 版回溯，`prev_style` **只有当前这一格**——它被下一次更新或下一次手动保存顶掉后就**永久消失**（Spec12 §2 手动编辑的确认强度就是为此而设）。看不全、又存不下来，等于这份唯一副本在页面上是半废的。本 Spec 补上"看得全 + 抄得走"。
- **不打扰主视觉**：主风格仍占据 Block 的主位，上一版仍是小字、低对比度的次要信息。弹窗只在**作者主动点**的时候出现，Block 的视觉层级**一个像素都不改**。
- **改动面刻意压到最小**：不上新组件、不上新依赖、不碰后端。同一个组件里已有 Spec6 §5.3 的全文 overlay 与复制能力，**复用而不再造**。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 触发方式 | **点「上次更新前：…」那一行本身**打开弹窗，**不新增按钮** | 与 Spec6 §5.3「点画廊卡片 prompt 打开全文」同构，用户已建立"截断的文字点一下能展开"的肌肉记忆；Block 内已有「基于我的新作品更新风格 / 编辑」两个按钮，再加第三个会稀释操作重心 |
| 弹窗形态 | **复用全局 `.gallery-lightbox` + `.gallery-lightbox-inner` overlay 卡片**（根 + 标题行 + 可滚动正文 + 底部操作行），`max-width: 640px`，正文 `max-height: 60vh` 内滚 | Spec10 已把 `.gallery-lightbox*` 提升到全局并用 `color-scheme: dark` 修过白底；`SuggestionPanel` / `CommunityPanel` 的弹窗同族。**不新建组件、不引第三方** |
| 是否给「复制全文」按钮 | **给** | Spec12 没有"一键恢复上一版"，作者想改回去只能**复制 → 点编辑 → 粘贴 → 保存**；复制是这条路径的**第一步**，少了它整条路径等于不存在。复用组件内既有的 `copyText()`（`navigator.clipboard` 失败自动回退 `execCommand`） |
| 是否加「恢复为当前风格」按钮 | **不加** | Spec12 §3 已明确排除多版本回退；此处加一个"读 prev 写 style"的按钮，等于在本 Spec 里偷偷开回退的口子，且与「编辑」按钮功能重叠 |
| `title` 属性 | **去掉 `:title="wiki.prev_style"` 全文悬浮**，改为 `title="点击查看全文"` | 有了真弹窗后，原生 tooltip 是**同一条信息的第二个更差的出口**（不可滚动、易消失、不可复制、触屏无）。统一成"点击查看全文"的提示语，与作品卡片 `gallery-prompt` 口径一致 |
| 折行仍保留 2 行 clamp | **保留**，只加"可点"的视觉提示（`cursor: pointer` + hover 提亮） | 上一版必须**不抢主风格的位置**（Spec12 §7.2 的原始设计意图）；本 Spec 解决的是"能不能看全文"，不是"要不要显示更多" |
| 短文本是否也弹窗 | **一律弹窗**，不判断"是否被截断" | 判断截断要量 DOM（`scrollHeight` 对比 / `ResizeObserver`），随字体、缩放、窗口宽度漂移，**脆且不值当**；点一下弹个小窗的成本是零 |
| Esc 关闭 | **支持**，且顺带让同组件既有的两处 overlay（大图 / prompt 全文）也响应 Esc | Spec8 / Spec9 已把 Esc 立为弹窗的标准关闭路径（Spec8 §2「四路都收敛到同一个 close」）；本组件的 overlay 目前**只能点遮罩或点「关闭」**，属既有的口径缺口，同一个 `keydown` 处理器顺手补齐。优先级按栈序：**wiki 全文 → prompt 全文 → 大图**（关最上面那层） |
| 弹窗内复制失败的提示位置 | 弹窗**内部**显示，不回落到页面错误条 | 页面错误条 `.login-error` 渲染在遮罩**背后**，弹窗开着时作者根本看不见。故 `copyText()` **增加返回值（`true/false`）**，弹窗据此渲染自身的一行提示。**返回值是纯增量**，既有调用方（`copyPrompt`）忽略它，行为不变 |
| 弹窗打开期间风格被更新 | 弹窗渲染的是**打开那一刻的文本快照** | 遮罩 `position: fixed; inset: 0` 已挡住 Block 上的按钮，实操中不可能在弹窗开着时点更新；快照写法让"万一发生"也不会显示成半新半旧 |
| 是否给「当前风格」也加同样的弹窗 | **不加** | 当前风格未做任何截断（`.wiki-style` 无 `line-clamp`），全文本来就在页面上，加弹窗是纯粹的冗余入口 |
| 是否计入 usage 统计 | **不涉及** | 纯前端查看动作，**不发任何请求**，与 Spec4 / Spec11 的调用统计无交集 |

---

## 3. 需求边界

### 范围内

- `.wiki-prev` 那行改为可点击；点击打开**「上次更新前的个人作品风格」全文弹窗**。
- 弹窗内容：标题 + 一句"仅供查看/复制"的说明 + `prev_style` 全文（可滚动）+ 「复制全文」+「关闭」。
- 关闭路径：点遮罩 / 点「关闭」/ 按 **Esc**。
- 同组件既有 overlay 也接上 Esc（大图、prompt 全文），关最上面那层。
- 复制失败时在弹窗内提示。

### 范围外（本 Spec 不做）

- **一键恢复上一版风格**：不做（Spec12 §3 已排除多版本回退）。
- **`prev_style` 的历史版本列表 / N 版回溯**：仍只保留一格（Spec12 §3 口径不变）。
- **加长 Block 里「上次更新前」的展示行数**（2 行 → 3 行 / 可展开）：不改，本 Spec 只做弹窗。
- **「当前风格」的全文弹窗**：不做（本就不截断）。
- **Markdown / 富文本渲染**：弹窗内是**纯文本**（`white-space: pre-wrap`），与主风格一致。
- **顺手修 prompt 全文 overlay 的同类问题**（复制失败提示也在遮罩背后）：**不在本 Spec 内**（见 §3 已知限制），避免扩大改动面。
- **后端任何改动**：接口、表、错误码、日志、配置一律不动。

### 已知限制（写入本文档，避免误读）

- **Esc 与 HelpModal 可能同时命中**：两者各自挂 `window` 的 `keydown`。若帮助弹窗正开着、同时点了作品风格全文弹窗（需先关掉帮助，实操中不会发生），Esc 会让两者都关。这是**既有架构**（Spec8 的 HelpModal 也是全局监听）下的极小概率场景，**接受，不加协调机制**。
- **prompt 全文 overlay 的复制失败提示仍在遮罩背后**：既有行为，本 Spec 不改（见范围外）。
- **弹窗正文不记忆滚动位置**：每次打开都从顶部开始（文本最多 2000 字，无需记忆）。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | **无任何改动** | 不碰 `main.py` / `db.py` / `wiki.py` / `schemas.py` / `errors.py` / `config.py` / `prompts.py` |
| 前端 | **无新依赖 / 无新组件 / 无新接口** | 只改 `frontend/src/views/GalleryPanel.vue` 一个文件（模板 + 脚本 + scoped 样式） |

> 无新 pip / npm 依赖；无新环境变量；`.gitignore` / `requirements.txt` / `package.json` 不变；`Server/artcn.db` 无变化。

---

## 5. 架构设计（增量）

### 5.1 现状与根因

**现状**（`frontend/src/views/GalleryPanel.vue`）：

| 位置 | 内容 |
|---|---|
| 模板 `:25-28` | `<p v-if="wiki.prev_style" class="wiki-prev" :title="wiki.prev_style">上次更新前：{{ wiki.prev_style }}</p>` |
| 样式 `:513-523` | `.wiki-prev`：`font-size: 12px`、`color: var(--text-muted)`、`-webkit-line-clamp: 2` + `overflow: hidden` |

**根因**：Spec12 §7.2 为「上一版是次要信息」刻意做了 2 行折叠，但**只留了原生 `title` 一条出口**。文本超过两行时：看不到全文、选不中、复制不了、触屏无 tooltip——与 Spec6 §5.3 修 prompt 行时**完全同型的问题**。

### 5.2 交互流

```
点「上次更新前：…」那一行
  → wikiPrevFull.value = wiki.prev_style        # 文本快照，非空 = 弹窗打开
  → 弹窗渲染：标题 + 说明 + 全文（可滚）+ [复制全文] [关闭]
       · 点「复制全文」 → copyText(wikiPrevFull) → true: 按钮变「已复制 ✓」1.5s
       ·                                        → false: 弹窗内显示「复制失败，请手动选择复制」
       · 点遮罩 / 点「关闭」 / 按 Esc → wikiPrevFull.value = ''
```

**不发任何网络请求**：全文已在 `wiki.prev_style` 里（`GET /api/wiki` 早就返回了）。这是纯本地展开。

### 5.3 关闭与键盘

在组件里挂一个 `window` 的 `keydown`（与 `CommunityPanel` / `HelpModal` 同写法），按**栈序**关最上面一层：

```
Esc → wikiPrevFull 非空 ? 关它
    : promptOverlay 非空 ? 关它
    : lightbox 非空 ? 关它
    : 不做任何事
```

`onMounted` 里 `addEventListener`，`onBeforeUnmount` 里 `removeEventListener`（**与既有的 `releaseThumbs` 合并到同一个卸载回调**）。

---

## 6. 接口约定

**无变更。** 本 Spec 不新增、不修改任何端点；`GET /api/wiki` 返回的 `prev_style` 原样使用（Spec12 §6.1）。§6.1~6.3 的全部约定（统一响应壳、Bearer 鉴权、`user_id` 只来自 token）**不变**。

---

## 7. 前端交互

### 7.1 模板改动（`GalleryPanel.vue`）

**（a）`:25-28`：那一行改为可点击**

```html
<!-- 「上次更新前」：次要信息，小字 + 低对比度 + 折叠两行；点击看全文（Spec13） -->
<p
  v-if="wiki.prev_style"
  class="wiki-prev"
  title="点击查看全文"
  @click="wikiPrevFull = wiki.prev_style"
>
  上次更新前：{{ wiki.prev_style }}
</p>
```

> `title` 由**全文**改为**提示语**（Spec13 §2 决策）。`v-if` 条件不变：`prev_style` 为空时不渲染、不可点。

**（b）在既有 prompt 全文 overlay（`:153-164`）之后、根 `</div>`（`:165`）之前，新增弹窗**

```html
<!-- 「上次更新前的作品风格」全文弹窗（Spec13）：点截断行打开，可看全文 + 复制 -->
<div v-if="wikiPrevFull" class="gallery-lightbox" @click.self="wikiPrevFull = ''">
  <div class="gallery-lightbox-inner wiki-prev-overlay">
    <div class="wiki-prev-overlay-head">
      <h3 class="wiki-prev-overlay-title">上次更新前的个人作品风格</h3>
      <span class="wiki-prev-overlay-hint">仅供查看 / 复制，不会自动恢复</span>
    </div>
    <p class="wiki-prev-overlay-text">{{ wikiPrevFull }}</p>
    <p v-if="wikiPrevCopyFail" class="wiki-prev-overlay-error">复制失败，请手动选择复制</p>
    <div class="gallery-lightbox-bar">
      <button class="btn-mini" @click="copyPrevStyle()">
        {{ copied ? '已复制 ✓' : '复制全文' }}
      </button>
      <button class="btn-clear" @click="wikiPrevFull = ''">关闭</button>
    </div>
  </div>
</div>
```

### 7.2 脚本改动（`GalleryPanel.vue`）

```js
// ---- 「上次更新前」全文弹窗（Spec13）----
const wikiPrevFull = ref('')      // 快照文本；非空 = 弹窗打开
const wikiPrevCopyFail = ref(false)
```

**`copyText()` 增加返回值**（`:312-338`，**纯增量，不改既有成功/失败表现**）：

```js
async function copyText(text) {
  copied.value = false
  let ok = false
  /* …既有实现不动… */
  if (ok) {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } else {
    error.value = '复制失败，请手动选择复制'   // 既有页面错误条，保留
  }
  return ok                                   // ← 新增：唯一改动
}

// 弹窗内的复制：失败提示画在弹窗里（页面错误条被遮罩挡住，看不见）
async function copyPrevStyle() {
  wikiPrevCopyFail.value = false
  const ok = await copyText(wikiPrevFull.value)
  if (!ok) wikiPrevCopyFail.value = true
}
```

**键盘**（新增 `onKeydown`，见 §5.3）：

```js
function onKeydown(e) {
  if (e.key !== 'Escape') return
  if (wikiPrevFull.value) wikiPrevFull.value = ''
  else if (promptOverlay.value) promptOverlay.value = null
  else if (lightbox.value) lightbox.value = null
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  loadWiki()
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  releaseThumbs()
})
```

> **不改 `refreshStyle` / `saveStyle` / `loadWiki`**：弹窗与写库路径完全解耦（更新成功后 `wiki.prev_style` 变新值，下次点开自然是新内容；无需任何"刷新弹窗"的逻辑）。

### 7.3 样式改动（`GalleryPanel.vue` `<style scoped>`）

**（a）`.wiki-prev`（`:513-523`）追加可点击态**（其余属性一律不动）：

```css
.wiki-prev {
  /* …既有：margin / font-size: 12px / line-height / color: var(--text-muted)
     / overflow: hidden / -webkit-box / -webkit-line-clamp: 2
     / -webkit-box-orient: vertical / word-break: break-all  全部保留… */
  cursor: pointer;
  transition: color var(--transition-fast);
}

.wiki-prev:hover {
  color: var(--text-secondary);   /* 低对比度 → 稍亮，提示"可点"；仍明显弱于主风格的 --text-primary */
}
```

**（b）弹窗样式**：与既有 `.prompt-overlay`（`:678-697`）**并列写在同一个声明块**，避免复制粘贴两份同值 CSS：

```css
.prompt-overlay,
.wiki-prev-overlay {
  max-width: 640px;
  width: 100%;
}

.prompt-overlay-text,
.wiki-prev-overlay-text {
  /* …既有 prompt-overlay-text 的全部属性：margin: 0 / padding: 16px
     / max-height: 60vh / overflow-y: auto / background: var(--bg-input)
     / border: 1px solid var(--border-color) / border-radius: var(--radius-lg)
     / color: var(--text-primary) / font-size: 13px / line-height: 1.7
     / white-space: pre-wrap / word-break: break-all … */
}

.wiki-prev-overlay-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.wiki-prev-overlay-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.wiki-prev-overlay-hint {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.wiki-prev-overlay-error {
  margin: 8px 0 0;
  font-size: 12px;
  color: #fca5a5;              /* 与既有的超长警示色同值 */
}
```

- 弹窗**不留白底**（Spec10 口径）：正文底用 `var(--bg-input)`，卡片底与其它 overlay 同族。
- 按钮复用既有 `btn-mini` / `btn-clear`，**不新增按钮样式**。
- 正文**纯文本 `pre-wrap`**（与 `.wiki-style` 一致），不渲染 Markdown。

---

## 8. 配置 / 环境变量 / .gitignore

**无变更。** 不新增环境变量、不新增 `config.py` 常量（前端也不新增常量——本 Spec 没有需要与后端对齐的阈值）。

---

## 9. 错误码

**无新增、无变更。** 本 Spec 不产生任何后端可返回的错误：

- 打开弹窗 / 关闭弹窗是纯前端状态切换，**不发请求**；
- 复制失败是**浏览器能力问题**（非安全上下文下 Clipboard API 不可用），走界面内提示，**不占用错误码**；
- `prev_style` 为空时那一行**根本不渲染**（`v-if`），不存在"点开一个空弹窗"的态。

---

## 10. 日志约定

**无新增。** 查看/复制上一版风格是纯前端动作，**不产生任何请求**，故不新增事件（与 Spec12 §10 的 `wiki.*` 两条无关）。

---

## 11. 目录结构增量

```
frontend/src/
  views/GalleryPanel.vue   # 唯一改动文件：
                           #   模板：.wiki-prev 可点击（title → "点击查看全文"）
                           #        + 新增「上次更新前」全文弹窗
                           #   脚本：wikiPrevFull / wikiPrevCopyFail 两个 ref
                           #        + copyText() 增加 return ok（纯增量）
                           #        + copyPrevStyle() + onKeydown/Esc（含既有两处 overlay）
                           #   样式：.wiki-prev 可点击态 + .wiki-prev-overlay* 新增
                           #        （.prompt-overlay* 的选择器并列扩展，不复制 CSS）
Server/static/             # 前端构建产物（npm run build 后同步，与既有提交口径一致）
```

> 后端目录**零改动**；无新文件、无新依赖。

---

## 12. 实施顺序（里程碑）

1. **F1 可点击**：`.wiki-prev` 改 `title` + `@click` + `cursor/hover` 样式；新增 `wikiPrevFull` ref。
2. **F2 弹窗**：模板新增 overlay 块；`.wiki-prev-overlay*` 样式（`.prompt-overlay*` 选择器并列扩展）。
3. **F3 复制**：`copyText()` 加返回值；`copyPrevStyle()` + 弹窗内失败提示。
4. **F4 Esc**：`onKeydown` + `onMounted` / `onBeforeUnmount` 挂载与卸载（同时覆盖大图 / prompt 全文）。
5. **F5 构建与验收**：`cd frontend && npm run build` → 同步 `Server/static/` → 按 §13 逐条走查。

---

## 13. 验收用例

| # | 操作 | 期望 |
|---|---|---|
| 1 | 新用户（无风格记录）进「我的作品」 | 无「上次更新前」行、点不到任何东西；弹窗不存在 |
| 2 | 首次更新风格后（`prev_style` 为空串） | 仍**不渲染**「上次更新前」行（Spec12 口径：`""` 与 `null` 表现一致） |
| 3 | 第二次更新后（`prev_style` 为长文） | Block 里那一行仍为 **2 行截断**；主风格视觉层级不变 |
| 4 | 点那一行 | 弹出「上次更新前的个人作品风格」全文弹窗，正文为**完整** `prev_style`（与数据库/接口返回逐字一致），可滚动到底 |
| 5 | 弹窗开着看 Block | 主风格与按钮**被遮罩覆盖**，不可误点 |
| 6 | 点遮罩 / 点「关闭」/ 按 **Esc** | 三种方式都能关闭（Spec8/9 的弹窗口径） |
| 7 | 点「复制全文」（HTTPS 或 localhost） | 按钮变「已复制 ✓」，1.5s 后复原；剪贴板内容 = 全文，可粘进「编辑」框并保存（即完成一次"改回上一版"） |
| 8 | 在 http 非安全上下文下点「复制全文」 | 回退 `execCommand` 成功即同上；**真失败时提示显示在弹窗内**（不是被遮罩挡住的页面错误条） |
| 9 | `prev_style` 为极短文本（一行内） | 点开同样弹窗（不判断是否截断，Spec13 §2 决策）|
| 10 | 弹窗开着时按 Esc | 只关弹窗；Block 与页面其它状态不变，无请求发出 |
| 11 | 先点开大图 / prompt 全文，再按 Esc | 依次关闭（关最上面那层）；连按到底后页面回到无遮罩状态 |
| 12 | 弹窗开着 → 关闭 → 点「基于我的新作品更新风格」成功 | 新 `prev_style` = **上一版**；再点那一行，弹窗显示的是**更新后的**上一版（弹窗永远读当前值） |
| 13 | 点「编辑」→ 保存成功 | 「上次更新前」小字变为**保存前那版**；点开弹窗看到的是它（Spec12 §5.2 C 的语义不变） |
| 14 | 浏览器缩放 / 窄窗口（≈400px） | 弹窗不溢出：卡片宽度自适应，正文 `max-height: 60vh` 内滚动，标题与说明换行不重叠 |
| 15 | 样式回归 | 弹窗为深紫主题下的一体化面板（**无白底**），按钮为既有 `btn-mini` / `btn-clear`；「上次更新前」仍是明显弱于主风格的次要信息 |
| 16 | 后端接口 / 数据库 | `git diff` 后端目录**零改动**；查看全文全程**无网络请求**（DevTools Network 面板为空） |

> 验收时明确排除：一键恢复上一版 / 历史版本列表 / 加长展示行数 / 当前风格弹窗 / Markdown 渲染 / 后端任何改动 / prompt overlay 复制失败提示的位置调整。
