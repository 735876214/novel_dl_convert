import { defineStore } from 'pinia'
import { api } from '@/lib/api'

const TOKEN_KEY = 'nf_token'

interface AuthState {
  token: string
  user: string
  /** 是否已尝试过鉴权初始化（用于决定是否显示登录门禁） */
  ready: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: (() => {
      try {
        return localStorage.getItem(TOKEN_KEY) || ''
      } catch {
        return ''
      }
    })(),
    user: '',
    ready: false,
  }),

  getters: {
    authenticated: (s) => !!s.token,
  },

  actions: {
    _setToken(t: string) {
      this.token = t
      try {
        if (t) localStorage.setItem(TOKEN_KEY, t)
        else localStorage.removeItem(TOKEN_KEY)
      } catch {
        /* ignore */
      }
    },

    logout() {
      this._setToken('')
      this.user = ''
    },

    async login(user: string, pin: string) {
      const r = await api.login(user, pin)
      this._setToken(r.token)
      this.user = r.user
    },

    /** 首屏调用：若已有 token 则校验，否则标记为未登录。 */
    async init() {
      if (!this.token) {
        this.ready = true
        return
      }
      try {
        const m = await api.me()
        this.user = m.user
      } catch {
        this._setToken('')
      }
      this.ready = true
    },
  },
})
