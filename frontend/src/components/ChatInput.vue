<template>
  <div class="input-area">
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

const canSend = computed(() => text.value.trim().length > 0 || !!file.value)

function onFile(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  // 客户端校验：格式与大小
  const okType = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(f.type)
  if (!okType) {
    alert('仅支持 jpg / png / webp / gif 图片')
    fileEl.value.value = ''
    return
  }
  if (f.size > 10 * 1024 * 1024) {
    alert('图片超过 10MB，请压缩后再试')
    fileEl.value.value = ''
    return
  }
  if (preview.value) URL.revokeObjectURL(preview.value)
  file.value = f
  preview.value = URL.createObjectURL(f)
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
