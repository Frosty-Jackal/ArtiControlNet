import { defineStore } from 'pinia'
import { clearToken, getToken, login as apiLogin, me as apiMe } from '../api/chatApi'

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
        this.logout() // token 失效 / 过期
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
