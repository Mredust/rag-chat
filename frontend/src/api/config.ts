import { http } from './client'
import type { SystemConfigList } from '../types'

export const configApi = {
  list: () => http.get<SystemConfigList>('/config'),
  update: (key: string, value: string, isSecret: boolean) =>
    http.put<null>(`/config/${key}`, { value, is_secret: isSecret }),
}