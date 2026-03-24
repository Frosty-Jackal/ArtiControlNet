<template>
  <Transition name="panel">
    <div class="config-overlay" v-if="visible" @click.self="$emit('close')">
      <div class="config-panel">
        <div class="panel-header">
          <h3>高级参数设置</h3>
          <button class="close-btn" @click="$emit('close')">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div class="panel-body">
          <div class="config-section">
            <label class="config-label">正向附加提示词</label>
            <textarea v-model="localSettings.aPrompt" rows="2" class="config-textarea" />
          </div>

          <div class="config-section">
            <label class="config-label">负向提示词</label>
            <textarea v-model="localSettings.nPrompt" rows="2" class="config-textarea" />
          </div>

          <div class="config-grid">
            <div class="config-item">
              <label class="config-label">生成张数</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.numSamples" min="1" max="4" step="1" class="config-range" />
                <span class="config-value">{{ localSettings.numSamples }}</span>
              </div>
            </div>

            <div class="config-item">
              <label class="config-label">图片分辨率</label>
              <select v-model.number="localSettings.imageResolution" class="config-select">
                <option :value="256">256</option>
                <option :value="384">384</option>
                <option :value="512">512</option>
                <option :value="768">768</option>
              </select>
            </div>

            <div class="config-item">
              <label class="config-label">采样步数</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.ddimSteps" min="1" max="50" step="1" class="config-range" />
                <span class="config-value">{{ localSettings.ddimSteps }}</span>
              </div>
            </div>

            <div class="config-item">
              <label class="config-label">CFG Scale</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.scale" min="1" max="20" step="0.5" class="config-range" />
                <span class="config-value">{{ localSettings.scale }}</span>
              </div>
            </div>

            <div class="config-item">
              <label class="config-label">控制强度</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.strength" min="0" max="2" step="0.1" class="config-range" />
                <span class="config-value">{{ localSettings.strength.toFixed(1) }}</span>
              </div>
            </div>

            <div class="config-item">
              <label class="config-label">随机种子</label>
              <input type="number" v-model.number="localSettings.seed" class="config-input" placeholder="-1 为随机" />
            </div>

            <div class="config-item">
              <label class="config-label">Canny 低阈值</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.lowThreshold" min="1" max="255" step="1" class="config-range" />
                <span class="config-value">{{ localSettings.lowThreshold }}</span>
              </div>
            </div>

            <div class="config-item">
              <label class="config-label">Canny 高阈值</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.highThreshold" min="1" max="255" step="1" class="config-range" />
                <span class="config-value">{{ localSettings.highThreshold }}</span>
              </div>
            </div>

            <div class="config-item">
              <label class="config-label">DDIM Eta</label>
              <div class="config-slider-row">
                <input type="range" v-model.number="localSettings.eta" min="0" max="1" step="0.1" class="config-range" />
                <span class="config-value">{{ localSettings.eta.toFixed(1) }}</span>
              </div>
            </div>

            <div class="config-item config-toggle-item">
              <label class="config-label">猜测模式</label>
              <button
                class="toggle-btn"
                :class="{ active: localSettings.guessMode }"
                @click="localSettings.guessMode = !localSettings.guessMode"
              >
                <span class="toggle-knob"></span>
              </button>
            </div>
          </div>
        </div>

        <div class="panel-footer">
          <button class="btn-reset" @click="resetToDefault">恢复默认</button>
          <button class="btn-apply" @click="applySettings">应用设置</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  visible: Boolean,
  settings: Object
})

const emit = defineEmits(['close', 'update:settings'])

const localSettings = reactive({ ...props.settings })

watch(() => props.settings, (val) => {
  Object.assign(localSettings, val)
}, { deep: true })

const defaults = {
  aPrompt: 'best quality, extremely detailed',
  nPrompt: 'longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality',
  numSamples: 1,
  imageResolution: 512,
  ddimSteps: 20,
  guessMode: false,
  strength: 1.0,
  scale: 9.0,
  seed: -1,
  eta: 0.0,
  lowThreshold: 100,
  highThreshold: 200
}

function resetToDefault() {
  Object.assign(localSettings, defaults)
}

function applySettings() {
  emit('update:settings', { ...localSettings })
  emit('close')
}
</script>

<style scoped>
.config-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.config-panel {
  width: 520px;
  max-width: 92vw;
  max-height: 85vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg), var(--shadow-glow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid var(--border-color);
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.close-btn:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.config-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.config-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.config-textarea {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-primary);
  resize: vertical;
  transition: border-color var(--transition-fast);
}

.config-textarea:focus {
  border-color: var(--purple-500);
}

.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.config-slider-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.config-range {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  outline: none;
}

.config-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--purple-500);
  cursor: pointer;
  transition: transform var(--transition-fast);
}

.config-range::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.config-value {
  font-size: 13px;
  color: var(--purple-300);
  min-width: 36px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.config-select, .config-input {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text-primary);
  transition: border-color var(--transition-fast);
}

.config-select:focus, .config-input:focus {
  border-color: var(--purple-500);
}

.config-select option {
  background: var(--bg-secondary);
}

.config-toggle-item {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.toggle-btn {
  width: 42px;
  height: 24px;
  border-radius: 12px;
  background: var(--border-color);
  padding: 2px;
  transition: background var(--transition-normal);
  position: relative;
}

.toggle-btn.active {
  background: var(--purple-600);
}

.toggle-knob {
  display: block;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: white;
  transition: transform var(--transition-normal);
}

.toggle-btn.active .toggle-knob {
  transform: translateX(18px);
}

.panel-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--border-color);
}

.btn-reset, .btn-apply {
  padding: 8px 20px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.btn-reset {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.btn-reset:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}

.btn-apply {
  background: var(--purple-600);
  color: white;
}

.btn-apply:hover {
  background: var(--purple-700);
}

.panel-enter-active, .panel-leave-active {
  transition: opacity 0.25s ease;
}
.panel-enter-active .config-panel, .panel-leave-active .config-panel {
  transition: transform 0.25s ease, opacity 0.25s ease;
}
.panel-enter-from, .panel-leave-to {
  opacity: 0;
}
.panel-enter-from .config-panel, .panel-leave-to .config-panel {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}
</style>
