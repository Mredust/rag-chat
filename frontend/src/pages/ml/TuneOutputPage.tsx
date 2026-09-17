import { ArrowLeft, ChevronRight, Copy, Loader2, X } from 'lucide-react'
import type { EChartsOption } from 'echarts'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import EChart from '../../components/EChart'
import { formatDate } from '../../lib/format'
import type { MLDataset, MLTrainTask } from '../../types/ml'
import { trainMethodFull, badgeCls, badgeLabel } from './constants'

/** 计算耗时 */
function duration(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (Number.isNaN(ms) || ms < 0) return '-'
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** 超参 key -> 中文 label */
const HP_LABELS: Record<string, string> = {
  num_epochs: '训练轮数 (num_epochs)',
  batch_size: '批次大小 (batch_size)',
  learning_rate: '学习率 (learning_rate)',
  temperature: '温度系数 (temperature)',
  query_max_len: '问题最大长度 (query_max_len)',
  passage_max_len: '文档最大长度 (passage_max_len)',
  add_instruction: '添加检索指令前缀 (add_instruction)',
  warmup_ratio: '预热比例 (warmup_ratio)',
  weight_decay: '权重衰减 (weight_decay)',
  eval_steps: '验证步数 (eval_steps)',
  save_steps: '保存步数 (save_steps)',
}

/** 复制时按此顺序输出（与训练页超参展示顺序一致） */
const HP_COPY_ORDER = [
  'batch_size',
  'eval_steps',
  'num_epochs',
  'save_steps',
  'temperature',
  'warmup_ratio',
  'weight_decay',
  'learning_rate',
  'query_max_len',
  'add_instruction',
  'passage_max_len',
]

/** 不属于超参的 config key */
const CONFIG_SKIP_KEYS = new Set(['train_mode', 'dataset_ids'])

type Tab = 'detail' | 'metrics' | 'logs'

export default function TuneOutputPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState<MLTrainTask | null>(null)
  const [datasets, setDatasets] = useState<MLDataset[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('detail')
  const [hpOpen, setHpOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    try {
      const t = await mlApi.getTrainTask(taskId)
      setTask(t)
      const ids = t.dataset_ids?.length ? t.dataset_ids : t.dataset_id ? [t.dataset_id] : []
      if (ids.length) {
        const list = await Promise.all(ids.map((id) => mlApi.getDataset(id).catch(() => null)))
        setDatasets(list.filter((d): d is MLDataset => d != null))
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    load()
  }, [load])

  // 运行中任务轮询，实时更新日志与指标
  useEffect(() => {
    if (!task || (task.status !== 'running' && task.status !== 'pending')) return
    const timer = window.setInterval(load, 2000)
    return () => window.clearInterval(timer)
  }, [task, load])

  if (loading) {
    return (
      <div className="flex justify-center py-24 text-slate-400">
        <Loader2 size={24} className="animate-spin" />
      </div>
    )
  }

  if (!task) {
    return <p className="py-24 text-center text-sm text-slate-400">训练任务不存在</p>
  }

  /** 状态中文 */
  const statusLabel: Record<string, string> = {
    pending: '排队中',
    running: '训练中',
    done: '训练完成',
    failed: '训练失败',
    stopped: '训练终止',
  }

  /** 超参列表 */
  const hpEntries = Object.entries(task.config ?? {}).filter(([k]) => !CONFIG_SKIP_KEYS.has(k))

  /** 复制全部超参数 */
  const handleCopyHp = async () => {
    const text = HP_COPY_ORDER
      .filter((k) => Object.prototype.hasOwnProperty.call(task.config ?? {}, k))
      .map((k) => `${HP_LABELS[k] ?? k}\t${String((task.config ?? {})[k])}`)
      .join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }

  const metrics = task.metrics ?? {}
  const epochs = Array.isArray(metrics.epochs) ? (metrics.epochs as number[]) : []
  const trainLoss = Array.isArray(metrics.train_loss) ? (metrics.train_loss as number[]) : []
  const valLoss = Array.isArray(metrics.val_loss) ? (metrics.val_loss as number[]) : []
  const valAcc = Array.isArray(metrics.val_acc) ? (metrics.val_acc as number[]) : []
  const hasMetrics = epochs.length > 0

  const outputModelName = task.output_model_name || `${task.name}-v1`

  const lossOption: EChartsOption = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['训练损失', '验证损失'], bottom: 0, textStyle: { color: '#64748b' } },
    grid: { left: 48, right: 24, top: 32, bottom: 48 },
    xAxis: {
      type: 'category',
      name: 'Epoch',
      data: epochs,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b' },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#64748b' },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [
      {
        name: '训练损失',
        type: 'line',
        data: trainLoss,
        smooth: true,
        itemStyle: { color: '#6366f1' },
      },
      {
        name: '验证损失',
        type: 'line',
        data: valLoss,
        smooth: true,
        itemStyle: { color: '#f59e0b' },
      },
    ],
  }

  const accOption: EChartsOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 24, top: 32, bottom: 48 },
    xAxis: {
      type: 'category',
      name: 'Epoch',
      data: epochs,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b' },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#64748b' },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [
      {
        name: '验证准确率',
        type: 'line',
        data: valAcc,
        smooth: true,
        itemStyle: { color: '#22c55e' },
        areaStyle: { color: '#22c55e', opacity: 0.1 },
        label: { show: true, position: 'top', formatter: '{c}%', color: '#334155' },
      },
    ],
  }

  return (
    <div>
      {/* 面包屑 */}
      <div className="mb-4 flex items-center gap-2 text-sm">
        <button type="button" onClick={() => navigate('/ml/tune')} className="flex items-center gap-1 text-slate-400 hover:text-slate-600">
          <ArrowLeft size={15} />
          模型调优
        </button>
        <ChevronRight size={14} className="text-slate-300" />
        <span className="font-medium text-slate-900">训练产出</span>
      </div>

      {/* 标题栏 */}
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-900">{task.name}</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeCls(task.status)}`}>
          {statusLabel[task.status] ?? badgeLabel(task.status)}
        </span>
      </div>

      {/* 顶部 Tab：详情 / 指标 / 日志 */}
      <div className="mb-6 flex justify-center gap-2">
        <TabButton active={tab === 'detail'} onClick={() => setTab('detail')}>详情</TabButton>
        <TabButton active={tab === 'metrics'} onClick={() => setTab('metrics')}>指标</TabButton>
        <TabButton active={tab === 'logs'} onClick={() => setTab('logs')}>日志</TabButton>
      </div>

      {tab === 'detail' && (
        <div className="mx-auto max-w-3xl space-y-6">
          {/* 训练配置 */}
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-5 text-base font-semibold text-slate-900">训练配置</h3>
            <div className="space-y-3 text-sm">
              <Row label="任务ID" mono>{task.id}</Row>
              <Row label="状态">
                <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(task.status)}`}>{statusLabel[task.status] ?? badgeLabel(task.status)}</span>
              </Row>
              <Row label="创建时间">{formatDate(task.created_at)}</Row>
              <Row label="结束时间">
                {task.updated_at && (task.status === 'done' || task.status === 'failed' || task.status === 'stopped')
                  ? (
                    <>
                      {formatDate(task.updated_at)}
                      <span className="ml-2 text-slate-400">（耗时 {duration(task.created_at, task.updated_at)}）</span>
                    </>
                  )
                  : '-'}
              </Row>
              <Row label="基础模型" mono>{task.base_model}</Row>
              <Row label="参数配置">
                <button type="button" onClick={() => setHpOpen(true)} className="text-indigo-600 hover:underline">
                  查看全部
                </button>
              </Row>
              <Row label="训练方法">{trainMethodFull(task.train_method, task.config)}</Row>
            </div>
          </section>

          {/* 数据配置 */}
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-5 text-base font-semibold text-slate-900">数据配置</h3>
            <div className="space-y-3 text-sm">
              <Row label="训练集">
                {datasets.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {datasets.map((d) => (
                      <span key={d.id} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                        {d.name}
                        {d.latest_version != null && <span className="text-slate-400">{' '}{'>'} V{d.latest_version}</span>}
                      </span>
                    ))}
                  </div>
                ) : (
                  '-'
                )}
              </Row>
              <Row label="验证集">
                {task.valid_ratio > 0
                  ? `随机分割 ${Math.round(task.valid_ratio * 100)}%`
                  : '无'}
              </Row>
            </div>
          </section>

          {/* 模型产出 */}
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-5 text-base font-semibold text-slate-900">模型产出</h3>
            <div>
              <p className="text-xs text-slate-400">模型名称</p>
              <p className="mt-1 truncate font-mono text-sm text-slate-800" title={outputModelName}>{outputModelName}</p>
            </div>
          </section>
        </div>
      )}

      {tab === 'metrics' && (
        <div className="mx-auto max-w-4xl space-y-6">
          {!hasMetrics ? (
            <div className="rounded-xl border border-slate-200 bg-white py-20 text-center text-sm text-slate-400">
              暂无指标数据，训练完成后将展示训练损失、准确率等图表
            </div>
          ) : (
            <>
              {/* 汇总卡片 */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <StatCard label="总步数" value={String(metrics.total_steps ?? '-')} />
                <StatCard label="最终训练损失" value={typeof metrics.final_loss === 'number' ? metrics.final_loss.toFixed(4) : '-'} />
                <StatCard label="最终验证准确率" value={typeof metrics.final_acc === 'number' ? `${metrics.final_acc.toFixed(2)}%` : '-'} />
                <StatCard label="总耗时" value={typeof metrics.total_time_sec === 'number' ? `${metrics.total_time_sec.toFixed(1)}s` : '-'} />
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-6">
                <h3 className="mb-4 text-sm font-semibold text-slate-700">训练损失 / 验证损失</h3>
                <EChart option={lossOption} height={280} />
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-6">
                <h3 className="mb-4 text-sm font-semibold text-slate-700">验证准确率</h3>
                <EChart option={accOption} height={280} />
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'logs' && (
        <div className="mx-auto max-w-4xl">
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-sm font-semibold text-slate-700">训练日志</h3>
            <pre className="max-h-[520px] overflow-y-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-3 text-xs leading-6 text-slate-700">
              {task.log || '（暂无日志）'}
            </pre>
          </div>
        </div>
      )}

      {/* 参数配置抽屉（右侧滑出） */}
      <div className={`fixed inset-0 z-50 ${hpOpen ? '' : 'pointer-events-none'}`}>
        <div
          className={`absolute inset-0 bg-black/30 transition-opacity duration-300 ${hpOpen ? 'opacity-100' : 'opacity-0'}`}
          onClick={() => setHpOpen(false)}
        />
        <div
          className={`absolute right-0 top-0 h-full w-96 max-w-full bg-white shadow-xl transition-transform duration-300 ${hpOpen ? 'translate-x-0' : 'translate-x-full'}`}
        >
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <h3 className="text-base font-semibold text-slate-900">参数配置</h3>
            <button type="button" onClick={() => setHpOpen(false)} className="text-slate-400 hover:text-slate-600">
              <X size={18} />
            </button>
          </div>
          <div className="p-5">
            {hpEntries.length === 0 ? (
              <p className="text-sm text-slate-400">暂无配置参数</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                    <th className="py-2 font-medium">参数名称</th>
                    <th className="py-2 font-medium">值</th>
                  </tr>
                </thead>
                <tbody>
                  {hpEntries.map(([key, value]) => (
                    <tr key={key} className="border-b border-slate-50 last:border-0">
                      <td className="py-2 pr-3 font-mono text-xs text-slate-700">{HP_LABELS[key] ?? key}</td>
                      <td className="break-all py-2 font-mono text-xs text-slate-600">{String(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {hpEntries.length > 0 && (
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  onClick={handleCopyHp}
                  className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                >
                  <Copy size={14} />
                  {copied ? '已复制' : '复制全部参数'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** Tab 按钮 */
function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-5 py-1.5 text-sm font-medium ${active ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-100'}`}
    >
      {children}
    </button>
  )
}

/** 信息行组件 */
function Row({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start gap-4 py-1.5">
      <span className="w-40 shrink-0 text-slate-500">{label}</span>
      <span className={`flex-1 text-slate-800 ${mono ? 'font-mono text-xs' : ''}`}>{children}</span>
    </div>
  )
}

/** 指标统计小卡片 */
function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-slate-200 bg-slate-50 p-4 text-center">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-bold text-slate-700">{value}</p>
    </div>
  )
}