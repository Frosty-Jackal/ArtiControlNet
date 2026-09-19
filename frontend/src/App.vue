<template>
  <!-- 启动中：校验登录态 -->
  <div v-if="!auth.loaded" class="boot-screen">加载中…</div>

  <!-- 未登录 → 登录页 -->
  <Login v-else-if="!auth.token" />

  <!-- 已登录 → 聊天页 / 管理视图 -->
  <div v-else class="app">
    <!-- Spec17 §7.5：对话历史侧边栏常驻在聊天视图左侧（其它面板视图下不渲染） -->
    <ConversationSidebar
      v-if="isChatView"
      :conversations="store.conversations"
      :current-id="store.currentConvId"
      @new="onNewConversation"
      @open="onOpenConversation"
      @delete="onDeleteConversation"
    />

    <div class="main-col">
      <header class="app-header">
        <div class="brand">
          <span class="brand-dot"></span>
          <h1>ArtiControlNet</h1>
        </div>
        <span class="brand-sub">
          赋能设计的 AIGC 系统 · {{ auth.username }}
        </span>
        <button class="btn-clear" @click="toggleGallery">
          {{ showGallery ? '返回聊天' : '我的作品' }}
        </button>
        <button class="btn-clear" @click="toggleCommunity">
          {{ showCommunity ? '返回聊天' : '社区' }}
        </button>
        <button class="btn-clear" @click="toggleSuggestions">
          {{ showSuggestions ? '返回聊天' : '建议' }}
        </button>
        <button v-if="auth.isAdmin" class="btn-clear" @click="toggleAdmin">
          {{ showAdmin ? '返回聊天' : '用户管理' }}
        </button>
        <button v-if="auth.isAdmin" class="btn-clear" @click="toggleStats">
          {{ showStats ? '返回聊天' : '数据统计' }}
        </button>
        <!-- Spec21 §7.1：余额与充值（仅普通用户）。管理员 used/quota_limit 照常累计
             但不参与判定，给他显示一个无业务含义的余额是误导（§2.9）。 -->
        <button v-if="!auth.isAdmin" class="btn-clear" @click="showRecharge = true">
          余额与充值
        </button>
        <button class="btn-clear" title="使用帮助" @click="showHelp = !showHelp">帮助</button>
        <button class="btn-logout" title="退出登录" @click="onLogout">退出</button>
      </header>

      <GalleryPanel v-if="showGallery" @close="showGallery = false" />
      <AdminPanel v-else-if="showAdmin" @close="showAdmin = false" />
      <StatsPanel v-else-if="showStats" @close="showStats = false" />
      <CommunityPanel v-else-if="showCommunity" @close="showCommunity = false" />
      <SuggestionPanel v-else-if="showSuggestions" @close="showSuggestions = false" />

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
            @vote="store.toggleFeedback"
          />
          <TypingIndicator v-if="store.sending" />
        </main>

        <ChatInput :disabled="store.sending" @send="onSend" />
      </template>

      <!-- Spec8：帮助弹窗（顶层 overlay，任何视图都可用） -->
      <HelpModal v-if="showHelp" @close="showHelp = false" />

      <!-- Spec21 §7.1：余额与充值弹窗（同样挂在顶层，任何面板视图下都可用） -->
      <RechargeModal v-if="showRecharge" @close="showRecharge = false" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useChatStore } from './store/chat'
import { useAuthStore } from './store/auth'
import ChatBubble from './components/ChatBubble.vue'
import ChatInput from './components/ChatInput.vue'
import ConversationSidebar from './components/ConversationSidebar.vue'
import TypingIndicator from './components/TypingIndicator.vue'
import Login from './views/Login.vue'
import AdminPanel from './views/AdminPanel.vue'
import StatsPanel from './views/StatsPanel.vue'
import GalleryPanel from './views/GalleryPanel.vue'
import CommunityPanel from './views/CommunityPanel.vue'
import SuggestionPanel from './views/SuggestionPanel.vue'
import HelpModal from './views/HelpModal.vue'
import RechargeModal from './views/RechargeModal.vue'
import { setQuotaUsername } from './utils/quotaNotice'

const auth = useAuthStore()
auth.init()

const store = useChatStore()

// Spec8：帮助弹窗开关（首次登录自动弹出，之后由「帮助」按钮手动开关）
const showHelp = ref(false)

// 登录态流转 → 按用户重载会话历史（Spec3 §5.2）
// 启动校验完成（auth.loaded）后取 username；登录 / 登出 / token 失效时 username 变化同样触发。
// 未登录（无 username）→ resetForUser(null)，保持空会话、不读任何历史键。
watch(
  () => [auth.loaded, auth.username],
  ([loaded]) => {
    if (!loaded) return
    store.resetForUser(auth.token ? auth.username : null)
    // Spec8：登录态就绪后，该用户首次登录自动弹出帮助弹窗（弹出即标记，只弹一次）
    if (auth.token && auth.username) {
      const seenKey = `artcn_help_seen:${auth.username}`
      if (!localStorage.getItem(seenKey)) {
        localStorage.setItem(seenKey, '1')
        showHelp.value = true
      }
    }
  },
  { immediate: true }
)

const showGallery = ref(false)
const showAdmin = ref(false)
const showStats = ref(false)
const showCommunity = ref(false)
const showSuggestions = ref(false)
// Spec21 §7.1：余额与充值弹窗不参与面板互斥——它是 overlay，不是视图（与帮助同款）
const showRecharge = ref(false)
// 「我的作品/社区/建议」所有登录用户可见，「用户管理/数据统计」仅管理员；五面板互斥：打开一个自动关闭其余四个
function closeOtherPanels(keep) {
  const map = { gallery: showGallery, admin: showAdmin, stats: showStats, community: showCommunity, suggestions: showSuggestions }
  Object.entries(map).forEach(([k, v]) => {
    if (k !== keep) v.value = false
  })
}
function toggleGallery() {
  showGallery.value = !showGallery.value
  if (showGallery.value) closeOtherPanels('gallery')
}
function toggleCommunity() {
  showCommunity.value = !showCommunity.value
  if (showCommunity.value) closeOtherPanels('community')
}
function toggleSuggestions() {
  showSuggestions.value = !showSuggestions.value
  if (showSuggestions.value) closeOtherPanels('suggestions')
}
function toggleAdmin() {
  showAdmin.value = !showAdmin.value
  if (showAdmin.value) closeOtherPanels('admin')
}
function toggleStats() {
  showStats.value = !showStats.value
  if (showStats.value) closeOtherPanels('stats')
}
function closeAllPanels() {
  showGallery.value = false
  showAdmin.value = false
  showStats.value = false
  showCommunity.value = false
  showSuggestions.value = false
}

// Spec17 §7.5：只有聊天视图才挂对话侧边栏（五个面板互斥，任一打开即非聊天视图）
const isChatView = computed(
  () => !showGallery.value && !showAdmin.value && !showStats.value
    && !showCommunity.value && !showSuggestions.value
)

// 撤销自身管理员 → 自动关闭管理视图（社区/建议对所有登录用户保留）
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
  closeAllPanels()
})

// Spec18 §7.1b：服务次数耗尽 → 与 401 同样地登出并关掉所有面板。
// 处理体与上面那条完全相同，但**不复用同一个事件名**：两者的原因不同
// （登录态坏了 vs 额度用完了），日志和将来可能的分叉处理都需要能分开。
// 提示语已由拦截器写进 utils/quotaNotice，由登出后挂载的 Login.vue 弹出。
window.addEventListener('artcn:quota_exceeded', () => {
  // Spec21 §7.1：补写 username 供登录页的欠费充值面板预填账号。
  // **必须在 auth.logout() 之前**——logout 之后 auth.username 就空了。
  // （提示语本身由拦截器写，那里拿不到 store；两处分工见 utils/quotaNotice.js）
  setQuotaUsername(auth.username)
  auth.logout()
  closeAllPanels()
})

function onLogout() {
  auth.logout()
  closeAllPanels()
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

// 侧边栏三个动作：切换 / 删除之后都要滚到底（新载入的历史从最新一条看起）
function onNewConversation() {
  store.newConversation()
  scrollToBottom()
}
async function onOpenConversation(id) {
  await store.openConversation(id)
  scrollToBottom()
}
async function onDeleteConversation(id) {
  await store.deleteConversation(id)
  scrollToBottom()
}
</script>
