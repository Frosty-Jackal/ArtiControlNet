import { defineStore } from 'pinia'
import {
  deleteConversation as apiDeleteConversation, getConversation, getTask, listConversations,
  postFeedback, sendChat, uploadImage
} from '../api/chatApi'
import { clearAuthedImageCache } from '../composables/useAuthedImage'

// Spec17 §7.3：聊天内容不再进 localStorage（历史数据在 artcn.db 里，按用户隔离）。
// 本地只记「上次所在的对话 id」，刷新页面后据此恢复现场。
function currentConvKey(username) {
  return `artcn_current_conv:${username}`
}

let uid = 0
function nextId(prefix = 'm') {
  uid += 1
  return `${prefix}_${Date.now()}_${uid}`
}

// 后端 chat_messages 行 → 前端消息形态（§7.3 表）
function fromRow(row) {
  return {
    id: `m_${row.id}`,
    role: row.role,
    kind: row.image_id ? 'images' : 'text', // 助手：有图 → images，否则 text
    text: row.text || '',
    imageId: row.image_id,
    tool: row.tool || null,
    taskId: row.task_id,
    vote: null // 历史气泡的点赞态不来自后端（Spec9 口径，§6.4）
  }
}

// 本地预览 objectURL 是"上传中"的临时物；消息被丢弃时必须一并 revoke
function releasePreviews(messages) {
  ;(messages || []).forEach((m) => {
    if (m && m.imageUrlPreview) URL.revokeObjectURL(m.imageUrlPreview)
  })
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    username: '', // 当前历史归属用户；未登录为空串 → 不拉不写
    conversations: [], // [{ id, created_at, updated_at }]，updated_at 倒序
    currentConvId: null, // null = 尚未开始的空对话
    messages: [],
    sending: false,
    loadingConv: false // 切换对话时的加载态（防连点）
  }),

  actions: {
    // 用户切换时重载（登录 / 登出 / token 失效由 App.vue 触发，Spec3 §5.2 机制不变）
    async resetForUser(username) {
      releasePreviews(this.messages)
      this.username = username || ''
      this.conversations = []
      this.currentConvId = null
      this.messages = []
      this.sending = false
      this.loadingConv = false
      clearAuthedImageCache() // 上一账号拉过的图片不再驻留内存
      if (!this.username) return

      await this.refreshConversations()
      // 载入策略（§7.3）：记住的对话还在列表里就开它；否则开列表首条；没有对话就空对话
      const remembered = this.readRemembered()
      const inList = remembered && this.conversations.some((c) => c.id === remembered)
      const target = inList ? remembered : this.conversations[0]?.id || null
      if (target) await this.openConversation(target)
      else this.newConversation()
    },

    async refreshConversations() {
      try {
        const d = await listConversations()
        this.conversations = d.items || []
      } catch (e) {
        // 列表拉取失败不阻断聊天（新对话仍然可用），只是侧边栏空着
        this.conversations = []
      }
    },

    // 新对话：不调后端——对话行在发出第一条消息时才创建（§5.3 "消息驱动"）
    newConversation() {
      releasePreviews(this.messages)
      this.currentConvId = null
      this.messages = []
      this.sending = false
      this.forgetRemembered()
    },

    async openConversation(id) {
      // 已在当前对话里就不重拉：任务在飞时重拉会把 pending 气泡冲掉，结果无处可去
      if (!id || id === this.currentConvId || this.loadingConv) return
      this.loadingConv = true
      try {
        const d = await getConversation(id)
        releasePreviews(this.messages)
        this.messages = (d.messages || []).map(fromRow)
        this.currentConvId = id
        this.remember(id)
      } catch (e) {
        window.alert('加载对话失败：' + e.message)
      } finally {
        this.loadingConv = false
      }
    },

    async deleteConversation(id) {
      if (!window.confirm('删除这段对话？聊天记录将被永久清除（作品库里的图片不受影响）')) return
      try {
        await apiDeleteConversation(id)
      } catch (e) {
        window.alert('删除失败：' + e.message)
        return
      }
      this.conversations = this.conversations.filter((c) => c.id !== id)
      if (this.currentConvId !== id) return
      // 删的就是当前对话 → 切到列表首条；一条不剩就回到空对话
      releasePreviews(this.messages)
      this.currentConvId = null
      this.messages = []
      if (this.conversations.length) await this.openConversation(this.conversations[0].id)
      else this.newConversation()
    },

    // 发送新消息：文本 + 可选图片文件
    async send(text, file) {
      if (!text.trim() && !file) return
      this.sending = true

      const userId = nextId('u')
      const userMsg = { id: userId, role: 'user', kind: 'text', text }
      let imageId = null
      if (file) {
        const previewUrl = URL.createObjectURL(file)
        userMsg.imageUrlPreview = previewUrl
        this.messages.push(userMsg)
        try {
          const up = await uploadImage(file)
          imageId = up.imageId
          // 上传成功后换成作品库引用（渲染走带 token 的 blob 拉取），本地预览即可释放
          const i = this.messages.findIndex((m) => m.id === userId)
          if (i !== -1) {
            const { imageUrlPreview, ...rest } = this.messages[i]
            this.messages[i] = { ...rest, imageId }
          }
          URL.revokeObjectURL(previewUrl)
        } catch (e) {
          URL.revokeObjectURL(previewUrl)
          const i = this.messages.findIndex((m) => m.id === userId)
          if (i !== -1) {
            const { imageUrlPreview, ...rest } = this.messages[i]
            this.messages[i] = rest
          }
          this.messages.push({
            id: nextId('e'), role: 'assistant', kind: 'error',
            error: '图片上传失败：' + e.message
          })
          this.sending = false
          return
        }
      } else {
        this.messages.push(userMsg)
      }

      const pendingId = nextId('p')
      const request = { text, imageId }
      this.messages.push({ id: pendingId, role: 'assistant', kind: 'pending', request })
      await this.submit(request, pendingId)
      this.sending = false
    },

    // 失败气泡重试（Spec7 §5.2：复用 errorId 作为气泡 id，完成/失败回调才能替换到气泡）
    async retry(errorId) {
      const err = this.messages.find((m) => m.id === errorId)
      if (!err || !err.request) return
      this.sending = true
      const request = err.request
      this.replaceMessage(errorId, { id: errorId, role: 'assistant', kind: 'pending', request })
      await this.submit(request, errorId)
      this.sending = false
    },

    async submit(request, pendingId) {
      const wasEmpty = this.currentConvId === null
      try {
        const chat = await sendChat({
          message: request.text,
          imageUrl: null, // Spec17：图片一律走作品库引用 image_id（§5.2A）
          imageId: request.imageId,
          threadId: this.currentConvId
        })
        if (wasEmpty) {
          // 首次发送成功 → 后端此刻才建对话行；记下 id 并让新对话出现在侧边栏
          this.currentConvId = chat.thread_id
          this.remember(chat.thread_id)
          this.refreshConversations()
        }
        this.pollTask(chat.task_id, pendingId)
      } catch (e) {
        this.replaceMessage(pendingId, {
          id: pendingId, role: 'assistant', kind: 'error',
          error: e.message, request
        })
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
          // Spec9：工具类结果（文生图 / 图文生图 / 图像QA）带上 tool + taskId，气泡下方可 👍/👎；
          // 纯对话结果无 tool → 不渲染反馈行。qa_image 虽是文本气泡（kind=text）同样可反馈。
          const isToolResult = ['generate_image', 'edit_image', 'qa_image'].includes(result.tool)
          const feedback = isToolResult ? { tool: result.tool, taskId, vote: null } : {}
          const imageId = (result.image_ids || [])[0] ?? null
          if (result.kind === 'text') {
            this.replaceMessage(pendingId, {
              id: pendingId, role: 'assistant', kind: 'text', text: result.text, ...feedback
            })
          } else {
            this.replaceMessage(pendingId, {
              id: pendingId, role: 'assistant', kind: 'images', imageId, ...feedback
            })
          }
        } else if (task.status === 'FAILED') {
          const msg = (task.error && task.error.message) || '任务失败'
          const prev = this.messageById(pendingId)
          this.replaceMessage(pendingId, {
            id: pendingId, role: 'assistant', kind: 'error', error: msg,
            request: prev ? prev.request : undefined
          })
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

    // Spec9：服务结果气泡 👍/👎（再点同一项取消）；仅 tool 类结果可反馈
    async toggleFeedback(msg, choice) {
      if (!msg || !msg.tool || !msg.taskId) return
      const next = msg.vote === choice ? null : choice
      try {
        await postFeedback({ taskId: msg.taskId, category: this.mapToolCategory(msg.tool), vote: next })
        msg.vote = next
      } catch (e) {
        window.alert('反馈提交失败：' + e.message)
      }
    },

    mapToolCategory(tool) {
      if (tool === 'edit_image') return 'edit'
      if (tool === 'qa_image') return 'qa'
      return 'generate'
    },

    // ---- localStorage：只存当前对话 id（§7.3）----

    readRemembered() {
      if (!this.username) return null
      try {
        return localStorage.getItem(currentConvKey(this.username))
      } catch (e) {
        return null
      }
    },

    remember(convId) {
      if (!this.username) return
      try {
        localStorage.setItem(currentConvKey(this.username), convId)
      } catch (e) {
        /* 隐私模式等场景下写不进去，不影响使用 */
      }
    },

    forgetRemembered() {
      if (!this.username) return
      try {
        localStorage.removeItem(currentConvKey(this.username))
      } catch (e) {
        /* 同上 */
      }
    }
  }
})
