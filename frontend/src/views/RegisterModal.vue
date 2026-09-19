<template>
  <div class="reg-overlay" @click.self="close">
    <div class="reg-card" role="dialog" aria-modal="true" aria-label="新用户注册">
      <button class="reg-close" title="关闭" @click="close">×</button>

      <!-- Spec23 §7.1：结果屏整个删掉。注册成功 = 已经登录进系统了，
           弹窗随后被父级的 v-if 卸掉，没有"让你看清提示再自己关"这一步。 -->
      <template>
        <h2 class="reg-title">新用户注册</h2>

        <form class="reg-form" @submit.prevent="submit">
          <label class="reg-label">账号 <b class="reg-star">*</b></label>
          <input v-model="username" class="login-input" placeholder="2~32 个字符" autocomplete="off" />

          <label class="reg-label">密码 <b class="reg-star">*</b></label>
          <!-- Spec22 §2.10：placeholder 跟着后端的常量走（6 → 2）。仍然**不做**代码校验：
               长度规则只有一份中文 message，在后端。 -->
          <input v-model="password" type="password" class="login-input"
                 placeholder="至少 2 位" autocomplete="new-password" />

          <!-- Spec22 新增：二次确认。**纯前端**——后端收不到第二个框（§2.10），
               所以这个校验**必须**在前端，而且它不进 schemas、不进后端。 -->
          <label class="reg-label">确认密码 <b class="reg-star">*</b></label>
          <input v-model="confirmPassword" type="password" class="login-input"
                 placeholder="再输入一次" autocomplete="new-password" />

          <!-- Spec22：联系方式整段改掉 —— 删掉手机号输入框与那句"至少填一项"的 reg-hint -->
          <label class="reg-label">邮箱 <b class="reg-star">*</b></label>
          <p class="reg-hint">注册需要邮箱验证，验证码会发到这个邮箱</p>
          <div class="reg-code-row">
            <input v-model="email" class="login-input" type="email"
                   placeholder="邮箱" autocomplete="off" autocapitalize="off" />
            <button type="button" class="btn-code" :disabled="codeCooldown > 0 || sendingCode"
                    @click="sendCode">
              {{ codeCooldown > 0 ? `${codeCooldown}s` : (sendingCode ? '发送中…' : '获取验证码') }}
            </button>
          </div>
          <input v-model="code" class="login-input" type="text" inputmode="numeric" maxlength="4"
                 placeholder="4 位验证码" autocomplete="off" />

          <!-- Spec23 §7.1 删除：预充值提示 + 收款码（.reg-pay 那一块）。
               注册不再要求先付钱——新用户自带免费试用额度，用完再自助充值。
               ⚠️ .reg-pay / .reg-qr / .reg-pay-title 三条 CSS **保留**：
               RechargeModal 还在用它们（§7.8）。 -->
          <!-- Spec23 §7.1 删除：微信昵称那一组（标签 + 输入框）。
               注册与对账从此刻起完全无关——微信昵称只对充值有效（§3.3-6）。 -->
          <!-- Spec22 删除：<p class="reg-note">{{ config.daily_notice }}</p> ← 规则已不存在（§2.11） -->
          <p v-if="error" class="login-error">{{ error }}</p>
          <button class="btn-primary reg-submit" type="submit" :disabled="loading">
            {{ loading ? '提交中…' : '提交申请' }}
          </button>
        </form>
      </template>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { getEmailCode } from '../api/chatApi'
import { useAuthStore } from '../store/auth'

// Spec23 §7.1：`config` prop 整个删掉。它是 `GET /api/auth/register-config` 的
// 唯一消费者（收款码 + 预充值提示），而那块 UI 已经没了。
// ⚠️ Login.vue 那边 `regCfg` **仍然保留**：`enabled` 决定注册按钮画不画、
//    `contact_email` 是登录页那行客服——只是不再往这里面传。
const emit = defineEmits(['close'])

const auth = useAuthStore()

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const email = ref('')
const code = ref('')
const error = ref('')
const loading = ref(false)

// Spec22 §7.1：发码按钮的倒计时。**只是体验**——真正的 1 分钟冷却在后端（40906），
// 这里的数字不参与任何判定，刷新页面就没了，这是允许的（后端才是闸门）。
const sendingCode = ref(false)
const codeCooldown = ref(0)
let cooldownTimer = null

function close() {
  // 再来一次就重开一个组件（父级的 v-if 已经保证），所以这里不重置任何状态
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

// 组件销毁时清掉定时器（弹窗是 v-if 挂载的，关掉即销毁）
onBeforeUnmount(() => clearInterval(cooldownTimer))

async function sendCode() {
  // 只拦"必填"——邮箱格式规则在后端（40020），前端不复制（Spec19 §7.3 的立场不变）
  if (!email.value.trim()) {
    error.value = '请先填写邮箱'
    return
  }
  error.value = ''
  sendingCode.value = true
  try {
    await getEmailCode(email.value.trim(), 'register')
    startCooldown(60) // 与后端 EMAIL_CODE_RESEND_SECONDS 同值；客户端倒计时只是体验
  } catch (e) {
    // 40907（已注册 / 已提交过申请）与 50302（邮箱服务不可用）的 message 都是**后端给的原文**，
    // 前端零副本：直接显示成红字。这正是 §2.4 那句"已注册账号<用户名>…"的落点。
    error.value = e.message || '验证码发送失败'
  } finally {
    sendingCode.value = false
  }
}

async function submit() {
  // 只拦"必填"——那是 * 号承诺的东西，本地拦能立刻给反馈。
  // 邮箱 @ 位置、密码长度这些**不在前端复制**：它们各有自己的中文 message，
  // 已经在后端实现了一份（40018 / 40020），前端再抄一份就是第二个会漂移的副本。
  if (!username.value.trim() || !password.value) {
    // Spec23 §7.1：那句话原来提「微信昵称」，而输入框已经删了——
    // 提示语指向一个不存在的字段，正是 Spec22 §0 第 6-a 条记过的那类问题。
    error.value = '请填写账号与密码'
    return
  }
  if (password.value !== confirmPassword.value) {
    // Spec22 §2.10：后端收不到 confirm，这一句只能在前端说
    error.value = '两次输入的密码不一致'
    return
  }
  if (!email.value.trim()) {
    error.value = '请填写邮箱'
    return
  }
  // 码的**形状**（4 位数字）本地拦一道只是为了少一次往返；真正的判据在后端
  // （码错、码过期、码不属于这个邮箱，一律 40020「验证码错误或已过期」）。
  if (!/^\d{4}$/.test(code.value.trim())) {
    error.value = '请填写 4 位数字验证码'
    return
  }
  error.value = ''
  loading.value = true
  try {
    // Spec23 §2.5：一次调用完成"建号 + 登录"。store 里 token / username / is_admin
    // 三个一落，App.vue 的 v-if 自动切到聊天视图——**这里不需要 emit 任何东西**，
    // 组件随后被父级的 v-if 卸掉。这正是 loginByEmail 的收尾方式，照抄。
    await auth.register(username.value.trim(), password.value,
                        email.value.trim(), code.value.trim())
  } catch (e) {
    error.value = e.message || '注册失败'
  } finally {
    loading.value = false
  }
}
</script>
