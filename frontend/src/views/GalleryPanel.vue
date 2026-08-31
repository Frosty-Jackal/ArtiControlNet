<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>我的作品</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>
    <p class="admin-tip">
      当前登录：{{ auth.username }} · 我的作品仅本人可见
    </p>

    <!-- 来源筛选 Tab（Spec5 §7） -->
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
          :title="item.prompt || '查看大图'"
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
        <p
          v-if="item.prompt"
          class="gallery-prompt"
          title="点击查看全文"
          @click="promptOverlay = item"
        >{{ item.prompt }}</p>
        <div class="gallery-actions">
          <button class="btn-mini" @click="openLightbox(item)">查看大图</button>
          <button class="btn-mini" @click="download(item)">下载</button>
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

    <!-- 全文 prompt overlay（Spec6 §5.3）：点击卡片提示词打开，可看全文 + 复制 -->
    <div v-if="promptOverlay" class="gallery-lightbox" @click.self="promptOverlay = null">
      <div class="gallery-lightbox-inner prompt-overlay">
        <p class="prompt-overlay-text">{{ promptOverlay.prompt }}</p>
        <div class="gallery-lightbox-bar">
          <button class="btn-mini" @click="copyPrompt(promptOverlay.prompt)">
            {{ copied ? '已复制 ✓' : '复制全文' }}
          </button>
          <button class="btn-clear" @click="promptOverlay = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { createShare, deleteGalleryItem, fetchGalleryFile, listGallery, revokeShare } from '../api/chatApi'
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

const activeSource = ref('')
const items = ref([])
const error = ref('')
const loading = ref(false)
const busyId = ref(null)
const lightbox = ref(null)
const promptOverlay = ref(null) // 全文 prompt 弹窗：当前展示的作品记录（Spec6 §5.3）
const copied = ref(false)
let objectUrls = [] // 统一回收，避免内存泄漏

const emptySuffix = computed(() => {
  const t = TABS.find((x) => x.value === activeSource.value)
  return t && t.value ? `「${t.label}」` : ''
})

function sourceLabel(src) {
  return SOURCE_LABELS[src] || src || '未知'
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
    await Promise.all(items.value.map((it) => loadThumb(it)))
  } catch (e) {
    error.value = e.message || '加载作品失败'
  } finally {
    loading.value = false
  }
}

async function loadThumb(item) {
  try {
    const resp = await fetchGalleryFile(item.id, false)
    item.objectUrl = URL.createObjectURL(resp.data)
    objectUrls.push(item.objectUrl)
  } catch (e) {
    item.objectUrl = null
  }
}

function releaseThumbs() {
  objectUrls.forEach((u) => URL.revokeObjectURL(u))
  objectUrls = []
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
      if (items.value[i].objectUrl) {
        URL.revokeObjectURL(items.value[i].objectUrl)
        objectUrls = objectUrls.filter((u) => u !== items.value[i].objectUrl)
      }
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
}

async function copyPrompt(text) {
  await copyText(text)
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

onMounted(load)
onBeforeUnmount(releaseThumbs)
</script>

<style scoped>
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

.prompt-overlay {
  max-width: 640px;
  width: 100%;
}

.prompt-overlay-text {
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

.gallery-actions {
  display: flex;
  gap: 8px;
  padding: 8px 12px 12px;
}

</style>
