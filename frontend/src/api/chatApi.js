import axios from 'axios'

import { setQuotaNotice } from '../utils/quotaNotice'

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

// 错误一律包成 Error，并把 HTTP 状态码挂到 err.status 上：
// 渲染站内图片要区分「404 图片已删除」（Spec17 §3.4，渲染占位框）与其它错误（可重试）。
// Spec18：再挂上业务错误码 err.code —— 四个 403（40301/02/03/04）只能靠它区分。
function httpError(message, status, code) {
  const e = new Error(message)
  e.status = status
  e.code = code
  return e
}

http.interceptors.response.use(
  (resp) => {
    // 二进制响应（blob，画廊文件）直接放行，不按 JSON {code} 契约校验
    if (resp.config.responseType === 'blob') return resp
    const body = resp.data
    if (body && body.code !== 200) {
      return Promise.reject(httpError(body.message || '请求失败', resp.status, body.code))
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
        let code
        try {
          const parsed = JSON.parse(txt)
          msg = parsed.message || msg
          code = parsed.code
        } catch (e) { /* 非 JSON 错误体 */ }
        if (resp.status === 401 && !url.includes('/api/auth/login')) {
          clearToken()
          window.dispatchEvent(new Event('artcn:unauthorized'))
        }
        // Spec18 §7.2b：作品库/社区图片的 <img> 渲染请求也会被中间件拦，
        // 不处理会让图片静默裂掉而没有登出。
        if (resp.status === 403 && code === 40304 && !url.includes('/api/auth/login')) {
          clearToken()
          setQuotaNotice(msg)
          window.dispatchEvent(new Event('artcn:quota_exceeded'))
        }
        return Promise.reject(httpError(msg, resp.status, code))
      })
    }
    const body = resp?.data
    // 任意业务请求 401 → 清 token 回登录页（登录接口自身的 40102 不触发）
    if (resp?.status === 401 && !url.includes('/api/auth/login')) {
      clearToken()
      window.dispatchEvent(new Event('artcn:unauthorized'))
    }
    // Spec18 §7.2b：服务次数耗尽 → 清 token 回登录页 + 记下提示，
    // 由 Login.vue 挂载时弹出。守卫与 401 分支同款：登录接口自己被拒时，
    // 用户本来就在登录页，不该派发"被踢"事件（提示由 Login.vue 的 catch 弹）。
    if (resp?.status === 403 && body?.code === 40304 && !url.includes('/api/auth/login')) {
      clearToken()
      setQuotaNotice(body?.message)
      window.dispatchEvent(new Event('artcn:quota_exceeded'))
    }
    const msg = (body && body.message) || err.message || '网络错误'
    return Promise.reject(httpError(msg, resp?.status, body?.code))
  }
)

// 上传图片：返回 { imageUrl, imageId }（Spec17 §5.2A：对话消息按 image_id 引用作品库）
export async function uploadImage(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/api/images', form)
  return { imageUrl: data.data.image_url, imageId: data.data.image_id }
}

export async function sendChat({ message, imageUrl, imageId, threadId }) {
  const { data } = await http.post('/api/chat', {
    message,
    image_url: imageUrl || null,
    image_id: imageId ?? null,
    thread_id: threadId || null
  })
  return data.data // { task_id, thread_id, status }
}

export async function getTask(taskId) {
  const { data } = await http.get(`/api/tasks/${taskId}`)
  return data.data // { task_id, thread_id, status, kind, error, result }
}

// ---- 对话历史（Spec17 §6.2）----

export async function listConversations() {
  const { data } = await http.get('/api/conversations')
  return data.data // { items: [{ id, created_at, updated_at }] }，updated_at 倒序
}

export async function getConversation(convId) {
  const { data } = await http.get(`/api/conversations/${convId}/messages`)
  return data.data // { conversation: {id,created_at,updated_at}, messages: [...] }
}

export async function deleteConversation(convId) {
  const { data } = await http.delete(`/api/conversations/${convId}`)
  return data.data // { id, message_count }
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
  // [{ id, username, is_admin, created_at, created_at_beijing, quota_limit, used,
  //    phone, email }]（Spec18 §6.1 + Spec21 §7.2，无 password_hash）
  return data.data
}

// Spec18 §6.2：设置某用户的累计服务限额（仅管理员）
export async function updateUserQuota(userId, quotaLimit) {
  const { data } = await http.put(`/api/admin/users/${userId}/quota`, {
    quota_limit: quotaLimit
  })
  return data.data // { id, quota_limit, used }
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

// ---- 注册申请与审批（Spec19 §7.6）----
// 注意：拦截器不用改。40305（注册未开放）与既有的 40301/40302/40303/40304 互不
// 干扰——拦截器只在 code === 40304 时才登出，而 40305 只可能出现在
// /api/auth/register 上（一个未登录用户根本不会被登出）。40902/40903 是 409，
// 拦截器不处理 409。

export async function getRegisterConfig() {
  const { data } = await http.get('/api/auth/register-config')
  // { enabled, contact_email, qr_url, price_notice, daily_notice }
  return data.data
}

export async function submitRegisterRequest({ username, password, phone, email, wechat }) {
  const { data } = await http.post('/api/auth/register', {
    username, password, phone, email, wechat
  })
  return data.data // { id }
}

export async function listRegisterRequests() {
  const { data } = await http.get('/api/admin/register-requests')
  // [{ id, username, phone, email, wechat, status, created_at, reviewed_at }]
  // pending 优先、组内 id 倒序；**无** password_hash / ip（Spec19 §6.4）
  return data.data
}

export async function approveRegisterRequest(id, quotaLimit) {
  const { data } = await http.post(`/api/admin/register-requests/${id}/approve`, {
    quota_limit: quotaLimit
  })
  return data.data // { id, username, is_admin, quota_limit }
}

export async function rejectRegisterRequest(id) {
  const { data } = await http.post(`/api/admin/register-requests/${id}/reject`)
  return data.data // { id }
}

export async function deleteRegisterRequest(id) {
  const { data } = await http.delete(`/api/admin/register-requests/${id}`)
  return data.data // { id }
}

// ---- 余额与充值（Spec21 §6）----
// 拦截器不用改：/api/auth/recharge-request 是公开端点，它的失败码是 40019/40904，
// 既不是 401 也不是 40304，不会误触发登出分支（与 Spec19 §6.8 对 40305 的处理同一个判断）。

export async function getRechargeInfo() {
  const { data } = await http.get('/api/recharge/info')
  // { balance, quota_limit, used, qr_url, price_notice }
  return data.data
}

export async function submitRecharge(wechat) {
  const { data } = await http.post('/api/recharge/requests', { wechat })
  return data.data // { id }
}

export async function submitOverdueRecharge(username, wechat) {
  const { data } = await http.post('/api/auth/recharge-request', { username, wechat })
  return data.data // { id }
}

export async function listRechargeRequests() {
  const { data } = await http.get('/api/admin/recharge-requests')
  // [{ id, user_id, username, wechat, source, status, amount,
  //    created_at, created_at_beijing, reviewed_at, reviewed_at_beijing? }]
  // pending 优先、组内 id 倒序；**无** ip（Spec21 §6.5）
  return data.data
}

export async function approveRechargeRequest(id, amount) {
  const { data } = await http.post(`/api/admin/recharge-requests/${id}/approve`, { amount })
  return data.data // { id, username, quota_limit, used }
}

export async function rejectRechargeRequest(id) {
  const { data } = await http.post(`/api/admin/recharge-requests/${id}/reject`)
  return data.data // { id }
}

export async function deleteRechargeRequest(id) {
  const { data } = await http.delete(`/api/admin/recharge-requests/${id}`)
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

// ---- 我的作品直传 / 备注（Spec16 §7.1）----

// 作品库直传：multipart，note 可选（空则不 append，后端按"无备注"处理）
export async function uploadGalleryImage(file, note = '') {
  const form = new FormData()
  form.append('file', file)
  if (note) form.append('note', note)
  const { data } = await http.post('/api/gallery', form)
  return data.data // 与 listGallery 的 items[] 同形
}

// 改 / 清空备注（note='' 即清空）
export async function updateGalleryNote(id, note) {
  const { data } = await http.put(`/api/gallery/${id}/note`, { note })
  return data.data // 同形作品项
}

// ---- 个人作品风格 Wiki（Spec12 §7.1）----

export async function getWiki() {
  const { data } = await http.get('/api/wiki')
  return data.data // { style, prev_style, style_updated_at, updated_at }
}

export async function refreshWikiStyle() {
  const { data } = await http.post('/api/wiki/style/refresh')
  // { updated, reason, style, prev_style, style_updated_at, used_count, pending_count }
  return data.data
}

export async function updateWikiStyle(style) {
  const { data } = await http.put('/api/wiki/style', { style })
  return data.data // 同 getWiki() 的 data
}

// ---- 社区（Spec9 §6.1）----

// multipart：text 必填；图片**可选**（Spec17 §5.2D）——gallery_id（作品库）或
// file（新上传）最多给一个，都不给即纯文字帖；两个都给由后端拦（40011）
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
  return data.data // { items: [...] }，每条带内嵌 comments: [...]（Spec17 §5.2E）
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

// ---- 帖子评论（Spec17 §6.10）----

// 评论文本长度由后端校验（COMMENT_TEXT_MAX，40016）；前端已用 maxlength 硬截断。
// 不发 listComments(postId)：评论随 GET /api/community 内嵌返回，前端没有单独拉取的时机（§7.2）。
export async function createComment(postId, text) {
  const { data } = await http.post(`/api/community/${postId}/comments`, { text })
  return data.data.comment // 与列表内嵌的评论同形，可直接 push
}

export async function deleteComment(postId, commentId) {
  const { data } = await http.delete(`/api/community/${postId}/comments/${commentId}`)
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

// Spec11：清零四类调用计数（对话/文生图/图文生图/图像QA），记录清零时间
export async function clearUsage() {
  const { data } = await http.post('/api/admin/usage/clear')
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
