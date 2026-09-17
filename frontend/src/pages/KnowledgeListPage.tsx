import { FolderOpen, Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import Modal from '../components/Modal'
import { formatDate } from '../lib/format'
import { useKnowledgeStore } from '../store/knowledge'
import type { KnowledgeSpace } from '../types'

export default function KnowledgeListPage() {
  const {
    spaces,
    spacesLoading,
    fetchSpaces,
    createSpace,
    updateSpace,
    deleteSpace,
  } = useKnowledgeStore()

  const navigate = useNavigate()

  const [spaceModalMode, setSpaceModalMode] = useState<'create' | 'edit' | null>(null)
  const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetchSpaces().catch(() => { })
  }, [fetchSpaces])

  const openCreateSpace = () => {
    setFormError('')
    setEditingSpace(null)
    setSpaceModalMode('create')
  }

  const openEditSpace = (space: KnowledgeSpace) => {
    setFormError('')
    setEditingSpace(space)
    setSpaceModalMode('edit')
  }

  const handleSpaceSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const name = String(form.get('name') || '').trim()
    const description = String(form.get('description') || '').trim()
    if (!name) {
      setFormError('请输入知识库名称')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      if (spaceModalMode === 'create') {
        await createSpace({ name, description })
      } else if (editingSpace) {
        await updateSpace(editingSpace.id, { name, description })
      }
      setSpaceModalMode(null)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteSpace = async (space: KnowledgeSpace) => {
    if (!window.confirm(`确定删除知识库「${space.name}」及其所有文档吗？`)) return
    await deleteSpace(space.id)
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-900">
          <FolderOpen size={22} className="text-indigo-600" />
          知识库
        </h1>
        <button
          type="button"
          onClick={openCreateSpace}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus size={16} />
          新建知识库
        </button>
      </div>

      {spacesLoading ? (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 size={24} className="animate-spin" />
        </div>
      ) : spaces.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white py-20 text-slate-400">
          <FolderOpen size={40} className="mb-3" />
          <p className="text-sm">暂无知识库，点击右上角「新建知识库」创建</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {spaces.map((space) => (
            <div
              key={space.id}
              onClick={() => navigate(`/knowledge/${space.id}`)}
              className="group flex cursor-pointer flex-col rounded-xl border border-slate-200 bg-white p-5 transition hover:border-indigo-300 hover:shadow-sm"
            >
              <div className="mb-3 flex items-start justify-between">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                  <FolderOpen size={20} />
                </span>
                <div className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      openEditSpace(space)
                    }}
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                    title="编辑"
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteSpace(space)
                    }}
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                    title="删除"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>

              <h2 className="truncate font-semibold text-slate-900">{space.name}</h2>
              <p className="mt-1 line-clamp-2 flex-1 text-sm text-slate-500">
                {space.description || '暂无描述'}
              </p>
              <p className="mt-3 text-xs text-slate-400">创建于 {formatDate(space.created_at)}</p>
            </div>
          ))}
        </div>
      )}

      {/* 知识库创建/编辑弹窗 */}
      <Modal
        open={spaceModalMode !== null}
        title={spaceModalMode === 'create' ? '新建知识库' : '编辑知识库'}
        onClose={() => setSpaceModalMode(null)}
      >
        <form onSubmit={handleSpaceSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">名称</label>
            <input
              name="name"
              required
              maxLength={128}
              defaultValue={editingSpace?.name ?? ''}
              placeholder="知识库名称"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">描述</label>
            <textarea
              name="description"
              rows={3}
              maxLength={5000}
              defaultValue={editingSpace?.description ?? ''}
              placeholder="简单描述该知识库（可选）"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          {formError && <p className="text-sm text-red-600">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setSpaceModalMode(null)}
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
    </div>
  )
}