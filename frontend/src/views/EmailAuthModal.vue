<template>
  <div class="reg-overlay" @click.self="close">
    <div class="reg-card email-auth-card" role="dialog" aria-modal="true"
         :aria-label="mode === 'reset' ? '修改密码' : '邮箱登录'">
      <button class="reg-close" title="关闭" @click="close">×</button>

      <h2 class="reg-title">{{ mode === 'reset' ? '修改密码' : '邮箱登录' }}</h2>

      <form class="reg-form" @submit.prevent="submit">
        <label class="reg-label">邮箱 <b class="reg-star">*</b></label>
        <!-- Spec22 §2.8 的前端配合：autocapitalize=off（手机上不自动首字母大写），
             真正的规范化（去空白 + 转小写）在后端。 -->
        <div class="reg-code-row">
          <input v-model="email" class="login-input" type="email"
                 placeholder="邮箱" autocomplete="off" autocapitalize="off"
                 :disabled="mode === 'reset' && verified" />
          <button type="button" class="btn-code" :disabled="codeCooldown > 0 || sendingCode"
                  @click="sendCode">
            {{ codeCooldown > 0 ? `${codeCooldown}s` : (sendingCode ? '发送中…' : '获取验证码') }}
          </button>
        </div>

        <label class="reg-label">验证码 <b class="reg-star">*</b></label>
        <!-- 修改密码模式多一个「验证」：验证通过才展开下面两栏密码。
             邮箱登录模式不需要它——「登录」那一下本身就是验证（§7.3）。 -->
        <div v-if="mode === 'reset'" class="reg-code-row">
          <input v-model="code" class="login-input" type="text" inputmode="numeric" maxlength="4"
                 placeholder="4 位验证码" autocomplete="off" :disabled="verified" />
          <button type="button" class="btn-code" :disabled="verifying || verified" @click="verify">
            {{ verified ? '已验证' : (verifying ? '验证中…' : '验证') }}
          </button>
        </div>
        <input v-else v-model="code" class="login-input" type="text" inputmode="numeric"
               maxlength="4" placeholder="4 位验证码" autocomplete="off" />

        <!-- 密码栏：**只有验证通过后**才出现（用户原话："过了也不让单选了，直接弹出新密码+二次确认"） -->
        <template v-if="mode === 'reset' && verified">
          <hr class="ea-sep" />
          <label class="reg-label">新密码 <b class="reg-star">*</b></label>
          <input v-model="password" type="password" class="login-input"
                 placeholder="至少 2 位" autocomplete="new-password" />
          <label class="reg-label">确认密码 <b class="reg-star">*</b></label>
          <input v-model="confirmPassword" type="password" class="login-input"
                 placeholder="再输入一次" autocomplete="new-password" />
        </template>

        <p v-if="error" class="login-error">{{ error }}</p>
        <button class="btn-primary reg-submit" type="submit" :disabled="loading">
          {{ loading ? '请稍候…' : (mode === 'reset' ? '完 成' : '登 录') }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getEmailCode, resetPassword, verifyEmailCode } from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const props = defineProps({
  // 'login' = 邮箱验证码登录（一步）
  // 'reset' = 修改密码（两阶段：先验证码，通过后展开新密码 + 二次确认）
  mode: { type: String, required: true }
})
// Spec22 §7.3 画的是 close | done；**多一个 overdraft** —— 见 submit() 里那段说明。
const emit = defineEmits(['close', 'done', 'overdraft'])

const auth = useAuthStore()

const email = ref('')
const code = ref('')
const password = ref('')
const confirmPassword = ref('')
const verified = ref(false)
const verifying = ref(false)
const sendingCode = ref(false)
const codeCooldown = ref(0)
const error = ref('')
const loading = ref(false)
const isReset = computed(() => props.mode === 'reset')

let cooldownTimer = null
onBeforeUnmount(() => clearInterval(cooldownTimer))

// Spec22 §7.3：**验证码一旦改动就收起密码栏**。否则用户改个码再点「完成」，
// 会拿到一个"看起来填过密码但这次没验证过"的界面，后端只会回一句 40020
// （reset-password 的二次校验是**真的**，§2.7 用例 14）——前端先把话说清楚。
watch(code, () => {
  if (password.value || confirmPassword.value) verified.value = false
})

function close() {
  emit('close')
}

function startCooldown(seconds) {
  codeCooldown.value = seconds
  clearInterval(cooldownTimer)
  cooldownTimer = setInterval(() => {
    codeCooldown.value -= 1
    if (codeCooldown.value <= 0) clearInterval(cooldownTimer)
  }, 1000)
}

async function sendCode() {
  if (!email.value.trim()) {
    error.value = '请先填写邮箱'
    return
  }
  error.value = ''
  sendingCode.value = true
  try {
    // purpose 直接取模式名：'login' / 'reset'——与后端白名单一一对应（§6.2）
    await getEmailCode(email.value.trim(), props.mode)
    startCooldown(60) // 客户端倒计时只是体验，真正的闸门是后端的 40906
  } catch (e) {
    // 40907（还没注册 / 已注册）、40020（场景非法）、40906（发太勤）、50302（邮箱服务不可用）
    // 的 message **全部是后端原文**，前端零副本
    error.value = e.message || '验证码发送失败'
  } finally {
    sendingCode.value = false
  }
}

// 修改密码第一阶段：验证码换一张"可以改密码"的通行证（服务端不记状态，只作前置校验）
async function verify() {
  if (!email.value.trim()) {
    error.value = '请先填写邮箱'
    return
  }
  if (!/^\d{4}$/.test(code.value.trim())) {
    error.value = '请填写 4 位数字验证码'
    return
  }
  error.value = ''
  verifying.value = true
  try {
    await verifyEmailCode(email.value.trim(), 'reset', code.value.trim())
    verified.value = true
  } catch (e) {
    error.value = e.message || '验证失败'
  } finally {
    verifying.value = false
  }
}

async function submit() {
  if (!email.value.trim()) {
    error.value = '请填写邮箱'
    return
  }
  if (!/^\d{4}$/.test(code.value.trim())) {
    error.value = '请填写 4 位数字验证码'
    return
  }

  if (isReset.value) {
    // 后端收不到第二个框（§2.10），这一句只能在前端说
    if (!password.value) {
      error.value = '请填写新密码'
      return
    }
    if (password.value !== confirmPassword.value) {
      error.value = '两次输入的密码不一致'
      return // 不发请求
    }
  }

  error.value = ''
  loading.value = true
  try {
    if (isReset.value) {
      const res = await resetPassword(email.value.trim(), code.value.trim(), password.value)
      emit('done', { username: res.username })
    } else {
      await auth.loginByEmail(email.value.trim(), code.value.trim())
      // token 已进 store，App.vue 的 v-if 会自动切到聊天视图，这里不用做事
      emit('done', {})
    }
  } catch (e) {
    error.value = e.message || '操作失败'
    // Spec22 §7.6：40304（该账号已超额）**复用** Spec21 §7.4 的欠费充值面板，
    // 不另写一套。这条路由是公开白名单里的，拦截器**不会**替我们派发
    // artcn:quota_exceeded —— 它的守卫是 `!url.includes('/api/auth/login')`，
    // 而 '/api/auth/login-by-email' 恰好包含那个子串（与 /api/auth/login 自身的
    // 处境一致，见 Spec18 §7.2b 那段注释）。所以和 Login.vue 的密码登录一样，
    // 被拒时的面板由**调用方**挂：这里只往上抛一句，面板用 Login.vue 现成的那一行。
    if (!isReset.value && e.code === 40304) {
      emit('overdraft', { message: e.message, username: email.value.trim() })
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* Spec22 §7.10：分隔线用既有变量，不新增调色板 */
.ea-sep {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 14px 0 10px;
}
</style>
