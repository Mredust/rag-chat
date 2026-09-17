import { http } from './client'
import type { Provider, ProviderList, ProviderPayload } from '../types'

export const providerApi = {
  list: () => http.get<ProviderList>('/providers'),
  create: (data: ProviderPayload) => http.post<Provider>('/providers', data),
  update: (id: string, data: ProviderPayload) => http.put<Provider>(`/providers/${id}`, data),
  remove: (id: string) => http.delete<null>(`/providers/${id}`),
  activate: (id: string) => http.post<Provider>(`/providers/${id}/activate`),
  deactivate: (id: string) => http.post<Provider>(`/providers/${id}/deactivate`),
}