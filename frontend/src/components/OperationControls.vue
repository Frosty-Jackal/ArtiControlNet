<template>
  <div class="operation-controls" v-if="images.length > 0">
    <button class="op-btn" @click="$emit('regenerate')" :disabled="disabled">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <polyline points="23 4 23 10 17 10"/>
        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
      </svg>
      <span>重新生成</span>
    </button>
    <button class="op-btn" @click="$emit('variation')" :disabled="disabled">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <rect x="2" y="2" width="9" height="9" rx="1"/>
        <rect x="13" y="13" width="9" height="9" rx="1"/>
        <path d="M13 2h4a2 2 0 0 1 2 2v4M2 13v4a2 2 0 0 0 2 2h4"/>
      </svg>
      <span>二次生成</span>
    </button>
    <button class="op-btn" @click="downloadImage" :disabled="!images.length">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      <span>下载图片</span>
    </button>
  </div>
</template>

<script setup>
const props = defineProps({
  images: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false }
})

defineEmits(['regenerate', 'variation'])

function downloadImage() {
  if (!props.images.length) return
  const resultImages = props.images.slice(1)
  const target = resultImages.length ? resultImages[0] : props.images[0]

  const link = document.createElement('a')
  link.href = target
  link.download = `arti-controlnet-${Date.now()}.png`
  link.click()
}
</script>

<style scoped>
.operation-controls {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.op-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 13px;
  transition: all var(--transition-fast);
}

.op-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  border-color: var(--purple-600);
}

.op-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
