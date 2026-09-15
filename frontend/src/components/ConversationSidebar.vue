<template>
  <!-- Spec17 §7.4：纯展示组件，状态全在 store 里（对话列表 / 当前对话 / 删除确认都在那边） -->
  <aside class="conv-sidebar">
    <div class="conv-sidebar-top">
      <button
        class="conv-sidebar-new"
        :disabled="currentId === null"
        :title="currentId === null ? '已经在空对话里了' : '开始一段新对话'"
        @click="emit('new')"
      >
        ＋ 新对话
      </button>
    </div>

    <div class="conv-list">
      <p v-if="!conversations.length" class="conv-empty">还没有对话，点「新对话」开始</p>
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: conv.id === currentId }"
      >
        <button class="conv-item-main" @click="emit('open', conv.id)">
          <span class="conv-item-time">{{ formatTime(conv.created_at) }}</span>
          <span class="conv-item-label">的对话</span>
        </button>
        <button class="conv-item-del" title="删除这段对话" @click="emit('delete', conv.id)">✕</button>
      </div>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  conversations: { type: Array, default: () => [] },
  currentId: { type: String, default: null }
})
const emit = defineEmits(['new', 'open', 'delete'])

// created_at（UTC ISO）→ 本地时区 YYYY-MM-DD HH:mm；一律精确到分，不做「今天/昨天」友好化（§2.1）
function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<!--
  样式全部在 assets/styles/main.css 的「对话历史侧边栏（Spec17 §7.4 / §7.8）」一节：
  侧边栏与 .app / .main-col 的 flex row 布局是一体的，拆成两处会看不出全貌。
-->
