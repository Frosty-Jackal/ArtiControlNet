<template>
  <!-- Spec24 §2.3：面板组件对游客整个不挂载，由它占位。
       它必须**不发任何请求** —— 一挂载就发请求的话，游客会立刻吃一个 401，
       chatApi.js 的拦截器会派发 artcn:unauthorized，全局登出（§2.3）。 -->
  <div class="login-gate">
    <p class="gate-title">🔒 {{ label }}需要登录后查看</p>
    <p class="gate-hint">登录后可以发送设计需求、保存自己的作品、在社区发帖与提建议。</p>
    <div class="gate-actions">
      <button class="gate-login" @click="emit('login')">登录 / 注册</button>
      <button class="gate-back" @click="emit('close')">返回聊天</button>
    </div>
  </div>
</template>

<script setup>
// Spec24 §5.5：纯展示组件，零 API、零 store。文案里的 label 由 App.vue 给。
defineProps({
  label: { type: String, default: '该页面' } // '我的作品' / '社区' / '建议' …
})
const emit = defineEmits(['login', 'close'])
</script>

<style scoped>
.login-gate {
  flex: 1;                    /* 顶满 main-col 的剩余高度，和面板同款 */
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 24px;
  text-align: center;
}
.gate-title { font-size: 16px; color: var(--text-secondary); }
.gate-hint { font-size: 13px; color: var(--text-muted); max-width: 320px; line-height: 1.7; }
.gate-actions { display: flex; gap: 10px; margin-top: 8px; }
.gate-login {
  padding: 8px 20px;
  font-size: 13px;
  color: #fff;
  background: var(--purple-500);
  border-radius: var(--radius-full);
  transition: background var(--transition-fast);
}
.gate-login:hover { background: var(--purple-600); }
.gate-back {
  padding: 8px 20px;
  font-size: 13px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-full);
  transition: all var(--transition-fast);
}
</style>
