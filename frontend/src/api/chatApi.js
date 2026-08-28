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

// 每个请求带 X-Request-Id，后端透传到日志（Spec §5.2）
http.interceptors.request.use((config) => {
  config.headers['X-Request-Id'] = randomId()
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

export { API_BASE }
