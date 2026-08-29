<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-dot"></span>
        <h1>ArtiControlNet</h1>
      </div>
      <p class="login-sub">多智能体 AI 创意工作台 · 登录后使用</p>

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
import { ref } from 'vue'
import { useAuthStore } from '../store/auth'

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

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
  } finally {
    loading.value = false
  }
}
</script>
