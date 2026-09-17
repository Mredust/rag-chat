import { http, postStream } from './client'
import type { ConversationList, MessageList, StreamEvent } from '../types'

export interface ChatPayload {
  question: string
  conversation_id?: string | null
  space_id?: string | null
  title?: string
}

export const chatApi = {
  listConversations: () => http.get<ConversationList>('/chat/conversations'),
  getMessages: (conversationId: string) =>
    http.get<MessageList>(`/chat/conversations/${conversationId}/messages`),
  deleteConversation: (conversationId: string) =>
    http.delete<null>(`/chat/conversations/${conversationId}`),

  ask: (payload: ChatPayload, onEvent: (event: StreamEvent) => void) =>
    postStream('/chat', payload, onEvent),
}