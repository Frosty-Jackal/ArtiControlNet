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

    <p class="admin-notice stats-summary">
      注册用户 {{ stats.user_count }} 人 · 调用总次数 {{ stats.total_calls }}
    </p>

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
        <h3>AI 服务反馈</h3>
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
import { clearFeedback, getUsageStats } from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const stats = ref({
  user_count: 0,
  total_calls: 0,
  totals: {},
  per_user_avg: {},
  shares: {},
  feedback_totals: {}
})
const error = ref('')
const clearing = ref(false)

// Spec9：三类服务反馈展示顺序
const FEEDBACK_ROWS = [
  { key: 'generate', label: '文生图' },
  { key: 'edit', label: '图文生图' },
  { key: 'qa', label: '图像QA' }
]

const feedbackTotals = computed(() => stats.value.feedback_totals || {})

// 4 类展示顺序（Spec4 §7）
const CATEGORIES = [
  { key: 'chat', label: '对话' },
  { key: 'generate', label: '文生图' },
  { key: 'edit', label: '图文生图' },
  { key: 'qa', label: '图像QA' }
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

onMounted(load)
</script>

<style scoped>
.feedback-wrap {
  margin-top: 20px;
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
</style>
