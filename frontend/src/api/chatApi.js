import axios from 'axios'

// 后端独立部署时设 VITE_API_BASE（如 https://api.example.com）；默认同源 /api
const API_BASE = import.meta.env.VITE_API_BASE || ''

const http = axios.create({ baseURL: API_BASE, timeout: 60000 })

function randomId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

const TOKEN_KEY = 'artcn_token'
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// 每个请求带 X-Request-Id（后端透传日志，Spec §5.2）+ Authorization Bearer 登录态（Spec2 §6.2）
http.interceptors.request.use((config) => {
  config.headers['X-Request-Id'] = randomId()
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && body.code !== 200) {
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return resp
  },
  (err) => {
    const body = err.response?.data
    // 任意业务请求 401 → 清 token 回登录页（登录接口自身的 40102 不触发）
    if (err.response?.status === 401 && !err.config?.url?.includes('/api/auth/login')) {
      clearToken()
      window.dispatchEvent(new Event('artcn:unauthorized'))
    }
    const msg = (body && body.message) || err.message || '网络错误'
    return Promise.reject(new Error(msg))
  }
)

export async function uploadImage(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/api/images', form)
  return data.data.image_url
}

export async function sendChat({ message, imageUrl, threadId }) {
  const { data } = await http.post('/api/chat', {
    message,
    image_url: imageUrl || null,
    thread_id: threadId || null
  })
  return data.data // { task_id, thread_id, status }
}

export async function getTask(taskId) {
  const { data } = await http.get(`/api/tasks/${taskId}`)
  return data.data // { task_id, thread_id, status, kind, error, result }
}

export async function getThread(threadId) {
  const { data } = await http.get(`/api/threads/${threadId}/messages`)
  return data.data // { messages: [...] }
}

// ---- 认证 / 用户管理（Spec2 §6.1）----

export async function login(username, password) {
  const { data } = await http.post('/api/auth/login', { username, password })
  return data.data // { token, username, is_admin }
}

export async function me() {
  const { data } = await http.get('/api/auth/me')
  return data.data // { username, is_admin }
}

export async function listUsers() {
  const { data } = await http.get('/api/admin/users')
  return data.data // [{ id, username, is_admin, created_at }]
}

export async function createUser(username, password) {
  const { data } = await http.post('/api/admin/users', { username, password })
  return data.data // { id, username, is_admin }
}

export async function resetUserPassword(userId, password) {
  const { data } = await http.put(`/api/admin/users/${userId}/password`, { password })
  return data.data // { id }
}

export async function setUserAdmin(userId, isAdmin) {
  const { data } = await http.put(`/api/admin/users/${userId}/admin`, { is_admin: isAdmin })
  return data.data // { id }
}

export async function deleteUser(userId) {
  const { data } = await http.delete(`/api/admin/users/${userId}`)
  return data.data // { id }
}

// ---- 使用统计（Spec4 §6.1）----

export async function getUsageStats() {
  const { data } = await http.get('/api/admin/stats')
  return data.data // { user_count, total_calls, totals, per_user_avg, shares }
}

export { API_BASE }
