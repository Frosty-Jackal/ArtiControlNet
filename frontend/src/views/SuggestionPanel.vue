<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>建议箱</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>

    <!-- 普通用户：写信 + 我的建议（点击弹窗只读查看） -->
    <template v-if="!auth.isAdmin">
      <p class="admin-tip">
        当前登录：{{ auth.username }} · 告诉我们哪里还能更好（≤2000 字）
      </p>
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

      <p v-if="error" class="login-error">{{ error }}</p>

      <div v-if="!loading && mine.length === 0" class="gallery-empty">还没有提交过建议</div>
      <div v-else class="suggestion-list">
        <button
          v-for="s in mine"
          :key="s.id"
          class="suggestion-card"
          @click="viewing = s"
        >
          <div class="suggestion-card-head">
            <span class="suggestion-status" :class="'st-' + s.status">{{ statusLabel(s.status) }}</span>
            <span class="suggestion-time">{{ formatTime(s.created_at) }}</span>
          </div>
          <p class="suggestion-card-text">{{ s.text }}</p>
          <p v-if="s.reply" class="suggestion-card-reply">回复：{{ s.reply }}</p>
          <span class="suggestion-card-hint">点击查看详情</span>
        </button>
      </div>

      <!-- 用户只读弹窗：全文 + 状态 + 管理员回复 -->
      <div v-if="viewing" class="gallery-lightbox" @click.self="viewing = null">
        <div class="suggestion-modal">
          <div class="suggestion-modal-head">
            <span class="suggestion-status" :class="'st-' + viewing.status">{{ statusLabel(viewing.status) }}</span>
            <span class="suggestion-time">{{ formatTime(viewing.created_at) }}</span>
          </div>
          <p class="suggestion-modal-text">{{ viewing.text }}</p>
          <p v-if="viewing.reply" class="suggestion-reply">管理员回复：{{ viewing.reply }}</p>
          <p v-else class="suggestion-reply-empty">管理员尚未回复</p>
          <div class="suggestion-modal-foot">
            <button class="btn-clear" @click="viewing = null">关闭</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 管理员：只能审批（回复弹窗 + 删除），无写信区 -->
    <template v-else>
      <p class="admin-tip">
        当前登录：{{ auth.username }}（管理员） · 只能审批建议，不能写信
      </p>

      <p v-if="error" class="login-error">{{ error }}</p>

      <div v-if="!loading && all.length === 0" class="gallery-empty">暂无建议</div>
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
                <span class="suggestion-status" :class="'st-' + s.status">{{ statusLabel(s.status) }}</span>
              </td>
              <td class="suggestion-cell-text" :title="s.text">{{ s.text }}</td>
              <td class="suggestion-cell-text" :title="s.reply || ''">{{ s.reply || '—' }}</td>
              <td class="suggestion-time">{{ formatTime(s.created_at) }}</td>
              <td>
                <div class="suggestion-actions">
                  <button class="btn-mini" @click="openEdit(s)">回复 / 审批</button>
                  <button class="btn-mini danger" @click="remove(s)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 管理员回复弹窗：状态二选一（默认已处理）+ 回复 + 发送，一次落库 -->
      <div v-if="editing" class="gallery-lightbox" @click.self="editing = null">
        <div class="suggestion-modal">
          <div class="suggestion-modal-head">
            <h3 class="suggestion-modal-title">回复 / 审批建议</h3>
            <span class="suggestion-time">{{ editing.author }} · {{ formatTime(editing.created_at) }}</span>
          </div>
          <p class="suggestion-modal-text">{{ editing.text }}</p>
          <div class="suggestion-edit-field">
            <label class="suggestion-edit-label">状态</label>
            <select v-model="editStatus" class="suggestion-select">
              <option value="resolved">已处理</option>
              <option value="pending">待管理员处理</option>
            </select>
          </div>
          <div class="suggestion-edit-field">
            <label class="suggestion-edit-label">回复内容</label>
            <textarea
              v-model="editReply"
              class="suggestion-textarea"
              :maxlength="2000"
              :placeholder="'回复（' + editReply.length + '/2000）'"
              rows="4"
            ></textarea>
          </div>
          <p class="suggestion-edit-hint">发送即保存到数据库；默认标记为「已处理」，可手动改为「待管理员处理」</p>
          <div class="suggestion-modal-foot">
            <button class="btn-clear" @click="editing = null">取消</button>
            <button class="btn-mini" :disabled="saving" @click="saveEdit">发送</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  deleteSuggestion, listAllSuggestions, listMySuggestions,
  submitSuggestion, updateSuggestion
} from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const draft = ref('')
const sending = ref(false)
const saving = ref(false)
const error = ref('')
const mine = ref([])
const all = ref([])
const loading = ref(false)
const viewing = ref(null) // 普通用户：当前只读查看的建议
const editing = ref(null) // 管理员：当前回复/审批的建议
const editStatus = ref('resolved')
const editReply = ref('')

// Spec10：状态收敛两态——待管理员处理 / 已处理（不再有"待用户处理/已读"）
const STATUS_LABELS = { pending: '待管理员处理', resolved: '已处理' }

function statusLabel(st) {
  return STATUS_LABELS[st] || st || '未知'
}

function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

function load() {
  loading.value = true
  error.value = ''
  const p = auth.isAdmin ? listAllSuggestions() : listMySuggestions()
  return p
    .then((data) => {
      if (auth.isAdmin) all.value = data.items || []
      else mine.value = data.items || []
    })
    .catch((e) => {
      error.value = e.message || '加载建议失败'
    })
    .finally(() => {
      loading.value = false
    })
}

// ---- 普通用户写信 ----
async function sendSuggestion() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  if (!window.confirm('确认发送这条建议吗？')) return
  sending.value = true
  error.value = ''
  try {
    await submitSuggestion(text)
    draft.value = ''
    await load()
  } catch (e) {
    error.value = e.message || '发送失败'
  } finally {
    sending.value = false
  }
}

// ---- 管理员回复/审批 ----
function openEdit(s) {
  editing.value = s
  // 发送回复自动标记「已处理」，管理员可手动改回「待管理员处理」
  editStatus.value = 'resolved'
  editReply.value = s.reply || ''
  error.value = ''
}

async function saveEdit() {
  if (!editing.value || saving.value) return
  saving.value = true
  error.value = ''
  const id = editing.value.id
  try {
    const r = await updateSuggestion(id, { status: editStatus.value, reply: editReply.value.trim() })
    const row = all.value.find((x) => x.id === id)
    if (row) {
      row.status = r.status
      row.reply = r.reply
    }
    editing.value = null
  } catch (e) {
    error.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function remove(s) {
  if (!window.confirm('确定删除这条建议？此操作不可撤销。')) return
  error.value = ''
  try {
    await deleteSuggestion(s.id)
    const i = all.value.findIndex((x) => x.id === s.id)
    if (i !== -1) all.value.splice(i, 1)
    if (editing.value && editing.value.id === s.id) editing.value = null
  } catch (e) {
    error.value = e.message || '删除失败'
  }
}

// Esc 关闭弹窗
function onKeydown(e) {
  if (e.key !== 'Escape') return
  if (editing.value) editing.value = null
  else if (viewing.value) viewing.value = null
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  load()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
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

/* 用户端建议卡片（点击弹窗只读查看） */
.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.suggestion-card {
  display: block;
  width: 100%;
  padding: 12px 14px;
  text-align: left;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color var(--transition-fast), transform var(--transition-fast);
}

.suggestion-card:hover {
  border-color: var(--purple-500);
  transform: translateY(-1px);
}

.suggestion-card-head {
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
  white-space: nowrap;
}

.suggestion-status.st-pending { color: #fbbf24; border-color: #92400e; }
.suggestion-status.st-resolved { color: #6ee7b7; border-color: #065f46; }

.suggestion-time {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.suggestion-card-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.suggestion-card-reply {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--purple-300);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.suggestion-card-hint {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

/* 弹窗（用户只读 / 管理员回复共用外壳） */
.suggestion-modal {
  max-width: 620px;
  width: 100%;
  max-height: 90%;
  overflow-y: auto;
  padding: 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.suggestion-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.suggestion-modal-title {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}

.suggestion-modal-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}

.suggestion-reply {
  margin: 0;
  padding: 10px 12px;
  font-size: 13px;
  color: var(--purple-300);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  background: rgba(124, 58, 237, 0.12);
  border: 1px solid rgba(168, 85, 247, 0.35);
  border-radius: var(--radius-md);
}

.suggestion-reply-empty {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.suggestion-modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

/* 管理员回复弹窗字段 */
.suggestion-edit-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.suggestion-edit-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.suggestion-select {
  padding: 6px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 13px;
}

.suggestion-edit-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

/* 管理表格 */
.suggestion-actions {
  display: flex;
  gap: 8px;
  white-space: nowrap;
}

.suggestion-cell-text {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
