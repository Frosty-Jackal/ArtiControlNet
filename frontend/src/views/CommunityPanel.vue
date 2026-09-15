<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>社区</h2>
      <div class="community-head-actions">
        <button class="btn-mini" @click="openCreate">发帖</button>
        <button class="btn-clear" @click="emit('close')">返回聊天</button>
      </div>
    </div>
    <p v-if="error" class="login-error">{{ error }}</p>

    <!-- 空态 / 瀑布流（Spec9 §2.1）；Spec17：纯文字帖不渲染图片区，卡片自然变矮 -->
    <div v-if="!loading && posts.length === 0" class="gallery-empty">还没有帖子，来发第一帖吧</div>
    <div v-else class="community-grid">
      <button
        v-for="p in posts"
        :key="p.id"
        class="community-card"
        @click="openPost(p)"
      >
        <img
          v-if="p.image_url && p.objectUrl"
          :src="p.objectUrl"
          class="community-thumb"
          :alt="'帖子 ' + p.id"
          loading="lazy"
        />
        <div v-else-if="p.image_url" class="community-thumb community-thumb-empty">…</div>
        <div class="community-card-body">
          <div class="community-author-row">
            <span class="community-author">{{ p.author }}</span>
            <span v-if="p.author_is_admin" class="community-admin-badge">管理员</span>
          </div>
          <p class="community-summary">{{ p.text }}</p>
        </div>
      </button>
    </div>

    <!-- 帖子弹窗：大图（可选）+ 全文 + 作者 + 时间 + 赞/踩 + 评论区 + 删除（作者或管理员） -->
    <div v-if="current" class="gallery-lightbox" @click.self="closePost">
      <div class="community-modal">
        <img
          v-if="current.image_url && current.objectUrl"
          :src="current.objectUrl"
          class="community-modal-img"
          :alt="'帖子 ' + current.id"
        />
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
            <!-- 只是计数展示，不承担展开/收起：评论区就在下面，总是可见（Spec17 §7.7） -->
            <span class="comment-count">💬 评论 {{ commentCount(current) }}</span>
            <span class="community-flex"></span>
            <button v-if="canDelete(current)" class="btn-mini danger" @click="remove(current)">删除</button>
            <button class="btn-clear" @click="closePost">关闭</button>
          </div>

          <!-- 评论区（Spec17 §7.7）：固定高滚动区，自动展示全部评论 -->
          <div class="post-comments">
            <p v-if="!commentCount(current)" class="comment-empty">还没有评论，来说两句</p>
            <div v-for="c in current.comments || []" :key="c.id" class="comment-row">
              <div class="comment-main">
                <span class="comment-author">{{ c.author }}：</span>
                <span class="comment-text" :title="c.text">{{ c.text }}</span>
                <span class="comment-time">{{ formatCommentTime(c.created_at) }}</span>
              </div>
              <button
                v-if="canDeleteComment(c)"
                class="btn-mini danger comment-del"
                @click="removeComment(current, c)"
              >
                删除
              </button>
            </div>
          </div>

          <div class="comment-form">
            <input
              v-model="commentDraft"
              class="comment-input"
              :maxlength="COMMENT_MAX"
              placeholder="写评论…"
              @keydown.enter="onCommentEnter($event, current)"
            />
            <span class="comment-count">{{ commentDraft.length }}/{{ COMMENT_MAX }}</span>
            <button
              class="btn-mini"
              :disabled="!commentDraft.trim() || commentBusy"
              @click="submitComment(current)"
            >
              {{ commentBusy ? '发表中…' : '发表' }}
            </button>
          </div>
          <p v-if="commentError" class="login-error">{{ commentError }}</p>
        </div>
      </div>
    </div>

    <!-- 发帖弹窗：文字（1~1000 字）+ **可选**配图（Spec17：作品库选择 / 上传新图 / 不配图） -->
    <div v-if="showCreate" class="gallery-lightbox" @click.self="closeCreate">
      <div class="community-modal community-create">
        <div class="community-create-tabs">
          <button
            class="gallery-tab"
            :class="{ active: createTab === 'gallery' }"
            @click="toggleTab('gallery')"
          >
            从作品库选择
          </button>
          <button
            class="gallery-tab"
            :class="{ active: createTab === 'upload' }"
            @click="toggleTab('upload')"
          >
            上传新图
          </button>
        </div>
        <p class="community-create-hint">文字 1~1000 字，配图可选</p>

        <div class="community-create-pick">
          <div v-if="createTab === null" class="community-no-image">
            不配图（纯文字帖）· 再点上方任一方式即可加图
          </div>
          <div v-else-if="createTab === 'gallery' && !myItems.length" class="gallery-empty">
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
          <label
            v-else
            class="community-upload-box"
            :class="{ 'drag-over': uploadDrag }"
            @dragenter.prevent="onDragEnter"
            @dragover.prevent
            @dragleave.prevent="onDragLeave"
            @drop.prevent="onDropFile"
          >
            <input type="file" accept="image/*" class="community-file-input" @change="onPickFile" />
            <template v-if="!previewUrl">
              <span class="community-upload-icon">🖼</span>
              <span class="community-upload-title">点击选择，或把图片拖到这里</span>
              <span class="community-upload-sub">jpg / png / webp / gif，≤2000px</span>
            </template>
            <template v-else>
              <img :src="previewUrl" class="community-preview" alt="预览" />
              <span class="community-upload-replace">点击或拖拽可更换图片</span>
            </template>
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
  createComment, createCommunityPost, deleteComment, deletePost, fetchCommunityImage,
  fetchGalleryFile, listCommunity, listGallery, votePost
} from '../api/chatApi'
import { attachObjectUrls, releaseObjectUrl } from '../composables/useAuthedImage'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const COMMENT_MAX = 200 // 与后端 config.COMMENT_TEXT_MAX 同值（Spec17 §8）

const posts = ref([])
const myItems = ref([]) // 发帖弹窗「作品库选择」用
const error = ref('')
const loading = ref(false)
const current = ref(null) // 当前打开的帖子
const showCreate = ref(false)
const createTab = ref(null) // 'gallery' | 'upload' | null（null = 不配图，Spec17 §7.7）
const pickedId = ref(null)
const createText = ref('')
const previewUrl = ref(null)
const uploadDrag = ref(false) // Spec10：上传区拖拽高亮
let pickedFile = null
let dragDepth = 0 // 拖拽进出计数，避免子元素间 dragleave 抖动

// ---- 评论（Spec17 §7.7）----
const commentDraft = ref('')
const commentBusy = ref(false)
const commentError = ref('')

function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

// 评论密集，不显示年份（MM-DD HH:mm）；跨年帖子可接受的信息损失（§7.7）
function formatCommentTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function canDelete(post) {
  return auth.isAdmin || post.author === auth.username
}

// 前端只做隐藏，后端仍会独立校验并返回 40303（§7.7）
function canDeleteComment(comment) {
  return auth.isAdmin || comment.author === auth.username
}

function commentCount(post) {
  return (post && post.comments ? post.comments.length : 0)
}

async function load() {
  loading.value = true
  error.value = ''
  releasePostThumbs()
  try {
    const data = await listCommunity(0, 50)
    posts.value = data.items || []
    // 纯文字帖没有图，不浪费一次必然 404 的请求
    await attachObjectUrls(posts.value, fetchCommunityImage, {
      getId: (p) => (p.image_url ? p.id : null),
      prefix: 'community'
    })
  } catch (e) {
    error.value = e.message || '加载社区失败'
  } finally {
    loading.value = false
  }
}

function releasePostThumbs() {
  posts.value.forEach((p) => releaseObjectUrl(p))
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
      releaseObjectUrl(posts.value[i]) // 释放缩略图缓存引用后再摘掉卡片
      posts.value.splice(i, 1)
    }
    if (current.value && current.value.id === post.id) closePost()
  } catch (e) {
    error.value = e.message || '删除失败'
  }
}

function openPost(post) {
  current.value = post
  resetCommentDraft()
}

function closePost() {
  current.value = null
  resetCommentDraft()
}

// ---- 评论（Spec17 §7.7）----

function resetCommentDraft() {
  commentDraft.value = ''
  commentError.value = ''
  commentBusy.value = false
}

// 中文输入法里回车是「选词确认」，不是「发表」——isComposing / keyCode 229 时放过
function onCommentEnter(e, post) {
  if (e.isComposing || e.keyCode === 229) return
  submitComment(post)
}

async function submitComment(post) {
  const text = commentDraft.value.trim()
  if (!text || commentBusy.value) return
  commentBusy.value = true
  commentError.value = ''
  try {
    const comment = await createComment(post.id, text)
    // 后端返回的形态与列表内嵌的评论同形 → 直接 push，💬 评论计数随之 +1
    if (!post.comments) post.comments = []
    post.comments.push(comment)
    commentDraft.value = ''
  } catch (e) {
    // 提示画在弹窗里：页面顶部的错误条被遮罩挡住，弹窗开着时看不见
    commentError.value = e.message || '发表评论失败'
  } finally {
    commentBusy.value = false
  }
}

async function removeComment(post, comment) {
  if (!window.confirm('确定删除这条评论？此操作不可撤销。')) return
  commentError.value = ''
  try {
    await deleteComment(post.id, comment.id)
    const i = (post.comments || []).findIndex((c) => c.id === comment.id)
    if (i !== -1) post.comments.splice(i, 1)
  } catch (e) {
    commentError.value = e.message || '删除评论失败'
  }
}

// ---- 发帖 ----
async function openCreate() {
  showCreate.value = true
  createText.value = ''
  createTab.value = null // Spec17：默认不配图（纯文字帖是合法且常见的选择）
  pickedId.value = null
  pickedFile = null
  uploadDrag.value = false
  dragDepth = 0
  releasePreview()
  await loadMyItems()
}

// 再点当前选中的方式 = 取消选择（回到"不配图"），无需额外的「×」入口
function toggleTab(tab) {
  createTab.value = createTab.value === tab ? null : tab
}

function closeCreate() {
  showCreate.value = false
  createText.value = ''
  createTab.value = null
  pickedId.value = null
  pickedFile = null
  uploadDrag.value = false
  dragDepth = 0
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
    await attachObjectUrls(myItems.value, (id) => fetchGalleryFile(id, false))
  } catch (e) {
    error.value = e.message || '加载作品库失败'
  }
}

function releaseItemThumbs() {
  myItems.value.forEach((it) => releaseObjectUrl(it))
  myItems.value = []
}

function acceptFile(f) {
  const okType = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(f.type)
  if (!okType) {
    error.value = '仅支持 jpg / png / webp / gif 图片'
    return false
  }
  return true
}

function onPickFile(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  if (!acceptFile(f)) {
    e.target.value = ''
    return
  }
  pickedFile = f
  releasePreview()
  previewUrl.value = URL.createObjectURL(f)
}

// Spec10：上传区拖拽拾取（点击选择仍保留）
function onDragEnter() {
  dragDepth += 1
  uploadDrag.value = true
}

function onDragLeave() {
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    uploadDrag.value = false
  }
}

function onDropFile(e) {
  dragDepth = 0
  uploadDrag.value = false
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]
  if (!f) return
  if (!acceptFile(f)) return
  pickedFile = f
  releasePreview()
  previewUrl.value = URL.createObjectURL(f)
}

// 文字必填；配图可选（Spec17 §7.7）——选了某种配图方式就要真的选到图
const canSubmit = computed(() => {
  const text = createText.value.trim()
  if (!text) return false
  if (createTab.value === 'gallery') return pickedId.value != null
  if (createTab.value === 'upload') return pickedFile != null
  return true
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
  if (current.value) closePost()
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
  gap: 8px;
  padding: 28px 20px;
  min-height: 140px;
  background: var(--bg-input);
  border: 1px dashed var(--border-light);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast),
    background var(--transition-fast), box-shadow var(--transition-fast);
}

.community-upload-box:hover {
  border-color: var(--purple-500);
  color: var(--text-secondary);
}

.community-upload-box.drag-over {
  border-color: var(--purple-500);
  border-style: solid;
  color: var(--text-primary);
  background: rgba(124, 58, 237, 0.12);
  box-shadow: var(--shadow-glow);
}

.community-upload-icon {
  font-size: 30px;
}

.community-upload-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}

.community-upload-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.community-upload-replace {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.community-file-input {
  display: none;
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

/* ---------- 发帖弹窗：配图可选（Spec17 §7.7）---------- */

.community-create-hint {
  margin: 8px 16px 0;
  font-size: 12px;
  color: var(--text-muted);
}

/* 不配图 = 合法选择，做成一块中性的说明区而不是空荡的留白 */
.community-no-image {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  padding: 20px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  background: var(--bg-input);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-lg);
}

/* ---------- 评论区（Spec17 §7.7；容器样式在 main.css）---------- */

.comment-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.comment-text {
  flex: 1;
  min-width: 0;
}

.comment-del {
  flex-shrink: 0;
  padding: 0 8px;
}

.comment-input {
  flex: 1;
  min-width: 0;
  padding: 7px 10px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  transition: border-color var(--transition-fast);
}

.comment-input:focus {
  outline: none;
  border-color: var(--purple-500);
}

.comment-input::placeholder {
  color: var(--text-muted);
}
</style>
