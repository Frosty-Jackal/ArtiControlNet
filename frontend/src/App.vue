<template>
  <div class="app">
    <header class="app-header">
      <div class="brand">
        <span class="brand-dot"></span>
        <h1>ArtiControlNet</h1>
      </div>
      <span class="brand-sub">多智能体 AI 创意工作台</span>
      <button class="btn-clear" title="清空当前对话" @click="onClear">清空</button>
    </header>

    <main class="chat-scroll" ref="scrollRef">
      <div v-if="store.messages.length === 0" class="empty-state">
        <p class="empty-title">🎨 想要什么，直接说</p>
        <p class="empty-hint">
          “做一张新年海报” · “上传线稿让它上色” · “上传照片问它是什么”
        </p>
      </div>
      <ChatBubble
        v-for="m in store.messages"
        :key="m.id"
        :message="m"
        @retry="onRetry"
      />
      <TypingIndicator v-if="store.sending" />
    </main>

    <ChatInput :disabled="store.sending" @send="onSend" />
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { useChatStore } from './store/chat'
import ChatBubble from './components/ChatBubble.vue'
import ChatInput from './components/ChatInput.vue'
import TypingIndicator from './components/TypingIndicator.vue'

const store = useChatStore()
store.init()

const scrollRef = ref(null)
function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
watch(() => store.messages, scrollToBottom, { deep: true })
scrollToBottom()

function onSend(payload) {
  store.send(payload.text, payload.file)
}
function onRetry(errorId) {
  store.retry(errorId)
}
function onClear() {
  store.clear()
  scrollToBottom()
}
</script>
