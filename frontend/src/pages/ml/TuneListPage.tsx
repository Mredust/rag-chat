import { Check, Loader2, Play, Plus, RefreshCw, Save, Square, Trash2, FileText, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import Modal from '../../components/Modal'
import { formatDate } from '../../lib/format'
import type { MLTrainTask } from '../../types/ml'
import { trainMethodFull } from './constants'

/** 训练状态徽章：训练中转圈 / 训练成功绿勾 / 训练终止红叉 */
function StatusBadge({ status }: { status: string }) {
  if (status === 'running' || status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
        <Loader2 size={13} className="animate-spin" />
        训练中
      </span>
    )
  }
  if (status === 'done') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700">
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-green-600 text-white">
          <Check size={11} />
        </span>
        训练成功
      </span>
    )
  }
  if (status === 'failed' || status === 'stopped') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-white">
          <X size={11} />
        </span>
        训练终止
      </span>
    )
  }
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{status}</span>
}

export default function TuneListPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<MLTrainTask[]>([])
  const [loading, setLoading] = useState(true)

  const [logTask, setLogTask] = useState<MLTrainTask | null>(null)
  const [logLoading, setLogLoading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<MLTrainTask | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [saveDone, setSaveDone] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await mlApi.listTrainTasks({})
      setTasks(res.tasks)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 运行中任务轮询
  useEffect(() => {
    if (!tasks.some((t) => t.status === 'running' || t.status === 'pending')) return
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [tasks, load])

  // 日志弹窗打开且任务运行中时，每 2 秒刷新一次日志，实时展示训练进度
  const logTaskId = logTask?.id
  const logTaskStatus = logTask?.status
  useEffect(() => {
    if (!logTaskId) return
    if (logTaskStatus !== 'running' && logTaskStatus !== 'pending') return
    const timer = setInterval(async () => {
      try {
        const res = await mlApi.getTrainTask(logTaskId)
        setLogTask(res)
      } catch {
        /* ignore */
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [logTaskId, logTaskStatus])

  const handleStop = async (t: MLTrainTask) => {
    await mlApi.stopTrainTask(t.id)
    await load()
  }

  const handleResume = async (t: MLTrainTask) => {
    try {
      await mlApi.resumeTrainTask(t.id)
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '恢复失败')
    }
    await load()
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await mlApi.deleteTrainTask(deleteTarget.id)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const openLog = async (t: MLTrainTask) => {
    setLogTask(t)
    setLogLoading(true)
    try {
      const res = await mlApi.getTrainTask(t.id)
      setLogTask(res)
    } catch {
      /* ignore */
    } finally {
      setLogLoading(false)
    }
  }

  const handleSaveModel = async (t: MLTrainTask) => {
    setSavingId(t.id)
    try {
      await mlApi.saveTrainTaskModel(t.id)
      // 轮询后台保存进度，直到完成或失败
      await new Promise<void>((resolve, reject) => {
        const timer = window.setInterval(async () => {
          try {
            const s = await mlApi.getSaveModelStatus(t.id)
            if (s.state === 'done') {
              window.clearInterval(timer)
              resolve()
            } else if (s.state === 'error') {
              window.clearInterval(timer)
              reject(new Error(s.error || '保存失败'))
            }
          } catch (err) {
            window.clearInterval(timer)
            reject(err instanceof Error ? err : new Error('查询保存进度失败'))
          }
        }, 800)
      })
      setSaveDone(true)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">模型调优</h2>
        <div className="flex items-center gap-2">
          <button type="button" onClick={load} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
            <RefreshCw size={14} />
            刷新
          </button>
          <button type="button" onClick={() => navigate('/ml/tune/new')} className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700">
            <Plus size={16} />
            创建训练任务
          </button>
        </div>
      </div>

      {/* 任务列表 */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
              <th className="px-4 py-3 font-medium">任务名称/ID</th>
              <th className="px-4 py-3 font-medium">基础模型</th>
              <th className="px-4 py-3 font-medium">训练方法</th>
              <th className="px-4 py-3 font-medium">训练状态</th>
              <th className="px-4 py-3 font-medium">产出</th>
              <th className="px-4 py-3 font-medium">创建时间</th>
              <th className="px-4 py-3 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7}>
                  <div className="flex justify-center py-16 text-slate-400">
                    <Loader2 size={22} className="animate-spin" />
                  </div>
                </td>
              </tr>
            ) : tasks.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-16 text-center text-sm text-slate-400">
                  暂无训练任务，点击右上角「创建训练任务」
                </td>
              </tr>
            ) : (
              tasks.map((t) => (
                <tr key={t.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <button type="button" onClick={() => navigate(`/ml/tune/output/${t.id}`)} className="cursor-pointer text-left font-medium text-blue-600 hover:text-blue-700">
                      {t.name}
                    </button>
                    <div className="font-mono text-xs text-slate-400" title={t.id}>{t.id}</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600" title={t.base_model}>{t.base_model}</td>
                  <td className="px-4 py-3 text-slate-600">{trainMethodFull(t.train_method, t.config)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {t.output_model_name ? (
                      <button type="button" onClick={() => navigate(`/ml/tune/output/${t.id}`)} className="text-blue-600 hover:underline">
                        {t.output_model_name}
                      </button>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-500">{formatDate(t.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3 text-xs">
                      {(t.status === 'running' || t.status === 'pending') && (
                        <button type="button" onClick={() => handleStop(t)} className="flex items-center gap-1 text-amber-600 hover:underline">
                          <Square size={13} />
                          停止
                        </button>
                      )}
                      {t.status === 'stopped' && (
                        <button type="button" onClick={() => handleResume(t)} className="flex items-center gap-1 text-green-600 hover:underline">
                          <Play size={13} />
                          恢复训练
                        </button>
                      )}
                      <button type="button" onClick={() => handleSaveModel(t)} disabled={t.status !== 'done' || savingId === t.id} className="flex items-center gap-1 text-blue-600 hover:underline disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:no-underline">
                        {savingId === t.id ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                        保存
                      </button>
                      <button type="button" onClick={() => openLog(t)} className="flex items-center gap-1 text-indigo-600 hover:underline">
                        <FileText size={13} />
                        查看日志
                      </button>
                      <button type="button" onClick={() => setDeleteTarget(t)} className="flex items-center gap-1 text-red-500 hover:underline">
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

      {/* 日志弹窗 */}
      <Modal open={logTask !== null} title={`训练日志 - ${logTask?.name ?? ''}`} onClose={() => setLogTask(null)} maxWidth="max-w-4xl">
        <div>
          {logLoading ? (
            <div className="flex justify-center py-10 text-slate-400">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : (
            <pre className="max-h-[40rem] overflow-y-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">
              {logTask?.log || '（暂无日志）'}
            </pre>
          )}
        </div>
      </Modal>

      {/* 删除训练任务确认 */}
      <Modal open={deleteTarget !== null} title="删除确认" onClose={() => setDeleteTarget(null)}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">
            确定删除训练任务「{deleteTarget?.name}」吗？此操作不可恢复。
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

      {/* 保存到我的模型成功提示 */}
      <Modal open={saveDone} title="提示" onClose={() => setSaveDone(false)}>
        <div className="flex items-center gap-2 text-sm text-slate-700">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-green-100 text-green-600">
            <Check size={14} />
          </span>
          已保存到我的模型中
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => setSaveDone(false)}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
          >
            确定
          </button>
        </div>
      </Modal>
    </div>
  )
}