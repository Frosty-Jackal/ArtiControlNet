// 服务次数耗尽提示的唯一落点（Spec18 §7.1）。
//
// Spec21 §7.7：多带一个"是谁被锁了"。
// 为什么需要：auth.logout() 会清掉 store 里的 username，而登录页的欠费充值面板
// 要把账号预填进去。写入方仍是 2 处，但分工变了：
//   api/chatApi.js 的 40304 分支 → 只写 message（拦截器里拿不到 store）
//   App.vue 的 artcn:quota_exceeded 监听 → 补写 username（此刻 auth.username 还在）
// 读取方仍是 1 处：views/Login.vue 挂载时取走。
// 用完即清（take 而非 get）：同一条警告只显示一次，刷新页面不该又冒出来。
// （提示语现在是登录页上的一行红字 + 一块充值面板，不再是 window.alert。）
import { ref } from 'vue'

export const quotaNotice = ref('')
export const quotaUsername = ref('')

export function setQuotaNotice(message) {
  if (message) quotaNotice.value = message
}

export function setQuotaUsername(name) {
  quotaUsername.value = name || ''
}

// 返回值从 string 变成对象——**两处写入方、一处读取方**都要跟着改（Spec21 §12 第 9 步）
export function takeQuotaNotice() {
  const payload = { message: quotaNotice.value, username: quotaUsername.value }
  quotaNotice.value = ''
  quotaUsername.value = ''
  return payload
}
