// 服务次数耗尽提示的唯一落点（Spec18 §7.1）。
// 两条写入方：api/chatApi.js 的 40304 拦截分支（在系统里被踢）、
//             store/auth.js 的 init() 40304 分支（启动时已超额）。
// 一个读取方：views/Login.vue 挂载时取走并弹窗。
// 用完即清（take 而非 get）：同一条警告只弹一次，用户点了"确定"之后再刷新页面
// 不该又被弹一遍。
import { ref } from 'vue'

export const quotaNotice = ref('')

export function setQuotaNotice(message) {
  if (message) quotaNotice.value = message
}

export function takeQuotaNotice() {
  const message = quotaNotice.value
  quotaNotice.value = ''
  return message
}
