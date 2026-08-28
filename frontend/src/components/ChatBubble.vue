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
defineEmits(['retry'])

// 只在助手文本上渲染 Markdown（用户消息保持纯文本）
const renderedText = computed(() => renderMarkdown(props.message.text || ''))
</script>
