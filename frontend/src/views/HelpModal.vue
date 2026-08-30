<template>
  <div class="help-overlay" @click.self="close">
    <div class="help-card" role="dialog" aria-modal="true" aria-label="使用帮助">
      <button class="help-close" title="关闭" @click="close">×</button>

      <h2 class="help-title">认识 ArtiControlNet</h2>
      <p class="help-lead">辅助设计的 AI 工作台——你说想法，它出图。三种玩法，照着说就行。</p>

      <div class="help-item">
        <p class="help-item-title">🎨 文生图</p>
        <p class="help-item-desc">没有参考图？直接描述想要的画面，它生成一张新图。</p>
        <p class="help-example">
          <span class="help-example-label">照着说</span>
          <code class="help-code">做一张赛博朋克风的新年海报</code>
        </p>
      </div>

      <div class="help-item">
        <p class="help-item-title">🖌 图文生图</p>
        <p class="help-item-desc">文字 + 参考图。把设计线稿传上来，按你的要求上色、上风格。</p>
        <p class="help-example">
          <span class="help-example-label">照着说</span>
          <code class="help-code">按这张线稿上色，日系动漫风</code>
        </p>
      </div>

      <div class="help-item">
        <p class="help-item-title">🔍 图片问答</p>
        <p class="help-item-desc">传一张图问它：评价、打分、分析都行。</p>
        <p class="help-example">
          <span class="help-example-label">照着说</span>
          <code class="help-code">这张图怎么样？帮我打个分</code>
        </p>
      </div>

      <p class="help-explore">✨ 以上三种只是基础玩法，更多神奇进阶功能，等你自己探索。</p>

      <div class="help-foot">
        <p class="help-tip">支持 jpg / png / webp / gif，≤10MB。每条消息都能带一张图。</p>
        <button class="btn-primary help-start" @click="close">开始使用</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted } from 'vue'

const emit = defineEmits(['close'])

function close() {
  emit('close')
}

function onKey(e) {
  if (e.key === 'Escape') close()
}

// 打开时锁 body 滚动，关闭时恢复（Spec8 §5.1）
onMounted(() => {
  document.addEventListener('keydown', onKey)
  document.body.style.overflow = 'hidden'
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.help-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(2px);
  animation: fade-in var(--transition-slow);
}

.help-card {
  position: relative;
  width: 100%;
  max-width: 560px;
  max-height: 88vh;
  overflow-y: auto;
  padding: 28px 28px 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  animation: slide-up var(--transition-normal);
}

.help-close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  background: var(--bg-surface-hover);
  color: var(--text-muted);
  font-size: 18px;
  line-height: 1;
  transition: all var(--transition-fast);
}

.help-close:hover {
  color: #fca5a5;
  background: rgba(127, 29, 29, 0.25);
}

.help-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-align: center;
  margin-bottom: 8px;
  background: linear-gradient(135deg, var(--purple-300), var(--purple-500));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.help-lead {
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.7;
  margin-bottom: 20px;
}

.help-item {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  margin-bottom: 12px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.help-item:hover {
  border-color: var(--purple-500);
  box-shadow: var(--shadow-glow);
}

.help-item-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.help-item-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 8px;
}

.help-example {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.help-example-label {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.help-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
  color: var(--purple-200);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 4px 10px;
  user-select: all;
  word-break: break-all;
}

.help-explore {
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  margin: 4px 0 16px;
}

.help-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--border-color);
  padding-top: 16px;
}

.help-tip {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}

.help-start {
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .help-card {
    padding: 22px 18px 18px;
  }
  .help-foot {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
  }
}
</style>
