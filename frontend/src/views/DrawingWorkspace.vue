<template>
  <div class="workspace">
    <!-- 顶栏 -->
    <header class="top-bar">
      <div class="brand">
        <div class="brand-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" fill="url(#brand-grad)" opacity="0.9"/>
            <path d="M2 17l10 5 10-5" stroke="url(#brand-grad)" stroke-width="2" fill="none" stroke-linecap="round"/>
            <path d="M2 12l10 5 10-5" stroke="url(#brand-grad)" stroke-width="2" fill="none" stroke-linecap="round"/>
            <defs>
              <linearGradient id="brand-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#c084fc"/>
                <stop offset="100%" stop-color="#7c3aed"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <span class="brand-name">ArtiControlNet</span>
      </div>
      <div class="top-actions">
        <button class="icon-btn" @click="chatStore.settingsVisible = true" title="高级参数设置">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>
            <line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>
            <line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/>
            <line x1="17" y1="16" x2="23" y2="16"/>
          </svg>
        </button>
        <button class="icon-btn" @click="clearChat" title="清空对话">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
        </button>
      </div>
    </header>

    <!-- 聊天消息区 -->
    <main class="chat-area" ref="chatAreaRef">
      <div class="chat-messages">
        <div
          v-for="msg in chatStore.messages"
          :key="msg.id"
          class="message-row"
          :class="msg.role"
        >
          <!-- 头像 -->
          <div class="avatar" :class="msg.role">
            <template v-if="msg.role === 'user'">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
            </template>
            <template v-else>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M12 2L2 7l10 5 10-5-10-5z" fill="currentColor" opacity="0.8"/>
                <path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="2" fill="none"/>
                <path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" fill="none"/>
              </svg>
            </template>
          </div>

          <!-- 消息气泡 -->
          <div class="bubble-wrapper">
            <!-- 用户消息：显示提示词+上传的图片 -->
            <template v-if="msg.role === 'user'">
              <div class="bubble user-bubble">
                <p class="msg-text">{{ msg.content }}</p>
                <div class="user-image-preview" v-if="msg.image">
                  <img :src="msg.image" alt="参考图" />
                </div>
              </div>
            </template>

            <!-- AI 消息 -->
            <template v-else>
              <!-- 普通文本消息 -->
              <div class="bubble assistant-bubble" v-if="msg.type === 'text'">
                <p class="msg-text">{{ msg.content }}</p>
              </div>

              <!-- 生成中 -->
              <div class="bubble assistant-bubble" v-else-if="msg.type === 'generating'">
                <ProgressIndicator :status="msg.status" />
              </div>

              <!-- 生成结果 -->
              <div class="bubble assistant-bubble result-bubble" v-else-if="msg.type === 'result'">
                <p class="result-header">生成完成</p>
                <div class="result-images">
                  <div
                    v-for="(img, idx) in msg.images"
                    :key="idx"
                    class="result-image-card"
                    @click="openPreview(img)"
                  >
                    <img :src="img" :alt="idx === 0 ? 'Canny 边缘图' : `生成结果 ${idx}`" />
                    <span class="image-label">{{ idx === 0 ? '边缘图' : `结果 ${idx}` }}</span>
                  </div>
                </div>
                <OperationControls
                  :images="msg.images"
                  :disabled="chatStore.isGenerating"
                  @regenerate="handleRegenerate(msg)"
                  @variation="handleVariation(msg)"
                />
                <AdjustToolbar :images="msg.images" />
              </div>

              <!-- 错误 -->
              <div class="bubble assistant-bubble error-bubble" v-else-if="msg.type === 'error'">
                <div class="error-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
                  </svg>
                </div>
                <p class="msg-text">{{ msg.content }}</p>
              </div>
            </template>

            <span class="msg-time">{{ formatTime(msg.timestamp) }}</span>
          </div>
        </div>
      </div>
    </main>

    <!-- 输入区域 -->
    <footer class="input-area">
      <div class="input-container">
        <!-- 图片上传预览 -->
        <div class="upload-preview" v-if="selectedImage">
          <img :src="imagePreviewUrl" alt="preview" />
          <button class="remove-image" @click="removeImage">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div class="input-row">
          <!-- 上传图片按钮 -->
          <button class="attach-btn" @click="triggerFileInput" title="上传参考图片">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <polyline points="21 15 16 10 5 21"/>
            </svg>
          </button>
          <input
            type="file"
            ref="fileInputRef"
            accept="image/*"
            style="display:none"
            @change="onFileSelected"
          />

          <!-- 文本输入框 -->
          <div class="text-input-wrapper">
            <textarea
              ref="textareaRef"
              v-model="promptText"
              placeholder="输入提示词描述你想要生成的图像..."
              rows="1"
              @keydown.enter.exact="handleSend"
              @input="autoResize"
            ></textarea>
          </div>

          <!-- 发送按钮 -->
          <button
            class="send-btn"
            :class="{ active: canSend }"
            :disabled="!canSend"
            @click="handleSend"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>

        <p class="input-hint">
          上传参考图片 + 输入提示词，按 Enter 发送。
          <span class="hint-link" @click="chatStore.settingsVisible = true">调整高级参数</span>
        </p>
      </div>
    </footer>

    <!-- 图片预览弹窗 -->
    <Transition name="preview">
      <div class="preview-overlay" v-if="previewImage" @click="previewImage = null">
        <img :src="previewImage" alt="preview" class="preview-img" @click.stop />
        <button class="preview-close" @click="previewImage = null">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- 参数设置面板 -->
    <DrawConfigPanel
      :visible="chatStore.settingsVisible"
      :settings="chatStore.settings"
      @close="chatStore.settingsVisible = false"
      @update:settings="v => Object.assign(chatStore.settings, v)"
    />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { useChatStore } from '../store/index.js'
import ProgressIndicator from '../components/ProgressIndicator.vue'
import DrawConfigPanel from '../components/DrawConfigPanel.vue'
import AdjustToolbar from '../components/AdjustToolbar.vue'
import OperationControls from '../components/OperationControls.vue'

const chatStore = useChatStore()

const promptText = ref('')
const selectedImage = ref(null)
const imagePreviewUrl = ref(null)
const previewImage = ref(null)

const chatAreaRef = ref(null)
const textareaRef = ref(null)
const fileInputRef = ref(null)

const canSend = computed(() => {
  return promptText.value.trim() && selectedImage.value && !chatStore.isGenerating
})

function triggerFileInput() {
  fileInputRef.value?.click()
}

function onFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file) return
  selectedImage.value = file
  imagePreviewUrl.value = URL.createObjectURL(file)
  e.target.value = ''
}

function removeImage() {
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  selectedImage.value = null
  imagePreviewUrl.value = null
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

async function handleSend(e) {
  if (e instanceof KeyboardEvent) e.preventDefault()
  if (!canSend.value) return

  const prompt = promptText.value.trim()
  const imageFile = selectedImage.value

  promptText.value = ''
  selectedImage.value = null
  imagePreviewUrl.value = null

  nextTick(() => {
    if (textareaRef.value) textareaRef.value.style.height = 'auto'
  })

  await chatStore.sendGenerateRequest(prompt, imageFile)
}

function handleRegenerate(msg) {
  if (!msg.taskId) return
  // TODO: 从历史记录中提取参数重新提交
}

function handleVariation(msg) {
  if (!msg.taskId) return
  // TODO: 基于上次结果进行二次生成
}

function openPreview(src) {
  previewImage.value = src
}

function clearChat() {
  chatStore.messages.splice(1)
}

function formatTime(ts) {
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

watch(
  () => chatStore.messages.length,
  () => {
    nextTick(() => {
      const el = chatAreaRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }
)
</script>

<style scoped>
.workspace {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
}

/* ===== 顶栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.15), rgba(192, 132, 252, 0.08));
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-name {
  font-size: 17px;
  font-weight: 700;
  background: linear-gradient(135deg, var(--purple-300), var(--purple-500));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: 0.3px;
}

.top-actions {
  display: flex;
  gap: 4px;
}

.icon-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}

/* ===== 聊天区域 ===== */
.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 0;
}

.chat-messages {
  max-width: 800px;
  margin: 0 auto;
  padding: 0 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.message-row {
  display: flex;
  gap: 12px;
  animation: slide-up 0.3s ease;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.avatar.user {
  background: linear-gradient(135deg, var(--purple-600), var(--purple-800));
  color: white;
}

.avatar.assistant {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--purple-400);
}

.bubble-wrapper {
  max-width: 75%;
  min-width: 0;
}

.message-row.user .bubble-wrapper {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.bubble {
  border-radius: var(--radius-md);
  padding: 12px 16px;
  word-break: break-word;
}

.user-bubble {
  background: linear-gradient(135deg, var(--purple-600), var(--purple-700));
  color: white;
  border-bottom-right-radius: 4px;
}

.assistant-bubble {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-bottom-left-radius: 4px;
}

.msg-text {
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.msg-time {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
  opacity: 0.7;
}

.message-row.user .msg-time {
  text-align: right;
}

/* 用户上传图片预览 */
.user-image-preview {
  margin-top: 10px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  max-width: 200px;
}

.user-image-preview img {
  width: 100%;
  display: block;
  border-radius: var(--radius-sm);
}

/* 生成结果 */
.result-bubble {
  padding: 16px;
}

.result-header {
  font-size: 14px;
  color: var(--purple-300);
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.result-header::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  display: inline-block;
}

.result-images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}

.result-image-card {
  position: relative;
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  border: 1px solid var(--border-color);
  transition: all var(--transition-fast);
}

.result-image-card:hover {
  border-color: var(--purple-500);
  box-shadow: var(--shadow-glow);
  transform: translateY(-2px);
}

.result-image-card img {
  width: 100%;
  display: block;
  aspect-ratio: 1;
  object-fit: cover;
}

.image-label {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 4px 8px;
  background: linear-gradient(transparent, rgba(0,0,0,0.7));
  font-size: 11px;
  color: rgba(255,255,255,0.9);
  text-align: center;
}

/* 错误消息 */
.error-bubble {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  border-color: rgba(239, 68, 68, 0.3);
}

.error-icon {
  color: #ef4444;
  flex-shrink: 0;
  margin-top: 1px;
}

.error-bubble .msg-text {
  color: #fca5a5;
}

/* ===== 输入区域 ===== */
.input-area {
  flex-shrink: 0;
  padding: 16px 20px 20px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
}

.input-container {
  max-width: 800px;
  margin: 0 auto;
}

.upload-preview {
  position: relative;
  display: inline-block;
  margin-bottom: 10px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.upload-preview img {
  height: 64px;
  width: auto;
  display: block;
  border-radius: var(--radius-sm);
}

.remove-image {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.65);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition-fast);
}

.remove-image:hover {
  background: rgba(239, 68, 68, 0.8);
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 8px 8px 8px 4px;
  transition: border-color var(--transition-fast);
}

.input-row:focus-within {
  border-color: var(--purple-500);
  box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.1);
}

.attach-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.attach-btn:hover {
  color: var(--purple-400);
  background: rgba(124, 58, 237, 0.1);
}

.text-input-wrapper {
  flex: 1;
  min-width: 0;
}

.text-input-wrapper textarea {
  width: 100%;
  background: transparent;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  padding: 8px 4px;
  max-height: 120px;
}

.text-input-wrapper textarea::placeholder {
  color: var(--text-muted);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--border-color);
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-normal);
}

.send-btn.active {
  background: linear-gradient(135deg, var(--purple-500), var(--purple-700));
  color: white;
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.3);
}

.send-btn.active:hover {
  transform: scale(1.05);
}

.send-btn:disabled {
  cursor: not-allowed;
}

.input-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
  text-align: center;
}

.hint-link {
  color: var(--purple-400);
  cursor: pointer;
  transition: color var(--transition-fast);
}

.hint-link:hover {
  color: var(--purple-300);
  text-decoration: underline;
}

/* ===== 图片预览 ===== */
.preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 40px;
}

.preview-img {
  max-width: 90vw;
  max-height: 85vh;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  object-fit: contain;
}

.preview-close {
  position: absolute;
  top: 20px;
  right: 20px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition-fast);
}

.preview-close:hover {
  background: rgba(255, 255, 255, 0.2);
}

.preview-enter-active, .preview-leave-active {
  transition: opacity 0.25s ease;
}
.preview-enter-from, .preview-leave-to {
  opacity: 0;
}

/* ===== 响应式 ===== */
@media (max-width: 640px) {
  .bubble-wrapper {
    max-width: 88%;
  }

  .result-images {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }

  .brand-name {
    font-size: 15px;
  }
}
</style>
