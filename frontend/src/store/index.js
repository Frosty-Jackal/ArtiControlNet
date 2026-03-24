import { defineStore } from 'pinia'
import { ref, nextTick } from 'vue'
import { submitTask, pollTaskUntilDone } from '../api/taskApi'

export const useChatStore = defineStore('chat', () => {
  const messages = ref([
    {
      id: 'welcome',
      role: 'assistant',
      type: 'text',
      content: '你好！我是 ArtiControlNet AI 图像生成助手。请上传一张参考图片并输入提示词，我将为你生成精美的图像。',
      timestamp: Date.now()
    }
  ])

  const isGenerating = ref(false)
  const currentTaskId = ref(null)

  const settingsVisible = ref(false)

  const settings = ref({
    aPrompt: 'best quality, extremely detailed',
    nPrompt: 'longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality',
    numSamples: 1,
    imageResolution: 512,
    ddimSteps: 20,
    guessMode: false,
    strength: 1.0,
    scale: 9.0,
    seed: -1,
    eta: 0.0,
    lowThreshold: 100,
    highThreshold: 200
  })

  function addMessage(msg) {
    messages.value.push({
      id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      timestamp: Date.now(),
      ...msg
    })
  }

  function updateMessage(id, updates) {
    const idx = messages.value.findIndex(m => m.id === id)
    if (idx !== -1) {
      messages.value[idx] = { ...messages.value[idx], ...updates }
    }
  }

  async function sendGenerateRequest(prompt, imageFile) {
    if (isGenerating.value) return
    isGenerating.value = true

    const imagePreviewUrl = URL.createObjectURL(imageFile)
    addMessage({
      role: 'user',
      type: 'generate',
      content: prompt,
      image: imagePreviewUrl
    })

    const assistantMsgId = `msg-${Date.now()}-assistant`
    messages.value.push({
      id: assistantMsgId,
      role: 'assistant',
      type: 'generating',
      content: '',
      status: 'PENDING',
      images: [],
      timestamp: Date.now()
    })

    try {
      const formData = new FormData()
      formData.append('image', imageFile)
      formData.append('prompt', prompt)
      Object.entries(settings.value).forEach(([key, val]) => {
        formData.append(key, val)
      })

      const submitRes = await submitTask(formData)
      const taskId = submitRes.data.taskId
      currentTaskId.value = taskId

      updateMessage(assistantMsgId, { status: 'PENDING', taskId })

      const result = await pollTaskUntilDone(taskId, (progress) => {
        updateMessage(assistantMsgId, { status: progress.status })
      })

      if (result.status === 'COMPLETED') {
        updateMessage(assistantMsgId, {
          type: 'result',
          status: 'COMPLETED',
          images: result.images || [],
          timeInfo: result.timeInfo
        })
      } else {
        updateMessage(assistantMsgId, {
          type: 'error',
          status: 'FAILED',
          content: result.errorMsg || '生成失败，请重试'
        })
      }
    } catch (e) {
      updateMessage(assistantMsgId, {
        type: 'error',
        status: 'FAILED',
        content: e.message || '请求失败，请检查网络连接'
      })
    } finally {
      isGenerating.value = false
      currentTaskId.value = null
    }
  }

  return {
    messages,
    isGenerating,
    currentTaskId,
    settings,
    settingsVisible,
    addMessage,
    updateMessage,
    sendGenerateRequest
  }
})
