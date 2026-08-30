# ArtiControlNet Spec 7：修复三项（比例画幅校验 / 重试无限转圈 / 失败清挂起）

> 目标读者：Claude Code（用于后续 Spec Coding）与项目作者（FJ）。
> 一句话：Spec6 上线后作者实测发现三个问题——①画幅追问后回「9:16」直接报「size 非法」；②失败气泡点「重试」后圈圈一直转；③任务失败后挂起意图残留。本 Spec 只做三处小修，不动 Spec5/6 已定架构（pending 内存、images 表、ask_clarification 工具均保留）。
> 背景事实（已实测确认）：系统提示词与 `size` 工具描述都要求主 Agent「用户给比例时换算成合法尺寸」，但这是对 LLM 的提示、不可靠——本次主 Agent 把 `9:16` 原样传给了子 Agent，后端 `validate_size` 只认 `^\d{3,4}x\d{3,4}$` 像素形式，于是抛 `RouterError` → 任务 FAILED。

---

## 1. 问题陈述（用户反馈原文要点）

### 1.1 比例画幅「9:16」报非法

- 用户对画幅追问回复「9:16」（或「9x16」）→ 任务 FAILED，错误文案「size 参数非法: 9:16（应为 宽x高，如 1024x576）」。
- 用户误读为"要 9x16"，但 `9x16` 同样不匹配（`\d{3,4}` 要求 3~4 位数字）。后端实际只接受 `1024x576` 这种像素值。

### 1.2 失败后点「重试」圈圈一直转

- 失败气泡点「重试」→ 该条气泡永远停在"生成中"（TypingIndicator 一直转），无论任务成功还是再次失败都不结束。

### 1.3 任务失败后挂起意图残留

- 画幅追问挂起（`missing=["size"]`）→ 用户回复「9:16」→ 任务 FAILED → 挂起意图未清除，残留到后续消息。

---

## 2. 根因分析

| 现象 | 根因 | 位置 |
|---|---|---|
| 比例画幅被拒 | 主 Agent 未把「9:16」换算成像素（LLM 行为不可靠）；后端 `validate_size` 只认像素形式，不认识 5 个预设比例（Spec6 §4「清单写入提示词与后端、两处口径一致」只做了提示词侧） | `agents/generation.py` / `agents/editing.py` 的 `validate_size` |
| 重试无限转圈 | `retry()` 把失败气泡替换成 pending 时传了 `{ id: pendingId, ... }`，但 `replaceMessage` 是 `{ ...msg, id }`——`id` 参数（errorId）最后覆盖，气泡 id 仍是 `errorId`；而 `submit`/`pollTask` 用新 `pendingId` 找气泡替换 → 找不到 → 永不替换 | `frontend/src/store/chat.js` `retry` / `replaceMessage` |
| 失败后挂起残留 | `handle_task` 两个异常分支直接 re-raise，未走到 `pending_store.clear`（清除只在成功路径） | `Server/main.py` `handle_task` |

---

## 3. 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 比例换算可靠性 | 后端 `validate_size` 内置预设映射（`1:1/16:9/9:16/4:3/3:4` + 短横式别名），主 Agent 传比例或像素都能通过；提示词/工具描述口径不变 | 不依赖 LLM 自觉；后端真正理解清单，兑现 Spec6 §4「两处口径一致」 |
| 「9x16」等短横式 | 作为比例别名并入预设映射（如 `9x16 → 576x1024`） | 消除实测歧义；像素形式仍要求 3~4 位数字，`9x16` 不会被误判为像素，无歧义 |
| 报错文案 | `validate_size` 错误信息补上预设清单提示（`1:1 / 16:9 / 9:16 / 4:3 / 3:4 或 宽x高`） | 用户一眼知道合法输入 |
| 重试 | 前端 `retry` 复用 `errorId`，不再新建 `pendingId` | 让完成/失败回调能替换到正确气泡（一次成功、再次失败都结束转圈） |
| 失败清挂起 | `handle_task` 异常分支也调用 `pending_store.clear` | 一轮交互以失败结束即挂起作废，避免残留污染后续消息；重试所需上下文由会话历史提供（history 已含追问 + 回答） |

---

## 4. 需求边界

### 范围内

- 后端 `validate_size`（`generation.py` / `editing.py` 各一份）加预设比例映射 + 小写化 + 报错文案更新。
- 前端 `store/chat.js` `retry()` 修复：气泡 id 前后一致，完成/失败都能替换。
- 后端 `main.py` `handle_task` 异常分支清挂起意图。

### 范围外（本 Spec 不做）

- 不改 Spec5/6 架构：pending 仍内存、images 表不变、ask_clarification 工具仍存在、透传语义不变。
- 不做前端超时轮询（poll 无限重试的上限）——那是另一个问题，本次聚焦「任务有终态但气泡不更新」。
- 不为「9:16」这类比例新增独立输入控件（下拉/按钮）——仍走文本，后续 v2 再议。

---

## 5. 方案设计（增量）

### 5.1 后端：`validate_size` 预设比例规范化

`generation.py` / `editing.py`（两份同步改）：

```python
_SIZE_PRESETS = {
    "1:1": "1024x1024",  "1x1": "1024x1024",
    "16:9": "1024x576",  "16x9": "1024x576",
    "9:16": "576x1024",  "9x16": "576x1024",
    "4:3": "1024x768",   "4x3": "1024x768",
    "3:4": "768x1024",   "3x4": "768x1024",
}

def validate_size(size: str) -> str | None:
    size = (size or "").strip().lower()
    if not size:
        return None
    preset = _SIZE_PRESETS.get(size)        # 预设比例/别名 → 规范化像素（Spec7 §5.1）
    if preset:
        return preset
    m = _SIZE_RE.match(size)                # 像素形式：宽x高（宽高 512~2048、面积 ≤1024²）
    if not m:
        raise RouterError(f"size 参数非法: {size}"
                          f"（应为 1:1 / 16:9 / 9:16 / 4:3 / 3:4 或 宽x高，如 1024x576）")
    w, h = int(m.group(1)), int(m.group(2))
    if not (_SIZE_MIN <= w <= _SIZE_MAX and _SIZE_MIN <= h <= _SIZE_MAX):
        raise RouterError(f"size 参数非法: {size}（宽高需在 {_SIZE_MIN}~{_SIZE_MAX} 之间）")
    if w * h > _SIZE_MAX_AREA:
        raise RouterError(f"size 参数非法: {size}（面积超出 1024×1024 限制）")
    return f"{w}x{h}"
```

说明：`.lower()` 让 `1024X576`、`16X9` 也命中；预设命中直接返回像素，不再走范围校验（预设本身就是合法尺寸）。

### 5.2 前端：`retry()` 复用 errorId

`frontend/src/store/chat.js`：

```js
// 失败气泡重试
async retry(errorId) {
  const err = this.messages.find((m) => m.id === errorId)
  if (!err || !err.request) return
  this.sending = true
  const request = err.request
  this.replaceMessage(errorId, { id: errorId, role: 'assistant', kind: 'pending', request })
  this.persist()
  await this.submit(request, errorId)
  this.sending = false
}
```

改动：删除 `const pendingId = nextId('p')`；`replaceMessage` 的 `id` 与传给 `submit` 的 id 都用 `errorId`。这样 `replaceMessage(errorId, {...})` 后气泡 id 保持 `errorId`，`submit(request, errorId)` → `pollTask(task_id, errorId)`，完成/失败时 `replaceMessage(errorId, ...)` 能找到气泡替换。

### 5.3 后端：`handle_task` 失败清挂起

`Server/main.py`，两个异常分支各加一行 `pending_store.clear`：

```python
except AppError as exc:
    await pending_store.clear(task.thread_id)   # 失败即作废挂起意图（Spec7 §5.3）
    await store.append(task.thread_id, {
        "role": "assistant", "text": f"（任务失败：{exc.message}）",
    })
    raise
except Exception as exc:  # noqa: BLE001
    await pending_store.clear(task.thread_id)   # 同上
    await store.append(task.thread_id, {
        "role": "assistant", "text": f"（任务失败：{exc}）",
    })
    raise
```

成功路径（clarify 写挂起 / 非 clarify 清挂起）不变。

---

## 6. 接口/交互改动

| 项 | 改动 |
|---|---|
| `size` 工具定义 / 系统提示词 | 不变（口径已一致；后端现在同样理解比例，不再依赖 LLM 换算） |
| `validate_size` 报错文案 | 补上合法输入提示：`1:1 / 16:9 / 9:16 / 4:3 / 3:4 或 宽x高` |
| 前端 | 无接口改动；`retry` 交互修复（气泡能正常结束转圈） |
| 挂起意图生命周期 | 新增「任务失败 → 清」一档；重试上下文由会话历史兜底 |

---

## 7. 实施顺序

1. **S7-1 后端 size 预设**：`generation.py` / `editing.py` 加 `_SIZE_PRESETS`、改 `validate_size`、更新报错文案。
2. **S7-2 前端重试**：`frontend/src/store/chat.js` `retry()` 复用 `errorId`。
3. **S7-3 后端失败清挂起**：`Server/main.py` 两个异常分支加 `pending_store.clear`。
4. **S7-4 验收**：按 §8 Smoke + 语法/导入检查 + 前端构建。

---

## 8. 验收用例（Smoke）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 画幅追问后回复「9:16」 | 正常出图（576x1024），不报错 |
| 2 | 画幅追问后回复「9x16」 | 同样出图（576x1024） |
| 3 | 回复「16:9」或「1024x576」 | 正常出图 |
| 4 | 回复「随便」 | 默认画幅直接出图，不再追问 |
| 5 | 回复非法值（如「huge」） | 报错文案提示合法格式（`1:1/16:9/9:16/4:3/3:4 或 宽x高`），任务正常 FAILED |
| 6 | 失败气泡点「重试」 | 气泡重新进入生成中，任务完成后正常替换（成功或再次失败都结束转圈） |
| 7 | 追问 → 回复后任务失败 → 换新话题 | 新消息不再被残留挂起上下文干扰 |
