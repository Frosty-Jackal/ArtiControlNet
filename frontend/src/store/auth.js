import { defineStore } from 'pinia'
import {
  clearToken, getToken, login as apiLogin, loginByEmailApi, me as apiMe,
  submitRegisterRequest as apiRegister
} from '../api/chatApi'
import { setQuotaNotice } from '../utils/quotaNotice'

// 登录态存 localStorage；登出 = 清 token（Spec2 §3 范围内）
const TOKEN_KEY = 'artcn_token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    username: '',
    isAdmin: false,
    loaded: false // 启动时是否已完成 token 校验
  }),

  actions: {
    // App 启动时调用：有 token 则向后端校验（GET /api/auth/me），失败回登录页
    async init() {
      this.loaded = false
      if (!this.token) {
        this.loaded = true
        return
      }
      try {
        const info = await apiMe()
        this.username = info.username
        this.isAdmin = info.is_admin
      } catch (e) {
        // Spec18 §7.3：启动时已超额（如换了设备登录、或后端在本设备停用期间被改小限额）
        // ——没有这一行，被踢的用户会**静默**回到登录页，不知道发生了什么。
        if (e.code === 40304) setQuotaNotice(e.message)
        this.logout() // token 失效 / 过期 / 超额
      } finally {
        this.loaded = true
      }
    },

    async login(username, password) {
      const res = await apiLogin(username, password)
      this.token = res.token
      this.username = res.username
      this.isAdmin = res.is_admin
      localStorage.setItem(TOKEN_KEY, res.token)
    },

    // Spec22 §6.4：邮箱验证码登录。收尾与 login() 完全一致——token / username /
    // is_admin 三个一落，App.vue 的 v-if 自动切到聊天视图，调用方不用做任何事。
    //
    // **40304（欠费）不在这里处理**：与 login() 的处境一模一样，store 只负责
    // "登录成功之后怎么收尾"，被拒时的欠费面板由调用方（Login.vue，Spec21 §7.4
    // 的那一行 `overdraft.value = {...}`）挂——这里**不另写一套**。
    async loginByEmail(email, code) {
      const res = await loginByEmailApi(email, code)
      this.token = res.token
      this.username = res.username
      this.isAdmin = res.is_admin
      localStorage.setItem(TOKEN_KEY, res.token)
    },

    // Spec23 §2.5：自助注册。后端在同一次响应里签发 token，所以收尾三行与
    // login() / loginByEmail() **逐字相同**——三个一落，App.vue 的 v-if 自动切视图。
    //
    // 与 login() 的处境差别只有一个：这里**不会**遇到 40304（新号刚拿到 10 次额度，
    // 不可能超额），所以不需要调用方挂欠费面板。
    //
    // 连带的好处（§2.5）：username 变化会触发 App.vue 那个 watcher，于是"首次登录
    // 自动弹帮助"对刚注册的人也自动生效——他刚读完改过文案的那一份帮助。
    async register(username, password, email, code) {
      const res = await apiRegister({ username, password, email, code })
      this.token = res.token
      this.username = res.username
      this.isAdmin = res.is_admin
      localStorage.setItem(TOKEN_KEY, res.token)
    },

    // 重新向后端同步当前用户信息（管理端操作后刷新权限）
    async refresh() {
      try {
        const info = await apiMe()
        this.username = info.username
        this.isAdmin = info.is_admin
      } catch (e) {
        this.logout()
      }
    },

    logout() {
      this.token = ''
      this.username = ''
      this.isAdmin = false
      clearToken()
    }
  }
})
