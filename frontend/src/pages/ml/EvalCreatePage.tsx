import { ChevronRight, Loader2, Plus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import { providerApi } from '../../api/provider'
import MultiSelect from '../../components/MultiSelect'
import Select from '../../components/Select'
import type { MLDataset, MLEvalDimension, MLLeaderboard, MLModel } from '../../types/ml'
import type { Provider } from '../../types'
import { sourceLabel } from './constants'

function timestampName(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `评测任务_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

export default function EvalCreatePage() {
  const navigate = useNavigate()

  const [name, setName] = useState(timestampName)
  const [modelId, setModelId] = useState('')
  const [modelType, setModelType] = useState<'vector' | 'llm'>('vector')
  const [llmModelId, setLlmModelId] = useState('')
  const [dataMode, setDataMode] = useState<'dataset' | 'auto_split'>('dataset')
  const [dataId, setDataId] = useState('')
  const [splitDatasetId, setSplitDatasetId] = useState('')
  const [splitRatio, setSplitRatio] = useState('10')
  const [dimensionIds, setDimensionIds] = useState<string[]>([])
  const [selectedLeaderboardId, setSelectedLeaderboardId] = useState('')

  const [models, setModels] = useState<MLModel[]>([])
  const [providers, setProviders] = useState<Provider[]>([])
  const [datasets, setDatasets] = useState<MLDataset[]>([])
  const [trainDatasets, setTrainDatasets] = useState<MLDataset[]>([])
  const [dimensions, setDimensions] = useState<MLEvalDimension[]>([])
  const [leaderboards, setLeaderboards] = useState<MLLeaderboard[]>([])

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const loadModels = useCallback(() => {
    mlApi.listModels().then((r) => setModels(r.models)).catch(() => { })
  }, [])

  const loadProviders = useCallback(() => {
    providerApi.list().then((r) => setProviders(r.providers)).catch(() => { })
  }, [])

  const loadDatasets = useCallback(() => {
    mlApi.listDatasets({ dataset_type: 'eval' }).then((r) => setDatasets(r.datasets)).catch(() => { })
  }, [])

  const loadTrainDatasets = useCallback(() => {
    mlApi.listDatasets({ dataset_type: 'train' }).then((r) => setTrainDatasets(r.datasets)).catch(() => { })
  }, [])

  const loadDimensions = useCallback(() => {
    mlApi.listDimensions().then((r) => setDimensions(r.dimensions)).catch(() => { })
  }, [])

  const loadLeaderboards = useCallback(() => {
    mlApi.listLeaderboards().then((r) => setLeaderboards(r.leaderboards)).catch(() => { })
  }, [])

  useEffect(() => {
    loadModels()
    loadProviders()
    loadDatasets()
    loadTrainDatasets()
    loadDimensions()
    loadLeaderboards()
  }, [loadModels, loadProviders, loadDatasets, loadTrainDatasets, loadDimensions, loadLeaderboards])

  /* 仅显示包含所选评测维度之一的排行榜 */
  const filteredLeaderboards = leaderboards.filter((lb) =>
    dimensionIds.some((id) => (lb.dimension_ids || []).includes(id)),
  )

  const handleSubmit = async () => {
    if (!name.trim()) return setError('请输入任务名称')
    if (modelType === 'vector' && !modelId) return setError('请选择向量模型')
    if (modelType === 'llm' && !llmModelId) return setError('请选择大模型')
    if (dataMode === 'auto_split' && !splitDatasetId) return setError('请选择用于切分的训练集')
    if (dataMode === 'dataset' && !dataId) return setError('请选择评测数据')
    if (dimensionIds.length === 0) return setError('请选择评测维度')
    const ratioNum = Math.max(0, Math.min(100, Number(splitRatio) || 10))
    setSubmitting(true)
    setError('')
    try {
      await mlApi.createEvalTask({
        name: name.trim(),
        model_id: modelType === 'vector' ? modelId : null,
        model_type: modelType,
        llm_model_id: modelType === 'llm' ? llmModelId : null,
        data_source: 'dataset',
        data_id: dataMode === 'auto_split' ? splitDatasetId : dataId,
        data_mode: dataMode,
        split_dataset_id: dataMode === 'auto_split' ? splitDatasetId : '',
        split_ratio: ratioNum / 100,
        dimension_ids: dimensionIds,
        sync_leaderboard: !!selectedLeaderboardId,
        leaderboard_id: selectedLeaderboardId || null,
      })
      navigate('/ml/eval')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-400">
        <button type="button" onClick={() => navigate('/ml/eval')} className="hover:text-slate-600">
          模型评测
        </button>
        <ChevronRight size={14} />
        <span className="font-medium text-slate-900">创建评测任务</span>
      </div>

      <div className="mx-auto max-w-3xl space-y-5 rounded-xl border border-slate-200 bg-white p-6">
        {/* 基础信息 */}
        <section>
          <h3 className="mb-4 text-base font-semibold text-slate-900">基础信息</h3>
          <div className="space-y-5">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                任务名称 <span className="text-red-500">*</span>
              </label>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={50} placeholder="请输入任务名称" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
              <div className="mt-1 text-right text-xs text-slate-400">{name.length}/50</div>
            </div>
          </div>
        </section>

        {/* 评测对象 */}
        <section className="border-t border-slate-100 pt-5">
          <h3 className="mb-4 text-base font-semibold text-slate-900">评测对象</h3>
          <div className="space-y-5">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">
                评测模型 <span className="text-red-500">*</span>
              </label>
              <div className="mb-3 flex flex-wrap gap-2">
                {([{ value: 'vector', label: '向量模型' }, { value: 'llm', label: '大模型' }] as const).map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => setModelType(o.value)}
                    className={`rounded-lg border px-4 py-2 text-sm transition-colors ${modelType === o.value
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                      : 'border-slate-200 text-slate-600 hover:border-slate-300'
                      }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
              {modelType === 'vector' ? (
                <Select
                  value={modelId}
                  onChange={setModelId}
                  placeholder="请选择参与评测的向量模型"
                  options={models.map((m) => ({ value: m.id, label: m.name, hint: sourceLabel(m.source_type) }))}
                  className="w-full"
                />
              ) : (
                <Select
                  value={llmModelId}
                  onChange={setLlmModelId}
                  placeholder="请选择参与评测的大模型"
                  options={providers.map((p) => ({ value: p.id, label: p.model_name && p.name !== p.model_name ? `${p.name}（${p.model_name}）` : p.name }))}
                  className="w-full"
                />
              )}
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                评测数据 <span className="text-red-500">*</span>
              </label>
              <div className="mb-3 flex gap-5">
                {([{ value: 'auto_split', label: '自动切分' }, { value: 'dataset', label: '选择测评集' }] as const).map((o) => (
                  <label key={o.value} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                    <input
                      type="radio"
                      name="dataMode"
                      checked={dataMode === o.value}
                      onChange={() => setDataMode(o.value)}
                      className="h-4 w-4 accent-indigo-600"
                    />
                    {o.label}
                  </label>
                ))}
              </div>
              {dataMode === 'auto_split' ? (
                <div className="flex items-center gap-3">
                  <Select
                    value={splitDatasetId}
                    onChange={setSplitDatasetId}
                    placeholder="请选择用于切分的训练集"
                    options={trainDatasets.map((d) => ({ value: d.id, label: d.name }))}
                    className="flex-1"
                  />
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-sm text-slate-600">切分比例</span>
                    <input
                      value={splitRatio}
                      onChange={(e) => setSplitRatio(e.target.value.replace(/[^\d.]/g, ''))}
                      inputMode="decimal"
                      className="w-20 rounded-lg border border-slate-300 px-3 py-2 text-right text-sm outline-none focus:border-indigo-500"
                    />
                    <span className="text-sm text-slate-500">%</span>
                  </div>
                  <button type="button" onClick={loadTrainDatasets} className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
                    <RefreshCw size={14} />
                    刷新
                  </button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Select
                    value={dataId}
                    onChange={setDataId}
                    placeholder="请选择测评集"
                    options={datasets.map((d) => ({ value: d.id, label: d.name }))}
                    className="flex-1"
                  />
                  <button type="button" onClick={loadDatasets} className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
                    <RefreshCw size={14} />
                    刷新
                  </button>
                  <button type="button" onClick={() => navigate('/ml/datasets/new')} className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
                    <Plus size={14} />
                    新增数据集
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* 评测规则 */}
        <section className="border-t border-slate-100 pt-5">
          <h3 className="mb-4 text-base font-semibold text-slate-900">评测规则</h3>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              评测维度 <span className="text-red-500">*</span>
            </label>
            <div className="flex gap-2">
              <MultiSelect
                value={dimensionIds}
                options={dimensions.map((d) => ({ value: d.id, label: d.name }))}
                onChange={setDimensionIds}
                placeholder="请选择评测维度"
                className="flex-1"
              />
              <button type="button" onClick={loadDimensions} className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
                <RefreshCw size={14} />
                刷新
              </button>
            </div>
          </div>
        </section>

        {/* 同步至排行榜 */}
        <section className="border-t border-slate-100 pt-5">
          <h3 className="mb-4 text-base font-semibold text-slate-900">同步至排行榜</h3>
          <Select
            value={selectedLeaderboardId}
            onChange={setSelectedLeaderboardId}
            placeholder="评测完成后同步至排行榜（可不选）"
            options={filteredLeaderboards.map((lb) => ({
              value: lb.id,
              label: lb.name + (lb.dimension_names?.length ? `（${lb.dimension_names.join('、')}）` : ''),
            }))}
            className="w-full"
          />
        </section>

        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* 底部操作 */}
        <div className="flex justify-end gap-3 border-t border-slate-100 pt-5">
          <button type="button" onClick={() => navigate('/ml/eval')} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
            {submitting && <Loader2 size={14} className="animate-spin" />}
            开始评测
          </button>
        </div>
      </div>
    </div>
  )
}