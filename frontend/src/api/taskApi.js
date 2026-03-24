import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000
})

http.interceptors.response.use(
  res => {
    if (res.data.code === 200) return res.data
    return Promise.reject(new Error(res.data.message || '请求失败'))
  },
  err => Promise.reject(err)
)

/**
 * 提交图片生成任务
 * @returns {{ data: { taskId: number, status: string } }}
 */
export function submitTask(formData) {
  return http.post('/task/submit', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/**
 * 查询任务进度
 * @returns {{ data: { taskId, status, errorMsg, images, timeInfo } }}
 */
export function getTaskProgress(taskId) {
  return http.get(`/task/progress/${taskId}`)
}

/**
 * 轮询任务直到完成或失败
 * @param {number} taskId
 * @param {function} onProgress - 每次轮询回调
 * @param {number} interval - 轮询间隔 ms
 * @returns {Promise}
 */
export function pollTaskUntilDone(taskId, onProgress, interval = 2000) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const res = await getTaskProgress(taskId)
        const progress = res.data
        if (onProgress) onProgress(progress)

        if (progress.status === 'COMPLETED' || progress.status === 'FAILED') {
          clearInterval(timer)
          resolve(progress)
        }
      } catch (e) {
        clearInterval(timer)
        reject(e)
      }
    }, interval)
  })
}
