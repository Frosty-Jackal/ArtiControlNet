<template>
  <div class="login-page">
    <div class="login-card">
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
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useAuthStore } from '../store/auth'
import { takeQuotaNotice } from '../utils/quotaNotice'

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

// Spec18 §7.4：落地到登录页时，若有一条待显示的限额警告 → 红色提示行 + 弹窗。
// 用户原话要求"弹出提示警告"，所以是 window.alert（而不是只写一行小字）。
onMounted(() => {
  const msg = takeQuotaNotice()
  if (msg) {
    error.value = msg
    window.alert(msg)
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
    // Spec18 §7.4：超额被拒时同样弹窗（错误对象带 code，见 api/chatApi.js）
    if (e.code === 40304) window.alert(e.message)
  } finally {
    loading.value = false
  }
}
</script>
