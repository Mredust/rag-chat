import { http } from './client'
import type { TokenResponse, UserInfo } from '../types'

export interface RegisterPayload {
  username: string
  password: string
  email: string
}

export interface LoginPayload {
  username: string
  password: string
}

export const authApi = {
  register: (data: RegisterPayload) => http.post<UserInfo>('/auth/register', data),
  login: (data: LoginPayload) => http.post<TokenResponse>('/auth/login', data),
  getMe: () => http.get<UserInfo>('/user/me'),
}