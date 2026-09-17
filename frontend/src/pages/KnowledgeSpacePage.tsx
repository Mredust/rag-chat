import {
  ArrowLeft,
  FileText,
  FolderOpen,
  Loader2,
  Pencil,
  Trash2,
  Upload,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ApiError } from '../api/client'
import { knowledgeApi } from '../api/knowledge'
import Modal from '../components/Modal'
import { formatSize, statusClass } from '../lib/format'
import { useKnowledgeStore } from '../store/knowledge'
import type { Chunk, Document } from '../types'

const PROCESSING_STATUS = ['待处理', '解析中', '切片中', '向量化中']

export default function KnowledgeSpacePage() {
  const { spaceId = '' } = useParams<{ spaceId: string }>()
  const navigate = useNavigate()

  const {
    spaces,
    fetchSpaces,
    documents,
    documentsLoading,
    fetchDocuments,
    updateDocument,
    deleteDocument,
  } = useKnowledgeStore()

  const space = spaces.find((s) => s.id === spaceId) ?? null

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)

  const [docModalMode, setDocModalMode] = useState<'rename' | null>(null)
  const [editingDoc, setEditingDoc] = useState<Document | null>(null)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Document | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    fetchSpaces().catch(() => { })
  }, [fetchSpaces])

  useEffect(() => {
    if (spaceId) {
      fetchDocuments(spaceId).catch(() => { })
    }
  }, [spaceId, fetchDocuments])

  // 实时刷新：存在处理中的文档时轮询列表，直到全部完成/失败
  const hasProcessing = documents.some((d) => PROCESSING_STATUS.includes(d.status))
  useEffect(() => {
    if (!spaceId || !hasProcessing) return
    const timer = setInterval(() => {
      fetchDocuments(spaceId).catch(() => { })
    }, 5000)
    return () => clearInterval(timer)
  }, [spaceId, hasProcessing, fetchDocuments])

  const selectDoc = async (doc: Document) => {
    setSelectedDocId(doc.id)
    setChunks([])
    setChunksLoading(true)
    try {
      const res = await knowledgeApi.listChunks(spaceId, doc.id)
      setChunks(res.chunks)
    } catch {
      setChunks([])
    } finally {
      setChunksLoading(false)
    }
  }

  const openRename = (doc: Document) => {
    setFormError('')
    setEditingDoc(doc)
    setDocModalMode('rename')
  }

  const handleRenameSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!editingDoc) return
    const form = new FormData(e.currentTarget)
    const filename = String(form.get('filename') || '').trim()
    if (!filename) {
      setFormError('请输入文档名称')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      await updateDocument(spaceId, editingDoc.id, { filename })
      setDocModalMode(null)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const confirmDeleteDoc = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteDocument(spaceId, deleteTarget.id)
      if (selectedDocId === deleteTarget.id) {
        setSelectedDocId(null)
        setChunks([])
      }
      setDeleteTarget(null)
    } catch {
      /* ignore */
    } finally {
      setDeleting(false)
    }
  }

  const selectedDoc = documents.find((d) => d.id === selectedDocId) ?? null

  return (
    <div>
      {/* 顶部：返回 + 空间标题 + 上传文档按钮 */}
      <div className="mb-5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50"
            title="返回知识库列表"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-900">
              <FolderOpen size={20} className="text-indigo-600" />
              {space?.name ?? '加载中…'}
            </h1>
            {space && (
              <p className="mt-1 max-w-xl text-sm text-slate-500">
                {space.description || '暂无描述'}
              </p>
            )}
          </div>
        </div>

        <button
          type="button"
          onClick={() => navigate(`/knowledge/${spaceId}/import`)}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Upload size={16} />
          上传文档
        </button>
      </div>

      {/* 主体：左文档列表 + 右分块列表 */}
      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        {/* 左侧：文档列表 */}
        <aside className="flex h-[calc(100vh-12rem)] flex-col rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 p-4">
            <h2 className="text-sm font-semibold text-slate-700">
              文档（{documents.length}）
            </h2>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {documentsLoading ? (
              <div className="flex items-center justify-center py-12 text-slate-400">
                <Loader2 size={20} className="animate-spin" />
              </div>
            ) : documents.length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-400">暂无文档</p>
            ) : (
              <ul className="space-y-1">
                {documents.map((doc) => (
                  <li key={doc.id}>
                    <button
                      type="button"
                      onClick={() => selectDoc(doc)}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg p-2.5 text-left transition ${doc.id === selectedDocId
                        ? 'bg-indigo-50 ring-1 ring-indigo-200'
                        : 'hover:bg-slate-50'
                        }`}
                    >
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                          <FileText size={16} />
                        </span>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-slate-900">
                            {doc.filename}
                          </div>
                          <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                            <span>{doc.file_type}</span>
                            <span>{formatSize(doc.file_size)}</span>
                          </div>
                        </div>
                      </div>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${statusClass(doc.status)}`}
                      >
                        {doc.status}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* 右侧：分块列表 */}
        <section className="flex h-[calc(100vh-12rem)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 p-4">
            <h2 className="truncate text-sm font-semibold text-slate-700">
              {selectedDoc ? `分块 · ${selectedDoc.filename}` : '分块列表'}
            </h2>
            {selectedDoc && (
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={() => openRename(selectedDoc)}
                  className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  title="重命名"
                >
                  <Pencil size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => setDeleteTarget(selectedDoc)}
                  className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  title="删除"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {!selectedDoc ? (
              <div className="flex h-full flex-col items-center justify-center text-slate-400">
                <FileText size={40} className="mb-3" />
                <p className="text-sm">请在左侧选择文档查看其分块</p>
              </div>
            ) : chunksLoading ? (
              <div className="flex items-center justify-center py-20 text-slate-400">
                <Loader2 size={20} className="animate-spin" />
              </div>
            ) : chunks.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-slate-400">
                <FileText size={40} className="mb-3" />
                <p className="text-sm">该文档暂无分块（可能尚未处理完成）</p>
              </div>
            ) : (
              <div className="space-y-3">
                {chunks.map((c) => (
                  <div
                    key={c.id}
                    className="rounded-lg border border-slate-200 p-3 transition-colors hover:border-purple-200 hover:bg-purple-50"
                  >
                    <div className="mb-1.5 flex items-center gap-2 text-xs text-slate-400">
                      <span className="font-medium text-slate-600">
                        片段 #{c.chunk_index + 1}
                      </span>
                      <span>· 字数 {c.char_count}</span>
                    </div>
                    <div className="markdown-body text-sm text-slate-700">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{c.content}</ReactMarkdown>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* 文档重命名弹窗 */}
      <Modal open={docModalMode === 'rename'} title="编辑文档" onClose={() => setDocModalMode(null)}>
        <form onSubmit={handleRenameSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">文档名称</label>
            <input
              name="filename"
              required
              maxLength={255}
              defaultValue={editingDoc?.filename ?? ''}
              placeholder="例如：产品使用手册.txt"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          {formError && <p className="text-sm text-red-600">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDocModalMode(null)}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              保存
            </button>
          </div>
        </form>
      </Modal>

      {/* 删除文档确认 */}
      <Modal open={deleteTarget !== null} title="删除确认" onClose={() => setDeleteTarget(null)}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">
            确定删除文档「{deleteTarget?.filename}」吗？此操作不可恢复。
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDeleteTarget(null)}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={confirmDeleteDoc}
              disabled={deleting}
              className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-60"
            >
              {deleting && <Loader2 size={14} className="animate-spin" />}
              确认删除
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}