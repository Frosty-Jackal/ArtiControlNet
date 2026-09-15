# ArtiControlNet Spec 16：我的作品直接上传入口（备注字段）+ 两处文案修正

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：给「我的作品」页补上**不经过聊天**的上传入口——一个按钮 + 弹窗，只能传图像、可附一条**备注**；备注与「文生图作品的原始 prompt」在卡片上**同位置显示**（点击看全文），并且在作品卡上**可改可清空**。`images` 表新增 `note TEXT` 列。顺带两处文案修正：Wiki 更新按钮下方的提示语改成不夸张的表述，成功后不再显示「已根据 N 张作品更新风格」这句。
> 本 Spec 是 **Spec.md / Spec2~15 的增量补充**，不推翻原有架构。数据库变化：**新增 1 列**（`images.note`，可空，无默认值）+ 一次幂等补列迁移。**无新表、无新依赖、无新环境变量**。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有 API Key 只在后端环境变量、除 Spec2 的本地单文件 SQLite `artcn.db` 外无其他数据库。**不新增 provider、不新增模型**——本次改动完全不调用任何外部 API。

---

## 1. 功能目的

- **补上传入口的缺口**：Spec5 起，图片进作品库**只有两条"顺带"的路**——在聊天里当参考图上传（`POST /api/images`，Spec5 §5.2 链路 1），或发帖时选「新上传」一张图（`POST /api/community`，Spec9 §5.3 链路 2）。两条都**必须蹭另一件事**才能走通：想单纯往作品库放一张自己的旧作、手绘稿、参考图，用户只能**先去聊天框传一次**，既别扭又会污染那段会话、还可能连带产生一条帖子。本 Spec 给「我的作品」页一个**直接入口**。
- **让上传的作品也有"话要说"**：生成/绘图作品有 `prompt`（画面描述），上传作品什么都没有——卡片上那行说明文字对上传作品**永远是空的**。备注就是上传作品的 `prompt` 对位物：一句"这是我 2019 年给某品牌做的包装"或者"参考了某个构图"。Spec15 之后上传作品已经会进风格归纳，备注让用户在作品库里**认得出自己传的是什么**。
- **备注要能改**：写错字、改主意、当时没想好——不能改就只能删掉重传，而重传会丢掉这张图已经攒下的 `wiki_used` 状态。改备注是纯元数据动作，代价极低。
- **文案要诚实**：Spec15 加的提示语「更新会逐张分析尚未纳入的上传作品，张数多时需要十几秒」把机制说窄了（生成作品也参与、已分析过的不会重分析），"十几秒"也是硬编码的猜测。改成如实描述机制、把等待交给"请耐心等待"。
- **成功不必自夸**：「已根据 1 张作品更新风格」是每次成功都出现的冗余播报——风格文本本身就在同一个 Block 里肉眼可见地变了。删掉它。**但警示必须留**：哪几张分析失败、还有几张没纳入，是用户唯一能知道"要不要再点一次"的地方。

---

## 2. 决策记录（为什么这么选）

| 决策 | 选择 | 理由 |
|---|---|---|
| 上传入口的接口形态 | **新增 `POST /api/gallery`**，不复用 `POST /api/images` | `/api/images` 是**聊天附件**通道：它额外写临时 `storage/`（TTL 1h、启动清空）并返回 `image_url`。作品库直传不需要这些——多写一份临时文件纯属浪费，返回值语义也不对（前端要的是作品项，不是图片 URL） |
| 备注字段名与列型 | `images.note TEXT`（**可空、无默认值**） | `ADD COLUMN note TEXT` 在 SQLite 里无 `NOT NULL` 约束即可加，不需要默认值；「没有备注」与「备注为空串」不必区分，统一用 `NULL` |
| 备注的身份 | **与 `prompt` 对位**：卡片上同一个位置、同一套「2 行截断 + 点击看全文」交互；显示优先级 `note \|\| prompt` | 作者原话"跟文生图会显示原始prompt一样"。两者**互斥**（上传作品的 `prompt` 恒为 `NULL`，生成作品的 `note` 恒为 `NULL`），所以 `note \|\| prompt` 不会歧义，也不需要前端判断来源 |
| 备注是否必填 | **可选**，strip 后为空即"没有备注" | 作者拍板。传一张图不该被逼着写字 |
| 备注长度上限 | `GALLERY_NOTE_MAX`（默认 **200**） | 作者拍板。与卡片上 prompt 的展示量级（2 行截断 + 全文弹窗）匹配；prompt 可以很长是因为它是模型输入，备注是给人看的 |
| 备注超长的错误码 | **新增 `40015 GalleryNoteError`** | 与 Spec9/12 的 `40011` / `40012` / `40013` / `40014` 同一序列，下一个空位就是 40015。不复用 `40001`——那会让前端无法给出"备注太长了"这种具体提示 |
| 备注能否修改 | **能**，`PUT /api/gallery/{item_id}/note` | 作者拍板"卡片上加「改备注」按钮"。可改 = 可清空（提交空串即清空），不额外区分"删除备注"动作 |
| 用 `PUT` 还是 `PATCH` | **`PUT`** | 全仓**没有任何 `PATCH`**（`main.py` 里更新类路由一律 `PUT`：`/api/wiki/style`、`/api/admin/users/{id}/password`、`/api/admin/users/{id}/admin`）。跟随既有约定，不引入第三种动词 |
| 谁能改备注 | **只有 `source='upload'` 的作品**（否则 `40015`） | 生成/绘图作品的说明位是**模型给的 `prompt`**，给它们写备注会和 `prompt` 抢同一个展示位（§2 第 3 条的 `note \|\| prompt` 会变成"备注盖住原始 prompt"）。既有两条上传路径产出的图同样是 `source='upload'`，因此也可写备注——口径统一，不会出现"这张上传图能写、那张不能"的怪现象 |
| 改备注是否触碰 `images.wiki_used` | **不触碰** | 与 Spec12 §5.2C「手动编辑风格不消费任何作品」同口径。改备注是资料整理，不是"纳入风格" |
| 改备注是否需要 confirm | **不需要** | 与「删除作品」「撤销分享」「覆盖风格」不同，改备注**不丢失任何已有内容**（旧备注只是被替换，且可再改回来），没有不可逆代价 |
| 备注是否参与风格归纳 | **不参与**（写入 §3 范围外） | Spec15 的上传段材料是**视觉 QA 对图片的判断**，与用户自述是两回事。把备注喂进文本 LLM 会改变既有提示词的语义与效果，属于独立的可评估改动，本 Spec 不做 |
| 备注是否进分享页 / 社区 | **不进** | 分享页（Spec9）本来就不显示 `prompt`；社区帖子（Spec9）只有图 + 帖子文字。本 Spec 不动这两处，保持"备注只在作品库内可见" |
| 是否写临时 `storage/` | **不写** | 作品库直传的图不进聊天链路，没有 TTL 可言。`gallery/` 是持久目录（Spec5 §5.3） |
| 是否计入 `usage` 统计 | **不计入** | `usage` 记的是 **AI 调用**（chat/generate/edit/qa 四类，Spec4 §5.4）。上传一张图不调用任何模型。改备注同理 |
| 弹窗是否支持拖拽上传 | **不支持**，只做点击选图 | 作者要的是「按钮 → 弹窗 → 选图」。Spec10 给主聊天与发帖做的拖拽是那两个场景的既有需求，不自动扩散到新弹窗（YAGNI） |
| 上传成功后如何刷新列表 | **prepend**（仅当当前 Tab 含上传作品），不整页 `load()` | 整页重拉会 `releaseThumbs()` 撤销所有 objectURL 再全部重下——几十张图闪一下，代价与收益不成比例 |
| 改备注成功后如何刷新 | **只就地合并 `note` 字段**（`{...旧项, note: 新值}`） | 服务端返回的作品项**不含 `objectUrl`**（那是前端 `URL.createObjectURL` 的产物）。整项替换会把缩略图打空，卡片变成"…" |
| 顺带修的样式问题 | `.gallery-actions` 加 `flex-wrap: wrap` | 上传作品的卡片现在最多 6 个按钮（查看大图/下载/备注/分享或复制链接+撤销分享/删除），而 `.gallery-actions` 是 `display:flex` 且**无 wrap**，200px 的卡片里必撑破 |
| 弹窗里预览图的样式 | **必须用 `.gallery-lightbox-inner .gallery-upload-preview` 这种两级选择器**覆盖 | `main.css` 有一条**全局**规则 `.gallery-lightbox-inner img { max-width:100%; max-height:80vh; box-shadow: … }`（特异性 0,1,1）。只写 `.gallery-upload-preview { max-height:240px }`（0,1,0）**压不住它**，预览图会顶到 80vh。既有 `.prompt-overlay` / `.wiki-prev-overlay` 里放的是 `<p>` 不是 `<img>`，所以此前没撞上这个坑 |
| Wiki 提示语（改动 1） | 逐字改为 **「更新会逐张分析个人作品（之前已分析过则不会分析），请耐心等待」** | 作者原话。旧文案把范围说窄了（只提上传作品）、把耗时写死了（"十几秒"是猜的） |
| 成功提示（改动 3） | **删除**「已根据 N 张作品更新风格」与「（其中分析了 N 张上传图）」，**保留**「N 张上传图分析失败，可再次点击重试」与「还有 N 张作品未纳入」；两者都没有 → **不显示任何提示** | 作者拍板"只保留警示部分"。风格文本就在同一个 Block 里，变了看得见，不需要再播报一次；而失败/未纳入是**没有别的地方能看到**的信息，删了用户就再也发现不了要再点一次 |
| 后端响应字段是否跟着删 | **不删**。`used_count` / `upload_analyzed` 仍在响应里 | 前端不再用，但它们是接口的既有契约（Spec15 §6.1），删字段是**破坏性变更**；留着零成本，且日后想恢复播报不用改后端 |

> **时间语义不变**：本 Spec 不引入任何新的时间字段。作品项仍用 `images.created_at`（UTC ISO），前端按本地时区格式化（`formatTime`）。

---

## 3. 需求边界

### 范围内

- **改动 1（文案）**：`GalleryPanel.vue` 的 `.wiki-hint` 文案逐字替换。
- **改动 2（上传 + 备注）**：
  - `images` 表新增 `note TEXT` 列 + 幂等补列迁移。
  - `POST /api/gallery`（multipart：`file` 必填、`note` 可选）。
  - `PUT /api/gallery/{item_id}/note`（JSON body：`note`）。
  - 新增 `40015 GalleryNoteError`、`config.GALLERY_NOTE_MAX`、`schemas.GalleryNoteUpdateRequest`。
  - 作品项（`GET /api/gallery` 列表与两个新接口的返回值）新增 `note` 字段。
  - 前端：Tab 行右侧「上传作品」按钮 + 上传弹窗；卡片说明位改显 `note || prompt`；上传作品卡片多一个「加备注／改备注」按钮 + 改备注弹窗；`.gallery-actions` 加 `flex-wrap: wrap`。
  - `api/chatApi.js` 新增 2 个函数。
  - 新增 1 条日志事件、扩展 1 条日志事件的字段。
- **改动 3（提示语）**：`refreshStyle()` 成功分支的 `wikiNotice` 拼装逻辑。

### 范围外（本 Spec 不做）

- **备注参与风格归纳**：`wiki.py` 的上传段仍只送视觉 QA 的分析结果，不把 `note` 喂给文本 LLM（§2）。`db.list_pending_style_images` 的 `SELECT` **不加 `note`**。
- **备注出现在分享页 / 社区帖子**：分享页与大图 overlay 之外的地方概不显示（§2）。
- **生成/绘图作品写备注**：`source != 'upload'` 一律 `40015`（§2）。想给生成作品加说明，那是改 `prompt` 的范畴，本 Spec 不碰。
- **多图批量上传**：一次弹窗只传一张（`<input>` 不带 `multiple`）。要传多张就点多次。
- **拖拽上传**：弹窗只做点击选图（§2）。
- **上传时选择 `source`**：作品库直传**恒为 `source='upload'`**，不提供"标记为生成作品"之类的入口。
- **备注的全文搜索 / 筛选**：作品列表仍只按 `source` 筛选（Spec5 §7），不按备注搜。
- **上传时的图片编辑**：不裁剪、不缩放、不转格式——`validate_upload` 是什么就存什么（与 `/api/images` 同口径）。
- **`images.note` 的历史数据回填**：存量作品一律 `note = NULL`。Spec15 之后上传的作品没有备注是**事实**，不该编一个出来。
- **改动 1 的提示语做成可配置**：仍写死在前端，不进 `config.py`（既有口径）。
- **`/api/images` 支持 `note` 参数**：聊天附件通道不写备注（§2）。聊天上传的图之后可以在作品库里补备注——「加备注」按钮对它们是可见的。

### 已知限制（写入本文档，避免误读）

- **三条路径产出的上传作品长得一模一样**：聊天参考图（`/api/images`）、发帖时新上传（`/api/community`）、作品库直传（`POST /api/gallery`）——三者都是 `source='upload'`、`prompt=NULL`，在「上传」Tab 里并列，**都可以写备注**。差别只在副作用：路径 1 额外在 `storage/` 有一份临时副本（1h 后清理，不影响作品库），路径 2 额外在 `community/` 有一份帖子图。用户视角下这是**有意为之**——它们本来就是同一类东西，作品库里不该分出三种"上传"。
- **`note` 与 `prompt` 的互斥是靠"写入路径"保证的，不是靠约束**：`note` 只在 `POST /api/gallery` / `PUT .../note` 写入，这两处都只作用于 `source='upload'`；`prompt` 只在 `gallery.save_gallery_image(..., prompt=...)` 写入，上传路径恒传 `None`。数据库层**没有 CHECK 约束**（与既有 `source` / `ext` 同口径，靠白名单与代码路径保证）。
- **卡片上的备注被截断到 2 行**：`.gallery-prompt` 的既有 `-webkit-line-clamp: 2`（Spec6）。200 字的备注在 200px 宽的卡片里通常显示不全，需要点击看全文弹窗。
- **改备注不会让作品重新参与风格归纳**：`wiki_used` 不动，所以改完备注后点「更新风格」，那张图**不会**因为备注变了而重分析（图片字节没变，视觉 QA 的结果也不会变）。这是**正确**的行为，但用户可能期望"改了备注风格也该更新"——不提供。
- **两个弹窗在请求期间都不可取消**：`uploadBusy` / `noteBusy` 期间对应的动作按钮置灰，`Esc` 与遮罩点击**都不关闭**弹窗，避免请求在途时本地状态被清空、成功结果无处可去。图 ≤10MB、备注一行小文本，正常都在秒级返回。这是**有意的**——不是漏了 `Esc` 处理。
- **`.gallery-tabs` 的 `flex-wrap: wrap` 是全局样式**（`main.css`）：新按钮加 `margin-left: auto` 右对齐，窄屏换行时它会单独占一行。既有 Tab 的换行行为不受影响。

---

## 4. 技术栈增量

| 层 | 新增 | 说明 |
|---|---|---|
| 后端 | **无新依赖** | `db.py`（建表语句加列 + `_migrate_images_note` + `add_image_record`/`_image_row_to_dict` 增 `note` + 新增 `set_image_note`）、`gallery.py`（`save_gallery_image` 增参、`_with_url` 增返 `note`、新增 `_clean_note` / `create_upload` / `update_note`）、`errors.py`（`GalleryNoteError`）、`schemas.py`（`GalleryNoteUpdateRequest`）、`config.py`（`GALLERY_NOTE_MAX`）、`main.py`（2 个新路由 + 1 条日志） |
| 前端 | 无新依赖 / 无新组件 / 无新路由 | `views/GalleryPanel.vue` 一个文件（按钮 + 2 个弹窗 + 显示逻辑 + 样式）；`api/chatApi.js` 新增 2 个函数；`assets/styles/main.css` 只改 `.gallery-actions` 一行（加 `flex-wrap`） |
| 数据库 | **无新表，新增 1 列** | `images.note TEXT`（可空）+ 一次幂等 `ALTER TABLE` |

> 无新 pip / npm 依赖；无新增环境变量（`GALLERY_NOTE_MAX` 有默认值）；`.gitignore` / `requirements.txt` / `package.json` 均不变。

---

## 5. 架构设计（增量）

### 5.1 数据变更

**（a）建表语句加列**（`db.py::_CREATE_IMAGES_TABLE`）——**只影响全新库**：

```sql
CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    source     TEXT NOT NULL,
    file_name  TEXT NOT NULL,
    ext        TEXT NOT NULL,
    prompt     TEXT,
    note       TEXT,                          -- Spec16：上传作品的备注（用户自写；生成/绘图作品恒为 NULL）
    created_at TEXT NOT NULL,
    wiki_used  INTEGER NOT NULL DEFAULT 0
)
```

**（b）幂等补列迁移**（`db.py`，与 `_migrate_images_wiki_used` 同构）：

```python
def _migrate_images_note(conn: sqlite3.Connection) -> None:
    """存量库补列（Spec16 §5.1b）：PRAGMA 查得无 note 才 ALTER，幂等。

    新建库由 _CREATE_IMAGES_TABLE 自带该列，此分支只服务已存在的 artcn.db。
    两条路径的**列顺序不同**（存量库把 note 追加在末尾），但所有读取一律按
    列名取值（`row["note"]`），行为无差别。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)").fetchall()}
    if "note" not in cols:
        conn.execute("ALTER TABLE images ADD COLUMN note TEXT")
        logger.info("images.note 列已补齐", extra={"event": "db.migrate"})
```

**调用点**：`init_db()` 内，**紧接 `_migrate_images_wiki_used(conn)` 之后**（两者互不依赖，排在一起便于阅读）：

```python
        # Spec12 §5.1b：存量库补 images.wiki_used 列
        _migrate_images_wiki_used(conn)
        # Spec15 §5.1b：存量上传作品放回待考虑队列（必须在 app_meta 建表之后）
        _migrate_upload_wiki_used(conn)
        # Spec16 §5.1b：存量库补 images.note 列
        _migrate_images_note(conn)
```

- `ADD COLUMN note TEXT` **不需要默认值**：SQLite 允许加可空且无默认值的列（`wiki_used` 当初是 `NOT NULL DEFAULT 0`，所以写法不同，这不是笔误）。
- **无数据回填**：存量行 `note` 全为 `NULL`（§3 范围外）。

### 5.2 关键数据流

**（A）读取作品列表（页面加载 / 切 Tab）** —— `GET /api/gallery` → `gallery.list_user_images` → `db.list_image_records`：**查询完全不变**，只在 `_with_url` 的输出里多带一个字段。

```python
def _with_url(record: dict, public_base: str = "") -> dict:
    ...
    return {
        "id": record["id"],
        "source": record["source"],
        "url": f"/api/gallery/{record['id']}/file",
        "prompt": record["prompt"],
        "note": record["note"],          # Spec16：上传作品的备注（可空）
        "created_at": record["created_at"],
        "share": share_out,
    }
```

**（B）作品库直传（新按钮 → 弹窗 → 提交）**

```
点「上传作品」→ 弹窗选图 + 可选备注 → 点「提交」
  → POST /api/gallery  (multipart: file, note?)
  → content_type 白名单校验（路由层，与 /api/images 逐字同一套，40003）
  → media.validate_upload(data)                  # 40002 空文件 / 40003 格式 / 40004 超 10MB
  → gallery.create_upload(data, user_id, note, _public_base(request))
       → text = _clean_note(note)                # strip → 空则 None；超长 → 40015
       → save_gallery_image(data, user_id, "upload", None, note=text)
            → media.detect_ext → 写 gallery/{uuid}{ext}
            → db.add_image_record(user_id, "upload", file_name, ext, prompt=None, note=text)
       → _with_url(record, public_base)          # 与列表项同形
  → 200 { code:200, message:"ok", data: { id, source, url, prompt, note, created_at, share } }
```

- **备注校验在业务层**（`_clean_note`），**不在路由层**——与 §6.5 / §11 的口径一致，`main.py` 只做参数解析、调模块、套统一响应壳。
- **不写临时 `storage/`**、**不产生 task**、**不计 `usage`**（§2）。
- 新作品的 `share` 恒为 `null`（刚入库不可能有分享）。

**（C）改 / 清空备注**

```
点卡片上的「加备注 / 改备注」→ 弹窗 → 改文字 → 点「保存」
  → PUT /api/gallery/{item_id}/note   body: { "note": "……" }
  → gallery.update_note(item_id, user_id, note)
       → _get_owned(item_id, user_id)              # 不存在 / 非本人 → 40403
       → record["source"] != "upload" → GalleryNoteError(40015)
       → text = _clean_note(note)                  # strip → 空则 None；超长 → 40015
       → db.set_image_note(item_id, text)          # None = 清空备注
       → logger.info("gallery.note_updated", ...)
       → _with_url(更新后的记录)
  → 200 { code:200, message:"ok", data: { ...同上，note 为新值 } }
```

两个业务函数共用的归一化助手（`gallery.py`）：

```python
def _clean_note(note: str | None) -> str | None:
    """备注归一化（Spec16 §5.2B/C）：strip → 空则 None（= 无备注）；超长 → 40015。

    长度按 strip 后的字符数算（中文按 1 字），与 config.GALLERY_NOTE_MAX 同口径。
    """
    text = (note or "").strip()
    if len(text) > config.GALLERY_NOTE_MAX:
        raise GalleryNoteError(f"备注需在 {config.GALLERY_NOTE_MAX} 字以内")
    return text or None
```

- **不触碰 `images.wiki_used`**、不碰 `wiki` 表、不碰 `shares`（§2）。
- 备注**不改变** `created_at`，所以列表排序位置不变。

**（D）基于新作品更新风格** —— `POST /api/wiki/style/refresh`：**完全不变**。`db.list_pending_style_images` 的 `SELECT` 不加 `note`（§3 范围外），Spec15 的上传段材料仍是视觉 QA 的输出。

**（E）其余写 `images` 的路径** —— **全部不变**，`note` 一律为 `NULL`。全仓共有 **5 处**写 `images`，本 Spec 只新增第 3 处：

| # | 调用点 | `source` | `prompt` | `note` |
|---|---|---|---|---|
| 1 | `main.py:389`（`POST /api/images`，聊天参考图上传） | `upload` | `None` | **`None`** |
| 2 | `community.py:79`（`POST /api/community` 带**新上传**的图，Spec9 §5.3 链路 2） | `upload` | `None` | **`None`** |
| 3 | **`POST /api/gallery`（本 Spec 新增）** | `upload` | `None` | **用户填的备注** |
| 4 | `agents/generation.py:68`（文生图） | `generate` | 完整描述 | `None` |
| 5 | `agents/editing.py:75`（图文生图） | `edit` | 完整描述 | `None` |

> `save_gallery_image(..., note=None)` 的**默认值**正是为 1 / 2 / 4 / 5 这四处准备的——它们**一行都不用改**。四处既有调用全部是**位置传参**（`data, user_id, source, prompt`），把 `note` 加在签名末尾并给默认值，调用点零改动。

### 5.3 一致性 / 失败语义

- **两个新接口都是单表单行写入**，各自一个 `sqlite3` 连接 + `commit`，无跨表事务需求（对比 `commit_style_update` 的"wiki + images 同事务"）。
- **无并发问题**：同一作品并发的两次改备注，后写覆盖先写——与 Spec12 §5.3 的既有口径一致，不加锁。
- **上传的部分失败不可能存在**：`gallery/{uuid}{ext}` 的写文件与 `db.add_image_record` 的顺序是**先文件后记录**（`save_gallery_image` 既有实现）。若记录写入抛异常，会留下一个**孤儿文件**——这与 Spec5 的既有行为一致，本 Spec 不改（`gallery/` 的清理不在任何既有 Spec 的范围内，且孤儿文件无害：没有任何记录指向它，不占用户可见空间）。
- **`note` 校验放在业务层而非 pydantic**：与 `WikiStyleRequest`（Spec12 §6.1："长度/空值校验在业务层（40014）"）同口径，保证 `40015` 这个具体错误码能带着中文提示返回，而不是 FastAPI 的 422。
- **数据作用域**：`user_id` **只来自 `request.state.user["id"]`**；改备注经 `_get_owned` 的归属校验兜底（非本人 → `40403`，**不泄露存在性**，与 Spec5 同口径）。请求体里**不接受 `user_id`**。

---

## 6. 接口约定

### 6.1 新增：`POST /api/gallery`

**请求**：`multipart/form-data`

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | 图像文件；`content_type` 须在 `config.ALLOWED_IMAGE_MIME`（jpeg/png/webp/gif），实际格式由 `media.validate_upload` 二次判定 |
| `note` | 否 | 备注，strip 后 ≤ `GALLERY_NOTE_MAX`（200）字；空 / 缺省 = 无备注 |

**响应**（`200`）——`data` 为**与 `GET /api/gallery` 列表项同形**的作品项，供前端直接 prepend：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "id": 42,
    "source": "upload",
    "url": "/api/gallery/42/file",
    "prompt": null,
    "note": "2019 年为某品牌做的包装方案",
    "created_at": "2026-09-15T07:20:11.482Z",
    "share": null
  }
}
```

**失败**：`40002`（空文件）/ `40003`（格式不支持）/ `40004`（>10MB）/ `40015`（备注超长）/ `40103`（无 token）。

### 6.2 新增：`PUT /api/gallery/{item_id}/note`

**请求**：`application/json`

```json
{ "note": "改过之后的备注（空串 = 清空备注）" }
```

**响应**（`200`）——`data` 同样是作品项，`note` 为新值（清空后为 `null`）：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "id": 42, "source": "upload", "url": "/api/gallery/42/file",
    "prompt": null, "note": null,
    "created_at": "2026-09-15T07:20:11.482Z", "share": null
  }
}
```

**失败**：`40015`（超长，或该作品不是 `source='upload'`）/ `40403`（不存在 / 非本人）/ `40103`（无 token）。

```python
# schemas.py —— 追加到 Spec12 §6 的 WikiStyleRequest 之后
class GalleryNoteUpdateRequest(BaseModel):
    """PUT /api/gallery/{item_id}/note 请求体。长度校验在业务层（40015）。"""

    note: str
```

### 6.3 变更：`GET /api/gallery` 的 `items[]` 新增 1 个字段

```json
{ "items": [ { "id": 42, "source": "upload", "url": "…", "prompt": null,
               "note": "…", "created_at": "…", "share": null } ] }
```

> **纯增量**：只多一个 `note`，既有字段一个不改。旧前端忽略它即可正常工作。

### 6.4 不变

| 端点 / 表 | 状态 |
|---|---|
| `POST /api/images` | **不变**（仍写 `storage/` + 入库 `source='upload', prompt=None, note=NULL`） |
| `GET /api/gallery/{id}/file`、`DELETE /api/gallery/{id}` | **不变** |
| `GET /api/wiki`、`POST /api/wiki/style/refresh`、`PUT /api/wiki/style` | **不变**（含响应字段，§2） |
| `POST /api/chat`、`/api/tasks/{id}`、`/api/threads/…` | **不变** |
| `/api/community*`、`/api/shares*`、`/api/feedback*`、`/api/suggestions*`、`/api/admin/*` | **不变** |
| `GET /share/{token}` 分享页 | **不变**（不显示 `prompt`，也不显示 `note`） |
| 其余表（`users` / `usage` / `posts` / `post_votes` / `feedback` / `shares` / `suggestions` / `app_meta` / `wiki`） | **不变** |

### 6.5 鉴权约定

沿用 Spec2 / Spec5：非 `/api/auth/login` 的全 `/api` 接口需 Bearer JWT（无 → `40103`）。两个新接口都是**普通登录用户**端点，**不涉及管理员权限**；请求体与 query 里**不接受任何 `user_id`**。

---

## 7. 前端交互

### 7.1 `api/chatApi.js`（新增 2 个函数）

```js
// ---- 我的作品（Spec16 §7.1）----

// 作品库直传：multipart，note 可选（空则不 append，后端按"无备注"处理）
export async function uploadGalleryImage(file, note = '') {
  const form = new FormData()
  form.append('file', file)
  if (note) form.append('note', note)
  const { data } = await http.post('/api/gallery', form)
  return data.data // 与 listGallery 的 items[] 同形
}

// 改 / 清空备注（note='' 即清空）
export async function updateGalleryNote(id, note) {
  const { data } = await http.put(`/api/gallery/${id}/note`, { note })
  return data.data // 同形作品项
}
```

### 7.2 `views/GalleryPanel.vue`

**（a）改动 1：`.wiki-hint` 文案**（替换现有那一行，位置与样式不变）

```html
<p class="wiki-hint">更新会逐张分析个人作品（之前已分析过则不会分析），请耐心等待</p>
```

**（b）上传入口按钮**（`.gallery-tabs` 内、Tab 之后）

```html
<div class="gallery-tabs">
  <button v-for="tab in TABS" …>{{ tab.label }}</button>
  <button class="btn-mini gallery-upload-btn" @click="openUpload">上传作品</button>
</div>
```

```css
/* Tab 行右对齐（.gallery-tabs 是 flex + flex-wrap，见 main.css Spec5 §7） */
.gallery-upload-btn {
  margin-left: auto;
}
```

**（c）卡片说明位：`note` 与 `prompt` 同位置显示**

```js
// 卡片上的说明文字：上传作品显示备注，生成/绘图作品显示原始 prompt（Spec16 §7.2c）。
// 两者互斥（上传作品 prompt 恒为 null，生成作品 note 恒为 null），故 || 不会歧义。
function itemText(item) {
  return item.note || item.prompt || ''
}
```

```html
<!-- 缩略图 title 与说明行都改用 itemText(item) -->
<button class="gallery-thumb-btn" :title="itemText(item) || '查看大图'" @click="openLightbox(item)">
…
<p
  v-if="itemText(item)"
  class="gallery-prompt"
  title="点击查看全文"
  @click="promptOverlay = item"
>{{ itemText(item) }}</p>
```

全文弹窗只需把取值从 `promptOverlay.prompt` 换成 `itemText(promptOverlay)`（**结构与样式一行不改**）：

```html
<p class="prompt-overlay-text">{{ itemText(promptOverlay) }}</p>
…
<button class="btn-mini" @click="copyPrompt(itemText(promptOverlay))">
```

**（d）卡片上的「加备注 / 改备注」按钮**（`.gallery-actions` 内，放在「下载」之后、「分享」之前）

```html
<button
  v-if="item.source === 'upload'"
  class="btn-mini"
  :disabled="busyId === item.id"
  @click="openNoteEdit(item)"
>
  {{ item.note ? '改备注' : '加备注' }}
</button>
```

```css
/* .gallery-actions 现在最多 6 个按钮，必须允许换行（Spec16 §2） */
.gallery-actions {
  flex-wrap: wrap;   /* 既有：display:flex / gap:8px / padding:8px 12px 12px 全部保留 */
}
```

**（e）上传弹窗**

```html
<div v-if="uploadOpen" class="gallery-lightbox" @click.self="onUploadBackdrop">
  <div class="gallery-lightbox-inner gallery-upload-dialog">
    <h3 class="gallery-dialog-title">上传作品</h3>

    <label class="gallery-upload-box">
      <input
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        class="gallery-file-input"
        @change="onPickUpload"
      />
      <template v-if="!uploadPreviewUrl">
        <span class="gallery-upload-icon">🖼</span>
        <span class="gallery-upload-title">点击选择图像</span>
        <span class="gallery-upload-sub">jpg / png / webp / gif，≤10MB</span>
      </template>
      <template v-else>
        <img :src="uploadPreviewUrl" class="gallery-upload-preview" alt="预览" />
        <span class="gallery-upload-replace">点击可更换图像</span>
      </template>
    </label>

    <textarea
      v-model="uploadNote"
      class="gallery-note-input"
      :maxlength="GALLERY_NOTE_MAX"
      rows="3"
      placeholder="加一句备注（可不填）…"
    ></textarea>
    <p class="gallery-note-count">{{ uploadNote.length }} / {{ GALLERY_NOTE_MAX }}</p>

    <p v-if="uploadError" class="login-error">{{ uploadError }}</p>

    <div class="gallery-lightbox-bar">
      <button class="btn-mini" :disabled="!uploadFile || uploadBusy" @click="submitUpload">
        {{ uploadBusy ? '上传中…' : '提交' }}
      </button>
      <button class="btn-clear" :disabled="uploadBusy" @click="closeUpload">取消</button>
    </div>
  </div>
</div>
```

**（f）改备注弹窗**

```html
<div v-if="noteEdit" class="gallery-lightbox" @click.self="onNoteBackdrop">
  <div class="gallery-lightbox-inner gallery-note-dialog">
    <h3 class="gallery-dialog-title">备注</h3>
    <textarea
      v-model="noteDraft"
      class="gallery-note-input"
      :maxlength="GALLERY_NOTE_MAX"
      rows="4"
      placeholder="写一句备注；清空即删除备注"
    ></textarea>
    <p class="gallery-note-count">{{ noteDraft.length }} / {{ GALLERY_NOTE_MAX }}</p>
    <p v-if="noteError" class="login-error">{{ noteError }}</p>
    <div class="gallery-lightbox-bar">
      <button class="btn-mini" :disabled="noteBusy" @click="saveNote">
        {{ noteBusy ? '保存中…' : '保存' }}
      </button>
      <button class="btn-clear" :disabled="noteBusy" @click="noteEdit = null">取消</button>
    </div>
  </div>
</div>
```

**（g）脚本状态与函数**

```js
const GALLERY_NOTE_MAX = 200 // 与后端 config.GALLERY_NOTE_MAX 同值（Spec16）

// 上传弹窗
const uploadOpen = ref(false)
const uploadFile = ref(null)
const uploadNote = ref('')
const uploadPreviewUrl = ref(null)   // objectURL，关闭/换图时必须 revoke
const uploadBusy = ref(false)
const uploadError = ref('')

// 改备注弹窗
const noteEdit = ref(null)           // 当前编辑的作品项；非 null = 弹窗打开
const noteDraft = ref('')
const noteBusy = ref(false)
const noteError = ref('')
```

```js
// ---- 上传作品（Spec16 §7.2e）----

function openUpload() {
  uploadOpen.value = true
  uploadFile.value = null
  uploadNote.value = ''
  uploadError.value = ''
  revokeUploadPreview()
}

function onPickUpload(e) {
  const f = e.target.files && e.target.files[0]
  e.target.value = ''            // 允许连续选同一个文件
  if (!f) return
  uploadError.value = ''
  revokeUploadPreview()
  uploadFile.value = f
  uploadPreviewUrl.value = URL.createObjectURL(f)
}

function revokeUploadPreview() {
  if (uploadPreviewUrl.value) {
    URL.revokeObjectURL(uploadPreviewUrl.value)
    uploadPreviewUrl.value = null
  }
}

// 提交中不允许用遮罩误关（请求在途时清空状态会让结果无处可去）
function onUploadBackdrop() {
  if (!uploadBusy.value) closeUpload()
}

function closeUpload() {
  revokeUploadPreview()
  uploadOpen.value = false
  uploadFile.value = null
  uploadNote.value = ''
  uploadError.value = ''
}

async function submitUpload() {
  if (!uploadFile.value || uploadBusy.value) return
  if (uploadNote.value.length > GALLERY_NOTE_MAX) return
  uploadBusy.value = true
  uploadError.value = ''
  try {
    const created = await uploadGalleryImage(uploadFile.value, uploadNote.value.trim())
    // 只有当前 Tab 会显示它时才插进列表（'generate' / 'edit' Tab 下插进去是错的）
    if (activeSource.value === '' || activeSource.value === 'upload') {
      items.value.unshift(created)
      await loadThumb(created)
    }
    closeUpload()
  } catch (e) {
    uploadError.value = e.message || '上传失败'
  } finally {
    uploadBusy.value = false
  }
}

// ---- 改备注（Spec16 §7.2f）----

// 与 onUploadBackdrop 同口径：保存中不允许用遮罩误关
function onNoteBackdrop() {
  if (!noteBusy.value) noteEdit.value = null
}

function openNoteEdit(item) {
  noteEdit.value = item
  noteDraft.value = item.note || ''
  noteError.value = ''
}

async function saveNote() {
  if (noteBusy.value || !noteEdit.value) return
  if (noteDraft.value.length > GALLERY_NOTE_MAX) return
  noteBusy.value = true
  noteError.value = ''
  const id = noteEdit.value.id
  try {
    const updated = await updateGalleryNote(id, noteDraft.value.trim())
    // 只就地合并 note：服务端返回的项不含 objectUrl，整项替换会把缩略图打空
    const i = items.value.findIndex((x) => x.id === id)
    if (i !== -1) items.value[i] = { ...items.value[i], note: updated.note }
    noteEdit.value = null
    noteDraft.value = ''
  } catch (e) {
    noteError.value = e.message || '保存失败'
  } finally {
    noteBusy.value = false
  }
}
```

- `onBeforeUnmount` 里在既有 `releaseThumbs()` 旁**加一行 `revokeUploadPreview()`**。
- `onKeydown` 的 Esc 栈序改为（两个新弹窗只可能从作品网格打开，恒在最上层）：

```js
function onKeydown(e) {
  if (e.key !== 'Escape') return
  if (noteEdit.value) onNoteBackdrop()            // 保存中不关
  else if (uploadOpen.value) onUploadBackdrop()   // 提交中不关
  else if (wikiPrevFull.value) wikiPrevFull.value = ''
  else if (promptOverlay.value) promptOverlay.value = null
  else if (lightbox.value) lightbox.value = null
}
```

**（h）改动 3：`refreshStyle()` 的提示语**

```js
async function refreshStyle() {
  if (wikiBusy.value) return
  wikiBusy.value = true
  wikiError.value = ''
  wikiNotice.value = ''
  try {
    const d = await refreshWikiStyle()
    if (d.updated) {
      wiki.value = {
        ...wiki.value,
        style: d.style,
        prev_style: d.prev_style,
        style_updated_at: d.style_updated_at
      }
      // Spec16：不再播报「已根据 N 张作品更新风格」——风格文本就在同一 Block 里，变了看得见。
      // 只保留用户没有别的地方能看到的警示；两句都没有 → 不显示任何提示。
      let msg = ''
      if (d.upload_failed) msg = `${d.upload_failed} 张上传图分析失败，可再次点击重试`
      if (d.pending_count > 0) msg += `${msg ? '，' : ''}还有 ${d.pending_count} 张作品未纳入`
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

> `d.used_count` 与 `d.upload_analyzed` 现在**前端不再读取**，但后端响应**保留**（§2）。

**（i）不变的部分**：Tab 切换与 `load()`、`loadThumb` / `releaseThumbs`、下载、分享 / 撤销分享、删除、大图 overlay、`promptOverlay` 全文弹窗的结构与样式、Spec13 的 `wikiPrevFull` 弹窗、编辑风格 textarea、`loadWiki()` 并发编排——**全部不变**。

### 7.3 样式约定

```css
/* ---------- 上传 / 备注（Spec16 §7.3）---------- */

/* 复用 main.css 的 .gallery-lightbox / .gallery-lightbox-inner。
   ⚠️ 写成两级选择器（.gallery-lightbox-inner.gallery-xxx，特异性 0,2,0）才能**确定地**
   压过全局的 `.gallery-lightbox-inner { max-width: 90%; display:flex; gap:12px }`（0,1,0）——
   只写单类（0,1,0）与它**特异性相同**，谁赢取决于打包顺序（main.css 与 scoped 样式的注入次序
   不是本 Spec 的契约）。既有 `.prompt-overlay` 用的是单类，属于该顺序恰好成立的既有事实，
   本 Spec 不依赖它。 */
.gallery-lightbox-inner.gallery-upload-dialog,
.gallery-lightbox-inner.gallery-note-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 480px;   /* 比全文弹窗（640px）窄：这里没有长文本要读 */
  max-height: 90%;
  width: 100%;
  padding: 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.gallery-dialog-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 点击选图区（结构对齐 CommunityPanel 的 .community-upload-box，但不做拖拽，Spec16 §2） */
.gallery-upload-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px;
  min-height: 160px;
  background: var(--bg-input);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}

.gallery-upload-box:hover {
  border-color: var(--purple-500);
}

.gallery-file-input {
  display: none;
}

.gallery-upload-icon { font-size: 28px; }
.gallery-upload-title { font-size: 14px; color: var(--text-primary); }
.gallery-upload-sub,
.gallery-upload-replace { font-size: 12px; color: var(--text-muted); }

/* ⚠️ 必须用两级选择器：main.css 的全局规则 `.gallery-lightbox-inner img`
   （特异性 0,1,1，含 max-height:80vh + box-shadow）压不过单类选择器（0,1,0）。
   不这么写，预览图会顶到 80vh 并带上大图阴影。 */
.gallery-lightbox-inner .gallery-upload-preview {
  max-width: 100%;
  max-height: 240px;
  object-fit: contain;
  border-radius: var(--radius-lg);
  box-shadow: none;
}

.gallery-note-input {
  display: block;
  width: 100%;
  padding: 10px 12px;
  resize: vertical;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.6;
}

.gallery-note-input:focus {
  outline: none;
  border-color: var(--purple-500);
}

.gallery-note-count {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  text-align: right;
}

/* Tab 行右对齐（Spec16 §7.2b） */
.gallery-upload-btn {
  margin-left: auto;
}
```

```css
/* 既有规则：只加一行 flex-wrap（Spec16 §2） */
.gallery-actions {
  display: flex;
  flex-wrap: wrap;          /* ← 新增 */
  gap: 8px;
  padding: 8px 12px 12px;
}
```

- 主题口径不变（Spec10）：深紫主题下不得出现浅色面板——两个弹窗的底色是 `--bg-surface` / `--bg-input`，输入框是 `--bg-input`。
- 按钮一律既有 `btn-mini` / `btn-clear`，**不新增按钮样式**。
- `.gallery-upload-box` 是 `<label>` 包隐藏 `<input>`（与 CommunityPanel 同手法），不写 `<button>` + `ref.click()`。
- 备注 `textarea` 用 `:maxlength="GALLERY_NOTE_MAX"` **硬截断**，所以**不设** `.wiki-count.over` 那种红色超长态——第 201 个字根本打不进去，红色态是死代码。这与 CommunityPanel 的 `:maxlength="1000"` + 纯计数同口径；本文件里 `.wiki-count.over` 之所以存在，是因为风格编辑框**没有** `maxlength`（Spec12 口径，本 Spec 不动它）。

---

## 8. 配置 / 环境变量 / .gitignore

`config.py` 新增 **1 个带默认值的常量**（`os.getenv` + 兜底，与既有写法一致），放在 `# ===== 图片 / 上传 =====` 段内：

```python
GALLERY_NOTE_MAX = int(os.getenv("GALLERY_NOTE_MAX", "200"))   # 上传作品备注字数上限（Spec16）
```

- **无强制新增环境变量**；`.env` 无需改动；`.env.example` **可不改**（与 Spec15 的 4 个常量同口径：纯调参项，不进 `.env.example` 以免误导为必填）。
- `GALLERY_NOTE_MAX` 与前端 `GalleryPanel.vue` 的 `GALLERY_NOTE_MAX = 200` 是**两份同值常量**（与 Spec12 的 `WIKI_STYLE_MAX` 同口径）。改后端默认值时**必须同步改前端**，否则字数计数与后端校验会不一致——`<textarea :maxlength>` 会先挡住，但两值不等时用户体验会分叉。
- 前端常量若为 200 而后端被调到 100：`maxlength=200` 允许输入 200，提交时后端返回 `40015`，错误显示在弹窗内。
- `.gitignore` / `requirements.txt` / `package.json` **均不变**。

---

## 9. 错误码

**新增 1 个，其余全部复用。**

| 码 | 类 | 本 Spec 中的角色 |
|---|---|---|
| `40002` | 既有 `FileMissingError` | 上传空文件 / 损坏（`validate_upload`，**不变**） |
| `40003` | 既有 `UnsupportedImageTypeError` | `content_type` 不在白名单、或实际格式不是 jpeg/png/webp/gif（**不变**） |
| `40004` | 既有 `ImageTooLargeError` | 上传 > 10MB（**不变**） |
| **`40015`** | **新增 `GalleryNoteError(BadRequestError)`** | 备注 strip 后 > `GALLERY_NOTE_MAX`（200）→ `备注需在 200 字以内`；或作品不是 `source='upload'` → `只有上传的作品可以写备注`。HTTP `400` |
| `40103` | 既有 `AuthTokenError` | 未带 / 无效 token（**不变**） |
| `40403` | 既有 `GalleryItemNotFoundError` | 改备注时作品不存在 / 非本人（**不变**，不泄露存在性） |
| `61001`-`61003` | 既有上游错误 | 本 Spec 的链路**不调用任何外部 API**，不会出现 |

```python
# errors.py —— 追加到 Spec12 §9 的 WikiContentError 之后
class GalleryNoteError(BadRequestError):
    """作品备注非法（上传作品才可写备注；或备注超过 GALLERY_NOTE_MAX）。"""

    def __init__(self, message="作品备注非法"):
        super().__init__(message, code=40015)
```

- **无权限问题**：两个新接口都是普通登录用户端点，无 `40301` / `40302` 场景。
- **无新增 404 变体**：改备注复用 `40403`。

---

## 10. 日志约定

沿用 Spec.md §10 单行 JSON。**新增 1 条事件、扩展 1 条事件的字段**：

- `gallery.saved`（**扩展**）—— 既有字段 `user_id` / `source` / `prompt` 全部保留，**新增** `has_note`（布尔）。该事件由 `save_gallery_image` 打，所以**三条上传路径都会带上它**（§5.2E 的 #1 / #2 / #3）：聊天参考图与发帖新上传恒为 `false`，作品库直传按其有没有备注取值。产出作品（#4 / #5）走同一函数，`has_note` 恒为 `false`——一并带上，不需要为它们加分支。
- `gallery.note_updated`（**新增**）—— 改 / 清空备注成功。附 `user_id`、`item_id`、`has_note`（清空后为 `false`）。

**不记录备注全文**：备注是用户自写的私人文字，与 `prompt`（模型输入、既有口径是截断 200 字入日志）性质不同。**只记 `has_note`**，排障够用（"到底写没写上"）。

**不新增**：上传成功的逐条文件大小 / 尺寸日志（`gallery.saved` 已覆盖）、`images.note` 的读取日志。

---

## 11. 目录结构增量

```
Server/
  db.py             # _CREATE_IMAGES_TABLE 加 note 列
                    #   新增 _migrate_images_note()（init_db 内、_migrate_upload_wiki_used 之后调用）
                    #   _image_row_to_dict 增返 note
                    #   add_image_record(..., note=None) 增参
                    #   新增 set_image_note(image_id, note)
  gallery.py        # save_gallery_image(..., note=None) 增参 + gallery.saved 日志加 has_note
                    #   _with_url 增返 note
                    #   新增 _clean_note(note) 归一化助手
                    #   新增 create_upload(image_bytes, user_id, note, public_base) / update_note(item_id, user_id, note)
  errors.py         # 新增 GalleryNoteError(40015)
  schemas.py        # 新增 GalleryNoteUpdateRequest
  config.py         # 新增 GALLERY_NOTE_MAX = 200
  main.py           # 新增 POST /api/gallery、PUT /api/gallery/{item_id}/note
frontend/src/
  views/GalleryPanel.vue   # 改动 1（.wiki-hint 文案）+ 改动 3（refreshStyle 提示语）
                           #   + .gallery-upload-btn 按钮 + 上传/改备注 2 个弹窗
                           #   + itemText() 显示逻辑 + .gallery-actions{flex-wrap} + 新样式
  api/chatApi.js           # 新增 uploadGalleryImage() / updateGalleryNote()
  assets/styles/main.css   # 仅 .gallery-actions 加 flex-wrap: wrap
Server/static/             # 前端构建产物（npm run build 后同步，与既有提交口径一致）
specs/Spec16.md            # 本文件
```

> `gallery.py` 仍是"拿到 `user_id` 就干活"的业务模块；`main.py` 只做参数解析、调模块、套统一响应壳。`note` 的校验两条路径都放在业务层（`gallery._clean_note`，被 `create_upload` 与 `update_note` 共用），路由层不做——与 Spec12 §6.1 同口径。

---

## 12. 实施顺序（里程碑）

1. **B1 数据层**：`_CREATE_IMAGES_TABLE` 加 `note` 列；`_migrate_images_note()` + `init_db()` 调用点；`_image_row_to_dict` 增 `note`；`add_image_record(..., note=None)`；新增 `set_image_note()`。
2. **B2 业务层**：`errors.GalleryNoteError`；`config.GALLERY_NOTE_MAX`；`gallery.save_gallery_image` 增参 + `_with_url` 增返 `note`；新增 `_clean_note()` 归一化助手 + `create_upload()` / `update_note()`（含 `gallery.note_updated` 日志）。
3. **B3 接口层**：`schemas.GalleryNoteUpdateRequest`；`main.py` 两个新路由（multipart 读取 + `validate_upload` + 调业务层）。
4. **F1 前端 API**：`chatApi.js` 两个函数。
5. **F2 前端界面**：`GalleryPanel.vue` —— `itemText()` 与卡片说明位 → `.gallery-upload-btn` + 上传弹窗 → 备注按钮 + 改备注弹窗 → `.gallery-actions{flex-wrap}` + 新样式 → **改动 1** 文案 → **改动 3** 提示语 → Esc 栈序与 `onBeforeUnmount` 的 revoke。
6. **A1 构建与验收**：`cd frontend && npm run build` → 同步 `Server/static/` → 按 §13 逐条走查。

> B1→B2→B3 有依赖，须顺序执行；F1 与 B1~B3 无依赖，可并行；**F2 依赖 F1**；**A1 必须在 F2 之后**。

---

## 13. 验收用例

| # | 操作 | 期望 |
|---|---|---|
| 1 | 打开「我的作品」页 | Tab 行右侧有「上传作品」按钮；按钮右对齐；窄屏换行时独占一行 |
| 2 | 点「上传作品」→ 未选图直接看「提交」 | 「提交」置灰（`!uploadFile`）；「取消」可用 |
| 3 | 选一张 jpg | 弹窗内出现预览图，高度 ≤240px、**无大图阴影**（验证 §7.3 的两级选择器）；文案变为「点击可更换图像」 |
| 4 | 承上，选图后直接提交（不填备注） | `200`；新作品出现在列表**最前面**（当前 Tab 为「全部」或「上传」时）；卡片类型标签为「上传」；**说明位为空**（`note` 与 `prompt` 都为 null）；`note: null` 入库 |
| 5 | 选图 + 填备注「2019 年某品牌包装方案」→ 提交 | 新作品卡片说明位显示**该备注**（与文生图卡片显示 prompt 的位置、字号、2 行截断完全一致）；点击说明行 → 全文弹窗显示备注全文，可复制 |
| 6 | 当前 Tab 切到「文生图」，再点「上传作品」提交 | `200`，但**新作品不出现在当前列表**（它是上传作品）；切回「上传」Tab 后能看到 |
| 7 | 备注填 201 字 | 前端 `maxlength=200` 挡住（根本打不进第 201 字）；用 devtools 绕过前端直接 `PUT` 201 字 → `40015`，提示「备注需在 200 字以内」 |
| 8 | 上传一张 .txt 改名为 .png | `40003`（`validate_upload` 的实际格式判定），错误显示在**弹窗内**（`uploadError`），弹窗不关闭 |
| 9 | 上传一张 12MB 的 jpg | `40004`；错误显示在弹窗内；弹窗不关闭，已选的图仍在 |
| 10 | 上传一张 gif | 正常入库；「上传」Tab 里可见；可写备注 |
| 11 | 上传弹窗 / 改备注弹窗开着时按 Esc | 对应弹窗关闭；**底层**若有开着的全文弹窗 / 大图 overlay，需再按一次才关（栈序正确） |
| 12 | 点「提交」（或「保存」）后立刻按 Esc / 点遮罩 | **对应的弹窗不关闭**（`uploadBusy` / `noteBusy` 期间不允许误关，两个弹窗口径一致）；请求完成后按状态正常关闭 |
| 13 | 选图 A → 换成图 B | 预览变成 B；A 的 objectURL 已 revoke（无内存泄漏） |
| 14 | 上传过程中点「取消」 | 置灰不可点 |
| 15 | 关闭上传弹窗后再打开 | 预览、备注、错误全部清空；previous objectURL 已 revoke |
| 16 | 点某张**上传作品**卡片上的「加备注」 | 弹窗打开，textarea 为空（该项 `note` 为 null）；标题为「备注」 |
| 17 | 承上填「参考某海报构图」→ 保存 | `200`；**该卡片缩略图仍在**（验证 §7.2g 的"只合并 note"），说明位变成新备注；按钮文案变为「改备注」 |
| 18 | 点某张**有备注**的上传作品 → 「改备注」→ 清空 textarea → 保存 | `200`，`note: null`；卡片说明位变空；按钮文案变回「加备注」 |
| 19 | 点某张**文生图作品**的卡片 | **没有**「加备注 / 改备注」按钮（`v-if="item.source === 'upload'"`）；说明位仍显示原始 prompt，一字不改 |
| 20 | 直接 `PUT /api/gallery/{文生图作品id}/note` | `40015`，提示「只有上传的作品可以写备注」；该作品 `prompt` **不变** |
| 21 | **两条既有的上传路径**：（a）在聊天里上传一张图（`/api/images`）；（b）发帖时选「新上传」传一张图（`/api/community`）→ 回到作品库 | 两张图都在「上传」Tab 可见、**说明位为空**（`note` 与 `prompt` 均为 null），但**都有**「加备注」按钮；点它写备注 → 保存成功。两个既有接口的请求/响应**一字未改** |
| 22 | `PUT /api/gallery/{他人作品id}/note` | `40403`（不泄露存在性）；他人作品的 `note` 不变 |
| 23 | `PUT /api/gallery/{不存在的id}/note` | `40403` |
| 24 | 未带 token 调 `POST /api/gallery` 与 `PUT /api/gallery/{id}/note` | 均 `401`（`40103`） |
| 25 | 上传作品后，点「基于我的新作品更新风格」 | Spec15 行为**完全不变**：新上传的图进入待考虑队列并被视觉 QA 分析；**备注不参与**（日志/材料里看不到备注文字） |
| 26 | 上传作品 → 写备注 → 再点「更新风格」 | 该图**不会**因为"备注变了"被重新分析（`wiki_used` 未变）——这是预期行为（§3 已知限制） |
| 27 | 上传作品后**删掉**它 | 记录与 `gallery/` 文件一并删除（Spec5 既有行为不变）；`shares` 级联失效 |
| 28 | 管理员删除某用户 | 该用户的作品（含带备注的）记录与物理文件随之删除；其他用户不受影响 |
| 29 | 上传作品后看**调用统计页**（Spec4 / Spec11） | 四类计数**均不变**（上传与改备注都不调用模型） |
| 30 | **改动 1**：看「个人作品风格」Block 的提示行 | 文案逐字为「更新会逐张分析个人作品（之前已分析过则不会分析），请耐心等待」；12px、`--text-muted`，样式不变 |
| 31 | **改动 3**：全部作品都成功纳入（`upload_failed=0`、`pending_count=0`）后点更新 | **不显示任何提示**（`wikiNotice` 为空串）；风格文本照常刷新 |
| 32 | **改动 3**：有 2 张上传图分析失败、且 `pending_count=3`，点更新 | 提示为「2 张上传图分析失败，可再次点击重试，还有 3 张作品未纳入」；**不含**「已根据 N 张作品更新风格」字样 |
| 33 | **改动 3**：只有 `pending_count=5`（无失败） | 提示为「还有 5 张作品未纳入」（**不以逗号开头**） |
| 34 | 承上，接口响应 | `data.used_count` / `data.upload_analyzed` **仍在**（后端未删字段），只是前端不显示 |
| 35 | **回归**：`POST /api/wiki/style/refresh` 的 `analysis_failed` 分支 | 仍 `window.alert('上传作品分析失败，本次没有可用的新材料，请稍后重试')` |
| 36 | **回归**：`GET /api/gallery` 的响应 | 每项都多一个 `note` 字段；既有 `id` / `source` / `url` / `prompt` / `created_at` / `share` 一个不少、取值不变 |
| 37 | **回归**：分享链接页（Spec9） | 页面**不显示**备注（与不显示 prompt 一致）；分享/撤销分享功能不变 |
| 38 | **回归**：把作品分享到社区（Spec9） | 帖子只有图 + 帖子文字；**不显示**备注 |
| 39 | **存量库迁移**：拿一个 Spec15 时期的 `artcn.db`（无 `note` 列），启动后端 | 日志出现一次 `images.note 列已补齐`（`event: db.migrate`）；`images` 表有 `note` 列；**所有存量作品 `note` 为 NULL**（不编造回填）；作品库页一切正常 |
| 40 | 承上，**再重启一次**后端 | **不再**出现 `db.migrate` 日志（幂等）；期间写过的备注**不被清掉** |
| 41 | **全新库**：删掉 `artcn.db` 后启动 | 由 `_CREATE_IMAGES_TABLE` 直接带 `note` 列；**不出现** `db.migrate` 事件（`wiki_used` 与 `note` 两条补列迁移都不触发）；上传/改备注全链路正常。注：`wiki.upload_migrated`（Spec15）仍会出现一次且 `affected=0`，那是既有行为，与本 Spec 无关 |
| 42 | 样式回归 | 6 个按钮的上传作品卡片内，按钮**换行排列不溢出**（`.gallery-actions{flex-wrap}`）；深紫主题下两个弹窗**无白底**；输入框、按钮沿用既有样式 |
| 43 | 键盘 / 可访问性 | 两个弹窗的 `<label>` 点击能唤起文件选择（`<input>` 是 `display:none` 的 `<label>` 子元素） |

> 验收时明确排除：备注参与风格归纳 / 备注进分享页与社区 / 生成作品写备注 / 多图批量上传 / 拖拽上传 / 备注搜索筛选 / 上传时图片编辑 / 存量备注回填 / 提示语配置化 / `/api/images` 支持 note。
