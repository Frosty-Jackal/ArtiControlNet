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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getUsageStats } from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const stats = ref({
  user_count: 0,
  total_calls: 0,
  totals: {},
  per_user_avg: {},
  shares: {}
})
const error = ref('')

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

onMounted(load)
</script>
