// Spec22 §2.9：五个入口点击的不重复 IP 统计。
//
// **刻意不用 api/chatApi.js 的 axios 实例**：
//   那个实例的响应拦截器会在 401 / 40304 时触发 artcn:unauthorized /
//   artcn:quota_exceeded 全局事件 —— 埋点绝不能把用户踢下线。
//   裸 fetch 彻底解耦，也省掉"这条路由必须留在公开白名单里，否则会登出"
//   这种看不见的隐式耦合。
//
// **不 await、异常全吞**：埋点是顺手记一笔，失败不能影响任何主流程。
const EVENTS = ['login_page', 'register', 'community', 'gallery', 'recharge']

// 与 api/chatApi.js 顶部同一口径（Spec22 §7.5）：前端独立部署时 VITE_API_BASE
// 指向远端后端，裸 '/api/click' 会打到前端自己的域名上。
const API_BASE = import.meta.env.VITE_API_BASE || ''

export function trackClick(event) {
  if (!EVENTS.includes(event)) return // 本地白名单，防止手误写出后端会拒的事件名
  try {
    fetch(`${API_BASE}/api/click`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event }),
      keepalive: true // 页面正在跳转时也把请求发完
    }).catch(() => {})
  } catch {
    /* 老浏览器没有 fetch 也照样不报错 */
  }
}
