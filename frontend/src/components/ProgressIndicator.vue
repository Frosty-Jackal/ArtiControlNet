<template>
  <div class="progress-indicator">
    <div class="progress-spinner">
      <svg class="spinner-ring" viewBox="0 0 40 40">
        <circle cx="20" cy="20" r="16" fill="none" stroke="currentColor"
          stroke-width="3" stroke-linecap="round"
          :stroke-dasharray="status === 'PROCESSING' ? '60 40' : '20 80'" />
      </svg>
    </div>
    <div class="progress-info">
      <span class="progress-label">{{ statusText }}</span>
      <span class="progress-dots">
        <span class="dot" v-for="i in 3" :key="i" :style="{ animationDelay: `${i * 0.15}s` }"></span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: 'PENDING' }
})

const statusText = computed(() => {
  switch (props.status) {
    case 'PENDING': return '排队中'
    case 'PROCESSING': return '正在生成'
    default: return '处理中'
  }
})
</script>

<style scoped>
.progress-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  animation: fade-in 0.3s ease;
}

.progress-spinner {
  width: 32px;
  height: 32px;
  color: var(--purple-400);
  flex-shrink: 0;
}

.spinner-ring {
  width: 100%;
  height: 100%;
  animation: spin 1.2s linear infinite;
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 4px;
}

.progress-label {
  font-size: 14px;
  color: var(--text-secondary);
}

.progress-dots {
  display: flex;
  gap: 3px;
  padding-top: 2px;
}

.dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--purple-400);
  animation: dot-bounce 1s infinite;
}
</style>
