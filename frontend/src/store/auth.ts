import { create } from 'zustand'
import { authApi, type LoginPayload, type RegisterPayload } from '../api/auth'
import { clearToken, getToken, setToken } from '../api/client'
import type { UserInfo } from '../types'

interface AuthState {
  token: string | null
  user: UserInfo | null
  loading: boolean
  login: (data: LoginPayload) => Promise<void>
  register: (data: RegisterPayload) => Promise<void>
  fetchMe: () => Promise<void>
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: getToken(),
  user: null,
  loading: false,

  login: async (data) => {
    set({ loading: true })
    try {
      const res = await authApi.login(data)
      setToken(res.access_token)
      set({ token: res.access_token })
      const user = await authApi.getMe()
      set({ user })
    } finally {
      set({ loading: false })
    }
  },

  register: async (data) => {
    set({ loading: true })
    try {
      await authApi.register(data)
      // 注册成功后自动登录
      const res = await authApi.login({ username: data.username, password: data.password })
      setToken(res.access_token)
      set({ token: res.access_token })
      const user = await authApi.getMe()
      set({ user })
    } finally {
      set({ loading: false })
    }
  },

  fetchMe: async () => {
    if (!getToken()) return
    set({ loading: true })
    try {
      const user = await authApi.getMe()
      set({ user })
    } catch {
      clearToken()
      set({ token: null, user: null })
    } finally {
      set({ loading: false })
    }
  },

  logout: () => {
    clearToken()
    set({ token: null, user: null })
  },
}))