<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>数据统计</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>
    <p class="admin-tip">
      当前登录：{{ auth.username }}（管理员）
      · 数据仅展示聚合统计，不含个人内容
    </p>

    <p v-if="error" class="login-error">{{ error }}</p>

    <!-- Spec11：统计区头部条 = 摘要 + 清零时间 + 清零按钮 -->
    <div class="usage-head">
      <p class="admin-notice stats-summary">
        注册用户 {{ stats.user_count }} 人 · 调用总次数 {{ stats.total_calls }}
        <span class="cleared-hint">· 上次清零：{{ usageClearedText }}</span>
      </p>
      <button class="btn-mini" :disabled="clearingUsage" @click="clearUsageStats">
        清空调用统计
      </button>
    </div>

    <div class="admin-table-wrap">
      <table class="user-table">
        <thead>
          <tr>
            <th>类型</th>
            <th>总数</th>
            <th>占比</th>
            <th>人均次数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key">
            <td>{{ row.label }}</td>
            <td>{{ row.total }}</td>
            <td>{{ row.share }}%</td>
            <td>{{ row.avg }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Spec9：AI 服务反馈汇总（仅统计，不含明细） -->
    <div class="admin-table-wrap feedback-wrap">
      <div class="feedback-head">
        <div class="head-titles">
          <h3>AI 服务反馈</h3>
          <span class="cleared-hint">上次清零：{{ feedbackClearedText }}</span>
        </div>
        <button class="btn-mini" :disabled="clearing" @click="clearFeedbackStats">
          清空反馈统计
        </button>
      </div>
      <table class="user-table">
        <thead>
          <tr>
            <th>服务类型</th>
            <th>👍 有用</th>
            <th>👎 没用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in FEEDBACK_ROWS" :key="row.key">
            <td>{{ row.label }}</td>
            <td>{{ (feedbackTotals[row.key] && feedbackTotals[row.key].like) || 0 }}</td>
            <td>{{ (feedbackTotals[row.key] && feedbackTotals[row.key].dislike) || 0 }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { clearFeedback, clearUsage, getUsageStats } from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const stats = ref({
  user_count: 0,
  total_calls: 0,
  totals: {},
  per_user_avg: {},
  shares: {},
  feedback_totals: {},
  usage_cleared_at: null,    // Spec11：两个清零时间（null = 从未清零）
  feedback_cleared_at: null
})
const error = ref('')
const clearing = ref(false)      // 反馈清空进行中
const clearingUsage = ref(false) // 调用统计清零进行中

// Spec9：三类服务反馈展示顺序
const FEEDBACK_ROWS = [
  { key: 'generate', label: '文生图' },
  { key: 'edit', label: '图文生图' },
  { key: 'qa', label: '图像QA' }
]

const feedbackTotals = computed(() => stats.value.feedback_totals || {})

// Spec11：清零时间格式化；null → 「从未清零」，否则转本地时区
function fmtCleared(iso) {
  return iso ? new Date(iso).toLocaleString('zh-CN') : '从未清零'
}
const usageClearedText = computed(() => fmtCleared(stats.value.usage_cleared_at))
const feedbackClearedText = computed(() => fmtCleared(stats.value.feedback_cleared_at))

// 5 类展示顺序（Spec4 §7；Spec18 §7.6a 追加风格归纳）
const CATEGORIES = [
  { key: 'chat', label: '对话' },
  { key: 'generate', label: '文生图' },
  { key: 'edit', label: '图文生图' },
  { key: 'qa', label: '图像QA' },
  // Spec18：按实际发出的图片数计（每张上传图 1 次 + 风格合成 1 次），粒度与前四类不同
  { key: 'style', label: '风格归纳' }
]

const rows = computed(() =>
  CATEGORIES.map((c) => ({
    key: c.key,
    label: c.label,
    total: stats.value.totals[c.key] ?? 0,
    share: (stats.value.shares[c.key] ?? 0).toFixed(1),
    avg: (stats.value.per_user_avg[c.key] ?? 0).toFixed(1)
  }))
)

async function load() {
  try {
    stats.value = await getUsageStats()
  } catch (e) {
    error.value = e.message || '加载统计数据失败'
  }
}

// Spec9：清空反馈统计（confirm 后调用，仅管理员可见此面板）
async function clearFeedbackStats() {
  if (!window.confirm('确定清空全部 AI 服务反馈统计？此操作不可撤销。')) return
  clearing.value = true
  error.value = ''
  try {
    await clearFeedback()
    await load()
  } catch (e) {
    error.value = e.message || '清空失败'
  } finally {
    clearing.value = false
  }
}

// Spec11：清空调用统计（confirm 一次防误触，成功后刷新；清零不可恢复）
// Spec18 §7.6b：文案必须同时说清"清什么"和"不清什么"，否则管理员会以为它顺带解封。
// window.confirm 是纯文本，不渲染 Markdown，故用【】而不是 **。
async function clearUsageStats() {
  if (!window.confirm(
    '确定清空全部调用统计？对话 / 文生图 / 图文生图 / 图像QA / 风格归纳 的计数将归 0。\n' +
    '注意：这只重置统计区间，【不影响】各用户在「用户管理」页的服务限额与已用次数。\n' +
    '此操作不可撤销。'
  )) return
  clearingUsage.value = true
  error.value = ''
  try {
    await clearUsage()
    await load()
  } catch (e) {
    error.value = e.message || '清空失败'
  } finally {
    clearingUsage.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.feedback-wrap {
  margin-top: 20px;
}

/* Spec11：统计区头部条（摘要 + 清零时间 + 清空按钮） */
.usage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.usage-head .admin-notice {
  margin-bottom: 0;
}

.usage-head .btn-mini {
  flex-shrink: 0;
}

/* Spec11：清零时间小字（两个区域共用） */
.cleared-hint {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.feedback-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.feedback-head h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

/* 反馈区标题 + 清零时间纵排 */
.head-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
</style>
