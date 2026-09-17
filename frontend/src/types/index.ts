// 与后端统一响应 { code, message, data, request_id } 对应的类型

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  request_id: string
}

export interface UserInfo {
  id: string
  username: string
  email: string
  avatar: string | null
  introduction: string | null
  status: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface KnowledgeSpace {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
}

export interface KnowledgeSpaceList {
  spaces: KnowledgeSpace[]
  total: number
}

export interface Document {
  id: string
  space_id: string
  filename: string
  file_type: string
  file_size: number
  storage_path: string
  status: string
  chunk_count: number
  char_count: number
  created_at: string
  processed_at: string | null
}

export interface DocumentList {
  documents: Document[]
  total: number
}

export interface Chunk {
  id: string
  document_id: string
  chunk_index: number
  content: string
  char_count: number
  meta: Record<string, unknown>
}

export interface ChunkList {
  chunks: Chunk[]
  total: number
}

export interface Citation {
  chunk_id: string
  document_id: string
  filename: string
  content: string
  score: number
}

export interface Conversation {
  id: string
  space_id: string | null
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationList {
  conversations: Conversation[]
  total: number
}

export interface Message {
  id: number
  conversation_id: string
  role: string
  content: string
  citations: Citation[] | null
  created_at: string
}

export interface MessageList {
  messages: Message[]
  total: number
}

export interface SystemConfig {
  key: string
  value: string
  is_secret: boolean
  updated_at: string
}

export interface SystemConfigList {
  configs: SystemConfig[]
  total: number
}

export interface Provider {
  id: string
  name: string
  api_type: string
  api_base: string
  model_name: string
  model_names: string[]
  is_active: boolean
  has_key: boolean
  masked_key: string
  created_at: string
}

export interface ProviderList {
  providers: Provider[]
  total: number
}

export interface ProviderPayload {
  name: string
  api_type: string
  api_base: string
  model_name: string
  model_names?: string[]
  api_key?: string
}

// 流式事件（SSE）
export interface StreamEvent {
  type: string
  data: unknown
}

