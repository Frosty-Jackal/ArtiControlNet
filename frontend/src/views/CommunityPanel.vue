<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>社区</h2>
      <div class="community-head-actions">
        <button class="btn-mini" @click="openCreate">发帖</button>
        <button class="btn-clear" @click="emit('close')">返回聊天</button>
      </div>
    </div>
    <p class="admin-tip">
      当前登录：{{ auth.username }} · 社区对所有人可见 · 单图 + 文字
    </p>

    <p v-if="error" class="login-error">{{ error }}</p>

    <!-- 空态 / 瀑布流（Spec9 §2.1） -->
    <div v-if="!loading && posts.length === 0" class="gallery-empty">还没有帖子，来发第一帖吧</div>
    <div v-else class="community-grid">
      <button
        v-for="p in posts"
        :key="p.id"
        class="community-card"
        @click="openPost(p)"
      >
        <img
          v-if="p.objectUrl"
          :src="p.objectUrl"
          class="community-thumb"
          :alt="'帖子 ' + p.id"
          loading="lazy"
        />
        <div v-else class="community-thumb community-thumb-empty">…</div>
        <div class="community-card-body">
          <div class="community-author-row">
            <span class="community-author">{{ p.author }}</span>
            <span v-if="p.author_is_admin" class="community-admin-badge">管理员</span>
          </div>
          <p class="community-summary">{{ p.text }}</p>
        </div>
      </button>
    </div>

    <!-- 帖子弹窗：大图 + 全文 + 作者 + 时间 + 赞/踩 + 删除（作者或管理员） -->
    <div v-if="current" class="gallery-lightbox" @click.self="current = null">
      <div class="community-modal">
        <img :src="current.objectUrl" class="community-modal-img" :alt="'帖子 ' + current.id" />
        <div class="community-modal-body">
          <div class="community-modal-head">
            <span class="community-author">{{ current.author }}</span>
            <span v-if="current.author_is_admin" class="community-admin-badge">管理员</span>
            <span class="community-time">{{ formatTime(current.created_at) }}</span>
          </div>
          <p class="community-modal-text">{{ current.text }}</p>
          <div class="community-modal-actions">
            <button
              class="btn-mini"
              :class="{ 'feedback-on': current.my_vote === 'like' }"
              @click="vote(current, 'like')"
            >
              👍 {{ current.like_count }}
            </button>
            <button
              class="btn-mini"
              :class="{ 'feedback-on dislike': current.my_vote === 'dislike' }"
              @click="vote(current, 'dislike')"
            >
              👎 {{ current.dislike_count }}
            </button>
            <span class="community-flex"></span>
            <button v-if="canDelete(current)" class="btn-mini danger" @click="remove(current)">删除</button>
            <button class="btn-clear" @click="current = null">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 发帖弹窗：Tab 作品库选择 / 上传新图 + 文字（1~1000 字） -->
    <div v-if="showCreate" class="gallery-lightbox" @click.self="closeCreate">
      <div class="community-modal community-create">
        <div class="community-create-tabs">
          <button
            class="gallery-tab"
            :class="{ active: createTab === 'gallery' }"
            @click="createTab = 'gallery'"
          >
            从作品库选择
          </button>
          <button
            class="gallery-tab"
            :class="{ active: createTab === 'upload' }"
            @click="createTab = 'upload'"
          >
            上传新图
          </button>
        </div>

        <div class="community-create-pick">
          <div v-if="createTab === 'gallery' && !myItems.length" class="gallery-empty">
            作品库暂无作品，可先上传图片或生成
          </div>
          <div v-else-if="createTab === 'gallery'" class="community-pick-grid">
            <button
              v-for="it in myItems"
              :key="it.id"
              class="community-pick-card"
              :class="{ selected: pickedId === it.id }"
              @click="pickedId = it.id"
            >
              <img
                v-if="it.objectUrl"
                :src="it.objectUrl"
                class="community-pick-thumb"
                :alt="'作品 ' + it.id"
                loading="lazy"
              />
              <div v-else class="community-pick-thumb community-thumb-empty">…</div>
            </button>
          </div>
          <label v-else class="community-upload-box">
            <input type="file" accept="image/*" class="community-file-input" @change="onPickFile" />
            <template v-if="!previewUrl">
              <span class="community-upload-icon">📷</span>
              <span>选择图片（≤2000px，jpg/png/webp/gif）</span>
            </template>
            <img v-else :src="previewUrl" class="community-preview" alt="预览" />
          </label>
        </div>

        <textarea
          v-model="createText"
          class="community-textarea"
          :maxlength="1000"
          :placeholder="'说点什么…（' + createText.length + '/1000）'"
          rows="4"
        ></textarea>
        <p class="community-count">{{ createText.length }}/1000</p>

        <div class="community-create-foot">
          <button class="btn-mini" :disabled="!canSubmit" @click="submitPost">发布</button>
          <button class="btn-clear" @click="closeCreate">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  createCommunityPost, deletePost, fetchCommunityImage, fetchGalleryFile,
  listCommunity, listGallery, votePost
} from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const posts = ref([])
const myItems = ref([]) // 发帖弹窗「作品库选择」用
const error = ref('')
const loading = ref(false)
const current = ref(null) // 当前打开的帖子
const showCreate = ref(false)
const createTab = ref('gallery')
const pickedId = ref(null)
const createText = ref('')
const previewUrl = ref(null)
let pickedFile = null
let postObjectUrls = [] // 社区帖子缩略图 objectURL
let itemObjectUrls = [] // 发帖弹窗作品库缩略图 objectURL

function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

function canDelete(post) {
  return auth.isAdmin || post.author === auth.username
}

async function load() {
  loading.value = true
  error.value = ''
  releasePostThumbs()
  try {
    const data = await listCommunity(0, 50)
    posts.value = data.items || []
    await Promise.all(posts.value.map(loadPostThumb))
  } catch (e) {
    error.value = e.message || '加载社区失败'
  } finally {
    loading.value = false
  }
}

async function loadPostThumb(post) {
  try {
    const resp = await fetchCommunityImage(post.id)
    post.objectUrl = URL.createObjectURL(resp.data)
    postObjectUrls.push(post.objectUrl)
  } catch (e) {
    post.objectUrl = null
  }
}

function releasePostThumbs() {
  postObjectUrls.forEach((u) => URL.revokeObjectURL(u))
  postObjectUrls = []
}

// 帖子点赞/点踩：再点同一项取消；后端返回现算计数与我的选择
async function vote(post, choice) {
  const next = post.my_vote === choice ? null : choice
  error.value = ''
  try {
    const r = await votePost(post.id, next)
    post.like_count = r.like_count
    post.dislike_count = r.dislike_count
    post.my_vote = r.my_vote
  } catch (e) {
    error.value = e.message || '投票失败'
  }
}

async function remove(post) {
  if (!window.confirm('确定删除这条帖子？此操作不可撤销。')) return
  error.value = ''
  try {
    await deletePost(post.id)
    const i = posts.value.findIndex((x) => x.id === post.id)
    if (i !== -1) {
      if (posts.value[i].objectUrl) {
        URL.revokeObjectURL(posts.value[i].objectUrl)
        postObjectUrls = postObjectUrls.filter((u) => u !== posts.value[i].objectUrl)
      }
      posts.value.splice(i, 1)
    }
    if (current.value && current.value.id === post.id) current.value = null
  } catch (e) {
    error.value = e.message || '删除失败'
  }
}

function openPost(post) {
  current.value = post
}

// ---- 发帖 ----
async function openCreate() {
  showCreate.value = true
  createText.value = ''
  pickedId.value = null
  pickedFile = null
  releasePreview()
  await loadMyItems()
}

function closeCreate() {
  showCreate.value = false
  createText.value = ''
  pickedId.value = null
  pickedFile = null
  releasePreview()
  releaseItemThumbs()
}

function releasePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

async function loadMyItems() {
  error.value = ''
  try {
    const data = await listGallery()
    myItems.value = data.items || []
    await Promise.all(myItems.value.map(async (it) => {
      try {
        const resp = await fetchGalleryFile(it.id, false)
        it.objectUrl = URL.createObjectURL(resp.data)
        itemObjectUrls.push(it.objectUrl)
      } catch (e) {
        it.objectUrl = null
      }
    }))
  } catch (e) {
    error.value = e.message || '加载作品库失败'
  }
}

function releaseItemThumbs() {
  itemObjectUrls.forEach((u) => URL.revokeObjectURL(u))
  itemObjectUrls = []
  myItems.value = []
}

function onPickFile(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  pickedFile = f
  releasePreview()
  previewUrl.value = URL.createObjectURL(f)
}

const canSubmit = computed(() => {
  const text = createText.value.trim()
  if (!text) return false
  if (createTab.value === 'gallery') return pickedId.value != null
  return pickedFile != null
})

async function submitPost() {
  if (!canSubmit.value) return
  error.value = ''
  try {
    await createCommunityPost({
      text: createText.value.trim(),
      galleryId: createTab.value === 'gallery' ? pickedId.value : null,
      file: createTab.value === 'upload' ? pickedFile : null
    })
    closeCreate()
    await load()
  } catch (e) {
    error.value = e.message || '发布失败'
  }
}

// Esc 关闭弹窗：先关帖子，再关发帖
function onKeydown(e) {
  if (e.key !== 'Escape') return
  if (current.value) current.value = null
  else if (showCreate.value) closeCreate()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  load()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  releasePostThumbs()
  releaseItemThumbs()
  releasePreview()
})
</script>

<style scoped>
.community-head-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.community-flex {
  flex: 1;
}

/* 瀑布流：CSS columns 多列，卡片不拆列 */
.community-grid {
  columns: 3 220px;
  column-gap: 16px;
}

.community-card {
  break-inside: avoid;
  display: block;
  width: 100%;
  margin-bottom: 16px;
  padding: 0;
  text-align: left;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  cursor: pointer;
  transition: transform var(--transition-normal), box-shadow var(--transition-normal);
}

.community-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--border-light);
}

.community-thumb {
  display: block;
  width: 100%;
  max-height: 420px;
  object-fit: cover;
  background: var(--bg-input);
}

.community-thumb-empty {
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}

.community-card-body {
  padding: 10px 12px 12px;
}

.community-author-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.community-author {
  font-size: 13px;
  font-weight: 600;
  color: var(--purple-300);
}

.community-admin-badge {
  font-size: 11px;
  padding: 0 8px;
  border-radius: var(--radius-full);
  color: var(--purple-200);
  border: 1px solid var(--purple-500);
}

.community-summary {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-all;
}

.community-time {
  font-size: 12px;
  color: var(--text-muted);
}

/* 帖子弹窗 */
.community-modal {
  max-width: 720px;
  width: 100%;
  max-height: 90%;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.community-modal-img {
  display: block;
  width: 100%;
  max-height: 60vh;
  object-fit: contain;
  background: var(--bg-input);
}

.community-modal-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.community-modal-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.community-modal-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}

.community-modal-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}

/* 发帖弹窗 */
.community-create {
  max-width: 620px;
}

.community-create-tabs {
  display: flex;
  gap: 8px;
  padding: 14px 16px 0;
}

.community-create-pick {
  padding: 14px 16px;
  min-height: 120px;
}

.community-pick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
  gap: 10px;
  max-height: 240px;
  overflow-y: auto;
}

.community-pick-card {
  padding: 0;
  border: 2px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--bg-input);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}

.community-pick-card.selected {
  border-color: var(--purple-500);
  box-shadow: 0 0 0 2px rgba(168, 85, 247, 0.35);
}

.community-pick-thumb {
  display: block;
  width: 100%;
  height: 90px;
  object-fit: cover;
}

.community-upload-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  border: 1px dashed var(--border-light);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}

.community-upload-box:hover {
  border-color: var(--purple-500);
  color: var(--text-secondary);
}

.community-file-input {
  display: none;
}

.community-upload-icon {
  font-size: 28px;
}

.community-preview {
  max-width: 100%;
  max-height: 220px;
  border-radius: var(--radius-lg);
}

.community-textarea {
  display: block;
  width: calc(100% - 32px);
  margin: 0 16px;
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

.community-textarea:focus {
  outline: none;
  border-color: var(--purple-500);
}

.community-count {
  margin: 4px 16px 0;
  font-size: 12px;
  color: var(--text-muted);
  text-align: right;
}

.community-create-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px 16px;
}
</style>
