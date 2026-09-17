import { ArrowLeft, ChevronRight, Crown, Loader2, Trash2, Trophy } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import type { MLLeaderboardDetail, MLLeaderboardTaskEntry } from '../../types/ml'

export default function LeaderboardDetailPage() {
  const { leaderboardId = '' } = useParams()
  const navigate = useNavigate()
  const [lb, setLb] = useState<MLLeaderboardDetail | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const data = await mlApi.getLeaderboard(leaderboardId)
      setLb(data)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [leaderboardId])

  useEffect(() => {
    load()
  }, [load])

  const handleRemove = async (task: MLLeaderboardTaskEntry) => {
    if (!window.confirm(`确定从排行榜移除评测任务「${task.name}」吗？`)) return
    await mlApi.removeLeaderboardTask(leaderboardId, task.id)
    await load()
  }

  if (loading) {
    return <div className="flex justify-center py-24 text-slate-400"><Loader2 size={24} className="animate-spin" /></div>
  }
  if (!lb) {
    return <p className="py-24 text-center text-sm text-slate-400">排行榜不存在</p>
  }

  // 按得分降序排名
  const tasks = [...lb.tasks].sort((a, b) => b.score - a.score)
  const dimensionNames = lb.dimension_names || []

  // 每列最佳值（用于高亮“皇冠”最佳图标）；排行榜得分同分时仅排名第一展示
  const showBest = tasks.length > 1
  const bestDimension: Record<string, number> = {}
  dimensionNames.forEach((name) => {
    const vals = tasks.map((t) => t.dimension_scores?.[name]).filter((v): v is number => v != null)
    bestDimension[name] = vals.length ? Math.max(...vals) : -Infinity
  })

  return (
    <div>
      {/* 面包屑 */}
      <div className="mb-4 flex items-center gap-2 text-sm">
        <button type="button" onClick={() => navigate('/ml/eval?tab=leaderboard')} className="flex items-center gap-1 text-slate-400 hover:text-slate-600">
          <ArrowLeft size={15} />
          排行榜
        </button>
        <ChevronRight size={14} className="text-slate-300" />
        <span className="font-medium text-slate-900">{lb.name}</span>
      </div>

      {/* 标题栏 */}
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-500">
            <Trophy size={20} />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-900">{lb.name}</h2>
            <div className="mt-1 flex flex-wrap gap-1">
              {dimensionNames.map((n) => (
                <span key={n} className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{n}</span>
              ))}
            </div>
          </div>
        </div>
        <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700">
          评测任务（{lb.task_count}/50）
        </span>
      </div>

      {/* 排名表格 */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
              <th className="px-4 py-3 font-medium">排名</th>
              <th className="px-4 py-3 font-medium">任务名称</th>
              <th className="px-4 py-3 font-medium">测评模型</th>
              <th className="px-4 py-3 font-medium">排行榜得分</th>
              {dimensionNames.map((name) => (
                <th key={name} className="px-4 py-3 font-medium">{name}得分</th>
              ))}
              <th className="px-4 py-3 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 ? (
              <tr>
                <td colSpan={5 + dimensionNames.length} className="py-16 text-center text-sm text-slate-400">暂无评测任务</td>
              </tr>
            ) : (
              tasks.map((t, i) => (
                <tr key={t.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${i === 0 ? 'bg-amber-100 text-amber-700' : i === 1 ? 'bg-slate-200 text-slate-700' : i === 2 ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-500'}`}>
                      {i + 1}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900">
                    <button type="button" onClick={() => navigate(`/ml/eval/${t.id}`)} className="cursor-pointer text-left text-indigo-600">
                      {t.name}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{t.model_name || '-'}</td>
                  <td className="px-4 py-3 font-mono text-sm font-semibold text-indigo-600">
                    {showBest && i === 0 && <Crown size={14} className="mr-1 inline-block text-amber-500" />}
                    {(t.score * 100).toFixed(2)}
                  </td>
                  {dimensionNames.map((name) => {
                    const val = t.dimension_scores?.[name]
                    const isBest = val != null && bestDimension[name] !== -Infinity && val === bestDimension[name]
                    return (
                      <td key={name} className="px-4 py-3 font-mono text-slate-600">
                        {showBest && isBest && <Crown size={14} className="mr-1 inline-block text-amber-500" />}
                        {val != null ? (val * 100).toFixed(2) : '-'}
                      </td>
                    )
                  })}
                  <td className="px-4 py-3">
                    <button type="button" onClick={() => handleRemove(t)} className="flex items-center gap-1 text-xs text-red-500 hover:underline">
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
    </div>
  )
}