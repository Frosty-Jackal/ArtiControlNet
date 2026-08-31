<template>
  <div
    class="input-area"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- Spec10：拖拽图片到输入区 → 浮层提示，松手即拾取 -->
    <div v-if="dragOver" class="input-drop-overlay">松开以添加参考图</div>

    <div v-if="preview" class="attach-row">
      <div class="attach-preview">
        <img :src="preview" alt="附件预览" />
        <button class="attach-remove" title="移除附件" @click="clearFile">×</button>
      </div>
    </div>

    <div class="input-row">
      <button class="btn-attach" title="上传参考图" @click="fileEl.click()">🖼</button>
      <textarea
        ref="textEl"
        v-model="text"
        class="input-text"
        rows="1"
        placeholder="描述你的想法，可附参考图…"
        @keydown.enter.exact.prevent="submit"
        @input="autoResize"
      ></textarea>
      <button class="btn-send" :disabled="!canSend || disabled" @click="submit">发送</button>
      <input
        ref="fileEl"
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        hidden
        @change="onFile"
      />
    </div>
    <p class="input-hint">支持 jpg / png / webp / gif，≤10MB</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['send'])

const text = ref('')
const file = ref(null)
const preview = ref('')
const textEl = ref(null)
const fileEl = ref(null)
const dragOver = ref(false) // Spec10：拖拽高亮
let dragDepth = 0 // 拖入/拖出计数，避免子元素间 dragleave 抖动

const canSend = computed(() => text.value.trim().length > 0 || !!file.value)

// 点击选择与拖拽共用同一份校验 + 拾取逻辑（Spec10）
function acceptFile(f) {
  const okType = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(f.type)
  if (!okType) {
    alert('仅支持 jpg / png / webp / gif 图片')
    return false
  }
  if (f.size > 10 * 1024 * 1024) {
    alert('图片超过 10MB，请压缩后再试')
    return false
  }
  return true
}

function setFile(f) {
  if (preview.value) URL.revokeObjectURL(preview.value)
  file.value = f
  preview.value = URL.createObjectURL(f)
}

function onFile(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  if (!acceptFile(f)) {
    fileEl.value.value = ''
    return
  }
  setFile(f)
}

function onDragEnter() {
  dragDepth += 1
  dragOver.value = true
}

function onDragLeave() {
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragOver.value = false
  }
}

function onDrop(e) {
  dragDepth = 0
  dragOver.value = false
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]
  if (!f) return
  if (!acceptFile(f)) return
  setFile(f)
}

function clearFile() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  file.value = null
  preview.value = ''
  if (fileEl.value) fileEl.value.value = ''
}

function autoResize() {
  const el = textEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function submit() {
  if (!canSend.value || props.disabled) return
  emit('send', { text: text.value.trim(), file: file.value })
  text.value = ''
  clearFile()
  autoResize()
}
</script>

<style scoped>
.input-area {
  position: relative; /* Spec10：拖拽浮层定位锚点 */
}

.input-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(12, 9, 21, 0.9);
  border: 2px dashed var(--purple-500);
  border-radius: var(--radius-lg);
  color: var(--purple-300);
  font-size: 14px;
  font-weight: 600;
  pointer-events: none;
  animation: fade-in var(--transition-fast);
}
</style>
