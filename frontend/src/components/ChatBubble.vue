<template>
  <div class="bubble-row" :class="message.role === 'user' ? 'row-user' : 'row-assistant'">
    <div class="bubble" :class="message.role === 'user' ? 'bubble-user' : 'bubble-assistant'">
      <!-- 用户消息：文本 + 图片（Spec17 §7.6：图片走作品库引用，本地预览只用于"上传中"） -->
      <template v-if="message.role === 'user'">
        <template v-if="hasImage">
          <div v-if="imageMissing" class="bubble-img bubble-img-missing">图片已删除</div>
          <img v-else-if="imageSrc" :src="imageSrc" class="bubble-img user-img" alt="参考图" />
          <div v-else class="bubble-img bubble-img-missing">…</div>
        </template>
        <p v-if="message.text" class="bubble-text">{{ message.text }}</p>
      </template>

      <!-- 助手：生成中 -->
      <div v-else-if="message.kind === 'pending'" class="pending">
        <TypingIndicator />
      </div>

      <!-- 助手：文本（Markdown 渲染） -->
      <div v-else-if="message.kind === 'text'" class="bubble-text markdown-body" v-html="renderedText" />

      <!-- 助手：结果图（单个 image_id → 作品库；已被删除时渲染占位，不可点开大图） -->
      <div v-else-if="message.kind === 'images'" class="images-grid">
        <div v-if="imageMissing" class="bubble-img bubble-img-missing">图片已删除</div>
        <a
          v-else-if="imageSrc"
          class="image-link"
          :href="imageSrc"
          target="_blank"
          rel="noopener"
          title="查看大图"
        >
          <img :src="imageSrc" class="bubble-img result-img" alt="生成结果" loading="lazy" />
        </a>
        <div v-else class="bubble-img bubble-img-missing">…</div>
      </div>

      <!-- 助手：失败 + 重试 -->
      <div v-else-if="message.kind === 'error'" class="error-box">
        <p class="error-text">😥 {{ message.error }}</p>
        <button v-if="message.request" class="btn-retry" @click="$emit('retry', message.id)">
          重试
        </button>
      </div>

      <!-- Spec9：工具结果（文生图/图文生图/图像QA）下方 👍/👎 反馈行；再点同一项取消 -->
      <div v-if="isToolResult" class="bubble-actions">
        <button
          class="btn-mini feedback-btn"
          :class="{ 'feedback-on': message.vote === 'like' }"
          @click="$emit('vote', message, 'like')"
        >
          👍 {{ message.vote === 'like' ? '已觉得有用' : '有用' }}
        </button>
        <button
          class="btn-mini feedback-btn"
          :class="{ 'feedback-on dislike': message.vote === 'dislike' }"
          @click="$emit('vote', message, 'dislike')"
        >
          👎 {{ message.vote === 'dislike' ? '已觉得没用' : '没用' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import TypingIndicator from './TypingIndicator.vue'
import { useAuthedImage } from '../composables/useAuthedImage'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({
  message: { type: Object, required: true }
})
defineEmits(['retry', 'vote'])

// 站内图片（作品库文件）带 token 拉取 → objectURL；404 = 图片已被删（Spec17 §3.4）
const { src: authedSrc, missing: authedMissing } = useAuthedImage(() => props.message.imageId)

// 用户消息可能仍在上传（只有本地预览），此时 imageId 还是空
const hasImage = computed(() => !!(props.message.imageId || props.message.imageUrlPreview))
const imageSrc = computed(() => authedSrc.value || props.message.imageUrlPreview || '')
// 只有"确实引用了作品库图片"才谈缺失；纯本地预览阶段不算
const imageMissing = computed(() => !!props.message.imageId && authedMissing.value)

// 只在助手文本上渲染 Markdown（用户消息保持纯文本）
const renderedText = computed(() => renderMarkdown(props.message.text || ''))

// Spec9：三类生成服务的工具结果才渲染反馈行；纯对话、pending、error 不渲染
const TOOL_RESULTS = ['generate_image', 'edit_image', 'qa_image']
const isToolResult = computed(() => {
  const m = props.message
  return (
    m.role === 'assistant' &&
    m.tool &&
    TOOL_RESULTS.includes(m.tool) &&
    (m.kind === 'text' || m.kind === 'images')
  )
})
</script>

<style scoped>
.bubble-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.feedback-btn {
  font-size: 12px;
}

.feedback-on {
  color: #fff;
  background: var(--purple-600);
  border-color: var(--purple-600);
}

.feedback-on.dislike {
  background: var(--bg-input);
  border-color: var(--text-muted);
  color: var(--text-secondary);
}
</style>
