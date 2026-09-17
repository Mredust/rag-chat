import { Box, Check, Copy, Loader2, Plus, RefreshCw, Search, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import Modal from '../../components/Modal'
import { formatDate } from '../../lib/format'
import type { MLModel } from '../../types/ml'
import { badgeCls, badgeLabel } from './constants'

/** 模型来源中文标签 */
const SOURCE_LABELS: Record<string, string> = {
  system: '系统内置模型',
  ftm: '微调模型',
  local: '本地模型',
}

/** 模型来源标签样式 */
const SOURCE_CLS: Record<string, string> = {
  system: 'bg-blue-50 text-blue-600',
  ftm: 'bg-purple-50 text-purple-600',
  local: 'bg-slate-100 text-slate-600',
}

const sourceLabel = (s?: string) => SOURCE_LABELS[s ?? ''] ?? '本地模型'
const sourceCls = (s?: string) => SOURCE_CLS[s ?? ''] ?? 'bg-slate-100 text-slate-600'

export default function ModelListPage() {
  const navigate = useNavigate()
  const [models, setModels] = useState<MLModel[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [deleteItem, setDeleteItem] = useState<MLModel | null>(null)
  const [deleteLocal, setDeleteLocal] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await mlApi.listModels(search || undefined)
      setModels(res.models)
    } catch {
      /* ignore */
    } finally {
      if (!silent) setLoading(false)
    }
  }, [search])

  useEffect(() => {
    load()
  }, [load])

  // 存在「导入中」模型时静默轮询，避免每轮刷新触发全表 loading 闪烁
  useEffect(() => {
    if (!models.some((m) => m.status === 'importing')) return
    const timer = window.setInterval(() => load(true), 2000)
    return () => window.clearInterval(timer)
  }, [models, load])

  const handleConfirmDelete = async () => {
    if (!deleteItem) return
    setDeleting(true)
    try {
      await mlApi.deleteModel(deleteItem.id, deleteLocal)
      setDeleteItem(null)
      setDeleteLocal(false)
      await load()
    } catch (err) {
      setDeleteItem(null)
      setDeleteLocal(false)
      window.alert(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const handleSaveLocal = async (model: MLModel) => {
    setBusyId(model.id)
    try {
      await mlApi.saveModelLocal(model.id)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '保存到本地失败')
    } finally {
      setBusyId(null)
    }
  }

  const handleCopyName = async (model: MLModel) => {
    try {
      await navigator.clipboard.writeText(model.name)
      setCopiedId(model.id)
      window.setTimeout(() => setCopiedId(null), 2000)
    } catch {
      /* ignore */
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-900">我的模型</h2>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{models.length}</span>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => load()} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
            <RefreshCw size={14} />
            刷新
          </button>
          <button type="button" onClick={() => navigate('/ml/models/import')} className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700">
            <Plus size={16} />
            导入模型
          </button>
        </div>
      </div>

      {/* 搜索栏 */}
      <div className="mb-4 flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
        <div className="relative">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索模型"
            className="w-64 rounded-lg border border-slate-300 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-indigo-500"
          />
        </div>
      </div>

      {/* 表格 */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
              <th className="px-4 py-3 font-medium">模型名称/ID</th>
              <th className="px-4 py-3 font-medium">基础模型</th>
              <th className="px-4 py-3 font-medium">来源</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">创建时间</th>
              <th className="px-4 py-3 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6}>
                  <div className="flex justify-center py-16 text-slate-400">
                    <Loader2 size={22} className="animate-spin" />
                  </div>
                </td>
              </tr>
            ) : models.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  <div className="flex flex-col items-center justify-center py-20">
                    <Box size={36} className="mb-3 text-slate-200" />
                    <p className="text-sm text-slate-500">暂无模型</p>
                    <p className="mt-1 text-xs text-slate-400">点击右上角「导入模型」导入模型文件夹</p>
                  </div>
                </td>
              </tr>
            ) : (
              models.map((m) => (
                <tr key={m.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                        <Box size={16} />
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-medium text-slate-900">{m.name}</span>
                          <button
                            type="button"
                            onClick={() => handleCopyName(m)}
                            title="复制模型名称"
                            className="shrink-0 text-slate-400 hover:text-slate-600"
                          >
                            {copiedId === m.id ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                          </button>
                        </div>
                        <div className="truncate font-mono text-xs text-slate-400" title={m.id}>{m.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600" title={m.base_model}>{m.base_model}</td>
                  <td className="px-4 py-3">
                    {m.source_type === 'provider' ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-600">
                        {m.provider_config?.provider || '供应商模型'}
                      </span>
                    ) : (
                      <span className={`rounded-full px-2 py-0.5 text-xs ${sourceCls(m.source_type)}`}>{sourceLabel(m.source_type)}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(m.status)}`}>{badgeLabel(m.status)}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{formatDate(m.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {!m.is_local && m.source_type !== 'provider' && (
                        <button type="button" onClick={() => handleSaveLocal(m)} disabled={busyId === m.id} className="flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-60">
                          {busyId === m.id && <Loader2 size={13} className="animate-spin" />}
                          保存到本地
                        </button>
                      )}
                      <button type="button" onClick={() => { setDeleteItem(m); setDeleteLocal(false) }} className="flex items-center gap-1 text-xs text-red-500 hover:underline">
                        <Trash2 size={13} />
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 删除确认 */}
      <Modal open={deleteItem !== null} title="删除确认" onClose={() => { setDeleteItem(null); setDeleteLocal(false) }}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">确定删除模型「{deleteItem?.name}」吗？此操作不可恢复。</p>
          {deleteItem && deleteItem.is_local && deleteItem.source_type !== 'system' && (
            <label className="flex items-start gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={deleteLocal}
                onChange={(e) => setDeleteLocal(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span>同时删除 models 目录下的本地模型文件夹</span>
            </label>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setDeleteItem(null); setDeleteLocal(false) }} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
              取消
            </button>
            <button type="button" onClick={handleConfirmDelete} disabled={deleting} className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-60">
              {deleting && <Loader2 size={14} className="animate-spin" />}
              确认删除
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}