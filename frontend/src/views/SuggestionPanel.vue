<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>建议箱</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>
    <p class="admin-tip">
      当前登录：{{ auth.username }} · 告诉我们哪里还能更好（≤2000 字）
    </p>

    <div class="gallery-tabs">
      <button
        class="gallery-tab"
        :class="{ active: tab === 'mine' }"
        @click="switchTab('mine')"
      >
        我的建议
      </button>
      <button
        v-if="auth.isAdmin"
        class="gallery-tab"
        :class="{ active: tab === 'admin' }"
        @click="switchTab('admin')"
      >
        管理建议
      </button>
    </div>

    <p v-if="error" class="login-error">{{ error }}</p>

    <!-- 我的建议：写信 + 列表（含状态与管理员回复） -->
    <template v-if="tab === 'mine'">
      <div class="suggestion-write">
        <textarea
          v-model="draft"
          class="suggestion-textarea"
          :maxlength="2000"
          :placeholder="'写下你的建议…（' + draft.length + '/2000）'"
          rows="4"
        ></textarea>
        <div class="suggestion-write-foot">
          <span class="suggestion-count">{{ draft.length }}/2000</span>
          <button class="btn-mini" :disabled="!draft.trim() || sending" @click="sendSuggestion">
            发送
          </button>
        </div>
      </div>

      <div v-if="!loadingMine && mine.length === 0" class="gallery-empty">还没有提交过建议</div>
      <div v-else class="suggestion-list">
        <div v-for="s in mine" :key="s.id" class="suggestion-item">
          <div class="suggestion-item-head">
            <span class="suggestion-status" :class="'st-' + s.status">{{ statusLabel(s.status) }}</span>
            <span class="community-time">{{ formatTime(s.created_at) }}</span>
          </div>
          <p class="suggestion-text">{{ s.text }}</p>
          <p v-if="s.reply" class="suggestion-reply">管理员回复：{{ s.reply }}</p>
        </div>
      </div>
    </template>

    <!-- 管理建议：改状态 + 写回复 + 删除 -->
    <template v-else>
      <div v-if="!loadingAll && all.length === 0" class="gallery-empty">暂无建议</div>
      <div v-else class="admin-table-wrap">
        <table class="user-table">
          <thead>
            <tr>
              <th>发送者</th>
              <th>状态</th>
              <th>建议</th>
              <th>回复</th>
              <th>时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in all" :key="s.id">
              <td>{{ s.author }}</td>
              <td>
                <select
                  v-model="s.status"
                  class="suggestion-select"
                  @change="onStatusChange(s)"
                >
                  <option value="pending">待处理</option>
                  <option value="read">已读</option>
                  <option value="resolved">已处理</option>
                </select>
              </td>
              <td class="suggestion-cell-text">{{ s.text }}</td>
              <td>
                <input
                  v-model="s.reply"
                  class="suggestion-reply-input"
                  :maxlength="2000"
                  :placeholder="s.reply || '回复…'"
                  @change="onReply(s)"
                />
              </td>
              <td class="community-time">{{ formatTime(s.created_at) }}</td>
              <td>
                <button class="btn-mini danger" @click="remove(s)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import {
  deleteSuggestion, listAllSuggestions, listMySuggestions,
  submitSuggestion, updateSuggestion
} from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const tab = ref('mine')
const draft = ref('')
const sending = ref(false)
const error = ref('')
const mine = ref([])
const all = ref([])
const loadingMine = ref(false)
const loadingAll = ref(false)

const STATUS_LABELS = { pending: '待处理', read: '已读', resolved: '已处理' }

function statusLabel(st) {
  return STATUS_LABELS[st] || st || '未知'
}

function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

function switchTab(v) {
  tab.value = v
  error.value = ''
  if (v === 'mine' && mine.value.length === 0) loadMine()
  if (v === 'admin' && all.value.length === 0) loadAll()
}

async function loadMine() {
  loadingMine.value = true
  error.value = ''
  try {
    const data = await listMySuggestions()
    mine.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载建议失败'
  } finally {
    loadingMine.value = false
  }
}

async function loadAll() {
  loadingAll.value = true
  error.value = ''
  try {
    const data = await listAllSuggestions()
    all.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载建议失败'
  } finally {
    loadingAll.value = false
  }
}

// Spec9 §6.2：发送前 confirm 警告一次（仅写信时）
async function sendSuggestion() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  if (!window.confirm('确认发送这条建议吗？')) return
  sending.value = true
  error.value = ''
  try {
    await submitSuggestion(text)
    draft.value = ''
    await loadMine()
  } catch (e) {
    error.value = e.message || '发送失败'
  } finally {
    sending.value = false
  }
}

async function onStatusChange(s) {
  error.value = ''
  try {
    const r = await updateSuggestion(s.id, { status: s.status })
    s.status = r.status
  } catch (e) {
    error.value = e.message || '更新状态失败'
    await loadAll() // 回滚为服务端状态
  }
}

async function onReply(s) {
  error.value = ''
  try {
    const r = await updateSuggestion(s.id, { reply: s.reply })
    s.reply = r.reply
  } catch (e) {
    error.value = e.message || '保存回复失败'
    await loadAll()
  }
}

async function remove(s) {
  if (!window.confirm('确定删除这条建议？此操作不可撤销。')) return
  error.value = ''
  try {
    await deleteSuggestion(s.id)
    const i = all.value.findIndex((x) => x.id === s.id)
    if (i !== -1) all.value.splice(i, 1)
  } catch (e) {
    error.value = e.message || '删除失败'
  }
}

onMounted(loadMine)
</script>

<style scoped>
.suggestion-write {
  margin-bottom: 20px;
}

.suggestion-textarea {
  display: block;
  width: 100%;
  padding: 10px 12px;
  resize: vertical;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.6;
  transition: border-color var(--transition-normal);
}

.suggestion-textarea:focus {
  outline: none;
  border-color: var(--purple-500);
}

.suggestion-write-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
}

.suggestion-count {
  font-size: 12px;
  color: var(--text-muted);
}

.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.suggestion-item {
  padding: 12px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.suggestion-item-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.suggestion-status {
  font-size: 12px;
  padding: 1px 10px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
}

.suggestion-status.st-pending { color: #fbbf24; border-color: #92400e; }
.suggestion-status.st-read { color: #93c5fd; border-color: #1e3a8a; }
.suggestion-status.st-resolved { color: #6ee7b7; border-color: #065f46; }

.suggestion-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.suggestion-reply {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--purple-300);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.suggestion-select {
  padding: 3px 6px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-full);
  color: var(--text-primary);
  font-size: 12px;
}

.suggestion-reply-input {
  width: 160px;
  padding: 5px 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
  font-size: 12px;
}

.suggestion-reply-input:focus {
  outline: none;
  border-color: var(--purple-500);
}

.suggestion-cell-text {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
