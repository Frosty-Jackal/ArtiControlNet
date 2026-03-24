<template>
  <div class="adjust-toolbar" v-if="images.length > 0">
    <div class="toolbar-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
      <span>图像调整工具</span>
    </div>

    <div class="toolbar-actions">
      <button
        v-for="tool in tools"
        :key="tool.id"
        class="tool-btn"
        :class="{ active: activeTool === tool.id }"
        @click="selectTool(tool.id)"
        :title="tool.label"
      >
        <span class="tool-icon" v-html="tool.icon"></span>
        <span class="tool-label">{{ tool.label }}</span>
      </button>
    </div>

    <div class="toolbar-detail" v-if="activeTool">
      <div class="detail-row" v-if="activeTool === 'depth'">
        <label>深度强度</label>
        <input type="range" v-model.number="depthStrength" min="0" max="1" step="0.05" class="tool-range" />
        <span class="tool-val">{{ depthStrength.toFixed(2) }}</span>
      </div>
      <div class="detail-row" v-if="activeTool === 'color'">
        <label>色彩偏移</label>
        <input type="range" v-model.number="colorShift" min="-50" max="50" step="1" class="tool-range" />
        <span class="tool-val">{{ colorShift }}</span>
      </div>
      <div class="detail-row" v-if="activeTool === 'edge'">
        <label>边缘强度</label>
        <input type="range" v-model.number="edgeStrength" min="0" max="255" step="1" class="tool-range" />
        <span class="tool-val">{{ edgeStrength }}</span>
      </div>
      <div class="detail-row" v-if="activeTool === 'lens'">
        <label>模糊半径</label>
        <input type="range" v-model.number="lensBlur" min="0" max="20" step="1" class="tool-range" />
        <span class="tool-val">{{ lensBlur }}px</span>
      </div>
      <div class="detail-row" v-if="activeTool === 'correction'">
        <label>亮度</label>
        <input type="range" v-model.number="brightness" min="-50" max="50" step="1" class="tool-range" />
        <span class="tool-val">{{ brightness }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  images: { type: Array, default: () => [] }
})

const activeTool = ref(null)
const depthStrength = ref(0.5)
const colorShift = ref(0)
const edgeStrength = ref(128)
const lensBlur = ref(0)
const brightness = ref(0)

const tools = [
  { id: 'depth', label: '深度控制', icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>' },
  { id: 'color', label: '色彩检测', icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/><circle cx="8.5" cy="15.5" r="2.5"/></svg>' },
  { id: 'edge', label: '边缘检测', icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18"/></svg>' },
  { id: 'lens', label: '镜头效果', icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>' },
  { id: 'correction', label: '色彩校正', icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v18M5.5 7.5l13 9M5.5 16.5l13-9"/></svg>' }
]

function selectTool(id) {
  activeTool.value = activeTool.value === id ? null : id
}
</script>

<style scoped>
.adjust-toolbar {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  margin-top: 8px;
  animation: slide-up 0.3s ease;
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.toolbar-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 12px;
  transition: all var(--transition-fast);
}

.tool-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

.tool-btn.active {
  background: var(--purple-600);
  border-color: var(--purple-500);
  color: white;
}

.tool-icon {
  display: flex;
  align-items: center;
}

.toolbar-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.detail-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-row label {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 60px;
}

.tool-range {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
}

.tool-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--purple-400);
  cursor: pointer;
}

.tool-val {
  font-size: 12px;
  color: var(--purple-300);
  min-width: 40px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
