<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>用户管理</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>
    <p class="admin-tip">
      当前登录：{{ auth.username }}（{{ auth.isAdmin ? '管理员' : '普通用户' }}）
      · 账号仅由管理员创建，无公开注册
    </p>

    <!-- 创建账号 -->
    <form class="admin-create" @submit.prevent="create">
      <input
        v-model="newName"
        class="login-input"
        placeholder="新用户名（≥2 字符）"
        autocomplete="off"
      />
      <input
        v-model="newPass"
        type="password"
        class="login-input"
        placeholder="初始密码（≥6 位）"
        autocomplete="new-password"
      />
      <button class="btn-primary" type="submit" :disabled="creating">
        {{ creating ? '创建中…' : '创建账号' }}
      </button>
    </form>

    <p v-if="error" class="login-error">{{ error }}</p>
    <p v-if="notice" class="admin-notice">{{ notice }}</p>

    <!-- 用户表格 -->
    <div class="admin-table-wrap">
      <table class="user-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>角色</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.id }}</td>
            <td>
              {{ u.username }}
              <span v-if="u.username === auth.username" class="me-tag">我</span>
            </td>
            <td>
              <span :class="u.is_admin ? 'role-admin' : 'role-normal'">
                {{ u.is_admin ? '管理员' : '普通' }}
              </span>
            </td>
            <td class="cell-muted">{{ u.created_at }}</td>
            <td class="row-actions">
              <button class="btn-mini" :disabled="busyId === u.id" @click="resetPassword(u)">
                重置密码
              </button>
              <button
                class="btn-mini"
                :disabled="busyId === u.id"
                @click="toggleAdmin(u)"
              >
                {{ u.is_admin ? '撤销管理员' : '设为管理员' }}
              </button>
              <button
                class="btn-mini danger"
                :disabled="busyId === u.id || u.username === auth.username"
                title="不能删除自己"
                @click="remove(u)"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import {
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  setUserAdmin
} from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const users = ref([])
const newName = ref('')
const newPass = ref('')
const error = ref('')
const notice = ref('')
const creating = ref(false)
const busyId = ref(null)

async function load() {
  try {
    users.value = await listUsers()
  } catch (e) {
    error.value = e.message || '加载用户列表失败'
  }
}

function flash(msg) {
  notice.value = msg
  setTimeout(() => (notice.value = ''), 2500)
}

async function create() {
  const name = newName.value.trim()
  const pass = newPass.value
  if (name.length < 2 || pass.length < 6) {
    error.value = '用户名至少 2 个字符，密码至少 6 位'
    return
  }
  error.value = ''
  creating.value = true
  try {
    await createUser(name, pass)
    newName.value = ''
    newPass.value = ''
    flash(`已创建账号：${name}`)
    await load()
  } catch (e) {
    error.value = e.message || '创建失败'
  } finally {
    creating.value = false
  }
}

async function resetPassword(u) {
  const pass = window.prompt(`为「${u.username}」设置新密码（至少 6 位）：`)
  if (!pass) return
  if (pass.length < 6) {
    error.value = '密码至少 6 位'
    return
  }
  error.value = ''
  busyId.value = u.id
  try {
    await resetUserPassword(u.id, pass)
    flash(`已重置「${u.username}」的密码`)
  } catch (e) {
    error.value = e.message || '重置失败'
  } finally {
    busyId.value = null
  }
}

async function toggleAdmin(u) {
  const next = !u.is_admin
  if (next && !window.confirm(`确定将「${u.username}」设为管理员？`)) return
  if (!next && !window.confirm(`确定撤销「${u.username}」的管理员权限？`)) return
  error.value = ''
  busyId.value = u.id
  try {
    await setUserAdmin(u.id, next)
    flash(next ? `已将「${u.username}」设为管理员` : `已撤销「${u.username}」管理员`)
    await load()
    // 若操作的是自己，向后端同步最新权限
    if (u.username === auth.username) await auth.refresh()
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    busyId.value = null
  }
}

async function remove(u) {
  if (u.username === auth.username) return
  if (!window.confirm(`确定删除用户「${u.username}」？此操作不可撤销。`)) return
  error.value = ''
  busyId.value = u.id
  try {
    await deleteUser(u.id)
    flash(`已删除用户「${u.username}」`)
    await load()
  } catch (e) {
    error.value = e.message || '删除失败'
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>
