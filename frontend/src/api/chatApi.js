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
    // 二进制响应（blob，画廊文件）直接放行，不按 JSON {code} 契约校验
    if (resp.config.responseType === 'blob') return resp
    const body = resp.data
    if (body && body.code !== 200) {
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return resp
  },
  (err) => {
    const resp = err.response
    const url = err.config?.url || ''
    // blob 请求出错时错误体也是 Blob，需异步解析其中的 {code,message}
    if (resp && err.config?.responseType === 'blob' && resp.data instanceof Blob) {
      return resp.data.text().then((txt) => {
        let msg = '请求失败'
        try { msg = (JSON.parse(txt).message) || msg } catch (e) { /* 非 JSON 错误体 */ }
        if (resp.status === 401 && !url.includes('/api/auth/login')) {
          clearToken()
          window.dispatchEvent(new Event('artcn:unauthorized'))
        }
        return Promise.reject(new Error(msg))
      })
    }
    const body = resp?.data
    // 任意业务请求 401 → 清 token 回登录页（登录接口自身的 40102 不触发）
    if (resp?.status === 401 && !url.includes('/api/auth/login')) {
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

// ---- 个人作品库（Spec5 §6.1 / §7）----

export async function listGallery(source = '') {
  const { data } = await http.get('/api/gallery', { params: source ? { source } : {} })
  return data.data // { items: [{ id, source, url, prompt, created_at }] }
}

// 返回 axios 响应：data 为 Blob。画廊文件需要 token，<img> 无法带 Authorization 头，
// 前端用带 token 的 axios 拉 blob → objectURL 渲染 / 触发下载（Spec5 §3）。
export function fetchGalleryFile(id, download = false) {
  return http.get(`/api/gallery/${id}/file`, {
    params: download ? { download: 1 } : {},
    responseType: 'blob'
  })
}

export async function deleteGalleryItem(id) {
  const { data } = await http.delete(`/api/gallery/${id}`)
  return data.data // { id }
}

// ---- 社区（Spec9 §6.1）----

// multipart：text 必填；图片来源二选一 gallery_id（作品库）或 file（新上传）
export async function createCommunityPost({ text, galleryId = null, file = null }) {
  const form = new FormData()
  form.append('text', text)
  if (galleryId != null) form.append('gallery_id', String(galleryId))
  if (file) form.append('file', file)
  const { data } = await http.post('/api/community', form)
  return data.data // { post: { id, text, author, author_is_admin, image_url, like_count, dislike_count, my_vote, created_at } }
}

export async function listCommunity(offset = 0, limit = 50) {
  const { data } = await http.get('/api/community', { params: { offset, limit } })
  return data.data // { items: [...] }
}

// 返回 axios 响应：data 为 Blob。帖子图片同画廊需带 token 拉 blob → objectURL 渲染
export function fetchCommunityImage(postId) {
  return http.get(`/api/community/${postId}/image`, { responseType: 'blob' })
}

export async function votePost(postId, vote) {
  const { data } = await http.post(`/api/community/${postId}/vote`, { vote })
  return data.data // { post_id, like_count, dislike_count, my_vote }
}

export async function deletePost(postId) {
  const { data } = await http.delete(`/api/community/${postId}`)
  return data.data // { id }
}

// ---- AI 服务反馈（Spec9 §6.1）----

// vote: 'like' | 'dislike' | null（取消）；category: 'generate' | 'edit' | 'qa'
export async function postFeedback({ taskId, category, vote }) {
  const { data } = await http.post('/api/feedback', { task_id: taskId, category, vote })
  return data.data // { task_id, category, vote }
}

export async function clearFeedback(category = '') {
  const { data } = await http.post('/api/admin/feedback/clear', null, {
    params: category ? { category } : {}
  })
  return data.data // { cleared }
}

// ---- 作品分享链接（Spec9 §6.1）----

export async function createShare(imageId) {
  const { data } = await http.post('/api/shares', { image_id: imageId })
  return data.data // { id, url, expires_at }
}

export async function revokeShare(shareId) {
  const { data } = await http.delete(`/api/shares/${shareId}`)
  return data.data // { id }
}

// ---- 建议箱（Spec9 §6.1）----

export async function listMySuggestions() {
  const { data } = await http.get('/api/suggestions/mine')
  return data.data // { items: [{ id, text, status, reply, created_at }] }
}

export async function submitSuggestion(text) {
  const { data } = await http.post('/api/suggestions', { text })
  return data.data // { suggestion: {...} }
}

export async function listAllSuggestions(status = '') {
  const { data } = await http.get('/api/admin/suggestions', { params: status ? { status } : {} })
  return data.data // { items: [{ id, author, text, status, reply, created_at }] }
}

export async function updateSuggestion(id, payload) {
  const { data } = await http.put(`/api/admin/suggestions/${id}`, payload)
  return data.data // { id, status, reply }
}

export async function deleteSuggestion(id) {
  const { data } = await http.delete(`/api/admin/suggestions/${id}`)
  return data.data // { id }
}

export { API_BASE }
