<template>
  <div class="login-page">
    <div class="login-card">
      <!-- Spec19 §7.1：品牌标识（透明底 SVG，深色卡片上直接成立）。
           标识里只有图形与「ACN」三个字母，全称由下面的标题提供，两者互补。 -->
      <img class="login-logo" :src="logoUrl" alt="ArtiControlNet" />
      <div class="login-brand">
        <span class="brand-dot"></span>
        <h1>ArtiControlNet</h1>
      </div>
      <p class="login-sub">赋能设计的 AIGC 系统 · 登录后使用</p>

      <form class="login-form" @submit.prevent="submit">
        <input
          v-model="username"
          class="login-input"
          placeholder="用户名"
          autocomplete="username"
        />
        <input
          v-model="password"
          type="password"
          class="login-input"
          placeholder="密码"
          autocomplete="current-password"
        />
        <p v-if="error" class="login-error">{{ error }}</p>
        <button class="btn-login" type="submit" :disabled="loading">
          {{ loading ? '登录中…' : '登 录' }}
        </button>
      </form>

      <!-- Spec19 §7.2：注册入口（REGISTER_ENABLED=false 时整体不渲染按钮，客服行保留） -->
      <div v-if="regCfg" class="login-register">
        <button v-if="regCfg.enabled" type="button" class="btn-register" @click="showRegister = true">
          新用户注册
        </button>
        <p class="login-service">有问题请致信官方客服：{{ regCfg.contact_email }}</p>
      </div>
    </div>

    <!-- Spec19 §7.3：注册申请弹窗 -->
    <RegisterModal v-if="showRegister" :config="regCfg" @close="showRegister = false" />

    <!-- Spec21 §7.4：被强制退出 / 登录被拒时，二维码直接弹在登录页上。
         这是提示语「若您单击登录键则会跳出充值面板」承诺的那块面板，红色提示行
         （.login-error）与它一个都不能少——没有它那句话就不成立。 -->
    <RechargeModal
      v-if="overdraft"
      mode="overdue"
      :username="overdraft.username"
      @close="overdraft = null"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import RegisterModal from './RegisterModal.vue'
import RechargeModal from './RechargeModal.vue'
import { getRegisterConfig } from '../api/chatApi'
import logoUrl from '../assets/logo.svg'
import { useAuthStore } from '../store/auth'
import { takeQuotaNotice } from '../utils/quotaNotice'

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

// Spec19 §7.2：注册弹窗的公开配置（取不到时为 null → 不画注册入口）
const regCfg = ref(null)
const showRegister = ref(false)
// Spec21 §7.4：欠费充值面板。null = 不显示；有值 = 显示，并把其中的 username 预填进账号框
const overdraft = ref(null)

onMounted(async () => {
  // Spec18 §7.4：落地到登录页时，若有一条待显示的限额警告 → 红色提示行 + 充值面板。
  // **不用 window.alert**（用户后来改的口径）：alert 是阻断式的，点掉「确定」之前
  // 用户看不到背后的登录页与充值面板，而且同一句话要说两遍。现在只留红色提示行
  // （.login-error，#fca5a5），信息一点没少，也不挡路。
  const notice = takeQuotaNotice()
  if (notice.message) {
    error.value = notice.message
    // Spec21 §7.4：充值面板直接弹出来（username 由被踢时的 App.vue 带过来）
    overdraft.value = notice
  }

  // Spec19 §7.2：静默降级——取不到就不画注册入口、不报错。
  // 登录页的首要职责是登录，注册接口挂了不该让它连带报错。
  try {
    regCfg.value = await getRegisterConfig()
  } catch {
    regCfg.value = null
  }
  // Spec19 §7.4：?register=1 深链接 → 自动打开注册弹窗。
  // **不清理 URL**：关掉弹窗后地址栏仍是 ?register=1，刷新会再次打开。
  // 对 README 引流的场景这是期望行为（用户从官网链接进来，中途刷新，注册窗还在）。
  // regCfg.enabled === false 时不打开（两层都拦，前端这层只是体验）。
  if (new URLSearchParams(window.location.search).get('register') === '1'
      && regCfg.value?.enabled) {
    showRegister.value = true
  }
})

async function submit() {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value.trim(), password.value)
  } catch (e) {
    error.value = e.message || '登录失败'
    // Spec18 §7.4：超额被拒时同样弹窗（错误对象带 code，见 api/chatApi.js）。
    // 这里就是提示语里那句「若您单击登录键则会跳出充值面板」的落点——所以这一支
    // **必须**把面板弹出来，否则那句话就是空头支票。同样不用 window.alert。
    if (e.code === 40304) {
      // 登录被拒（而不是从系统内被踢）时也弹充值面板。
      // 这里没有 store 里的 username 可用（还没登录成功），就拿用户刚敲进去的那个。
      overdraft.value = { message: e.message, username: username.value.trim() }
    }
  } finally {
    loading.value = false
  }
}
</script>
