import { ChevronRight, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import MultiSelect from '../../components/MultiSelect'
import Select from '../../components/Select'
import type { MLDataset, MLModel } from '../../types/ml'
import { CardRadio, type CardOption } from './components'
import { sourceHint } from './constants'

const TRAIN_MODE_OPTIONS: CardOption[] = [
  { value: 'efficient', label: 'LoRA 高效训练', desc: '在训练过程中只更新部分参数，显存占用更低，部分场景能降低过拟合概率' },
  { value: 'full', label: '全参训练', desc: '训练时更新模型全部参数，在复杂任务上会有更好效果' },
]

interface HpRow {
  key: string
  label: string
  desc: string
  type: 'int' | 'float' | 'text' | 'bool'
  min?: number
  max?: number
  step?: number | string
}

// bge 向量模型微调专用超参：移除 vit_lr / freeze_* / loss_scale / lr_scheduler_type / max_length 等无效参数
const HP_ROWS: HpRow[] = [
  { key: 'num_epochs', label: 'num_epochs', type: 'int', min: 1, max: 5, step: 1, desc: '训练轮数，模型训练过程中遍历数据集的次数，向量模型微调一般建议 1-3 轮' },
  { key: 'batch_size', label: 'batch_size', type: 'int', min: 1, max: 32, step: 1, desc: '批次大小，模型每看多少条数据更新一次参数，显存较小时建议 16' },
  { key: 'learning_rate', label: 'learning_rate', type: 'text', desc: '学习率，每次更新数据的参数增量权重，数值越大参数变化越大' },
  { key: 'temperature', label: 'temperature', type: 'float', min: 0.01, max: 0.5, step: 'any', desc: '温度系数，对比学习损失中的温度超参，控制正负样本相似度拉近/推开的敏感度' },
  { key: 'query_max_len', label: 'query_max_len', type: 'int', min: 16, max: 512, step: 1, desc: '问题最大长度，单个 query 样本的最大 token 长度（bge 上限 512）' },
  { key: 'passage_max_len', label: 'passage_max_len', type: 'int', min: 64, max: 512, step: 1, desc: '文档最大长度，单个正/负样本的最大 token 长度（bge 上限 512）' },
  { key: 'add_instruction', label: 'add_instruction', type: 'bool', desc: '是否给 query 添加检索指令前缀，bge 官方推荐开启' },
  { key: 'warmup_ratio', label: 'warmup_ratio', type: 'float', min: 0, max: 0.3, step: 'any', desc: '预热比例，学习率预热阶段占总训练步数的比例' },
  { key: 'weight_decay', label: 'weight_decay', type: 'float', min: 0, max: 0.1, step: 'any', desc: '权重衰减，对模型参数施加 L2 正则化，防止过拟合' },
  { key: 'eval_steps', label: 'eval_steps', type: 'int', min: 10, max: 500, step: 1, desc: '验证步数，训练阶段针对模型的验证间隔步长，用于阶段性评估训练损失' },
  { key: 'save_steps', label: 'save_steps', type: 'int', min: 10, max: 1000, step: 1, desc: '保存步数，训练阶段保存模型检查点的间隔步长' },
]

const defaultHp: Record<string, string | number | boolean> = {
  num_epochs: 3,
  batch_size: 16,
  learning_rate: '2e-5',
  temperature: 0.05,
  query_max_len: 128,
  passage_max_len: 512,
  add_instruction: true,
  warmup_ratio: 0.1,
  weight_decay: 0.01,
  eval_steps: 50,
  save_steps: 100,
}

export default function TuneCreatePage() {
  const navigate = useNavigate()
  const [models, setModels] = useState<MLModel[]>([])
  const [datasets, setDatasets] = useState<MLDataset[]>([])

  const [name, setName] = useState('')
  const [baseModel, setBaseModel] = useState('')
  const [trainMode, setTrainMode] = useState('efficient')
  const [datasetIds, setDatasetIds] = useState<string[]>([])
  const [validPercent, setValidPercent] = useState(10)
  const [outputName, setOutputName] = useState('')
  const [hp, setHp] = useState<Record<string, string | number | boolean>>(defaultHp)

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    mlApi
      .listModels()
      .then((r) => setModels(r.models))
      .catch(() => { })
    mlApi
      .listDatasets({ dataset_type: 'train' })
      .then((r) => setDatasets(r.datasets))
      .catch(() => { })
  }, [])

  const setField = (key: string, value: string | number | boolean) => {
    setHp((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async () => {
    if (!name.trim()) return setError('请输入任务名称')
    if (!baseModel) return setError('请选择基础模型')
    if (!outputName.trim()) return setError('请输入保存模型名')
    setSubmitting(true)
    setError('')
    try {
      await mlApi.createTrainTask({
        name: name.trim(),
        train_method: 'sft',
        base_model: baseModel,
        dataset_id: datasetIds[0] ?? null,
        dataset_ids: datasetIds,
        valid_ratio: validPercent / 100,
        config: { train_mode: trainMode, ...hp },
        output_model_name: outputName.trim(),
      })
      navigate('/ml/tune')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const renderHpInput = (row: HpRow) => {
    const value = hp[row.key]
    const inputCls = 'rounded-lg border border-slate-300 px-2 py-1 text-sm outline-none focus:border-indigo-500'
    if (row.type === 'bool') {
      return (
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => setField(row.key, e.target.checked)}
          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
        />
      )
    }
    if (row.type === 'text') {
      return <input type="text" value={String(value)} onChange={(e) => setField(row.key, e.target.value)} className={`${inputCls} w-32 font-mono`} />
    }
    return (
      <input
        type="number"
        value={Number(value)}
        min={row.min}
        max={row.max}
        step={row.step}
        onChange={(e) => setField(row.key, Number(e.target.value))}
        className={`${inputCls} w-28`}
      />
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-400">
        <button type="button" onClick={() => navigate('/ml/tune')} className="hover:text-slate-600">
          模型调优
        </button>
        <ChevronRight size={14} />
        <span className="font-medium text-slate-900">创建训练任务</span>
      </div>

      <div className="mx-auto max-w-3xl space-y-6">
        {/* 基础信息 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">基础信息</h3>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              任务名称 <span className="text-red-500">*</span>
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={50}
              placeholder="请输入任务名称"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
            <div className="mt-1 text-right text-xs text-slate-400">{name.length}/50</div>
          </div>
        </section>

        {/* 训练配置 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">训练配置</h3>
          <div className="space-y-5">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                基础模型 <span className="text-red-500">*</span>
              </label>
              <Select
                value={baseModel}
                onChange={setBaseModel}
                placeholder="请选择调优底座模型"
                options={models.map((m) => ({ value: m.name, label: m.name, hint: sourceHint(m) }))}
                className="w-full"
              />
              <p className="mt-1 text-xs text-slate-400">基础模型来自「我的模型」中已导入的模型。</p>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">训练方法</label>
              <CardRadio options={TRAIN_MODE_OPTIONS} value={trainMode} onChange={setTrainMode} columns={2} />
            </div>
          </div>
        </section>

        {/* 数据配置 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">数据配置</h3>
          <div className="space-y-5">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">训练集</label>
              <MultiSelect
                value={datasetIds}
                options={datasets.map((d) => ({ value: d.id, label: d.name }))}
                onChange={setDatasetIds}
                placeholder="请选择训练集"
                className="w-full"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">验证集比例</label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={validPercent}
                  onChange={(e) => setValidPercent(Math.max(0, Math.min(100, Number(e.target.value))))}
                  className="w-28 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
                <span className="text-sm text-slate-500">%</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">默认自动切分 10% 作为验证集</p>
            </div>
          </div>
        </section>

        {/* 超参配置 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-base font-semibold text-slate-900">超参配置</h3>
            <button
              type="button"
              onClick={() => setHp({ ...defaultHp })}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
            >
              重置
            </button>
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs text-slate-500">
                  <th className="px-3 py-2.5 font-medium">参数名称</th>
                  <th className="px-3 py-2.5 font-medium">配置</th>
                  <th className="px-3 py-2.5 font-medium">说明</th>
                </tr>
              </thead>
              <tbody>
                {HP_ROWS.map((row) => (
                  <tr key={row.key} className="border-b border-slate-50 last:border-0">
                    <td className="px-3 py-2.5 font-mono text-xs text-slate-700">{row.label}</td>
                    <td className="px-3 py-2.5">{renderHpInput(row)}</td>
                    <td className="px-3 py-2.5 text-xs leading-relaxed text-slate-500">{row.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 训练产出 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">训练产出</h3>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              保存模型名 <span className="text-red-500">*</span>
            </label>
            <input
              value={outputName}
              onChange={(e) => setOutputName(e.target.value)}
              maxLength={128}
              placeholder="训练完成后保存的模型名称"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
          </div>
        </section>

        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* 底部操作 */}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => navigate('/ml/tune')} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
            {submitting && <Loader2 size={14} className="animate-spin" />}
            确认
          </button>
        </div>
      </div>
    </div>
  )
}