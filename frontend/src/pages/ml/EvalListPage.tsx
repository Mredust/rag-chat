import {
  CheckCircle2,
  CircleDot,
  ClipboardList,
  Clock,
  Download,
  Gauge,
  ListOrdered,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Square,
  Trash2,
  Trophy,
  X,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import Modal from '../../components/Modal'
import MultiSelect from '../../components/MultiSelect'
import Select from '../../components/Select'
import { formatDate } from '../../lib/format'
import type { MLEvalDimension, MLEvalTask, MLLeaderboard } from '../../types/ml'
import { EVAL_TYPE_LABELS, badgeCls, badgeLabel } from './constants'

type Tab = 'tasks' | 'leaderboard' | 'dimensions'

/* 状态图标 */
function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'done':
      return <CheckCircle2 size={14} className="text-green-500" />
    case 'running':
      return <Loader2 size={14} className="animate-spin text-blue-500" />
    case 'pending':
      return <Clock size={14} className="text-amber-500" />
    case 'failed':
      return <XCircle size={14} className="text-red-500" />
    case 'stopped':
      return <Square size={14} className="text-slate-400" />
    default:
      return <CircleDot size={14} className="text-slate-400" />
  }
}

/* 维度标签：最多展示 5 个，超出用 +N 省略表示 */
function DimensionTags({ names }: { names: string[] }) {
  if (!names?.length) return <span className="text-slate-400">-</span>
  return (
    <div className="flex flex-wrap gap-1">
      {names.slice(0, 5).map((n) => (
        <span key={n} className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{n}</span>
      ))}
      {names.length > 5 && (
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">+{names.length - 5}</span>
      )}
    </div>
  )
}

export default function EvalListPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const [tab, setTab] = useState<Tab>(tabParam === 'dimensions' || tabParam === 'leaderboard' ? tabParam : 'tasks')

  const [tasks, setTasks] = useState<MLEvalTask[]>([])
  const [leaderboards, setLeaderboards] = useState<MLLeaderboard[]>([])
  const [dimensions, setDimensions] = useState<MLEvalDimension[]>([])
  const [loading, setLoading] = useState(true)

  /* 搜索与筛选 */
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [lbFilterDim, setLbFilterDim] = useState('')
  const [lbSort, setLbSort] = useState<'desc' | 'asc'>('desc')

  /* 创建排行榜弹窗 */
  const [showCreate, setShowCreate] = useState(false)
  const [editingLb, setEditingLb] = useState<MLLeaderboard | null>(null)
  const [lbName, setLbName] = useState('')
  const [lbDimensionIds, setLbDimensionIds] = useState<string[]>([])
  const [lbTaskIds, setLbTaskIds] = useState<string[]>([])
  const [lbSubmitting, setLbSubmitting] = useState(false)
  const [lbError, setLbError] = useState('')

  /* 删除确认 */
  const [deleteTarget, setDeleteTarget] = useState<{ kind: 'task' | 'leaderboard' | 'dimension'; id: string; name: string } | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [stoppingIds, setStoppingIds] = useState<Set<string>>(new Set())

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      if (tab === 'tasks') {
        const r = await mlApi.listEvalTasks()
        setTasks(r.tasks)
      } else if (tab === 'leaderboard') {
        const [lr, dr, tr] = await Promise.all([
          mlApi.listLeaderboards(),
          mlApi.listDimensions(),
          mlApi.listEvalTasks(),
        ])
        setLeaderboards(lr.leaderboards)
        setDimensions(dr.dimensions)
        setTasks(tr.tasks)
      } else {
        const r = await mlApi.listDimensions()
        setDimensions(r.dimensions)
      }
    } catch {
      /* ignore */
    } finally {
      if (!silent) setLoading(false)
    }
  }, [tab])

  useEffect(() => {
    load()
  }, [load])

  // 运行中任务轮询（静默刷新，不触发整页 loading 抖动）
  useEffect(() => {
    if (tab !== 'tasks' || !tasks.some((t) => t.status === 'running' || t.status === 'pending')) return
    const timer = setInterval(() => load(true), 3000)
    return () => clearInterval(timer)
  }, [tab, tasks, load])

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      if (deleteTarget.kind === 'task') await mlApi.deleteEvalTask(deleteTarget.id)
      else if (deleteTarget.kind === 'leaderboard') await mlApi.deleteLeaderboard(deleteTarget.id)
      else await mlApi.deleteDimension(deleteTarget.id)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const handleDownloadTask = async (t: MLEvalTask) => {
    try {
      await mlApi.downloadEvalTask(t.id)
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '下载失败')
    }
  }

  const handleStopTask = async (t: MLEvalTask) => {
    if (stoppingIds.has(t.id)) return
    setStoppingIds((prev) => new Set(prev).add(t.id))
    try {
      await mlApi.stopEvalTask(t.id)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '终止失败')
    } finally {
      setStoppingIds((prev) => {
        const next = new Set(prev)
        next.delete(t.id)
        return next
      })
    }
  }

  const openCreate = () => {
    setEditingLb(null)
    setLbName('')
    setLbDimensionIds([])
    setLbTaskIds([])
    setLbError('')
    setShowCreate(true)
  }

  const openEdit = (lb: MLLeaderboard) => {
    setEditingLb(lb)
    setLbName(lb.name)
    setLbDimensionIds(lb.dimension_ids || [])
    setLbTaskIds(lb.task_ids || [])
    setLbError('')
    setShowCreate(true)
  }

  const toggleTask = (id: string) => {
    setLbTaskIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const submitLeaderboard = async () => {
    if (!lbName.trim()) return setLbError('请输入排行榜名称')
    if (lbDimensionIds.length === 0) return setLbError('请选择评测维度')
    setLbSubmitting(true)
    setLbError('')
    try {
      const payload = { name: lbName.trim(), dimension_ids: lbDimensionIds, task_ids: lbTaskIds }
      if (editingLb) {
        await mlApi.updateLeaderboard(editingLb.id, payload)
      } else {
        await mlApi.createLeaderboard(payload)
      }
      setShowCreate(false)
      setEditingLb(null)
      await load()
    } catch (err) {
      setLbError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setLbSubmitting(false)
    }
  }

  /* 筛选后的数据 */
  const filteredTasks = tasks.filter((t) => {
    if (statusFilter && t.status !== statusFilter) return false
    if (search && !t.name.toLowerCase().includes(search.toLowerCase()) && !t.id.includes(search)) return false
    return true
  })
  const filteredDims = dimensions.filter((d) => {
    if (search && !d.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })
  const filteredLeaderboards = leaderboards
    .filter((lb) => !lbFilterDim || (lb.dimension_ids || []).includes(lbFilterDim))
    .sort((a, b) => {
      const ta = new Date(a.created_at).getTime()
      const tb = new Date(b.created_at).getTime()
      return lbSort === 'asc' ? ta - tb : tb - ta
    })

  /* 弹窗中可选任务：需包含所选评测维度之一 */
  const lbTaskOptions = lbDimensionIds.length
    ? tasks.filter((t) => (t.dimension_ids || []).some((id) => lbDimensionIds.includes(id)))
    : []

  /* Tab 按钮 */
  const tabBtn = (v: Tab, label: string, icon: React.ReactNode) => (
    <button
      type="button"
      onClick={() => { setTab(v); setSearch(''); setStatusFilter('') }}
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${tab === v ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-100'}`}
    >
      {icon}
      {label}
    </button>
  )

  /* 右侧主按钮 */
  const primaryBtn = () => {
    if (tab === 'dimensions') {
      return (
        <button type="button" onClick={() => navigate('/ml/eval/dimension/new')} className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700">
          <Plus size={16} />
          创建评测维度
        </button>
      )
    }
    if (tab === 'leaderboard') {
      return (
        <button type="button" onClick={openCreate} className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700">
          <Plus size={16} />
          创建排行榜
        </button>
      )
    }
    return (
      <button type="button" onClick={() => navigate('/ml/eval/new')} className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700">
        <Plus size={16} />
        创建评测任务
      </button>
    )
  }

  const inputCls = 'w-full rounded-lg border border-slate-200 py-2 px-3 text-sm outline-none focus:border-indigo-500'

  return (
    <div>
      {/* 顶部：标题 + Tab + 操作 */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-semibold text-slate-900">模型评测</h2>
          <div className="flex items-center gap-1">
            {tabBtn('tasks', '评测任务', <ClipboardList size={14} />)}
            {tabBtn('leaderboard', '排行榜', <Trophy size={14} />)}
            {tabBtn('dimensions', '评测维度', <Gauge size={14} />)}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={load} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50" title="刷新">
            <RefreshCw size={14} />
          </button>
          {primaryBtn()}
        </div>
      </div>

      {/* 搜索与筛选栏 */}
      {tab === 'tasks' && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="输入任务名称或ID"
              className={inputCls.replace('py-2', 'py-2 pl-9')}
            />
          </div>
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: '', label: '全部状态' },
              { value: 'pending', label: '排队中' },
              { value: 'running', label: '运行中' },
              { value: 'done', label: '已完成' },
              { value: 'failed', label: '失败' },
              { value: 'stopped', label: '已停止' },
            ]}
            className="w-36"
          />
        </div>
      )}

      {tab === 'dimensions' && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="输入维度名称"
              className={inputCls.replace('py-2', 'py-2 pl-9')}
            />
          </div>
        </div>
      )}

      {tab === 'leaderboard' && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Select
            value={lbFilterDim}
            onChange={setLbFilterDim}
            placeholder="请选择评测维度"
            options={dimensions.map((d) => ({ value: d.id, label: d.name }))}
            className="min-w-[200px]"
          />
          <Select
            value={lbSort}
            onChange={(v) => setLbSort(v as 'desc' | 'asc')}
            options={[
              { value: 'desc', label: '按创建时间排序（最新优先）' },
              { value: 'asc', label: '按创建时间排序（最早优先）' },
            ]}
            className="min-w-[220px]"
          />
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-24 text-slate-400">
          <Loader2 size={24} className="animate-spin" />
        </div>
      ) : tab === 'tasks' ? (
        tasks.length === 0 ? (
          <EmptyGuide onCreate={() => navigate('/ml/eval/new')} />
        ) : (
          <div>
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                    <th className="px-4 py-3 font-medium">状态</th>
                    <th className="px-4 py-3 font-medium">任务名称</th>
                    <th className="px-4 py-3 font-medium">模型</th>
                    <th className="px-4 py-3 font-medium">维度</th>
                    <th className="px-4 py-3 font-medium">得分</th>
                    <th className="px-4 py-3 font-medium">时间</th>
                    <th className="px-4 py-3 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTasks.map((t) => {
                    const score = typeof t.result?.score === 'number' ? (t.result.score as number) : null
                    return (
                      <tr key={t.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                        <td className="px-4 py-3">
                          <StatusIcon status={t.status} />
                        </td>
                        <td className="px-4 py-3">
                          <button type="button" onClick={() => navigate(`/ml/eval/${t.id}`)} className="cursor-pointer text-left">
                            <div className="font-medium text-indigo-600">{t.name}</div>
                            <div className="font-mono text-xs text-slate-400" title={t.id}>{t.id.slice(0, 8)}...</div>
                          </button>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{t.model_name || '-'}</td>
                        <td className="px-4 py-3"><DimensionTags names={t.dimension_names || []} /></td>
                        <td className="px-4 py-3">
                          {score !== null ? (
                            <span className="font-mono text-sm font-semibold text-indigo-600">{(score * 100).toFixed(2)}</span>
                          ) : (
                            <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(t.status)}`}>{badgeLabel(t.status)}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{formatDate(t.created_at)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3 text-xs">
                            {(t.status === 'running' || t.status === 'pending') && (
                              <button
                                type="button"
                                onClick={() => handleStopTask(t)}
                                disabled={stoppingIds.has(t.id)}
                                className="flex items-center gap-1 text-amber-600 hover:underline disabled:opacity-50"
                              >
                                {stoppingIds.has(t.id) ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                                终止
                              </button>
                            )}
                            {t.status === 'done' && (
                              <button type="button" onClick={() => handleDownloadTask(t)} className="flex items-center gap-1 text-indigo-600 hover:underline">
                                <Download size={13} />
                                下载
                              </button>
                            )}
                            <button type="button" onClick={() => setDeleteTarget({ kind: 'task', id: t.id, name: t.name })} className="flex items-center gap-1 text-red-500 hover:underline">
                              <Trash2 size={13} />
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                  {filteredTasks.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-16 text-center text-sm text-slate-400">无匹配的评测任务</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : tab === 'leaderboard' ? (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                <th className="px-4 py-3 font-medium">排行榜名称</th>
                <th className="px-4 py-3 font-medium">评测维度</th>
                <th className="px-4 py-3 font-medium">评测任务数</th>
                <th className="px-4 py-3 font-medium">创建时间</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredLeaderboards.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-16 text-center text-sm text-slate-400">暂无排行榜，点击右上角创建</td>
                </tr>
              ) : (
                filteredLeaderboards.map((lb) => (
                  <tr key={lb.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">
                      <button type="button" onClick={() => navigate(`/ml/leaderboard/${lb.id}`)} className="cursor-pointer text-left text-indigo-600">
                        {lb.name}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      {lb.dimension_names?.length ? (
                        <div className="flex flex-wrap gap-1">
                          {lb.dimension_names.map((n) => (
                            <span key={n} className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{n}</span>
                          ))}
                        </div>
                      ) : '-'}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{lb.task_count}</td>
                    <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{formatDate(lb.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3 text-xs">
                        <button type="button" onClick={() => openEdit(lb)} className="flex cursor-pointer items-center gap-1 text-indigo-600">
                          <Pencil size={13} />
                          编辑
                        </button>
                        <button type="button" onClick={() => navigate('/ml/eval/new')} className="flex cursor-pointer items-center gap-1 text-indigo-600">
                          <Plus size={13} />
                          创建评测任务
                        </button>
                        <button type="button" onClick={() => setDeleteTarget({ kind: 'leaderboard', id: lb.id, name: lb.name })} className="flex items-center gap-1 text-red-500 hover:underline">
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
      ) : (
        /* 评测维度 */
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                <th className="px-4 py-3 font-medium">维度名称</th>
                <th className="px-4 py-3 font-medium">类型</th>
                <th className="px-4 py-3 font-medium">描述</th>
                <th className="px-4 py-3 font-medium">创建时间</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredDims.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-16 text-center text-sm text-slate-400">暂无评测维度，点击右上角创建</td>
                </tr>
              ) : (
                filteredDims.map((d) => (
                  <tr key={d.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">{d.name}</td>
                    <td className="px-4 py-3">
                      <span className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
                        {EVAL_TYPE_LABELS[d.eval_type] ?? d.eval_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 max-w-xs truncate">{d.description || '-'}</td>
                    <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{formatDate(d.created_at)}</td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => setDeleteTarget({ kind: 'dimension', id: d.id, name: d.name })} className="flex items-center gap-1 text-xs text-red-500 hover:underline">
                        <Trash2 size={13} />
                        删除
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* 创建排行榜弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setShowCreate(false)} />
          <div className="relative z-10 max-h-[85vh] w-full max-w-6xl overflow-auto rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
              <h3 className="text-base font-semibold text-slate-900">{editingLb ? '编辑排行榜' : '创建排行榜'}</h3>
              <button type="button" onClick={() => setShowCreate(false)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-5 px-6 py-5">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  排行榜名称 <span className="text-red-500">*</span>
                </label>
                <input value={lbName} onChange={(e) => setLbName(e.target.value)} maxLength={50} placeholder="请输入排行榜名称" className={inputCls} />
                <div className="mt-1 text-right text-xs text-slate-400">{lbName.length} / 50</div>
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  评测维度 <span className="text-red-500">*</span>
                </label>
                <MultiSelect
                  value={lbDimensionIds}
                  options={dimensions.map((d) => ({ value: d.id, label: d.name }))}
                  onChange={(ids) => {
                    setLbDimensionIds(ids)
                    setLbTaskIds([])
                  }}
                  placeholder="请选择评测维度"
                  className="mt-2"
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  关联可选任务（共{lbTaskOptions.length}条）
                </label>
                <p className="mb-2 text-xs text-slate-400">可选评测任务需要包含该排行榜评测维度</p>
                <div className="overflow-hidden rounded-lg border border-slate-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs text-slate-500">
                        <th className="w-10 px-3 py-2 font-medium" />
                        <th className="px-3 py-2 font-medium">任务名称</th>
                        <th className="px-3 py-2 font-medium">评测维度</th>
                        <th className="px-3 py-2 font-medium">评测模型</th>
                        <th className="px-3 py-2 font-medium">创建时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lbTaskOptions.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="py-10 text-center text-sm text-slate-400">暂无数据</td>
                        </tr>
                      ) : (
                        lbTaskOptions.map((t) => (
                          <tr key={t.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                            <td className="px-3 py-2">
                              <input
                                type="checkbox"
                                checked={lbTaskIds.includes(t.id)}
                                onChange={() => toggleTask(t.id)}
                                className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                              />
                            </td>
                            <td className="px-3 py-2 font-medium text-slate-900">{t.name}</td>
                            <td className="px-3 py-2"><DimensionTags names={t.dimension_names || []} /></td>
                            <td className="px-3 py-2 text-slate-600">{t.model_name || '-'}</td>
                            <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{formatDate(t.created_at)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {lbError && <p className="text-sm text-red-600">{lbError}</p>}
            </div>

            <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
              <button type="button" onClick={() => setShowCreate(false)} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
                取消
              </button>
              <button type="button" onClick={submitLeaderboard} disabled={lbSubmitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
                {lbSubmitting && <Loader2 size={14} className="animate-spin" />}
                {editingLb ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认 */}
      <Modal open={deleteTarget !== null} title="删除确认" onClose={() => setDeleteTarget(null)}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">
            确定删除「{deleteTarget?.name}」吗？此操作不可恢复。
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
              onClick={confirmDelete}
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

function EmptyGuide({ onCreate }: { onCreate: () => void }) {
  const steps = [
    { icon: Gauge, title: '定义评测维度' },
    { icon: ClipboardList, title: '创建评测任务' },
    { icon: Trophy, title: '查看或标注评测结果' },
  ]
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-slate-200 bg-white py-20">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-400">
        <ListOrdered size={32} />
      </div>
      <h3 className="text-base font-semibold text-slate-900">还没有创建过评测任务</h3>
      <p className="mt-1 text-sm text-slate-500">按照以下三步，快速开始你的模型评测</p>
      <div className="mt-6 grid max-w-2xl gap-4 sm:grid-cols-3">
        {steps.map((s, i) => (
          <div key={s.title} className="rounded-xl border border-slate-100 bg-slate-50 p-4 text-center">
            <div className="mx-auto mb-2 flex h-9 w-9 items-center justify-center rounded-full bg-white text-indigo-600 shadow-sm">
              <s.icon size={18} />
            </div>
            <div className="text-xs text-indigo-500">步骤 {i + 1}</div>
            <div className="mt-1 text-sm font-medium text-slate-800">{s.title}</div>
          </div>
        ))}
      </div>
      <button type="button" onClick={onCreate} className="mt-8 flex items-center gap-1.5 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700">
        <Plus size={16} />
        创建评测任务
      </button>
    </div>
  )
}