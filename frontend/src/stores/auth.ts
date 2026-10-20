import { defineStore } from 'pinia'
import { api, type AccountProfile } from '@/lib/api'

const TOKEN_KEY = 'nf_token'

interface AuthState {
  token: string
  user: string
  /** 展示名（账号资料，可空，空时回退 username） */
  displayName: string
  /** IANA 时区（用于时间类成就归一） */
  timezone: string
  /** 头像分发 URL（带 ?token=，可空） */
  avatarUrl: string | null
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
    displayName: '',
    timezone: '',
    avatarUrl: null,
    ready: false,
  }),

  getters: {
    authenticated: (s) => !!s.token,
    /** 顶栏/资料页显示名：优先展示名，回退 username。 */
    display: (s) => s.displayName || s.user || '已登录',
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
      this.displayName = ''
      this.timezone = ''
      this.avatarUrl = null
    },

    /** 拉取账号资料写进 store（失败不致命，保留现有值）。 */
    async loadProfile() {
      try {
        this.applyProfile(await api.getProfile())
      } catch {
        /* 未登录或非致命：保留现有值 */
      }
    },

    /** 用后端返回的资料覆盖 store 字段。 */
    applyProfile(p: AccountProfile) {
      if (p.username) this.user = p.username
      this.displayName = p.display_name || ''
      this.timezone = p.timezone || ''
      this.avatarUrl = p.avatar_url || null
    },

    async login(user: string, pin: string) {
      const r = await api.login(user, pin)
      this._setToken(r.token)
      this.user = r.user
      await this.loadProfile()
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
        await this.loadProfile()
      } catch {
        // `api.request()` 只在 **401** 时删 `nf_token`（并派发 `nf-unauthorized`
        // 弹出登录门禁）。502（后端重启中）/ 超时 / 断网都属于「暂时问不到」，
        // 第 135 期前一概清 token ⇒ 服务端打个嗝就把人锁在登录页，还要重输密码。
        // 以 **localStorage 为准**：401 的清理发生在 api 层，pinia 里的旧值不会变。
        let alive: string
        try {
          alive = localStorage.getItem(TOKEN_KEY) || ''
        } catch {
          alive = this.token // 隐私模式读不到 ≠ 未登录，按原值保留
        }
        if (!alive) this._setToken('')
      }
      this.ready = true
    },
  },
})
