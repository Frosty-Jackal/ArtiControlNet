import { defineStore } from 'pinia'
import { getTask, sendChat, uploadImage } from '../api/chatApi'

// 历史键按用户名隔离：artcn_chat_v2:<username>（Spec3 §5.1）；旧的单一键 artcn_chat_v2 废弃不再读写
function chatKey(username) {
  return `artcn_chat_v2:${username}`
}

function loadHistory(username) {
  try {
    const raw = localStorage.getItem(chatKey(username))
    if (raw) {
      const saved = JSON.parse(raw)
      return { threadId: saved.threadId || null, messages: saved.messages || [] }
    }
  } catch (e) {
    /* 忽略损坏的本地历史 */
  }
  return { threadId: null, messages: [] }
}

let uid = 0
function nextId(prefix = 'm') {
  uid += 1
  return `${prefix}_${Date.now()}_${uid}`
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    username: '', // 当前历史归属用户（Spec3），未登录为空串 → 不读不写历史键
    threadId: null,
    messages: [],
    sending: false
  }),

  actions: {
    // 用户切换时重载历史：登录 / 登出 / token 失效由 App.vue 触发（Spec3 §5.2）
    resetForUser(username) {
      this.username = username || ''
      this.threadId = null
      this.messages = []
      this.sending = false
      if (this.username) {
        const saved = loadHistory(this.username)
        this.threadId = saved.threadId
        this.messages = saved.messages
      }
    },

    persist() {
      if (!this.username) return // 未登录不读写历史键（Spec3 §5.1）
      localStorage.setItem(
        chatKey(this.username),
        JSON.stringify({ threadId: this.threadId, messages: this.messages })
      )
    },

    // 发送新消息：文本 + 可选图片文件
    async send(text, file) {
      if (!text.trim() && !file) return
      this.sending = true

      const userId = nextId('u')
      const userMsg = { id: userId, role: 'user', kind: 'text', text }
      let imageUrl = null
      let previewUrl = null
      if (file) {
        previewUrl = URL.createObjectURL(file)
        userMsg.imageUrlPreview = previewUrl
        this.messages.push(userMsg)
        this.persist()
        try {
          imageUrl = await uploadImage(file)
          // 上传成功后用服务端地址替换本地预览
          const i = this.messages.findIndex((m) => m.id === userId)
          if (i !== -1) this.messages[i] = { ...this.messages[i], imageUrl, imageUrlPreview: previewUrl }
        } catch (e) {
          this.messages.push({
            id: nextId('e'), role: 'assistant', kind: 'error',
            error: '图片上传失败：' + e.message
          })
          this.sending = false
          this.persist()
          return
        }
      } else {
        this.messages.push(userMsg)
      }

      const pendingId = nextId('p')
      const request = { text, imageUrl }
      this.messages.push({ id: pendingId, role: 'assistant', kind: 'pending', request })
      this.persist()
      await this.submit(request, pendingId)
      this.sending = false
    },

    // 失败气泡重试
    async retry(errorId) {
      const err = this.messages.find((m) => m.id === errorId)
      if (!err || !err.request) return
      this.sending = true
      const pendingId = nextId('p')
      const request = err.request
      this.replaceMessage(errorId, { id: pendingId, role: 'assistant', kind: 'pending', request })
      this.persist()
      await this.submit(request, pendingId)
      this.sending = false
    },

    async submit(request, pendingId) {
      try {
        const chat = await sendChat({ message: request.text, imageUrl: request.imageUrl, threadId: this.threadId })
        this.threadId = chat.thread_id
        this.persist()
        this.pollTask(chat.task_id, pendingId)
      } catch (e) {
        this.replaceMessage(pendingId, {
          id: pendingId, role: 'assistant', kind: 'error',
          error: e.message, request
        })
        this.persist()
      }
    },

    pollTask(taskId, pendingId, delay = 1500) {
      setTimeout(async () => {
        let task
        try {
          task = await getTask(taskId)
        } catch (e) {
          // 轮询瞬时失败，稍后重试
          this.pollTask(taskId, pendingId, 2000)
          return
        }
        if (task.status === 'COMPLETED') {
          const result = task.result || {}
          if (result.kind === 'text') {
            this.replaceMessage(pendingId, { id: pendingId, role: 'assistant', kind: 'text', text: result.text })
          } else {
            this.replaceMessage(pendingId, { id: pendingId, role: 'assistant', kind: 'images', images: result.images || [] })
          }
          this.persist()
        } else if (task.status === 'FAILED') {
          const msg = (task.error && task.error.message) || '任务失败'
          this.replaceMessage(pendingId, {
            id: pendingId, role: 'assistant', kind: 'error', error: msg,
            request: this.messageById(pendingId) ? this.messageById(pendingId).request : undefined
          })
          this.persist()
        } else {
          this.pollTask(taskId, pendingId, 1500)
        }
      }, delay)
    },

    replaceMessage(id, msg) {
      const i = this.messages.findIndex((m) => m.id === id)
      if (i !== -1) this.messages[i] = { ...msg, id }
    },

    messageById(id) {
      return this.messages.find((m) => m.id === id)
    },

    clear() {
      this.threadId = null
      this.messages = []
      this.sending = false
      this.persist()
    }
  }
})
