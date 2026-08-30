<template>
  <!-- 启动中：校验登录态 -->
  <div v-if="!auth.loaded" class="boot-screen">加载中…</div>

  <!-- 未登录 → 登录页 -->
  <Login v-else-if="!auth.token" />

  <!-- 已登录 → 聊天页 / 管理视图 -->
  <div v-else class="app">
    <header class="app-header">
      <div class="brand">
        <span class="brand-dot"></span>
        <h1>ArtiControlNet</h1>
      </div>
      <span class="brand-sub">
        多智能体 AI 创意工作台 · {{ auth.username }}
      </span>
      <button class="btn-clear" @click="toggleGallery">
        {{ showGallery ? '返回聊天' : '我的作品' }}
      </button>
      <button v-if="auth.isAdmin" class="btn-clear" @click="toggleAdmin">
        {{ showAdmin ? '返回聊天' : '用户管理' }}
      </button>
      <button v-if="auth.isAdmin" class="btn-clear" @click="toggleStats">
        {{ showStats ? '返回聊天' : '数据统计' }}
      </button>
      <button v-if="!showAdmin && !showStats && !showGallery" class="btn-clear" title="清空当前对话" @click="onClear">
        清空
      </button>
      <button class="btn-logout" title="退出登录" @click="onLogout">退出</button>
    </header>

    <GalleryPanel v-if="showGallery" @close="showGallery = false" />
    <AdminPanel v-else-if="showAdmin" @close="showAdmin = false" />
    <StatsPanel v-else-if="showStats" @close="showStats = false" />

    <template v-else>
      <main class="chat-scroll" ref="scrollRef">
        <div v-if="store.messages.length === 0" class="empty-state">
          <p class="empty-title">🎨 想要什么，直接说</p>
          <p class="empty-hint">
            “做一张新年海报” · “上传线稿让它上色” · “上传照片问它是什么”
          </p>
        </div>
        <ChatBubble
          v-for="m in store.messages"
          :key="m.id"
          :message="m"
          @retry="onRetry"
        />
        <TypingIndicator v-if="store.sending" />
      </main>

      <ChatInput :disabled="store.sending" @send="onSend" />
    </template>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { useChatStore } from './store/chat'
import { useAuthStore } from './store/auth'
import ChatBubble from './components/ChatBubble.vue'
import ChatInput from './components/ChatInput.vue'
import TypingIndicator from './components/TypingIndicator.vue'
import Login from './views/Login.vue'
import AdminPanel from './views/AdminPanel.vue'
import StatsPanel from './views/StatsPanel.vue'
import GalleryPanel from './views/GalleryPanel.vue'

const auth = useAuthStore()
auth.init()

const store = useChatStore()

// 登录态流转 → 按用户重载会话历史（Spec3 §5.2）
// 启动校验完成（auth.loaded）后取 username；登录 / 登出 / token 失效时 username 变化同样触发。
// 未登录（无 username）→ resetForUser(null)，保持空会话、不读任何历史键。
watch(
  () => [auth.loaded, auth.username],
  ([loaded]) => {
    if (!loaded) return
    store.resetForUser(auth.token ? auth.username : null)
  },
  { immediate: true }
)

const showGallery = ref(false)
const showAdmin = ref(false)
const showStats = ref(false)
// 「我的作品」所有登录用户可见（Spec5 §7）；三面板互斥：打开一个自动关闭另外两个
function toggleGallery() {
  showGallery.value = !showGallery.value
  if (showGallery.value) {
    showAdmin.value = false
    showStats.value = false
  }
}
function toggleAdmin() {
  showAdmin.value = !showAdmin.value
  if (showAdmin.value) {
    showStats.value = false
    showGallery.value = false
  }
}
function toggleStats() {
  showStats.value = !showStats.value
  if (showStats.value) {
    showAdmin.value = false
    showGallery.value = false
  }
}

// 撤销自身管理员 → 自动关闭管理视图
watch(
  () => auth.isAdmin,
  (v) => {
    if (!v) {
      showAdmin.value = false
      showStats.value = false
    }
  }
)

// 任意业务请求 401（token 失效）→ 清登录态回登录页
window.addEventListener('artcn:unauthorized', () => {
  auth.logout()
  showGallery.value = false
  showAdmin.value = false
  showStats.value = false
})

function onLogout() {
  auth.logout()
  showGallery.value = false
  showAdmin.value = false
  showStats.value = false
}

const scrollRef = ref(null)
function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
watch(() => store.messages, scrollToBottom, { deep: true })
scrollToBottom()

function onSend(payload) {
  store.send(payload.text, payload.file)
}
function onRetry(errorId) {
  store.retry(errorId)
}
function onClear() {
  store.clear()
  scrollToBottom()
}
</script>
