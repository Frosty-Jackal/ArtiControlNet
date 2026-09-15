# ArtiControlNet Spec 15：上传作品纳入个人风格（视觉 QA 分析 + 历史风格参考 + 双段式输出）

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：Spec12 把**上传作品排除在风格归纳之外**（`source='upload'` 没有 prompt，直接跳过并"视为已考虑"）。本 Spec **反转该决策**：点「基于我的新作品更新风格」时，**每一张尚未考虑的上传图都送一次图像 QA**（问题为作者原话「请给我分析这张图片是什么设计风格，不要说并不存在的风格，简洁清楚自然有力，无废话」），得到的分析结果与生成作品的 prompt **一起**送纯文本 LLM；同时把**上一次的风格**（`wiki.style`）作为独立材料段喂进去；最终风格从 Spec12 的「一段连贯自述」改为**两段带标题**：`【上传作品的风格】` + `【生成作品的风格】`。
> 本 Spec 是 **Spec.md / Spec2~14 的增量补充**，不推翻原有架构。数据库变化：**无新表、无新列**——`images.wiki_used` 的语义扩展到上传作品（上传图现在真的会被"考虑"），外加**一次性迁移**把旧口径下被无条件标记的上传图放回待考虑队列。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 Spec2 的本地单文件 SQLite `artcn.db` 外无其他数据库。复用**既有两个通道**——视觉 QA（`providers.qa` → `deepseek.qa_image`，模型 `VLM_MODEL`）与纯文本（`providers.deepseek.chat_text`，模型 `MODEL_NAME`），**不新增 provider、不新增模型、不新增依赖**。

---

## 1. 功能目的

- **补上"我传的图"这个缺口**：Spec12 只把**生成/绘图作品**的文字 prompt 沉淀成风格，用户自己上传的图**完全不参与**——可对设计师来说，上传的往往才是自己真正的作品（手绘稿、旧作、参考收集）。本 Spec 让上传图**真的被分析并纳入风格**，`wiki_used` 也从"一个空账本"变成**真实的"是否被考虑过"标记**。
- **让两种来源各自说话**：上传图能提供的风格信息（笔触、材质、色彩、构图取向）与生成作品的 prompt（画面描述）**不是一回事**。合成一段会让"水彩灰调"和"赛博朋克夜景"搅在一起，用户看不出哪来的。两段带标题，用户一眼就知道**自己传的图是什么风格、自己让 AI 画的又是什么风格**。
- **历史风格必须被看见**：风格是**累积**的资产，本次归纳若不知道上一版长什么样，就会把用户此前定稿的表述丢干净（Spec12 靠"新旧合并"的提示词缓解，但历史风格此前只出现在一个裸标签后面）。现在它有独立的段标题、明确的角色，模型被要求**参考它**。
- **缺料也要说人话**：某一段没有材料时（第一次用、只传了图没生成过、或某批分析全失败），不能输出一句话都接不上的空段，更不能在有历史风格的前提下声称"没有风格"——**历史风格非空时，缺料的那段就从历史里续写**。
- **失败要留痕迹、要能重来**：一张图分析失败不应该让整次更新白干，也不应该悄悄吞掉那张图。**跳过、保持未考虑、计入失败数、下次自动重试**。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 上传作品是否纳入风格 | **纳入**（反转 Spec12 §2 的原始决策） | 作者拍板。上传的图也是"个人作品"，且往往是用户最在意的那些 |
| `images.wiki_used` 对上传作品的语义 | **与生成作品同一套语义**：真实记录"是否已被分析并纳入过"；Spec12 的 `_mark_uploaded_wiki_used()`（无条件把上传图标为已考虑）**整个删除** | 作者原话"同样应具有'是否被考虑到'的 key"。旧口径下这个标记对上传图是**假账**——从没被考虑过却记着已考虑 |
| 存量上传图（旧口径已标记 `wiki_used=1`） | **一次性迁移放回**：`UPDATE images SET wiki_used = 0 WHERE source = 'upload'`，用 `app_meta` 键 `wiki_upload_migrated` 做幂等保护 | 不放回则所有老用户的上传图**永远**不参与风格，新功能对老用户几乎不可见。**必须**有保护位：否则每次重启都会把新标记的图重置回 0，陷入"同一张图反复重分析"的死循环 |
| 单次刷新的分析张数 | 上限 `WIKI_UPLOAD_QA_MAX`（默认 **10**），并发 `WIKI_UPLOAD_QA_CONCURRENCY`（默认 **3**） | 作者拍板。接口是同步的、每张图一次视觉调用：串行 30 张会等到分钟级。并发 3 路下 10 张约 10~20 秒，仍在"点一下等一会儿"的可接受区间；超上限的保持 `wiki_used=0`，下次点继续——与 Spec12 触顶截断的增量口径同构 |
| 单张分析失败 | **跳过并保持未考虑**（`wiki_used` 不动），本次继续；计入 `upload_failed` | 作者拍板。整次失败会把已花掉的视觉调用全部作废；永久标记则等于那张图再也不会被分析。保持未考虑 = 下次点按钮自动重试，且用户可去作品库删掉那张坏图 |
| 本次材料全部不可用（上传全失败且无生成作品） | `200 + updated:false` + `reason:"analysis_failed"`，**不占错误码** | 与 Spec12「所有作品已全部考虑到」的 `nothing_new` 同构：这是"点了但没有可用材料"的**正常业务状态**，不是错误 |
| 送进文本 LLM 的材料组织 | **三段带标题**：`【我的历史风格，这是我之前的作品风格】` / `【上传作品的风格分析】` / `【生成作品的画面描述】`；**某段无材料则整段不出现** | 作者拍板 + Spec12 §2 的既有教训（空标签段会让模型输出"原有风格为空，我为你归纳"之类元话语）。段标题逐字采用作者原话，便于日后对照调试 |
| LLM 的输出形态 | **两段带标题**：`【上传作品的风格】` + `【生成作品的风格】`，顺序固定。Spec12 的"不要标题、不要分点"规则**改写**为"只允许这两个标题，且必须都在" | 作者拍板："返回上传作品的风格和生成作品的风格给我" |
| 缺料段写什么 | 历史风格**非空** → 该段**基于历史风格续写**，不得出现"无"、不得声明"没有材料/没有新作品"；历史风格**为空** → 该段正文只写 `无` | 作者拍板："如果我的历史作品风格非空，即使某个部分为空，也不能说它是空的" |
| 历史风格为空时 | **不出现**「我的历史风格」段（而不是放一段空标签）；系统提示词另加一句"若未收到该段，说明这是首次归纳" | 同"空标签会诱发元话语"的理由（Spec12 §2） |
| 系统提示词份数 | Spec12 的 `WIKI_MERGE_SYSTEM_PROMPT` / `WIKI_INIT_SYSTEM_PROMPT` **合并为一份** `WIKI_STYLE_SYSTEM_PROMPT` | 两份的分歧点只有"有没有历史风格"，而这已由"段在不在"表达；输出格式本就要整体重写，留两份等于有两份需要同步维护的同一段规则 |
| 新增约束句的位置 | **用户提示词末尾**（`【输出要求】…`，按作者原话），**系统提示词不重复这条** | 作者明确要求"用户提示词里再加一条"。分工也更干净：**系统提示词管结构与规则**（材料语义、输出格式、缺料规则），**用户消息管语感要求**（紧贴材料，即时生效） |
| 上传图送模型前的处理 | 读 `Server/gallery/` 原图字节 → 最长边缩到 `WIKI_UPLOAD_QA_MAX_SIDE`（默认 **1024**）→ base64 data URI | 上传原图上限 10MB，base64 后 13MB，视觉接口又慢又易触限；判断"是什么设计风格"根本不需要原图分辨率。复用既有 `media.downscale_to_max_side` |
| `media.to_data_uri()` | **新增**该函数（签名 `to_data_uri(image_bytes, max_side=0) -> str`）；`agents/qa.py` 里的 `_MIME` 表 + base64 那几行**同步改用它** | 上传图的 data URI 与 `qa.py` 是同一件事的两份实现；不抽出来就要在 `wiki.py` 里把 mime 表和编码逻辑再抄一遍。`qa.py` 的替换是机械的、行为不变（§13 用例 16 覆盖回归） |
| `to_data_uri` 的 mime 判定基准 | **以"最终送出的那些字节"为准重新 `detect_ext`**，不接受调用方传入的 `ext` | `downscale_to_max_side` 对 **GIF** 的处理是：未超限原样返回，超限则存成 **PNG**（`fmt if fmt in ("PNG","WEBP") else "PNG"`）。若沿用 `images.ext`（`.gif`）拼 mime，就会把 PNG 字节标成 `image/gif`。重新识别一次即可彻底躲开这类"缩放改格式"的坑，代价是每张图多一次 PIL 打开（单轮 ≤10 张，可忽略） |
| 上传分析结果是否参与"触顶丢弃" | **不参与**，全部分析成功的都纳入；`WIKI_PROMPT_TOTAL_MAX`（6000）**只约束生成作品的 prompt** | 视觉调用已经花掉了，再因为额度把它丢掉 = 白烧一次调用、下次还要重烧。默认 10×300＝3000 字，正常规模下不会挤压生成段 |
| 上传段与生成段的先后 | **上传段在前**，生成段在后；各段内部**时间倒序**（新 → 旧） | 把"已付出调用代价、信息密度更高"的那段放在前面；也让模型的注意力先落在图片风格上 |
| 响应新增字段 | `upload_analyzed` / `upload_failed`；`used_count` / `pending_count` 的口径随之覆盖上传图 | 前端必须如实告诉用户"几张分析失败、可以重试"，否则失败对用户完全不可见；而"没纳入"的原因现在有两种（额度触顶 / 分析失败），提示语要说清 |
| 这些视觉调用是否计入 usage 统计 | **不计入**（`usage.qa` 不变） | 与 Spec12 §2 一致：维护 Wiki 是账号资料管理动作，不是用户的创作调用。计进去会让"人均 QA 调用"被一次点按钮灌水 |
| 前端如何渲染两段标题 | `.wiki-style` 从"一段纯文本"改为**按 `【…】` 行切块渲染**（小标题 + 正文）；不含 `【…】` 行的历史文本原样单块渲染 | 两段带标题的文本用 `pre-wrap` 直接铺出来是一坨。切块是**纯展示层**的事，不动存储格式，手动编辑框里改的仍是原文 |
| `WIKI_STYLE_MAX` | **保持 2000 不变**；系统提示词的长度规则从"总共 200~600 字"改为"**每段** 100~400 字" | 两段合计 200~800 字，离 2000 的截断线还有一倍余量；不改默认值就不用动前端那份同值常量 |
| 接口形态 | 仍为**同步** `POST /api/wiki/style/refresh` | 与 Spec12 §2 同口径。本 Spec 只是把等待时间从"几秒"变成"十几秒"，不足以把整条链路改造成任务队列 + 前端轮询 |
| 并发 | 仍**不加锁**，后写覆盖先写 | 与 Spec12 §5.3 一致 |

> **时间语义不变**：`style_updated_at` / `updated_at` 仍是 UTC ISO（`_now_iso()`），前端按本地时区格式化。

---

## 3. 需求边界

### 范围内

- **上传作品进入待考虑队列**：`list_pending_style_images` 的 `source` 过滤加入 `upload`，并返回 `source` / `file_name` 供后续读图。
- **删除** `_mark_uploaded_wiki_used()` 及其在 `commit_style_update()` 里的调用。
- **一次性迁移**：把旧口径下被无条件标记的上传图放回待考虑（`app_meta` 幂等保护）。
- **上传图的视觉风格分析**：逐张读原图 → 缩放 → data URI → `providers.qa(data_uri, WIKI_UPLOAD_QA_PROMPT)`，并发 3 路、单轮最多 10 张。
- **三段材料 + 双段输出的提示词重构**（系统提示词合并重写、用户消息三段带标题 + `【输出要求】`）。
- **失败语义**：单张失败跳过且不标记；材料全空返回 `analysis_failed`。
- **前端**：忙态文案、提示语（含失败张数）、`.wiki-style` 按 `【…】` 切块渲染与样式。
- **新增 4 个带默认值的配置常量**、新增 2 条日志事件、扩展 1 条日志的字段与 1 条日志的取值域。

### 范围外（本 Spec 不做）

- **上传分析结果的持久化 / 缓存**：不建表、不存每张图的 QA 答案——只留最终风格文本。`wiki_used` 保证**每张图只分析一次**，够用。
- **把"上传作品的风格 / 生成作品的风格"分别用于出图**：本 Spec 只负责风格的沉淀与展示（Spec12 §3 的口径不变）。
- **`wiki_used` 的前端露出与手动翻转**：仍不加角标、不提供"把某张作品捞回来重算"的开关（Spec12 §2 口径不变）。
- **历史风格的多版本 / 一键回退**：仍只保留"当前"与"上次更新前"两格（Spec12 / Spec13 口径不变）。
- **异步任务化**：不改用 `task_queue` + 轮询；仍是同步接口。
- **上传图的多图合并分析**：不做"一次请求塞多张图"，每张独立一次调用（视觉接口的语义就是单图问答）。
- **清空风格 / 重置 Wiki**：仍不提供。
- **管理员查看 / 编辑他人 Wiki**：`/api/wiki*` 一律只作用于 `request.state.user`。
- **手编风格时的格式校验**：不校验用户手写的文本里有没有 `【…】` 标题、标题是否合法——编辑框是逃生口，原文什么样就存什么样。

### 已知限制（写入本文档，避免误读）

- **文本 LLM 整体失败时，本轮已成功的上传图分析会作废**：Spec12「失败即无痕」不允许"风格没写成功却留下已标记的作品"，所以那些图 `wiki_used` 仍为 0，下次点按钮**会重新分析**、重复消耗视觉调用。这是本 Spec 唯一"会重复烧调用"的路径，接受——它只在文本 LLM 整体失败时发生，而整体失败本身是罕见事件。
- **分析失败的上传图会长期留在待考虑队列**：`pending_count` 一直 > 0，「所有作品已全部考虑到」的提示因此可能长期不出现。**逃生口**：在作品库删掉那张坏图。
- **存量迁移是单向的**：跑过一次就不再回头。迁移后第一次点按钮，最多一次涌入 `WIKI_UPLOAD_QA_MAX`（10）张上传图的分析。
- **"续写历史"会让缺料段与历史高度相似**：这是作者要的语义（不能说它是空的），但历史风格非空、两段又都缺料时，两段正文可能出现措辞重复——由系统提示词要求模型避免逐字复述，但不做硬保证。
- **`WIKI_STYLE_MAX`（2000）是总长截断线**：按提示词约定两段合计 200~800 字，正常不会触顶。若上游不守约定而超长，截断可能把第二段整体切掉——这是 Spec12 既有行为（`_clean(raw)[:WIKI_STYLE_MAX]`），本 Spec 不改。
- **`WIKI_UPLOAD_QA_MAX × WIKI_UPLOAD_ANSWER_MAX` 与 `WIKI_PROMPT_TOTAL_MAX` 无强制约束关系**：默认 10×300＝3000 ≤ 6000 是**建议值**，靠 §8 的注释提醒；配置失当时提示词会变长，但不报错。
- **上传图分析用的是 `VLM_MODEL`（`deepseek-v4-flash-vision-exp`）**：这是实验性视觉模型，分析质量与稳定性以实测为准；失败按"单张跳过"处理，不会污染风格。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | **无新依赖** | `db.py`（`_PENDING_SOURCES` 加 `upload`、`list_pending_style_images` 增返字段、删 `_mark_uploaded_wiki_used`、新增一次性迁移）、`wiki.py`（编排重写：分组 → 并发视觉分析 → 三段材料 → 文本 LLM → 落库）、`media.py`（新增 `to_data_uri`）、`agents/qa.py`（改用 `media.to_data_uri`，机械替换）、`agents/prompts.py`（新增 1 份 + 合并重写 2 份为 1 份）、`config.py`（4 个常量）、`main.py`（日志字段与事件） |
| 前端 | 无新依赖 / 无新组件 / 无新接口 | `views/GalleryPanel.vue` 一个文件（忙态文案 + 提示语 + 切块渲染 + 样式）；`api/chatApi.js` **不改** |
| 数据库 | **无新表、无新列** | 仅一次幂等 `UPDATE`（存量上传图放回待考虑）+ 一条 `app_meta` 键 |

> 无新 pip / npm 依赖；无新增强制环境变量（4 个常量均有默认值）；`.gitignore` / `requirements.txt` / `package.json` 均不变。

---

## 5. 架构设计（增量）

### 5.1 数据变更

**（a）无 schema 变化。** `images.wiki_used` 列（Spec12 §5.1b 已存在）语义扩展为**对上传作品也真实有效**。

**（b）一次性迁移**（`init_db()` 内、`_migrate_images_wiki_used(conn)` **之后**调用，幂等）：

```python
# app_meta 键：值 = UTC ISO 时间，表示"存量上传作品已放回待考虑队列"（Spec15）
WIKI_UPLOAD_MIGRATED_KEY = "wiki_upload_migrated"

def _migrate_upload_wiki_used(conn: sqlite3.Connection) -> None:
    """Spec15：旧口径把上传作品无条件标记为'已考虑'（假账），放回待考虑队列。

    幂等保护：app_meta 里有键就不再执行——否则每次重启都会把 Spec15 之后
    新标记的上传图重置回 0，同一张图被反复重分析。
    """
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key = ?", (WIKI_UPLOAD_MIGRATED_KEY,)
    ).fetchone()
    if row is not None:
        return
    cur = conn.execute("UPDATE images SET wiki_used = 0 WHERE source = 'upload'")
    _upsert_meta(conn, WIKI_UPLOAD_MIGRATED_KEY, _now_iso())
    conn.commit()
    logger.info("存量上传作品已放回待考虑队列", extra={
        "event": "wiki.upload_migrated", "affected": cur.rowcount,
    })
```

- **全新库**上该迁移更新 0 行、写下键，行为无差别。
- **它必须在 `app_meta` 建表之后**（`db.py` 建表顺序里 `app_meta` 在 `images` 之后；`init_db` 内调用点在 `_migrate_images_wiki_used` 之后即可）。

### 5.2 关键数据流

**（A）读取风格（页面加载）** —— `GET /api/wiki` → `db.get_wiki(user_id)`：**完全不变**（含"行不存在返回全空、不建行"）。

**（B）基于新作品更新风格（按钮）**

```
点「基于我的新作品更新风格」
  → POST /api/wiki/style/refresh
  → db.list_pending_style_images(user_id)          # 现在含 source='upload'，时间倒序
  → 若为空 → updated:false / reason:"nothing_new"  # 不变（不调 LLM、不写库、不改标记）
  → 分组：
        uploads = [source == 'upload'][:WIKI_UPLOAD_QA_MAX]
        others  = [source ∈ {generate, edit}]
  → A. 上传图风格分析（并发 WIKI_UPLOAD_QA_CONCURRENCY 路）
       逐张：
         gallery.read_gallery_file(id, user_id)        # 归属校验；非本人的图 → 40403
           → (record, image_bytes)
         media.to_data_uri(image_bytes, max_side=WIKI_UPLOAD_QA_MAX_SIDE)
           # 内部：超限则缩放 → 以最终字节 detect_ext 定 mime → base64（§2 决策）
         await providers.qa(data_uri, WIKI_UPLOAD_QA_PROMPT)   # 视觉 QA，VLM_MODEL
         → 文本 strip，截断到 WIKI_UPLOAD_ANSWER_MAX
       成功 → analyses = [{id, created_at, text}]
       失败（AppError 子类：61001/61002/61003/40403，或清洗后为空）
            → failed = [{id, reason}]，该张 wiki_used 保持 0，打 wiki.upload_analysis_failed 日志
  → B. 生成作品参考文字（既有逻辑不变）
       逐条 prompt 截断到 WIKI_PROMPT_ITEM_MAX，时间倒序累加 ≤ WIKI_PROMPT_TOTAL_MAX；
       触顶装不下的本条丢弃且不标记（不 break，后面的短条目仍可用余量）
  → C. 若 analyses 为空且 gen_refs 为空
       → updated:false / reason:"analysis_failed"（不调文本 LLM、不写库、不改标记）
  → D. history = db.get_wiki(user_id)["style"]
       raw = await deepseek.chat_text(_build_messages(history, analyses, gen_refs))
  → E. style = _clean(raw)[:WIKI_STYLE_MAX]；为空 → UpstreamApiError(61001)
  → F. 单事务写库（db.commit_style_update）：
         wiki.prev_style ← 旧 style（首次更新时旧 style 为空串 → prev_style 存 ''）
         wiki.style      ← 新风格
         style_updated_at / updated_at ← now
         used_ids = [分析成功的上传图 id] + [纳入的生成作品 id]  → images.wiki_used = 1
  → G. 返回 {updated:true, reason:null, style, prev_style, style_updated_at,
            used_count, pending_count, upload_analyzed, upload_failed}
```

> **`_mark_uploaded_wiki_used()` 消亡**：Spec12 里"上传作品一并视为已考虑"的那次批量 UPDATE 是**假账**（从没被考虑过），本 Spec 删除它，上传图只能靠**真的被分析并纳入**来拿到 `wiki_used = 1`。

**（C）手动编辑风格** —— `PUT /api/wiki/style`：**完全不变**（覆盖式写入、旧值进 `prev_style`、**不触碰** `images.wiki_used`）。此前未考虑的作品仍是待考虑。

### 5.3 提示词设计

**（a）新增：上传图的问题（`agents/prompts.py`）** —— 逐字采用作者原话：

```python
# Spec15：每张未考虑的上传图都送这条问题给视觉 QA（VLM_MODEL）
WIKI_UPLOAD_QA_PROMPT = (
    "请给我分析这张图片是什么设计风格，不要说并不存在的风格，简洁清楚自然有力，无废话"
)
```

**（b）用户消息（`wiki.py::_build_messages`）** —— 三段材料按需出现，末尾恒定一行输出要求：

```
【我的历史风格，这是我之前的作品风格】
{history 全文}                        ← 仅当 history 非空时出现

【上传作品的风格分析】
1. {第 1 张上传图的分析}
2. …                                  ← 仅当有分析成功时出现

【生成作品的画面描述】
1. {第 1 条生成/绘图作品的 prompt}
2. …                                  ← 仅当有可用 prompt 时出现

【输出要求】无废话，简洁清楚自然有力，用简洁的语言描述清楚风格，不要说并不存在的风格。
```

- `【输出要求】` **恒定出现**（它不是材料段，是贴在材料上的即时要求）。
- 材料段**整段略去**（不是留空标签）——Spec12 §2 已确认空标签会诱发元话语。

**（c）系统提示词 `WIKI_STYLE_SYSTEM_PROMPT`** —— 由 `WIKI_MERGE_SYSTEM_PROMPT` + `WIKI_INIT_SYSTEM_PROMPT` **合并重写**，要点：

| 部分 | 内容 |
|---|---|
| 身份与材料说明 | 你是个人作品风格归纳助手；用户可能给你三段材料：①「我的历史风格」＝这位用户**此前的定稿**；②「上传作品的风格分析」＝视觉模型对用户上传图片的逐张风格判断；③「生成作品的画面描述」＝用户此前生成/绘图作品的画面 prompt。**某段可能不出现** |
| 输出格式 | **只输出两段**，标题与顺序固定：`【上传作品的风格】` 换行正文，空行，`【生成作品的风格】` 换行正文。除此之外**不要任何内容**：不要前后缀、不要引号、不要 Markdown、不要代码块、不要"好的""以下是"之类元话语 |
| 有材料时 | 归纳该段的一贯取向（常见题材与主体、构图与视角、光影与色彩、材质与笔触、画面氛围与审美倾向），**一段连贯中文，100~400 字**；不要复述单张作品的细节，不要罗列清单，不要因为某类只出现一次就抬成主风格 |
| **缺料规则（本 Spec 的核心）** | 该段没有对应材料时：<br>· **收到了**「我的历史风格」段 → 基于历史风格**续写**该段（保留其中仍然成立的表述），**绝对不要写"无"**、不要写"暂未新增""没有材料""没有新作品"之类任何表示空的意思<br>· **没收到**「我的历史风格」段 → 该段正文只写一个字：`无` |
| 历史风格的用法 | 收到该段时，它是作者此前的定稿：两段新描述都要与之**保持连续**（读起来像同一位作者），但不要写成"在原有基础上新增了…"这类修订说明，也不要逐字复述历史原文 |
| 首次归纳 | 若**未收到**「我的历史风格」段，说明这是第一次为这位用户归纳风格 |
| 人称 | 用客观陈述（不写"我""你"），把风格写成"这位作者一贯的样子" |

> **系统提示词不重复**「不要说并不存在的风格／无废话」这条——它在用户消息的 `【输出要求】` 里（§2 决策）。系统管**结构与规则**，用户消息管**语感要求**。

### 5.4 并发 / 一致性 / 失败语义

- **上传分析并发**：`asyncio.Semaphore(config.WIKI_UPLOAD_QA_CONCURRENCY)` + `asyncio.gather(*tasks, return_exceptions=True)`。并发路数默认 3，避免同时打爆视觉接口。
- **失败分类**：
  - `AppError` 子类（`UpstreamApiError 61001` / `UpstreamTimeoutError 61002` / `ImageProcessError 61003` / `GalleryItemNotFoundError 40403`）→ **记为该张失败**（跳过、不标记、计入 `upload_failed`）。
  - 清洗后为空的分析结果 → 同样记为失败。
  - **其它未预期异常不吞**：整次刷新抛出（保持既有"失败即无痕"的边界清晰）。
- **文本 LLM 失败** → `61001` / `61002` 抛出，`wiki` 与 `images.wiki_used` **全部不变**（含本轮刚分析成功的上传图，它们**不标记**）。见 §3 已知限制第 1 条。
- **事务边界不变**：`wiki` 的 UPSERT 与 `images.wiki_used` 的批量 UPDATE 在**同一个 `sqlite3` 连接/事务**里提交。
- **数据作用域**：`user_id` **只来自 `request.state.user["id"]`**。上传图额外经 `gallery.read_gallery_file(item_id, user_id)` 的归属校验兜底——即使 `list_pending_style_images` 出错也不可能读到别人的图。
- **不加锁**：同一用户并发的两次刷新，后完成者覆盖（含 `prev_style`），与 Spec12 §5.3 一致。

---

## 6. 接口约定

### 6.1 变更：`POST /api/wiki/style/refresh` 响应 `data` 新增 2 个字段

**（a）有更新**

```json
{
  "updated": true,
  "reason": null,
  "style": "【上传作品的风格】\n以水彩手绘质感为主……\n\n【生成作品的风格】\n高饱和的赛博朋克夜景……",
  "prev_style": "……更新前的风格……",
  "style_updated_at": "2026-09-15T06:12:33.123Z",
  "used_count": 7,
  "pending_count": 0,
  "upload_analyzed": 3,
  "upload_failed": 1
}
```

**（b）没有新东西可考虑**（与 Spec12 完全一致，只多两个恒为 0 的字段）

```json
{
  "updated": false, "reason": "nothing_new",
  "style": "……原样……", "prev_style": "……原样……",
  "style_updated_at": "……原样……",
  "used_count": 0, "pending_count": 0,
  "upload_analyzed": 0, "upload_failed": 0
}
```

**（c）材料全部不可用**（新增状态）

```json
{
  "updated": false, "reason": "analysis_failed",
  "style": "……原样……", "prev_style": "……原样……",
  "style_updated_at": "……原样……",
  "used_count": 0, "pending_count": 3,
  "upload_analyzed": 0, "upload_failed": 3
}
```

**字段口径**：

| 字段 | 含义 |
|---|---|
| `used_count` | 本次**真正被纳入合并**的作品数 = 分析成功的上传图 + 纳入的生成作品 = 本次新标记 `wiki_used=1` 的行数 |
| `pending_count` | 本次结束后该用户**仍未考虑**的作品数（**含上传图**） |
| `upload_analyzed` | 本次成功分析出风格的上传图张数 |
| `upload_failed` | 本次**尝试过并失败**的上传图张数（这些保持 `wiki_used=0`，下次点按钮自动重试）。**不含**"因超过 `WIKI_UPLOAD_QA_MAX` 而本轮没轮到"的——那些只计入 `pending_count` |

> `reason` 取值域扩为 `null | "nothing_new" | "analysis_failed"`，三者都走 `200`，**都不占错误码**。

### 6.2 不变

| 端点 / 表 | 状态 |
|---|---|
| `GET /api/wiki` | **不变** |
| `PUT /api/wiki/style` | **不变**（1~2000 字校验、旧值进 `prev_style`、不触碰 `wiki_used`） |
| `images` 表 schema | **不变**（只多一次幂等 `UPDATE`） |
| `POST /api/chat`、`/api/images`、`/api/gallery*`、`/api/community*`、`/api/shares*`、`/api/feedback*`、`/api/suggestions*`、`/api/admin/*` | **全部不变** |
| `DELETE /api/admin/users/{user_id}` | 级联删除 `wiki` 行**不变** |

### 6.3 鉴权约定

沿用 Spec2 / Spec11 / Spec12：非 `/api/auth/login` 的全 `/api` 接口需 Bearer JWT（无 → `40103`）。`/api/wiki*` 均为**普通登录用户**端点，**不涉及管理员权限**；请求体里**不接受任何 `user_id`**。

---

## 7. 前端交互

### 7.1 `api/chatApi.js`

**不改。** `refreshWikiStyle()` 原样返回 `data.data`，新增字段直接被 `GalleryPanel.vue` 使用。

### 7.2 `views/GalleryPanel.vue`

**（a）按钮忙态与提示**（`.wiki-actions` 区）：

- 忙态文案 `更新中…` → **`分析中…`**（现在真的是在逐张分析图片，十几秒很正常）。
- 按钮下方新增一行常量提示（`.wiki-hint`，12px、`var(--text-muted)`）：

  > 更新会逐张分析尚未纳入的上传作品，张数多时需要十几秒。

**（b）`refreshStyle()` 的提示语拼装**：

```js
async function refreshStyle() {
  if (wikiBusy.value) return
  wikiBusy.value = true
  wikiError.value = ''
  wikiNotice.value = ''
  try {
    const d = await refreshWikiStyle()
    if (d.updated) {
      wiki.value = { ...wiki.value, style: d.style, prev_style: d.prev_style,
                     style_updated_at: d.style_updated_at }
      let msg = `已根据 ${d.used_count} 张作品更新风格`
      if (d.upload_analyzed) msg += `（其中分析了 ${d.upload_analyzed} 张上传图）`
      if (d.upload_failed) msg += `，${d.upload_failed} 张上传图分析失败，可再次点击重试`
      if (d.pending_count > 0) msg += `，还有 ${d.pending_count} 张作品未纳入`
      wikiNotice.value = msg
    } else if (d.reason === 'analysis_failed') {
      window.alert('上传作品分析失败，本次没有可用的新材料，请稍后重试')
    } else {
      window.alert('所有作品已全部考虑到')
    }
  } catch (e) {
    wikiError.value = e.message || '更新风格失败'
  } finally {
    wikiBusy.value = false
  }
}
```

> `reason === 'nothing_new'` 与原逻辑一致（`window.alert('所有作品已全部考虑到')`），只是多了一个 `analysis_failed` 分支。

**（c）`.wiki-style` 按 `【…】` 切块渲染**

```js
// 风格文本按【…】标题切块：两段式新格式 → 两个块；Spec12 的单段旧文本 → 一个无标题块（外观不变）
const wikiBlocks = computed(() => {
  const text = wiki.value.style || ''
  if (!text) return []
  const blocks = []
  let cur = { title: '', body: [] }
  for (const line of text.split('\n')) {
    const m = line.match(/^【(.+)】\s*$/)
    if (m) {
      if (cur.title || cur.body.length) blocks.push(cur)
      cur = { title: m[1], body: [] }
    } else {
      cur.body.push(line)
    }
  }
  if (cur.title || cur.body.length) blocks.push(cur)
  return blocks
    .map(b => ({ title: b.title, body: b.body.join('\n').trim() }))
    .filter(b => b.title || b.body)
})
```

模板（替换原 `:22-23` 那两行）：

```html
<div v-if="wikiBlocks.length" class="wiki-style">
  <div v-for="(b, i) in wikiBlocks" :key="i" class="wiki-seg">
    <h4 v-if="b.title" class="wiki-seg-title">{{ b.title }}</h4>
    <p v-if="b.body" class="wiki-seg-body">{{ b.body }}</p>
  </div>
</div>
<p v-else class="wiki-empty">还没有风格记录，点下面的按钮从你的作品里归纳一版。</p>
```

**（d）不变的部分**：

- 「上次更新前」那一行（`.wiki-prev`）与 Spec13 的全文弹窗**完全不变**——`prev_style` 里现在是带标题的两段文本，弹窗的 `white-space: pre-wrap` 原样显示，正合适。
- 编辑态仍是**原文 textarea**（含标题行），1~2000 字校验、字数计数、"保存/取消"行为**全部不变**。用户可以手动删掉标题或改标题，不额外校验（§3 范围外）。
- `loadWiki()` / `load()` 的并发编排、切 Tab 不重拉 Wiki：**不变**。

### 7.3 样式约定

```css
/* 容器不再承担 pre-wrap，改由正文块各自承担（Spec15） */
.wiki-style {
  /* 既有：margin / font-size: 14px / line-height / color: var(--text-primary) 保留 */
}

.wiki-seg + .wiki-seg {
  margin-top: 10px;
}

.wiki-seg-title {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);   /* 小标题：弱于正文的 --text-primary，明显强于 --text-muted */
}

.wiki-seg-body {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.wiki-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}
```

- 主题口径不变（Spec10）：深紫主题下不得出现浅色面板。
- 按钮一律既有 `btn-mini` / `btn-clear`，**不新增按钮样式**。

---

## 8. 配置 / 环境变量 / .gitignore

`config.py` 新增 4 个**带默认值**的常量（`os.getenv` + 兜底，与既有写法一致）：

```python
# ---- 上传作品纳入风格（Spec15）----
WIKI_UPLOAD_QA_MAX = int(os.getenv("WIKI_UPLOAD_QA_MAX", "10"))              # 单次刷新最多分析的上传图张数
WIKI_UPLOAD_QA_CONCURRENCY = int(os.getenv("WIKI_UPLOAD_QA_CONCURRENCY", "3"))  # 视觉 QA 并发路数
WIKI_UPLOAD_ANSWER_MAX = int(os.getenv("WIKI_UPLOAD_ANSWER_MAX", "300"))     # 单条上传图分析结果的截断上限（字）
WIKI_UPLOAD_QA_MAX_SIDE = int(os.getenv("WIKI_UPLOAD_QA_MAX_SIDE", "1024"))  # 送模型前缩放的最长边（px）
# 调参建议：WIKI_UPLOAD_QA_MAX × WIKI_UPLOAD_ANSWER_MAX 宜 ≤ WIKI_PROMPT_TOTAL_MAX（默认 10×300=3000 ≤ 6000）
```

- `WIKI_STYLE_MAX` / `WIKI_PROMPT_ITEM_MAX` / `WIKI_PROMPT_TOTAL_MAX` **默认值不变**。
- `WIKI_UPLOAD_QA_MAX = 0` 是**合法但特殊**的取值：上传作品永远轮不到分析（只有生成作品时仍能正常更新；若当轮全是上传作品则返回 `reason:"analysis_failed"`）。保留它作为"临时关掉上传分析"的排障开关，**不是**受支持的常规配置。
- **无强制新增环境变量**；`.env` 无需改动；`.env.example` **可选**补 4 行注释版占位。
- `.gitignore` / `requirements.txt` / `package.json` **均不变**。

---

## 9. 错误码

**无新增、无修改。**

| 码 | 类 | 本 Spec 中的角色 |
|---|---|---|
| `40014` | 既有 `WikiContentError` | 手动编辑校验（**不变**） |
| `40103` | 既有 `AuthTokenError` | 未带 / 无效 token（**不变**） |
| `61001` | 既有 `UpstreamApiError` | 文本 LLM 调用失败；或返回清洗后为空 → **整次刷新失败，库不变**。上传图分析失败时**在路径内被吞成"该张失败"**，不向上抛 |
| `61002` | 既有 `UpstreamTimeoutError` | 文本 LLM 超时 → 整次刷新失败；上传图视觉 QA 超时 → **该张失败** |
| `61003` | 既有 `ImageProcessError` | 图片缩放/读取失败 → 上传图路径内**该张失败**（生成/编辑链路的既有语义不变） |
| `40403` | 既有 `GalleryItemNotFoundError` | 上传图文件缺失 / 非本人 → 该张失败（**不泄露存在性**的既有口径不变） |

- `reason: "nothing_new"` 与 `reason: "analysis_failed"` **都不是错误码**（§6.1），不落进错误处理链路。
- 无权限问题：`/api/wiki*` 无管理员门槛，无 `40301` / `40302` 场景。

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON。**新增 2 条事件、扩展 1 条字段、扩展 1 条取值域**：

- `wiki.style_updated`（**扩展**）—— 附 `user_id`、`source`（`"refresh"` \| `"manual"`）、`used_count`、`style_len`，**新增** `upload_analyzed` / `upload_failed`（手动编辑时均为 0）。**始终不记录风格全文**（可含用户创作倾向，属个人数据）。
- `wiki.upload_analysis_failed`（**新增**）—— 单张上传图分析失败。附 `user_id`、`image_id`、`reason`（上游错误串截断 200 字）。**逐张都要有痕迹**：否则用户只看到一个数字，排障无从下手。
- `wiki.refresh_skipped`（**扩展取值域**）—— `reason` 取值扩为 `"nothing_new" | "analysis_failed"`。附 `user_id`；`analysis_failed` 时另附 `upload_failed`。
- `wiki.upload_migrated`（**新增**）—— 一次性迁移真正执行的那一次记录，附 `affected`（被放回待考虑的上传图行数）。**只在迁移那一次出现**，之后每次启动都不会再打。

**不新增**：逐条上传图分析成功日志（正常路径，刷屏无价值）、`images.wiki_used` 的逐条标记日志。

---

## 11. 目录结构增量

```
Server/
  db.py             # _PENDING_SOURCES 加 'upload'
                    #   list_pending_style_images：SELECT 增返 source / file_name
                    #   删除 _mark_uploaded_wiki_used() 及 commit_style_update 内的调用
                    #   新增 WIKI_UPLOAD_MIGRATED_KEY + _migrate_upload_wiki_used()（init_db 内调用）
  wiki.py           # refresh_style 重写：分组 → 并发视觉分析 → 收集 → 三段材料 → 文本 LLM → 落库
                    #   新增 _analyze_uploads() / _collect_prompt_refs() / _build_messages(history, analyses, refs)
                    #   新增 import gallery / media；prompts 导入改为 WIKI_STYLE_SYSTEM_PROMPT
                    #   新增 from providers import qa
  media.py          # 新增 to_data_uri(image_bytes, max_side=0) -> str
                    #   + 模块级 _MIME_BY_EXT（.jpg/.jpeg/.png/.webp/.gif → mime）
  agents/qa.py      # _MIME + base64 四行改用 media.to_data_uri（机械替换，行为不变）
  agents/prompts.py # 新增 WIKI_UPLOAD_QA_PROMPT
                    #   WIKI_MERGE_SYSTEM_PROMPT + WIKI_INIT_SYSTEM_PROMPT → 合并重写为 WIKI_STYLE_SYSTEM_PROMPT
  config.py         # 新增 WIKI_UPLOAD_QA_MAX / _QA_CONCURRENCY / _ANSWER_MAX / _QA_MAX_SIDE
  main.py           # refresh 路由：wiki.style_updated 字段扩展 + wiki.refresh_skipped 的 reason 取值
  .env.example      # 【可选】补 4 行注释占位
frontend/src/
  views/GalleryPanel.vue   # 忙态文案 + .wiki-hint + refreshStyle 提示语/分支
                           #   + wikiBlocks 切块渲染 + .wiki-seg* / .wiki-hint 样式
  api/chatApi.js           # 不改
Server/static/             # 前端构建产物（npm run build 后同步，与既有提交口径一致）
specs/Spec15.md            # 本文件
```

> `wiki.py` 仍是"拿到 `user_id` 就干活"的业务模块；`main.py` 只做参数解析、调模块、套统一响应壳。

---

## 12. 实施顺序（里程碑）

1. **B1 数据层**：`_PENDING_SOURCES` 加 `upload`；`list_pending_style_images` 增返 `source` / `file_name`；删除 `_mark_uploaded_wiki_used()` 及其调用；新增一次性迁移（`app_meta` 幂等位 + `wiki.upload_migrated` 日志）。
2. **B2 图片工具**：`media.to_data_uri()`；`agents/qa.py` 改用之（**先跑一轮聊天链路的图像问答冒烟**，确认行为不变）。
3. **B3 提示词**：`WIKI_UPLOAD_QA_PROMPT` 新增；两份系统提示词合并重写为 `WIKI_STYLE_SYSTEM_PROMPT`（含缺料规则）。
4. **B4 编排**：`wiki.py` —— 分组（按 `WIKI_UPLOAD_QA_MAX` 切片）→ 并发视觉分析（Semaphore + gather + 失败分类）→ 生成段收集（既有逻辑）→ 全空判定 → 三段材料组装 → `chat_text` → 清洗 → 单事务写库。
5. **B5 配置与日志**：`config.py` 4 个常量；`main.py` 日志字段与 `reason` 取值域。
6. **F1 前端**：`GalleryPanel.vue` 忙态文案 + `.wiki-hint` + `refreshStyle` 提示语/分支 + `wikiBlocks` 切块渲染 + 样式。
7. **A1 构建与验收**：`cd frontend && npm run build` → 同步 `Server/static/` → 按 §13 逐条走查（含用例 16 的回归）。

> B1~B5 与 F1 无依赖，可并行；**A1 必须在 F1 之后**。

---

## 13. 验收用例

| # | 操作 | 期望 |
|---|---|---|
| 1 | 全新用户，只生成 2 张图，点更新 | 走**首次**分支（用户消息里**没有**「我的历史风格」段）；输出两段标题；`【上传作品的风格】` 正文为 `无`（历史为空 + 该段无材料）；`【生成作品的风格】` 有内容；`upload_analyzed = 0` |
| 2 | 已有风格的用户，只说新生成 1 张图（无新上传图），点更新 | 用户消息里有「我的历史风格」段；`【上传作品的风格】` **不出现「无」**，而是基于历史续写；`upload_analyzed = 0`、`used_count = 1` |
| 3 | 全新用户，只上传 3 张图（无生成作品），点更新 | 3 张各调一次视觉 QA（问题逐字为 `WIKI_UPLOAD_QA_PROMPT`）；`【上传作品的风格】` 有内容、`【生成作品的风格】` 为 `无`；`upload_analyzed = 3`、`used_count = 3` |
| 4 | 上传 3 张 + 生成 2 张，点更新 | 两段都有内容；`used_count = 5`、`upload_analyzed = 3`、`pending_count = 0` |
| 5 | 上传 15 张，点更新 | 只分析 **10** 张（`WIKI_UPLOAD_QA_MAX`）；`upload_analyzed = 10`、`used_count = 10`、`pending_count = 5`；前端提示「还有 5 张作品未纳入」；**再点一次** → 处理剩下 5 张，`pending_count = 0` |
| 6 | 某张上传图的文件被手工删掉（或非本人），点更新 | 该张计入 `upload_failed`，`wiki_used` 保持 0，日志有 `wiki.upload_analysis_failed`；其余张照常纳入，风格正常产出；**下次点按钮会重新尝试该张** |
| 7 | 视觉接口整体 5xx（断网 / 改坏 key），且**没有**生成作品，点更新 | `updated:false` / `reason:"analysis_failed"`，前端 `alert`；`wiki` 与 `images.wiki_used` **全部不变**；**不调用**文本 LLM |
| 8 | 视觉接口整体 5xx，但**有**生成作品，点更新 | 生成段照常产出；缺料的 `【上传作品的风格】` 按「历史非空 → 续写 / 历史为空 → 无」输出；`upload_failed > 0`；前端提示里带失败张数 |
| 9 | 文本 LLM 5xx（视觉全成功），点更新 | `61001`；`wiki` 与 `images.wiki_used` **全不变**——**已分析成功的那几张上传图仍为 `wiki_used = 0`**（下次会重新分析，§3 已知限制 1） |
| 10 | 文本 LLM 返回空字符串 | `61001`（`风格生成返回为空`）；库不变 |
| 11 | 首次更新后再点一次（无新作品） | `alert('所有作品已全部考虑到')`；`updated:false` / `reason:"nothing_new"`；不调任何 LLM、不写库 |
| 12 | **存量库迁移**：拿一个 Spec14 时期的 `artcn.db`（上传图 `wiki_used=1`），启动后端 | 日志出现一次 `wiki.upload_migrated`（`affected = 上传图行数`）；点更新 → 这些上传图开始被分析 |
| 13 | 承上，**再重启一次**后端 | **不再**出现 `wiki.upload_migrated`；且 Spec15 之后新标记的上传图**不会被重置**（`wiki_used` 仍为 1） |
| 14 | 已纳入过的上传图，再点更新 | **不再**重复分析（`upload_analyzed = 0`），只处理新作品 |
| 15 | 上传图的分析结果 > 300 字 | 截断到 `WIKI_UPLOAD_ANSWER_MAX`；风格产出正常；不报错 |
| 16 | **回归**：聊天里上传一张图 + 「这张图里有什么？」 | `qa_image` 行为与改前**完全一致**（`media.to_data_uri` 替换是机械的）；回答正常 |
| 17 | 上传原图接近 10MB，点更新 | 送模型前缩到最长边 ≤ `WIKI_UPLOAD_QA_MAX_SIDE`（1024）；请求体显著小于原图；分析正常返回 |
| 18 | 同时看后端日志 | 上传图的分析请求**并发不超过 `WIKI_UPLOAD_QA_CONCURRENCY`（3）路** |
| 19 | 上传 + 生成作品合计超 `WIKI_PROMPT_TOTAL_MAX`（6000 字） | 上传段**全部纳入**（不参与触顶丢弃）；生成段按时间倒序取到触顶，未纳入者 `wiki_used` 仍为 0；`pending_count > 0`，前端提示准确 |
| 20 | 点开「上次更新前」那一行（Spec13 弹窗） | 显示的是**上一版带标题的两段全文**，可滚动、可复制；样式不变 |
| 21 | 点「编辑」→ 手动改成任意文本（可含也可不含 `【…】`）→ 保存 | 1~2000 字校验与 Spec12 一致；保存后 Block 按新文本切块渲染（无标题则单块）；**不触碰** `images.wiki_used`（此前未纳入的作品仍是待考虑） |
| 22 | 手工把 `wiki.style` 改成一段**不带 `【…】`** 的旧格式文本 | Block 渲染为**单个正文块**（无小标题），外观与 Spec12 时期一致（向后兼容） |
| 23 | **调用统计页**（Spec4 / Spec11） | 点一次按钮就算产生 10 次视觉调用，`usage.qa` **也不增加**；四类计数均不变 |
| 24 | 用户 A 调 `POST /api/wiki/style/refresh` | 只分析 A 自己的上传图（`list_pending_style_images` 按 `user_id` 过滤，`gallery.read_gallery_file` 再校验归属）；请求体里塞 `user_id` 不产生任何影响 |
| 25 | 未带 token 调 `/api/wiki/style/refresh` | `401`（`40103`） |
| 26 | 管理员删除某用户 | 该用户 `wiki` 行、`images` 行（含上传图文件）随之删除；其他用户不受影响 |
| 27 | 把 `WIKI_UPLOAD_QA_CONCURRENCY` 设为 1（串行） | 不报错，只是变慢；结果与并发 3 时一致 |
| 28 | 样式回归 | 两段小标题 + 正文层级分明，深紫主题下**无白底**；`.wiki-hint` 为低对比度小字；按钮仍是既有 `btn-mini` |

> 验收时明确排除：`wiki_used` 的前端角标与手动翻转 / 分析结果的持久化 / 风格参与出图 / 历史风格多版本 / 异步任务化 / 多图合并分析 / 手编文本的格式校验。
