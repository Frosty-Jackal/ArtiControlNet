<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>我的作品</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>
    <p class="admin-tip">
      当前登录：{{ auth.username }} · 我的作品仅本人可见
    </p>

    <!-- 个人作品风格（Spec12 §7.2）：整页的语境，先于作品网格出现 -->
    <div class="wiki-block">
      <div class="wiki-head">
        <h3 class="wiki-title">个人作品风格</h3>
        <span v-if="wiki.style_updated_at" class="wiki-time">
          更新于 {{ formatTime(wiki.style_updated_at) }}
        </span>
      </div>

      <p v-if="wikiError" class="login-error">{{ wikiError }}</p>

      <!-- 风格文本按【…】标题切块渲染（Spec15 §7.2c）：两段式新格式 → 两块；
           Spec12 的单段旧文本 → 一个无标题块（外观不变） -->
      <div v-if="wikiBlocks.length" class="wiki-style">
        <div v-for="(b, i) in wikiBlocks" :key="i" class="wiki-seg">
          <h4 v-if="b.title" class="wiki-seg-title">{{ b.title }}</h4>
          <p v-if="b.body" class="wiki-seg-body">{{ b.body }}</p>
        </div>
      </div>
      <p v-else class="wiki-empty">还没有风格记录，点下面的按钮从你的作品里归纳一版。</p>

      <!-- 「上次更新前」：次要信息，小字 + 低对比度 + 折叠两行；点击看全文（Spec13） -->
      <p
        v-if="wiki.prev_style"
        class="wiki-prev"
        title="点击查看全文"
        @click="wikiPrevFull = wiki.prev_style"
      >
        上次更新前：{{ wiki.prev_style }}
      </p>

      <p v-if="wikiNotice" class="admin-notice">{{ wikiNotice }}</p>

      <div class="wiki-actions">
        <button class="btn-mini" :disabled="wikiBusy" @click="refreshStyle">
          {{ wikiBusy ? '分析中…' : '基于我的新作品更新风格' }}
        </button>
        <button v-if="!wikiEditing" class="btn-mini" @click="openEdit">编辑</button>
      </div>
      <!-- Spec21 §7.6：这句话是"分析中"的说明，与按钮上的「分析中…」同一个生命周期。
           常驻展示是噪音；分析结束（成功或失败）后它还留着就是死字。
           wikiBusy 由 refreshStyle() 自己置位与复位，本行不改它一个字。 -->
      <p v-if="wikiBusy" class="wiki-hint">
        更新会逐张分析个人作品（之前已分析过则不会分析），请耐心等待
      </p>

      <!-- 编辑态：就地改风格，保存即覆盖（旧版落进「上次更新前」） -->
      <div v-if="wikiEditing" class="wiki-edit">
        <textarea
          v-model="wikiDraft"
          class="wiki-textarea"
          rows="6"
          placeholder="写下你的个人作品风格…"
        ></textarea>
        <div class="wiki-edit-foot">
          <span class="wiki-count" :class="{ over: wikiDraft.length > WIKI_STYLE_MAX }">
            {{ wikiDraft.length }} / {{ WIKI_STYLE_MAX }}
          </span>
          <div class="wiki-edit-btns">
            <button
              class="btn-mini"
              :disabled="wikiDraft.length > WIKI_STYLE_MAX || wikiSaving"
              @click="saveStyle"
            >
              保存
            </button>
            <button class="btn-clear" @click="cancelEdit">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 来源筛选 Tab（Spec5 §7）+ 直传入口（Spec16 §7.2b） -->
    <div class="gallery-tabs">
      <button
        v-for="tab in TABS"
        :key="tab.value"
        class="gallery-tab"
        :class="{ active: tab.value === activeSource }"
        @click="switchTab(tab.value)"
      >
        {{ tab.label }}
      </button>
      <button class="btn-mini gallery-upload-btn" @click="openUpload">上传作品</button>
    </div>

    <p v-if="error" class="login-error">{{ error }}</p>

    <!-- 空态 -->
    <div v-if="!loading && items.length === 0" class="gallery-empty">
      还没有{{ emptySuffix }}作品
    </div>

    <!-- 网格 -->
    <div v-else class="gallery-grid">
      <div v-for="item in items" :key="item.id" class="gallery-card">
        <button
          v-if="item.objectUrl"
          class="gallery-thumb-btn"
          :title="itemText(item) || '查看大图'"
          @click="openLightbox(item)"
        >
          <img :src="item.objectUrl" class="gallery-thumb" alt="作品缩略图" loading="lazy" />
        </button>
        <div v-else class="gallery-thumb gallery-thumb-empty">…</div>
        <div class="gallery-meta">
          <span class="gallery-source" :class="'src-' + item.source">
            {{ sourceLabel(item.source) }}
          </span>
          <span class="gallery-time">{{ formatTime(item.created_at) }}</span>
        </div>
        <!-- 说明位：上传作品显示备注，生成/绘图作品显示原始 prompt（Spec16 §7.2c） -->
        <p
          v-if="itemText(item)"
          class="gallery-prompt"
          title="点击查看全文"
          @click="promptOverlay = item"
        >{{ itemText(item) }}</p>
        <div class="gallery-actions">
          <button class="btn-mini" @click="openLightbox(item)">查看大图</button>
          <button class="btn-mini" @click="download(item)">下载</button>
          <!-- 备注是上传作品对位 prompt 的字段，只有它能写（Spec16 §7.2d） -->
          <button
            v-if="item.source === 'upload'"
            class="btn-mini"
            :disabled="busyId === item.id"
            @click="openNoteEdit(item)"
          >
            {{ item.note ? '改备注' : '加备注' }}
          </button>
          <!-- Spec9：临时分享链接（7 天有效，可撤销；链接绝对 URL 供外部免登录访问） -->
          <button
            v-if="!item.share"
            class="btn-mini"
            :disabled="busyId === item.id"
            @click="shareItem(item)"
          >
            分享
          </button>
          <template v-else>
            <button class="btn-mini" title="复制免登录链接" @click="copyShare(item.share.url)">复制链接</button>
            <button
              class="btn-mini danger"
              :disabled="busyId === item.id"
              @click="revokeItem(item)"
            >
              撤销分享
            </button>
          </template>
          <button
            class="btn-mini danger"
            :disabled="busyId === item.id"
            @click="remove(item)"
          >
            删除
          </button>
        </div>
      </div>
    </div>

    <!-- 大图 overlay -->
    <div v-if="lightbox" class="gallery-lightbox" @click.self="lightbox = null">
      <div class="gallery-lightbox-inner">
        <img :src="lightbox.objectUrl" :alt="'作品 ' + lightbox.id" />
        <div class="gallery-lightbox-bar">
          <span>{{ sourceLabel(lightbox.source) }} · {{ formatTime(lightbox.created_at) }}</span>
          <button class="btn-clear" @click="lightbox = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 全文 prompt / 备注 overlay（Spec6 §5.3，Spec16 起同位置显示两者之一）：
         点击卡片说明行打开，可看全文 + 复制 -->
    <div v-if="promptOverlay" class="gallery-lightbox" @click.self="promptOverlay = null">
      <div class="gallery-lightbox-inner prompt-overlay">
        <p class="prompt-overlay-text">{{ itemText(promptOverlay) }}</p>
        <div class="gallery-lightbox-bar">
          <button class="btn-mini" @click="copyPrompt(itemText(promptOverlay))">
            {{ copied ? '已复制 ✓' : '复制全文' }}
          </button>
          <button class="btn-clear" @click="promptOverlay = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 上传作品弹窗（Spec16 §7.2e）：点击选图 + 可选备注，不写 storage/、不产生 task -->
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

    <!-- 改备注弹窗（Spec16 §7.2f）：清空即删除备注 -->
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
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  createShare, deleteGalleryItem, fetchGalleryFile, getWiki, listGallery,
  refreshWikiStyle, revokeShare, updateGalleryNote, updateWikiStyle, uploadGalleryImage
} from '../api/chatApi'
import { attachObjectUrls, releaseObjectUrl } from '../composables/useAuthedImage'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const TABS = [
  { value: '', label: '全部' },
  { value: 'upload', label: '上传' },
  { value: 'generate', label: '文生图' },
  { value: 'edit', label: '图文生图' }
]

const SOURCE_LABELS = { upload: '上传', generate: '文生图', edit: '图文生图' }

const WIKI_STYLE_MAX = 2000 // 与后端 config.WIKI_STYLE_MAX 同值（Spec12 §7.2）
const GALLERY_NOTE_MAX = 200 // 与后端 config.GALLERY_NOTE_MAX 同值（Spec16）

const activeSource = ref('')
const items = ref([])
const error = ref('')
const loading = ref(false)
const busyId = ref(null)
const lightbox = ref(null)
const promptOverlay = ref(null) // 全文 prompt 弹窗：当前展示的作品记录（Spec6 §5.3）
const copied = ref(false)

// ---- 上传作品 / 改备注弹窗（Spec16 §7.2g）----
const uploadOpen = ref(false)
const uploadFile = ref(null)
const uploadNote = ref('')
const uploadPreviewUrl = ref(null)   // objectURL，关闭/换图时必须 revoke
const uploadBusy = ref(false)
const uploadError = ref('')

const noteEdit = ref(null)           // 当前编辑的作品项；非 null = 弹窗打开
const noteDraft = ref('')
const noteBusy = ref(false)
const noteError = ref('')

// ---- 个人作品风格（Spec12 §7.2）----
const wiki = ref({ style: '', prev_style: null, style_updated_at: null })
const wikiError = ref('')
const wikiNotice = ref('')
const wikiBusy = ref(false)     // 等 LLM 期间按钮置灰（挡住连点）
const wikiEditing = ref(false)
const wikiDraft = ref('')
const wikiSaving = ref(false)
const wikiPrevFull = ref('')       // 「上次更新前」全文弹窗的文本快照；非空 = 弹窗打开（Spec13）
const wikiPrevCopyFail = ref(false)

const emptySuffix = computed(() => {
  const t = TABS.find((x) => x.value === activeSource.value)
  return t && t.value ? `「${t.label}」` : ''
})

// 风格文本按【…】标题切块（Spec15 §7.2c）：两段式新格式 → 两个块；
// Spec12 的单段旧文本 → 一个无标题块（外观不变）。纯展示层，不动存储格式。
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
    .map((b) => ({ title: b.title, body: b.body.join('\n').trim() }))
    .filter((b) => b.title || b.body)
})

function sourceLabel(src) {
  return SOURCE_LABELS[src] || src || '未知'
}

// 卡片上的说明文字：上传作品显示备注，生成/绘图作品显示原始 prompt（Spec16 §7.2c）。
// 两者互斥（上传作品 prompt 恒为 null，生成作品 note 恒为 null），故 || 不会歧义。
function itemText(item) {
  return (item && (item.note || item.prompt)) || ''
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString()
}

function switchTab(v) {
  activeSource.value = v
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  releaseThumbs()
  try {
    const data = await listGallery(activeSource.value)
    items.value = data.items || []
    await attachObjectUrls(items.value, (id) => fetchGalleryFile(id, false))
  } catch (e) {
    error.value = e.message || '加载作品失败'
  } finally {
    loading.value = false
  }
}

async function loadThumb(item) {
  await attachObjectUrls([item], (id) => fetchGalleryFile(id, false))
}

// 释放走共享缓存的引用计数（Spec17 §7.1）：同一张图在别处还挂着时不会被 revoke
function releaseThumbs() {
  items.value.forEach((it) => releaseObjectUrl(it))
}

function download(item) {
  error.value = ''
  fetchGalleryFile(item.id, true)
    .then((resp) => {
      const blobUrl = URL.createObjectURL(resp.data)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = `artcn_${item.id}${extFromType(resp.data.type)}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(blobUrl), 2000)
    })
    .catch((e) => {
      error.value = e.message || '下载失败'
    })
}

function extFromType(type) {
  if (type === 'image/png') return '.png'
  if (type === 'image/webp') return '.webp'
  if (type === 'image/gif') return '.gif'
  return '.jpg'
}

async function remove(item) {
  if (!window.confirm('确定删除这张作品？此操作不可撤销。')) return
  error.value = ''
  busyId.value = item.id
  try {
    await deleteGalleryItem(item.id)
    const i = items.value.findIndex((x) => x.id === item.id)
    if (i !== -1) {
      releaseObjectUrl(items.value[i]) // 释放缓存引用后再摘掉卡片
      items.value.splice(i, 1)
    }
    if (lightbox.value && lightbox.value.id === item.id) lightbox.value = null
    if (promptOverlay.value && promptOverlay.value.id === item.id) promptOverlay.value = null
  } catch (e) {
    error.value = e.message || '删除失败'
  } finally {
    busyId.value = null
  }
}

function openLightbox(item) {
  if (item.objectUrl) lightbox.value = item
}

// 复制：优先 navigator.clipboard，非安全上下文回退隐藏 textarea + execCommand（Spec9 分享链接复用）
async function copyText(text) {
  copied.value = false
  let ok = false
  try {
    await navigator.clipboard.writeText(text)
    ok = true
  } catch (e) {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      ok = document.execCommand('copy')
    } catch (e2) {
      ok = false
    }
    ta.remove()
  }
  if (ok) {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } else {
    error.value = '复制失败，请手动选择复制'
  }
  return ok // Spec13：返回值供弹窗内联提示用（调用方可忽略）
}

async function copyPrompt(text) {
  await copyText(text)
}

// 弹窗内复制：失败提示画在弹窗里（页面错误条被遮罩挡住，弹窗开着时看不见）（Spec13）
async function copyPrevStyle() {
  wikiPrevCopyFail.value = false
  const ok = await copyText(wikiPrevFull.value)
  if (!ok) wikiPrevCopyFail.value = true
}

// Spec9 §5.3：生成分享链接 → 立即复制到剪贴板（后端返回绝对 URL）
async function shareItem(item) {
  error.value = ''
  busyId.value = item.id
  try {
    const share = await createShare(item.id)
    item.share = share
    await copyText(share.url)
  } catch (e) {
    error.value = e.message || '生成分享链接失败'
  } finally {
    busyId.value = null
  }
}

async function copyShare(url) {
  await copyText(url)
}

// Spec9 §5.3：撤销分享（链接立即失效；前端仅移除本地引用）
async function revokeItem(item) {
  if (!item.share) return
  if (!window.confirm('确定撤销这条分享链接？链接将立即失效。')) return
  error.value = ''
  busyId.value = item.id
  try {
    await revokeShare(item.share.id)
    item.share = null
  } catch (e) {
    error.value = e.message || '撤销失败'
  } finally {
    busyId.value = null
  }
}

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

// ---- 改 / 清空备注（Spec16 §7.2f）----

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

// ---- 个人作品风格（Spec12 §7.2）----

// 风格加载失败只写 wikiError，不阻断作品列表渲染
async function loadWiki() {
  wikiError.value = ''
  try {
    wiki.value = await getWiki()
  } catch (e) {
    wikiError.value = e.message || '加载个人作品风格失败'
  }
}

// 基于未纳入过的作品更新风格：同步等 LLM（按钮期间置灰）
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
      // Spec16：不再播报「已根据 N 张作品更新风格」——风格文本就在同一个 Block 里，变了看得见。
      // 只保留用户没有别的地方能看到的警示（分析失败 / 未纳入）；两句都没有 → 不显示任何提示。
      // used_count / upload_analyzed 后端仍返回（接口契约不变），前端不再读。
      let msg = ''
      if (d.upload_failed) msg = `${d.upload_failed} 张上传图分析失败，可再次点击重试`
      if (d.pending_count > 0) msg += `${msg ? '，' : ''}还有 ${d.pending_count} 张作品未纳入`
      wikiNotice.value = msg
    } else if (d.reason === 'analysis_failed') {
      // 上传图全部分析失败且没有生成作品可参考 —— 点了但没有可用材料，不是错误
      window.alert('上传作品分析失败，本次没有可用的新材料，请稍后重试')
    } else {
      // 「所有作品已全部考虑到」是正常业务状态，不是错误
      window.alert('所有作品已全部考虑到')
    }
  } catch (e) {
    wikiError.value = e.message || '更新风格失败'
  } finally {
    wikiBusy.value = false
  }
}

function openEdit() {
  wikiEditing.value = true
  wikiDraft.value = wiki.value.style || ''
  wikiError.value = ''
  wikiNotice.value = ''
}

function cancelEdit() {
  wikiEditing.value = false
  wikiDraft.value = ''
}

// 手动覆盖风格：旧版自动落进「上次更新前」，属准不可逆操作 → confirm 一次
async function saveStyle() {
  const text = wikiDraft.value.trim()
  if (!text) {
    wikiNotice.value = '风格内容不能为空'
    return
  }
  if (wikiDraft.value.length > WIKI_STYLE_MAX) return
  if (!window.confirm('确定用这段文字覆盖当前的个人作品风格？原风格会存入"上次更新前"。')) return
  wikiSaving.value = true
  wikiError.value = ''
  wikiNotice.value = ''
  try {
    wiki.value = await updateWikiStyle(text)
    wikiEditing.value = false
    wikiDraft.value = ''
    wikiNotice.value = '已保存'
  } catch (e) {
    wikiError.value = e.message || '保存失败'
  } finally {
    wikiSaving.value = false
  }
}

// Esc 关闭：按栈序关最上面那层（备注 → 上传 → 风格全文 → prompt 全文 → 大图）（Spec13 / Spec16）
// 两个新弹窗只可能从作品网格打开，恒在最上层；请求在途时各自的 onXxxBackdrop 不关。
function onKeydown(e) {
  if (e.key !== 'Escape') return
  if (noteEdit.value) onNoteBackdrop()
  else if (uploadOpen.value) onUploadBackdrop()
  else if (wikiPrevFull.value) wikiPrevFull.value = ''
  else if (promptOverlay.value) promptOverlay.value = null
  else if (lightbox.value) lightbox.value = null
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // 风格与作品互不依赖，并发发起（切 Tab 只重拉作品列表，不重拉风格）
  loadWiki()
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  releaseThumbs()
  revokeUploadPreview()
})
</script>

<style scoped>
/* ---------- 个人作品风格 Block（Spec12 §7.3）---------- */

.wiki-block {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.wiki-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.wiki-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.wiki-time {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* 容器不再承担 pre-wrap，改由正文块各自承担（Spec15 §7.3） */
.wiki-style {
  margin: 0;
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-primary);
  word-break: break-word;
}

.wiki-seg + .wiki-seg {
  margin-top: 10px;
}

/* 小标题：弱于正文的 --text-primary，明显强于 --text-muted */
.wiki-seg-title {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
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

.wiki-empty {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-muted);
}

/* 上次更新前：明确是次要信息（更小字号 + 低对比度 + 折叠两行）；点击看全文（Spec13） */
.wiki-prev {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-all;
  cursor: pointer;
  transition: color var(--transition-fast);
}

.wiki-prev:hover {
  color: var(--text-secondary); /* 稍亮提示"可点"，仍明显弱于主风格的 --text-primary */
}

.wiki-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.wiki-edit {
  margin-top: 12px;
}

.wiki-textarea {
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
  transition: border-color var(--transition-normal);
}

.wiki-textarea:focus {
  outline: none;
  border-color: var(--purple-500);
}

.wiki-textarea::placeholder {
  color: var(--text-muted);
}

.wiki-edit-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
}

.wiki-count {
  font-size: 12px;
  color: var(--text-muted);
}

.wiki-count.over {
  color: #fca5a5;
  font-weight: 600;
}

.wiki-edit-btns {
  display: flex;
  gap: 8px;
}

/* ---------- 作品网格 ---------- */

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.gallery-card {
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: transform var(--transition-normal), box-shadow var(--transition-normal);
}

.gallery-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.gallery-thumb-btn {
  display: block;
  padding: 0;
  background: var(--bg-input);
  border-bottom: 1px solid var(--border-color);
}

.gallery-thumb {
  display: block;
  width: 100%;
  height: 180px;
  object-fit: cover;
}

.gallery-thumb-btn:hover .gallery-thumb {
  opacity: 0.9;
}

.gallery-thumb-empty {
  height: 180px;
  background: var(--bg-input);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-color);
}

.gallery-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px 0;
}

.gallery-source {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
}

.gallery-source.src-upload { color: var(--purple-300); border-color: var(--purple-500); }
.gallery-source.src-generate { color: #6ee7b7; border-color: #065f46; }
.gallery-source.src-edit { color: #fbbf24; border-color: #92400e; }

.gallery-time {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.gallery-prompt {
  flex: 1;
  padding: 6px 12px 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-all;
  cursor: pointer;
  transition: color var(--transition-fast);
}

.gallery-prompt:hover {
  color: var(--text-primary);
}

.prompt-overlay,
.wiki-prev-overlay {
  max-width: 640px;
  width: 100%;
}

.prompt-overlay-text,
.wiki-prev-overlay-text {
  margin: 0;
  padding: 16px;
  max-height: 60vh;
  overflow-y: auto;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 「上次更新前」全文弹窗（Spec13） */
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
  color: #fca5a5;
}

.gallery-actions {
  display: flex;
  /* Spec16：上传作品的卡片现在最多 6 个按钮，200px 的卡片里必须允许换行 */
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px 12px;
}

/* ---------- 上传 / 备注弹窗（Spec16 §7.3）---------- */

/* 复用 main.css 的 .gallery-lightbox / .gallery-lightbox-inner。
   ⚠️ 写成两级选择器（0,2,0）才能确定地压过全局 `.gallery-lightbox-inner`（0,1,0）——
   单类与它特异性相同，谁赢取决于 main.css 与 scoped 样式的注入次序（不是本文件的契约）。 */
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

/* ⚠️ 必须两级：main.css 的全局 `.gallery-lightbox-inner img`（0,1,1，含 max-height:80vh
   + 大图阴影）压不过单类选择器（0,1,0）。不这么写，预览图会顶到 80vh 并带上阴影。 */
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

.gallery-note-input::placeholder {
  color: var(--text-muted);
}

/* 纯计数：textarea 有 maxlength 硬截断，超长态打不出来，不需要红色告警态 */
.gallery-note-count {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  text-align: right;
}

/* Tab 行右对齐（.gallery-tabs 是 flex + flex-wrap，见 main.css Spec5 §7） */
.gallery-upload-btn {
  margin-left: auto;
}

</style>
