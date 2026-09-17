import { http, getToken, ApiError } from './client'
import type {
  ApiResponse,
  ChunkList,
  Document,
  DocumentList,
  KnowledgeSpace,
  KnowledgeSpaceList,
} from '../types'

export interface SpacePayload {
  name: string
  description?: string
}

export interface DocumentPayload {
  filename: string
  file_type?: string
  file_size?: number
  storage_path?: string
}

// 导入向导分段策略
export interface ImportStrategy {
  segment_mode: 'auto' | 'custom' | 'hierarchy'
  parse_mode: 'accurate' | 'fast'
  max_level?: number
  keep_hierarchy?: boolean
  chunk_size?: number
  chunk_overlap?: number
  separator?: string
  collapse_whitespace?: boolean
  remove_urls_email?: boolean
}

export interface PreviewChunk {
  content: string
  level: number | null
  title: string | null
}

export interface DocumentPreview {
  filename: string
  file_type: string
  file_size: number
  raw_text: string
  chunks: PreviewChunk[]
  chunk_count: number
}

export interface ImportResult {
  documents: Document[]
  total: number
}

const API_BASE = '/api/v1'

async function readBody<T>(res: Response): Promise<T> {
  let body: ApiResponse<T>
  try {
    body = (await res.json()) as ApiResponse<T>
  } catch {
    throw new ApiError('服务器返回格式错误', -1, res.status)
  }
  if (!res.ok || body.code !== 0) {
    throw new ApiError(body.message || '请求失败', body.code, res.status)
  }
  return body.data
}

function appendStrategy(form: FormData, s: ImportStrategy): void {
  form.append('segment_mode', s.segment_mode)
  form.append('parse_mode', s.parse_mode)
  form.append('keep_hierarchy', String(s.keep_hierarchy ?? false))
  form.append('collapse_whitespace', String(s.collapse_whitespace ?? false))
  form.append('remove_urls_email', String(s.remove_urls_email ?? false))
  if (s.segment_mode === 'hierarchy') {
    form.append('max_level', String(s.max_level ?? 3))
  } else if (s.segment_mode === 'custom') {
    form.append('chunk_size', String(s.chunk_size ?? 800))
    form.append('chunk_overlap', String(s.chunk_overlap ?? 10))
    form.append('separator', s.separator ?? '\n')
  }
}

async function previewImport(
  spaceId: string,
  file: File,
  strategy: ImportStrategy,
): Promise<DocumentPreview> {
  const token = getToken()
  const form = new FormData()
  form.append('file', file)
  appendStrategy(form, strategy)

  const res = await fetch(`${API_BASE}/knowledge/spaces/${spaceId}/import/preview`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  return readBody<DocumentPreview>(res)
}

async function batchImport(
  spaceId: string,
  files: File[],
  strategy: ImportStrategy,
): Promise<ImportResult> {
  const token = getToken()
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  appendStrategy(form, strategy)

  const res = await fetch(`${API_BASE}/knowledge/spaces/${spaceId}/import`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  return readBody<ImportResult>(res)
}

export const knowledgeApi = {
  // 知识库（空间）
  listSpaces: () => http.get<KnowledgeSpaceList>('/knowledge/spaces'),
  createSpace: (data: SpacePayload) => http.post<KnowledgeSpace>('/knowledge/spaces', data),
  updateSpace: (spaceId: string, data: Partial<SpacePayload>) =>
    http.put<KnowledgeSpace>(`/knowledge/spaces/${spaceId}`, data),
  deleteSpace: (spaceId: string) => http.delete<null>(`/knowledge/spaces/${spaceId}`),

  // 文档
  listDocuments: (spaceId: string) =>
    http.get<DocumentList>(`/knowledge/spaces/${spaceId}/documents`),
  updateDocument: (spaceId: string, docId: string, data: Partial<DocumentPayload>) =>
    http.put<Document>(`/knowledge/spaces/${spaceId}/documents/${docId}`, data),
  deleteDocument: (spaceId: string, docId: string) =>
    http.delete<null>(`/knowledge/spaces/${spaceId}/documents/${docId}`),

  // 导入向导：预览 + 按策略批量导入
  previewImport: (spaceId: string, file: File, strategy: ImportStrategy) =>
    previewImport(spaceId, file, strategy),
  batchImport: (spaceId: string, files: File[], strategy: ImportStrategy) =>
    batchImport(spaceId, files, strategy),

  // 切片
  listChunks: (spaceId: string, docId: string) =>
    http.get<ChunkList>(`/knowledge/spaces/${spaceId}/documents/${docId}/chunks`),
}