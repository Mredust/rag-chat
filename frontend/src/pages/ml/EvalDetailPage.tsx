import { ArrowLeft, ChevronRight, Download, Loader2, RotateCcw, Search, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { EChartsOption } from 'echarts'
import { mlApi } from '../../api/ml'
import EChart from '../../components/EChart'
import Select from '../../components/Select'
import { formatDate } from '../../lib/format'
import type { MLEvalTask, MLEvalTaskDetailItem } from '../../types/ml'
import { badgeCls, badgeLabel } from './constants'

type DetailTab = 'detail' | 'metrics'

type Metric = { name: string; score: number; eval_type?: string; metric?: string | null }

/* 超过 8 个字符的内容截断并追加省略号 */
function truncateText(s: string, max = 8): string {
  return s.length > max ? `${s.slice(0, max)}...` : s
}

/* 排名展示：null 视为未命中 */
function rankText(r: number | null): string {
  return r == null ? '未命中' : `第 ${r} 位`
}

/** 评测过程详情弹窗（按维度类型分区块展示） */
function TraceModal({ item, metrics, onClose }: {
  item: MLEvalTaskDetailItem
  metrics: Metric[]
  onClose: () => void
}) {
  const trace = item.trace
  if (!trace) return null

  const hasRetrieval = metrics.some((m) => m.eval_type === 'retrieval' && (m.metric === 'recall_at_5' || m.metric === 'mrr'))
  const hasStrategy = metrics.some((m) => m.eval_type === 'retrieval' && ['vector_qa_accuracy', 'fulltext_qa_accuracy', 'hybrid_qa_accuracy', 'rerank_qa_accuracy'].includes(m.metric ?? ''))
  const hasLlm = metrics.some((m) => m.eval_type === 'llm_classify' || m.eval_type === 'llm_numeric')

  const strategies = [
    { name: '向量检索', rank: trace.vector_rank },
    { name: '全文检索', rank: trace.fulltext_rank },
    { name: '混合检索', rank: trace.hybrid_rank },
    { name: '重排序检索', rank: trace.rerank_rank },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-4">
          <h3 className="text-base font-semibold text-slate-800">评测详情 · 第 {item.index} 条样本</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={18} /></button>
        </div>

        <div className="space-y-5 px-5 py-4">
          {/* 基本信息 */}
          <section>
            <h4 className="mb-2 text-sm font-medium text-slate-700">基本信息</h4>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm space-y-2">
              <p><span className="text-slate-500">Query：</span><span className="text-slate-800">{item.query}</span></p>
              <p><span className="text-slate-500">Positive：</span><span className="text-slate-800">{item.positive}</span></p>
              <p><span className="text-slate-500">Negative：</span><span className="text-slate-800">{item.negative}</span></p>
            </div>
          </section>

          {/* 检索评估 */}
          {hasRetrieval && (
            <section>
              <h4 className="mb-2 text-sm font-medium text-slate-700">检索结果（Top-{trace.top_k}）</h4>
              <div className="overflow-hidden rounded-lg border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs text-slate-500">
                    <tr><th className="px-3 py-2 font-medium">排名</th><th className="px-3 py-2 font-medium">文档内容</th><th className="px-3 py-2 font-medium">相似度分数</th></tr>
                  </thead>
                  <tbody>
                    {trace.vector_top5.map((doc) => (
                      <tr key={doc.rank} className="border-t border-slate-100">
                        <td className="px-3 py-2 text-slate-500">{doc.rank}</td>
                        <td className="px-3 py-2 text-slate-700 whitespace-pre-wrap break-words">{doc.content}</td>
                        <td className="px-3 py-2 text-slate-600">{doc.score.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 rounded-lg border border-slate-200 p-3 text-sm space-y-1 text-slate-700">
                <p>Positive 排名：{rankText(trace.vector_rank)}</p>
                <p>Top-{trace.top_k} 是否包含 Positive：{trace.vector_rank != null && trace.vector_rank <= trace.top_k ? '是' : '否'}</p>
                <p>该查询 MRR 贡献：{trace.vector_rank != null ? (1 / trace.vector_rank).toFixed(4) : '0'}</p>
              </div>
            </section>
          )}

          {/* 策略评估 */}
          {hasStrategy && (
            <section>
              <h4 className="mb-2 text-sm font-medium text-slate-700">各策略检索结果对比</h4>
              <div className="overflow-hidden rounded-lg border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs text-slate-500">
                    <tr><th className="px-3 py-2 font-medium">策略名称</th><th className="px-3 py-2 font-medium">Positive 排名</th><th className="px-3 py-2 font-medium">是否在 Top-{trace.top_k}</th><th className="px-3 py-2 font-medium">该查询贡献得分</th></tr>
                  </thead>
                  <tbody>
                    {strategies.map((s) => {
                      const inTop = s.rank != null && s.rank <= trace.top_k
                      return (
                        <tr key={s.name} className="border-t border-slate-100">
                          <td className="px-3 py-2 text-slate-700">{s.name}</td>
                          <td className="px-3 py-2 text-slate-600">{rankText(s.rank)}</td>
                          <td className="px-3 py-2">
                            <span className={inTop ? 'text-green-600' : 'text-red-600'}>{inTop ? '是' : '否'}</span>
                          </td>
                          <td className="px-3 py-2 text-slate-600">{inTop ? '1' : '0'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* 大模型评估 */}
          {hasLlm && (
            <section>
              <h4 className="mb-2 text-sm font-medium text-slate-700">大模型评估</h4>
              <div className="rounded-lg border border-slate-200 p-3 text-sm">
                <p className="text-slate-500">RAG 生成回答：</p>
                <p className="mt-1 text-slate-700">{trace.rag_answer ?? '（无）'}</p>
                <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
                  <span>裁判模型：{trace.judge_model ?? '—'}</span>
                  <span>Token 消耗：{trace.tokens?.total ?? 0}（输入 {trace.tokens?.input ?? 0}，输出 {trace.tokens?.output ?? 0}）</span>
                </div>
                <div className="mt-3 space-y-1.5">
                  {(trace.checks || []).map((c) => (
                    <p key={c.name} className="flex items-start gap-2">
                      <span className={c.pass ? 'text-green-600' : 'text-red-600'}>{c.pass ? '✅ 通过' : '❌ 未通过'}</span>
                      <span className="text-slate-700">{c.name}：{c.reason}</span>
                    </p>
                  ))}
                </div>
                <div className="mt-3 rounded-lg bg-slate-50 p-2.5">
                  <p className="text-slate-700">结论：<span className={trace.conclusion === 'Pass' ? 'text-green-600' : 'text-red-600'}>{trace.conclusion === 'Pass' ? '✅ Pass' : '❌ Fail'}</span>　幻觉率：{trace.hallucination ?? '—'} 分</p>
                  <p className="mt-1 text-slate-500">评测原因：{trace.reason ?? '—'}</p>
                </div>
              </div>
            </section>
          )}
        </div>

        <div className="sticky bottom-0 flex justify-end border-t border-slate-100 bg-white px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">关闭</button>
        </div>
      </div>
    </div>
  )
}

export default function EvalDetailPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState<MLEvalTask | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailTab, setDetailTab] = useState<DetailTab>('metrics')
  const [detailField, setDetailField] = useState<'query_positive' | 'negative'>('query_positive')
  const [detailKeyword, setDetailKeyword] = useState('')
  const [detailQuery, setDetailQuery] = useState('')
  const [detailPage, setDetailPage] = useState(1)
  const [detailPageSize, setDetailPageSize] = useState(10)
  const [detailItems, setDetailItems] = useState<MLEvalTaskDetailItem[]>([])
  const [detailTotal, setDetailTotal] = useState(0)
  const [traceItem, setTraceItem] = useState<MLEvalTaskDetailItem | null>(null)

  const load = useCallback(async () => {
    try {
      const t = await mlApi.getEvalTask(taskId)
      setTask(t)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => { load() }, [load])

  // 运行中任务轮询
  useEffect(() => {
    if (!task || (task.status !== 'running' && task.status !== 'pending')) return
    const timer = setInterval(load, 2000)
    return () => clearInterval(timer)
  }, [task, load])

  // 数据明细：服务端分页 + 关键词搜索
  useEffect(() => {
    if (detailTab !== 'detail') return
    let cancelled = false
    mlApi
      .listEvalTaskDetails(taskId, {
        page: detailPage,
        page_size: detailPageSize,
        field: detailField,
        keyword: detailQuery,
      })
      .then((res) => {
        if (cancelled) return
        setDetailItems(res.items)
        setDetailTotal(res.total)
      })
      .catch(() => {
        if (cancelled) return
        setDetailItems([])
        setDetailTotal(0)
      })
    return () => {
      cancelled = true
    }
  }, [detailTab, detailPage, detailPageSize, detailField, detailQuery, taskId])

  if (loading) {
    return <div className="flex justify-center py-24 text-slate-400"><Loader2 size={24} className="animate-spin" /></div>
  }
  if (!task) {
    return <p className="py-24 text-center text-sm text-slate-400">评测任务不存在</p>
  }

  const result = task.result ?? {}
  const score = typeof result.score === 'number' ? result.score : 0
  const scorePercent = Math.round(score * 100)
  const metrics = Array.isArray(result.metrics) ? (result.metrics as Array<{ name: string; score: number; eval_type?: string; metric?: string | null }>) : []
  const passCount = typeof result.pass_count === 'number' ? result.pass_count : 0
  const failCount = typeof result.fail_count === 'number' ? result.fail_count : 0
  const total = task.total_count || 0
  const completed = task.completed_count || (task.status === 'done' ? total : 0)
  const progressPercent = total > 0 ? Math.round((completed / total) * 100) : 0

  /* 明细分页（服务端数据） */
  const totalDetailPages = Math.max(1, Math.ceil(detailTotal / detailPageSize))
  const safeDetailPage = Math.min(detailPage, totalDetailPages)
  const hasDetailSearch = !!detailQuery

  const statusLabel: Record<string, string> = {
    pending: '排队中', running: '进行中', done: '评测完成', failed: '评测失败', stopped: '已停止',
  }

  const barOption: EChartsOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 24, top: 32, bottom: 36 },
    xAxis: {
      type: 'category',
      data: metrics.map((m) => m.name),
      axisLabel: { interval: 0, rotate: metrics.length > 3 ? 20 : 0, color: '#64748b' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'value',
      max: 100,
      interval: 25,
      axisLabel: { formatter: '{value}%', color: '#64748b' },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [
      {
        type: 'bar',
        data: metrics.map((m) => Number((m.score * 100).toFixed(2))),
        barWidth: 32,
        itemStyle: { color: '#6366f1', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top', formatter: '{c}%', color: '#334155' },
      },
    ],
  }

  const pieOption: EChartsOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c}（{d}%）' },
    legend: { bottom: 0, textStyle: { color: '#64748b' } },
    series: [
      {
        type: 'pie',
        radius: ['40%', '65%'],
        center: ['50%', '45%'],
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}\n{c}', color: '#334155' },
        data: [
          { value: passCount, name: 'Pass', itemStyle: { color: '#22c55e' } },
          { value: failCount, name: 'Fail', itemStyle: { color: '#f87171' } },
        ],
      },
    ],
  }

  const handleDownload = async () => {
    try {
      await mlApi.downloadEvalTask(taskId)
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '下载失败')
    }
  }

  const applyDetailSearch = () => {
    setDetailQuery(detailKeyword.trim())
    setDetailPage(1)
  }

  const resetDetailSearch = () => {
    setDetailField('query_positive')
    setDetailKeyword('')
    setDetailQuery('')
    setDetailPage(1)
  }

  return (
    <div>
      {/* 面包屑 */}
      <div className="mb-4 flex items-center gap-2 text-sm">
        <button type="button" onClick={() => navigate('/ml/eval')} className="flex items-center gap-1 text-slate-400 hover:text-slate-600">
          <ArrowLeft size={15} />
          模型评测
        </button>
        <ChevronRight size={14} className="text-slate-300" />
        <span className="font-medium text-slate-900">{task.name}</span>
      </div>

      {/* 标题栏 */}
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-900">{task.name}</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeCls(task.status)}`}>
          {statusLabel[task.status] ?? badgeLabel(task.status)}
        </span>
      </div>

      {/* 居中 Tab：指标统计在前，数据明细在后 */}
      <div className="mb-6 flex justify-center gap-2">
        <button
          type="button"
          onClick={() => setDetailTab('metrics')}
          className={`rounded-lg px-4 py-1.5 text-sm font-medium ${detailTab === 'metrics' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-100'}`}
        >
          指标统计
        </button>
        <button
          type="button"
          onClick={() => setDetailTab('detail')}
          className={`rounded-lg px-4 py-1.5 text-sm font-medium ${detailTab === 'detail' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-100'}`}
        >
          数据明细
        </button>
      </div>

      {detailTab === 'metrics' ? (
        <div className="space-y-5">
          {/* 卡片一：综合得分（左 1 列）+ 评测进度（右 4 列） */}
          <div className="grid gap-6 rounded-xl border border-slate-200 bg-white p-6 lg:grid-cols-5">
            <div className="flex flex-col items-center justify-center border-slate-100 lg:col-span-1 lg:border-r">
              <p className="mb-3 text-sm font-medium text-slate-500">综合得分</p>
              <div className="relative">
                <svg viewBox="0 0 120 70" className="w-36">
                  {/* 背景弧 */}
                  <path
                    d="M 10 65 A 50 50 0 0 1 110 65"
                    fill="none"
                    stroke="#e2e8f0"
                    strokeWidth="10"
                    strokeLinecap="round"
                  />
                  {/* 进度弧 */}
                  <path
                    d="M 10 65 A 50 50 0 0 1 110 65"
                    fill="none"
                    stroke="#6366f1"
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`${(scorePercent / 100) * 157} 157`}
                  />
                </svg>
                <div className="absolute inset-0 flex items-end justify-center pb-1">
                  <span className="text-3xl font-bold text-indigo-600">{(score * 100).toFixed(2)}</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:col-span-4">
              <StatCard label="评测进度" value={`${progressPercent}%`} />
              <StatCard label="评测集总量" value={String(total)} />
              <StatCard label="未完成量" value={String(total - completed)} />
              <StatCard label="已完成量" value={String(completed)} />
            </div>
          </div>

          {/* 卡片二：单维度汇总（柱状图）+ 数据项分布（饼图） */}
          {metrics.length > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white p-6">
              <div className="grid gap-6 lg:grid-cols-2">
                <div>
                  <h3 className="mb-4 text-sm font-semibold text-slate-700">单维度汇总</h3>
                  <EChart option={barOption} height={260} />
                </div>
                <div>
                  <h3 className="mb-4 text-sm font-semibold text-slate-700">得分明细 - 数据项分布</h3>
                  {passCount > 0 || failCount > 0 ? (
                    <EChart option={pieOption} height={260} />
                  ) : (
                    <div className="flex items-center justify-center text-sm text-slate-400" style={{ height: 260 }}>暂无数据</div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* 基础信息 */}
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-sm font-semibold text-slate-700">基础信息</h3>
            <div className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
              <InfoRow label="评测模型" value={task.model_name || '-'} />
              <InfoRow label="数据来源" value={task.data_name || task.data_id || '-'} />
              <InfoRow label="评测维度" value={task.dimension_names?.join('、') || '-'} />
              <InfoRow label="创建时间" value={formatDate(task.created_at)} />
              <InfoRow label="完成时间" value={task.status === 'done' ? formatDate(task.updated_at) : '-'} />
              <InfoRow label="排行榜" value={task.sync_leaderboard ? '已同步' : '未同步'} />
            </div>
          </div>
        </div>
      ) : (
        /* 数据明细 Tab */
        <div className="space-y-4">
          {/* 筛选栏 */}
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={detailField}
              onChange={(v) => setDetailField(v as 'query_positive' | 'negative')}
              options={[
                { value: 'query_positive', label: 'query & positive' },
                { value: 'negative', label: 'negative' },
              ]}
              className="w-48"
            />
            <div className="relative flex-1 max-w-xs">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={detailKeyword}
                onChange={(e) => setDetailKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') applyDetailSearch()
                }}
                placeholder="数据关键词"
                className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none focus:border-indigo-500"
              />
            </div>
            <button
              type="button"
              onClick={applyDetailSearch}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
            >
              <Search size={14} />
              搜索
            </button>
            <button
              type="button"
              onClick={resetDetailSearch}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              <RotateCcw size={14} />
              重置
            </button>
            <button type="button" onClick={handleDownload} className="ml-auto flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
              <Download size={14} />
              下载
            </button>
          </div>

          {/* 明细表格 */}
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                  <th className="px-4 py-3 font-medium w-14">序号</th>
                  <th className="px-4 py-3 font-medium">query</th>
                  <th className="px-4 py-3 font-medium">positive</th>
                  <th className="px-4 py-3 font-medium">negative</th>
                  {metrics.map((m) => (
                    <th key={m.name} className="px-4 py-3 font-medium">{m.name}</th>
                  ))}
                  <th className="px-4 py-3 font-medium w-20">操作</th>
                </tr>
              </thead>
              <tbody>
                {detailItems.length === 0 ? (
                  <tr>
                    <td colSpan={5 + metrics.length} className="py-16 text-center text-sm text-slate-400">
                      {hasDetailSearch ? '无匹配结果' : '暂无评测明细数据'}
                    </td>
                  </tr>
                ) : (
                  detailItems.map((d) => (
                    <tr key={d.index} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                      <td className="px-4 py-3 text-slate-400">{d.index}</td>
                      <td className="px-4 py-3 text-slate-700 max-w-[200px]" title={d.query}>{truncateText(d.query)}</td>
                      <td className="px-4 py-3 text-slate-600 max-w-[200px]" title={d.positive}>{truncateText(d.positive)}</td>
                      <td className="px-4 py-3 text-slate-600 max-w-[200px]" title={d.negative}>{truncateText(d.negative)}</td>
                      {metrics.map((m) => {
                        const dim = d.dims?.[m.name]
                        if (!dim) return <td key={m.name} className="px-4 py-3 text-slate-300">-</td>
                        if (dim.value != null) {
                          return (
                            <td key={m.name} className="px-4 py-3">
                              <span className="inline-block rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                                {Number(dim.value).toFixed(2)}
                              </span>
                            </td>
                          )
                        }
                        const positive = dim.label === 'Pass' || dim.label === '命中' || dim.label === '正确'
                        return (
                          <td key={m.name} className="px-4 py-3">
                            <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${positive ? 'border-green-200 bg-green-50 text-green-700' : 'border-red-200 bg-red-50 text-red-700'}`}>
                              {dim.label}
                            </span>
                          </td>
                        )
                      })}
                      <td className="px-4 py-3">
                        {d.trace ? (
                          <button type="button" onClick={() => setTraceItem(d)} className="text-indigo-600 hover:text-indigo-700">
                            详情
                          </button>
                        ) : (
                          <span className="text-slate-300">-</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* 分页 */}
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="flex items-center gap-2 text-slate-500">
              <span>每页</span>
              <Select
                value={String(detailPageSize)}
                onChange={(v) => { setDetailPageSize(Number(v)); setDetailPage(1) }}
                options={[10, 20, 50, 100].map((n) => ({ value: String(n), label: String(n) }))}
                className="w-20"
              />
              <span>条</span>
            </div>
            <div className="flex items-center gap-2 text-slate-500">
              <span>共 {detailTotal} 条 · 第 {safeDetailPage}/{totalDetailPages} 页</span>
              <button type="button" disabled={safeDetailPage <= 1} onClick={() => setDetailPage((p) => p - 1)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-transparent">
                上一页
              </button>
              <button type="button" disabled={safeDetailPage >= totalDetailPages} onClick={() => setDetailPage((p) => p + 1)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-transparent">
                下一页
              </button>
            </div>
          </div>
        </div>
      )}
      {traceItem && <TraceModal item={traceItem} metrics={metrics} onClose={() => setTraceItem(null)} />}
    </div>
  )
}

/* 统计小卡片 */
function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-slate-200 bg-slate-50 p-4 text-center">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-bold text-slate-700">{value}</p>
    </div>
  )
}

/* 信息行 */
function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="text-slate-800">{value}</span>
    </div>
  )
}
