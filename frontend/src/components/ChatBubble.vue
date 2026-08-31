<template>
  <div class="bubble-row" :class="message.role === 'user' ? 'row-user' : 'row-assistant'">
    <div class="bubble" :class="message.role === 'user' ? 'bubble-user' : 'bubble-assistant'">
      <!-- 用户消息：文本 + 图片 -->
      <template v-if="message.role === 'user'">
        <img
          v-if="message.imageUrl || message.imageUrlPreview"
          :src="message.imageUrl || message.imageUrlPreview"
          class="bubble-img user-img"
          alt="参考图"
        />
        <p v-if="message.text" class="bubble-text">{{ message.text }}</p>
      </template>

      <!-- 助手：生成中 -->
      <div v-else-if="message.kind === 'pending'" class="pending">
        <TypingIndicator />
      </div>

      <!-- 助手：文本（Markdown 渲染） -->
      <div v-else-if="message.kind === 'text'" class="bubble-text markdown-body" v-html="renderedText" />

      <!-- 助手：结果图 -->
      <div v-else-if="message.kind === 'images'" class="images-grid">
        <a
          v-for="(img, i) in message.images"
          :key="i"
          class="image-link"
          :href="img"
          target="_blank"
          rel="noopener"
          :title="'查看大图 ' + (i + 1)"
        >
          <img :src="img" class="bubble-img result-img" :alt="'生成结果 ' + (i + 1)" loading="lazy" />
        </a>
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
import { renderMarkdown } from '../utils/markdown'

const props = defineProps({
  message: { type: Object, required: true }
})
defineEmits(['retry', 'vote'])

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
