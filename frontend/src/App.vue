<template>
  <!-- 启动中：校验登录态 -->
  <div v-if="!auth.loaded" class="boot-screen">加载中…</div>

  <!-- Spec24 §2.1：不再是"未登录 → 整页登录页"。游客照常进 .app 外壳，碰到会落后端
       的动作被拦下时才把登录层（.app 的**兄弟**节点，见模板末尾）盖上来。
       ⚠️ 这一支必须保留成 v-else —— 外壳不挂载的话，回填的落点 ChatInput 与
       五个面板的 boolean 就都没了（§14 陷阱 1）。 -->
  <div v-else class="app">
    <!-- Spec17 §7.5：对话历史侧边栏常驻在聊天视图左侧（其它面板视图下不渲染） -->
    <ConversationSidebar
      v-if="isChatView"
      :conversations="store.conversations"
      :current-id="store.currentConvId"
      :guest="isGuest"
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
        <!-- Spec24 §7.2：恒定文案。原句是"品牌定位短语 · 用户名插值"两件事拼在一行，
             整行删除 —— 它把"品牌定位"和"当前身份"塞进同一个位置，而未登录时
             auth.username 是空串，屏幕上只剩一个孤零零的「· 」。品牌句与身份位
             现在是两个元素（身份位见下面新增的 .login-state）。
             注：这里刻意不逐字引用旧文案，好让 §13-H-27 的 grep 真正输出为空。 -->
        <span class="brand-sub">AI辅助设计的系统</span>
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
        <button v-if="!auth.isAdmin" class="btn-clear" @click="openRecharge">
          余额与充值
        </button>
        <button class="btn-clear" title="使用帮助" @click="showHelp = !showHelp">帮助</button>
        <!-- Spec24 §7.2：登录状态。**两个条件一起判** —— token 是同步从 localStorage 读的，
             username 要等 GET /api/auth/me 回来；只判 token 会在启动那一瞬闪一下
             「目前登录：」（§14 陷阱 8）。 -->
        <span class="login-state">
          目前登录：{{ auth.token && auth.username ? auth.username : '未登录' }}
        </span>
        <!-- Spec24 §3.1：「退出」只对登录用户有意义，游客位换成主动登录入口
             （不给它的话，游客只能靠"被拦下"才能登录）。 -->
        <button v-if="isGuest" class="btn-login-entry" @click="openLogin">登录</button>
        <button v-else class="btn-logout" title="退出登录" @click="onLogout">退出</button>
      </header>

      <!-- Spec24 §2.3：面板组件对游客**整个不挂载**（它们的 onMounted 会立刻发请求 → 401
           → artcn:unauthorized → 全局登出）。分发权交给 activePanel 计算属性，见 script：
           它互斥且穷尽，游客永远拿不到任何一个面板分支。 -->
      <GalleryPanel v-if="activePanel === 'gallery'" @close="showGallery = false" />
      <AdminPanel v-else-if="activePanel === 'admin'" @close="showAdmin = false" />
      <StatsPanel v-else-if="activePanel === 'stats'" @close="showStats = false" />
      <CommunityPanel v-else-if="activePanel === 'community'" @close="showCommunity = false" />
      <SuggestionPanel v-else-if="activePanel === 'suggestions'" @close="showSuggestions = false" />

      <!-- Spec24 §5.5：游客的落点。:label 是"他想开的那个面板"的名字（guestPanelLabel）。 -->
      <LoginGate
        v-else-if="activePanel === 'gate'"
        :label="guestPanelLabel"
        @login="openLogin"
        @close="closeAllPanels"
      />

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

        <ChatInput
          :disabled="store.sending"
          :draft="draft"
          @send="onSend"
          @draft-consumed="draft = null"
        />
      </template>

      <!-- Spec8：帮助弹窗（顶层 overlay，任何视图都可用） -->
      <HelpModal v-if="showHelp" @close="showHelp = false" />

      <!-- Spec21 §7.1：余额与充值弹窗（同样挂在顶层，任何面板视图下都可用） -->
      <RechargeModal v-if="showRecharge" @close="showRecharge = false" />
    </div>
  </div>

  <!-- Spec24 §2.1：登录层是 **.app 的兄弟节点**，不是 v-else 替换物。
       ⚠️ 绝不能改成替换式：外壳一旦卸载，回填的落点 ChatInput（§2.6）与五个面板的
       boolean 就都没了 —— 用户点「← 返回继续浏览」回去时，看到的是一个被重置的界面
       （§14 陷阱 1）。class 由 Vue 合并到 Login.vue 的单根节点上（main.css 的
       .login-page.login-overlay 把它固定成覆盖层）。 -->
  <Login v-if="showLogin" class="login-overlay" @close="onLoginClose" />
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
import LoginGate from './components/LoginGate.vue'
import { setQuotaUsername } from './utils/quotaNotice'
import { trackClick } from './utils/track'
import { stashRequest, takeRequest } from './utils/pendingRequest'

const auth = useAuthStore()
auth.init()

const store = useChatStore()

// Spec8：帮助弹窗开关（首次登录自动弹出，之后由「帮助」按钮手动开关）
const showHelp = ref(false)

// Spec24 §5.1：游客态判定。**判据用 auth.token，不是 auth.username** —— token 是
// **同步**从 localStorage 读出来的（store/auth.js 的 state 初始化），username 要等
// GET /api/auth/me 回来才有值；用 username 判会在启动那一瞬把已登录用户误判成游客。
const isGuest = computed(() => !auth.token)

// Spec24 §2.1：登录层的开关。它是 .app 的**兄弟**节点，不是 v-else 替换物。
const showLogin = ref(false)
// Spec24 §2.6：待回填的暂存内容 { text, file }；null = 没有。父组件持有它，
// ChatInput 消费完通过 @draft-consumed 通知这里清空。
const draft = ref(null)

// Spec24 §5.8：?register=1 深链接 → 游客也要先看到登录层（注册弹窗由 Login.vue
// 的 onMounted 照旧挂出）。**不清理 URL**（Spec19 §7.4 的既定行为）。
// ⚠️ 这段排在 showLogin 的 ref 声明之后；auth.token 是同步读的，所以这里就判得到。
if (!auth.token && new URLSearchParams(window.location.search).get('register') === '1') {
  showLogin.value = true
}

// 登录态流转 → 按用户重载会话历史（Spec3 §5.2）
// 启动校验完成（auth.loaded）后取 username；登录 / 登出 / token 失效时 username 变化同样触发。
// 未登录（无 username）→ resetForUser(null)，保持空会话、不读任何历史键。
watch(
  () => [auth.loaded, auth.username],
  async ([loaded]) => {
    if (!loaded) return
    store.resetForUser(auth.token ? auth.username : null)
    // Spec8：登录态就绪后，该用户首次登录自动弹出帮助弹窗（弹出即标记，只弹一次）
    if (auth.token && auth.username) {
      // Spec24 §5.9 路径 1：登录成功 → 收起登录层，并把被拦下时暂存的内容回填进输入框。
      // **只在这一支里做**：登出（username 变空）时不许碰 showLogin，否则「退出登录」
      // 会被弹回登录页 —— §13 F-24 要的是回到游客外壳。
      // **回填不是自动发送**：填完由用户自己再点一次「发送」（§2.7、§14 陷阱 10）。
      showLogin.value = false
      await restorePending()

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
// Spec22 §7.4：三个埋点插在这三个函数的开头（保持"所有入口逻辑都在这个函数里"的现状）。
// **只计"打开"**：toggleGallery 在"返回聊天"那一次也会被调用，于是同一个 IP 会被再报
// 一遍——而 IP 去重让它在库里不产生任何影响（§2.9），这正是选 IP 去重而不是"计数"的好处。
// **不需要**在这里判断"是打开还是关闭"。
function toggleGallery() {
  trackClick('gallery')
  showGallery.value = !showGallery.value
  if (showGallery.value) closeOtherPanels('gallery')
}
function toggleCommunity() {
  trackClick('community')
  showCommunity.value = !showCommunity.value
  if (showCommunity.value) closeOtherPanels('community')
}
// 余额与充值：它是 overlay（不参与面板互斥），直接置 true
// Spec24 §5.3：它是两个"没有页面可给"的例外之一 —— 余额面板是 overlay 不是视图，
// 所以游客直接弹登录层，而不是像五个面板那样走 LoginGate。
function openRecharge() {
  trackClick('recharge')                       // ← 位置不变（§2.9：埋点在门禁之前）
  if (isGuest.value) { openLogin(); return }   // ← 唯一新增
  showRecharge.value = true
}
// toggleSuggestions / toggleAdmin / toggleStats 与 toggleGallery / toggleCommunity 同款：
// **一个字不改**（Spec24 §5.3）。门禁不在它们里面 —— 游客点它们照样翻转 boolean，
// 由 activePanel 把渲染分流到 LoginGate。加 `if (isGuest) { openLogin(); return }`
// 会让游客"被糊一脸登录卡"，而用户选的口径是"先看到页面，只有内容是登录专属的"。
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

// Spec24 §5.3：打开登录层。
function openLogin() {
  showLogin.value = true
}

// Spec24 §2.6：两条恢复路径（登录成功 / 从登录层返回）共用它。
// takeRequest() 内部判 3 分钟 TTL，过期返回 null（§2.5）。
async function restorePending() {
  const pending = await takeRequest()
  if (pending) draft.value = pending
}

// Spec24 §5.8：点「← 返回继续浏览」收起登录层，**并把暂存放回输入框**。
// 这是 §5.9 路径 2 —— 没有它的话，用户打完字、点发送、看到登录页、点返回，字就没了，
// 那是整套改造里唯一一处"用户会明确感到被坑"的地方。
async function onLoginClose() {
  showLogin.value = false
  await restorePending()
}

// Spec24 §5.2：游客态下"他想开的是哪个面板"——只用来给登录门选一句文案。
// 顺序与下面 activePanel 里的顺序一致。
const guestPanel = computed(() => {
  if (showGallery.value) return 'gallery'
  if (showCommunity.value) return 'community'
  if (showSuggestions.value) return 'suggestions'
  if (showStats.value) return 'stats'
  if (showAdmin.value) return 'admin'
  return null
})

// Spec24 §2.3：**唯一**决定 main-col 里渲染什么的东西。
// 互斥、穷尽，且游客永远拿不到任何面板分支（§2.10 的第 2 级保证 —— 将来有人手滑
// 给游客打开了 showAdmin，落到也是登录门，不是管理面板）。
// 为什么不是"给每个 v-if 补一个 && !isGuest"：那五个面板的 onMounted 全都会立刻发
// 请求 → 401 → chatApi.js 拦截器派发 artcn:unauthorized → 全局登出（§14 陷阱 2）。
// 门禁必须做在**挂载之前**。
const activePanel = computed(() => {
  if (isGuest.value) return guestPanel.value ? 'gate' : null
  if (showGallery.value) return 'gallery'
  if (showAdmin.value) return 'admin'
  if (showStats.value) return 'stats'
  if (showCommunity.value) return 'community'
  if (showSuggestions.value) return 'suggestions'
  return null
})

// Spec24 §5.2：登录门上那句「🔒 XXX 需要登录后查看」里的 XXX。
// 组件自己不猜，名字由这里给（§7.4 的硬约束 2）。
const PANEL_LABELS = {
  gallery: '我的作品', admin: '用户管理', stats: '数据统计',
  community: '社区', suggestions: '建议'
}
const guestPanelLabel = computed(() => PANEL_LABELS[guestPanel.value] || '该页面')

// Spec17 §7.5：只有聊天视图才挂对话侧边栏。语义没变（"没有面板开着"），
// 改成从 activePanel 推 —— 游客在聊天视图时 activePanel 是 null，侧边栏照常渲染。
const isChatView = computed(() => activePanel.value === null)

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
// Spec24 §2.8：**必须补 showLogin = true**。旧结构里"登出即回登录页"是 auth.logout()
// 的副作用（模板的 v-else-if="!auth.token"），新结构里没有那个副作用了 —— 登出之后
// 只是一个游客态外壳。漏了它，被踢的用户会静默落到游客界面，看不到任何解释。
window.addEventListener('artcn:unauthorized', () => {
  auth.logout()
  closeAllPanels()
  showLogin.value = true
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
  // Spec24 §2.8：这一行是欠费充值面板**仍然可见**的唯一保证。Login.vue 的 onMounted
  // 会 takeQuotaNotice() 并把面板挂出来 —— Spec21 §7.4 那句「若您单击登录键则会跳出
  // 充值面板」的落点就在那儿。登录页不再是 auth.logout() 的副作用之后，**这条漏了
  // 面板就永不出现，那句提示语当场变成空头支票**（§14 陷阱 3、§13 G-25）。
  showLogin.value = true
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

// Spec24 §5.3：唯一一个**带暂存**的门禁点。
async function onSend(payload) {
  if (isGuest.value) {
    // §2.4/§5.4：先落盘再弹登录 —— **顺序不能反**。反过来的话"弹登录"与"写暂存"
    // 会并发，用户秒点「返回继续浏览」时可能读到空暂存。
    // ⚠️ 这里**不 await**（Spec24 终审 F2）：stashRequest 在它第一个 await 之前就把文本
    // 同步写进了 localStorage，所以这一句返回时暂存已经落盘；而再往后是 IndexedDB 的
    // 尽力而为（图可能 10MB），await 它会让"弹出登录层"排在一个可能永不 settle 的
    // IDB 事务后面 —— 挂住时用户看到的是"点了发送，输入框空了，什么都没发生"。
    // 落盘是前置条件，IDB 的尾巴不是。
    // ⚠️ ChatInput.submit() 在 emit 之后就清空了自己的 text/file，所以此刻输入框
    // 已经空了 —— 这正是回填（§5.9 路径 2）必须存在的原因。
    stashRequest(payload.text, payload.file)
    openLogin()
    return
  }
  store.send(payload.text, payload.file)
}
function onRetry(errorId) {
  store.retry(errorId)
}

// 侧边栏三个动作：切换 / 删除之后都要滚到底（新载入的历史从最新一条看起）
function onNewConversation() {
  // Spec24 §5.3：另一个"没有页面可给"的例外 —— 它是列表里的一个动作，直接弹登录层。
  // （游客的 currentConvId 恒为 null，ConversationSidebar 的 :disabled 会把这个按钮
  // 变成灰的、点不动 —— 靠 §5.7 的 guest prop 才让它可点，这两处缺一不可。）
  if (isGuest.value) { openLogin(); return }
  store.newConversation()
  scrollToBottom()
}
async function onOpenConversation(id) {
  // Spec24 §5.3：防御（游客的对话列表恒为空，正常够不着）
  if (isGuest.value) { openLogin(); return }
  await store.openConversation(id)
  scrollToBottom()
}
async function onDeleteConversation(id) {
  await store.deleteConversation(id)
  scrollToBottom()
}
</script>
