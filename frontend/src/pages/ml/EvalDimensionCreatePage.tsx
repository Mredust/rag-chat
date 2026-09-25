import { ChevronRight, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import { providerApi } from '../../api/provider'
import type { Provider } from '../../types'
import Select from '../../components/Select'

const EVAL_TYPES = [
  { value: 'llm_classify', label: '大模型评估-分类型' },
  { value: 'llm_numeric', label: '大模型评估-数值型' },
  { value: 'retrieval', label: '检索评估' },
  { value: 'spearman', label: '统计评估-Spearman相关系数' },
]

/* 检索评估指标清单（评测维度 / 指标 / 说明） */
const RETRIEVAL_METRICS = [
  { key: 'recall_at_5', name: '召回率', metric: 'Recall@K', desc: '正确答案是否排在前K位（K为下方Recall值）' },
  { key: 'mrr', name: '平均倒数排名', metric: 'MRR', desc: '第一个正确答案排名的倒数平均值' },
  { key: 'vector_qa_accuracy', name: '向量检索', metric: '准确率', desc: '仅用向量检索的问答准确率' },
  { key: 'fulltext_qa_accuracy', name: '全文检索', metric: '准确率', desc: '仅用全文检索的问答准确率' },
  { key: 'hybrid_qa_accuracy', name: '混合检索', metric: '准确率', desc: '向量+全文融合检索的问答准确率' },
  { key: 'rerank_qa_accuracy', name: '重排序检索', metric: '准确率', desc: '混合检索+交叉编码器重排序的问答准确率' },
]

/* 统计评估-Spearman相关系数 相似度计算方法 */
const SPEARMAN_SIM_METHODS = [
  { value: 'cosine', label: 'COSINE（余弦相似度）' },
  { value: 'euclidean', label: '欧氏距离（相似度 = -距离）' },
  { value: 'dot', label: '点积' },
]

/* 大模型评估-分类型 评分器模板（prompt 正文从 prompts/ 经接口加载） */
const CLASSIFY_TEMPLATES: Record<string, { label: string; prompt: string; labels: { pass: string; fail: string }; name: string; description: string }> = {
  standard: {
    label: '标准匹配',
    labels: { pass: 'Pass', fail: 'Fail' },
    name: '准确率',
    description: '根据评分器标准判断回答是否正确，结果为 Pass / Fail',
    prompt: '',
  },
  sentiment: {
    label: '情感分析',
    labels: { pass: '积极', fail: '中性、消极' },
    name: '情感分析',
    description: '判断回答的情感倾向，积极为 Pass，中性、消极为 Fail',
    prompt: '',
  },
}

/* 大模型评估-数值型 评分器模板（prompt 正文从 prompts/ 经接口加载） */
const NUMERIC_TEMPLATES: Record<string, { label: string; prompt: string; threshold: number; name?: string; description?: string }> = {
  overall: {
    label: '综合评测',
    threshold: 3,
    name: '综合评测',
    description: '综合评估回答的整体质量（准确性、相关性、完整性等），1~5分，得分越高表示表现越好',
    prompt: '',
  },
  similarity: {
    label: '语义相似度',
    threshold: 4,
    name: '语义相似度',
    description: '评估回答与参考答案的语义相似程度，1~5分，得分越高表示越相似',
    prompt: '',
  },
  hallucination: {
    label: '幻觉率',
    threshold: 4,
    name: '幻觉率',
    description: '评估回答是否存在事实错误或幻觉，1~5分，得分越高表示幻觉越少',
    prompt: '',
  },
  relevance: {
    label: '答案相关性',
    threshold: 3,
    name: '答案相关性',
    description: '评估回答与问题的相关程度，1~5分，得分越高表示越切题',
    prompt: '',
  },
  completeness: {
    label: '答案完整性',
    threshold: 3,
    name: '答案完整性',
    description: '评估回答是否覆盖问题所需的所有必要信息，1~5分，得分越高表示越完整',
    prompt: '',
  },
}

/* 可被模板回填的维度名称/描述特征：判断基础信息是否为模板默认值（不覆盖用户自定义内容） */
const TEMPLATE_NAME_SET = new Set(
  [...Object.values(CLASSIFY_TEMPLATES), ...Object.values(NUMERIC_TEMPLATES)]
    .map((t) => (t.name || '').trim())
    .filter(Boolean),
)
const TEMPLATE_DESC_BASES = [...new Set(
  [...Object.values(CLASSIFY_TEMPLATES), ...Object.values(NUMERIC_TEMPLATES)]
    .map((t) => (t.description || '').split('，')[0].trim())
    .filter(Boolean),
)]
const canBackfillName = (s: string) => !s.trim()
  || TEMPLATE_NAME_SET.has(s.trim())
  || /^(召回率|平均倒数排名|向量检索|全文检索|混合检索|重排序检索)@\d+$/.test(s.trim())
const canBackfillDesc = (s: string) => !s.trim()
  || TEMPLATE_DESC_BASES.some((b) => s.trim().startsWith(b))
  || isRecallDesc(s)

/* 描述中追加/刷新「通过阈值N」后缀 */
function withThresholdDesc(desc: string, threshold: number): string {
  const base = desc.replace(/[，,]?\s*通过阈值[\d.]+/g, '').trim()
  const suffix = `通过阈值${threshold}`
  return base ? `${base}，${suffix}` : suffix
}

/* 检索评估名称回填：如 召回率@6 */
function retrievalName(metricKey: string, k: number): string {
  const m = RETRIEVAL_METRICS.find((x) => x.key === metricKey)
  return m ? `${m.name}@${k}` : ''
}

/* 召回率描述回填：K 随 Recall 值联动，如 正确答案是否排在前1位 */
function recallDesc(k: number): string {
  return `正确答案是否排在前${k}位`
}

/* 判断描述是否为召回率模板描述（可随 Recall 值联动更新） */
function isRecallDesc(desc: string): boolean {
  return /^正确答案是否排在前/.test(desc.trim())
}

export default function EvalDimensionCreatePage() {
  const navigate = useNavigate()
  const { dimensionId } = useParams<{ dimensionId: string }>()
  const isEdit = Boolean(dimensionId)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [evalType, setEvalType] = useState('llm_classify')
  const [providers, setProviders] = useState<Provider[]>([])

  // 大模型评估-分类型
  const [judgeModel, setJudgeModel] = useState('')
  const [classifyTemplate, setClassifyTemplate] = useState('standard')
  const [classifyPrompt, setClassifyPrompt] = useState(CLASSIFY_TEMPLATES.standard.prompt)
  const [labels, setLabels] = useState(CLASSIFY_TEMPLATES.standard.labels)

  // 大模型评估-数值型
  const [numJudgeModel, setNumJudgeModel] = useState('')
  const [numericTemplate, setNumericTemplate] = useState('overall')
  const [numericPrompt, setNumericPrompt] = useState(NUMERIC_TEMPLATES.overall.prompt)
  const [numericThreshold, setNumericThreshold] = useState(NUMERIC_TEMPLATES.overall.threshold)

  // 检索评估
  const [topK, setTopK] = useState(5)
  const [recallK, setRecallK] = useState(5)
  const [retrievalMetric, setRetrievalMetric] = useState('recall_at_5')

  // 统计评估-Spearman相关系数
  const [spearmanSimMethod, setSpearmanSimMethod] = useState('cosine')
  const [spearmanThreshold, setSpearmanThreshold] = useState(0.5)
  const [spearmanOutputType, setSpearmanOutputType] = useState('numeric')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [loadingDetail, setLoadingDetail] = useState(isEdit)
  const userEditedPrompt = useRef(false)
  const dimLoaded = useRef(false)

  useEffect(() => {
    providerApi.list().then((r) => setProviders(r.providers)).catch(() => { })
  }, [])

  // 从 prompts/ 加载评分器模板正文
  useEffect(() => {
    mlApi.getEvalPromptTemplates().then((r) => {
      Object.entries(r.classify || {}).forEach(([key, t]) => {
        if (CLASSIFY_TEMPLATES[key]) CLASSIFY_TEMPLATES[key].prompt = t.prompt
      })
      Object.entries(r.numeric || {}).forEach(([key, t]) => {
        if (NUMERIC_TEMPLATES[key]) NUMERIC_TEMPLATES[key].prompt = t.prompt
      })
      if (!dimLoaded.current && !userEditedPrompt.current) {
        setClassifyPrompt((p) => p || CLASSIFY_TEMPLATES.standard.prompt)
        setNumericPrompt((p) => p || NUMERIC_TEMPLATES.overall.prompt)
      }
    }).catch(() => { /* 回退为页面内联默认（为空时用户手动填写） */ })
  }, [])

  // 编辑模式：回填已有维度
  useEffect(() => {
    if (!dimensionId) return
    let cancelled = false
    mlApi.getDimension(dimensionId).then((d) => {
      if (cancelled) return
      dimLoaded.current = true
      setLoadingDetail(false)
      setName(d.name)
      setDescription(d.description || '')
      setEvalType(d.eval_type)
      const cfg = (d.eval_config || {}) as Record<string, unknown>
      if (d.eval_type === 'llm_classify') {
        setJudgeModel(String(cfg.judge_model || ''))
        const t = String(cfg.template || 'standard')
        setClassifyTemplate(t)
        setLabels(
          (cfg.labels as { Pass?: string; Fail?: string } | undefined)
            ? {
              pass: String((cfg.labels as { Pass?: string }).Pass || CLASSIFY_TEMPLATES[t]?.labels.pass || 'Pass'),
              fail: String((cfg.labels as { Fail?: string }).Fail || CLASSIFY_TEMPLATES[t]?.labels.fail || 'Fail'),
            }
            : CLASSIFY_TEMPLATES[t]?.labels || CLASSIFY_TEMPLATES.standard.labels,
        )
        if (cfg.prompt) {
          userEditedPrompt.current = true
          setClassifyPrompt(String(cfg.prompt))
        } else {
          setClassifyPrompt(CLASSIFY_TEMPLATES[t]?.prompt || CLASSIFY_TEMPLATES.standard.prompt)
        }
      } else if (d.eval_type === 'llm_numeric') {
        setNumJudgeModel(String(cfg.judge_model || ''))
        const t = String(cfg.template || 'overall')
        setNumericTemplate(t)
        if (cfg.threshold != null) setNumericThreshold(Number(cfg.threshold))
        if (cfg.prompt) {
          userEditedPrompt.current = true
          setNumericPrompt(String(cfg.prompt))
        } else {
          setNumericPrompt(NUMERIC_TEMPLATES[t]?.prompt || NUMERIC_TEMPLATES.overall.prompt)
        }
      } else if (d.eval_type === 'retrieval') {
        const m = String(cfg.metric || 'recall_at_5')
        setRetrievalMetric(m)
        if (m === 'recall_at_5') setRecallK(Number(cfg.recall_k) || 5)
        else setTopK(Number(cfg.top_k) || 5)
      } else if (d.eval_type === 'spearman') {
        setSpearmanSimMethod(String(cfg.similarity_method || 'cosine'))
        if (cfg.threshold != null) setSpearmanThreshold(Number(cfg.threshold))
        setSpearmanOutputType(String(cfg.output_type || 'numeric'))
      }
    }).catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : '加载维度失败')
    }).finally(() => {
      if (!cancelled) setLoadingDetail(false)
    })
    return () => {
      cancelled = true
    }
  }, [dimensionId])

  const chooseClassifyTemplate = (key: string) => {
    const t = CLASSIFY_TEMPLATES[key]
    if (!t) return
    setClassifyTemplate(key)
    setClassifyPrompt(t.prompt)
    setLabels(t.labels)
    userEditedPrompt.current = false
    // 按模板回填上方基础信息：维度名称与描述
    setName(t.name)
    setDescription(t.description)
  }

  const chooseNumericTemplate = (key: string) => {
    const t = NUMERIC_TEMPLATES[key]
    if (!t) return
    setNumericTemplate(key)
    setNumericPrompt(t.prompt)
    setNumericThreshold(t.threshold)
    userEditedPrompt.current = false
    let nextDesc = description
    if (t.name) setName(t.name)
    if (t.description) nextDesc = t.description
    setDescription(withThresholdDesc(nextDesc, t.threshold))
  }

  /* 切换类型时按当前模板回填基础信息（仅基础信息仍为模板默认值时才覆盖） */
  const backfillBasicsForType = (type: string) => {
    if (type === 'llm_classify') {
      const t = CLASSIFY_TEMPLATES[classifyTemplate]
      if (!t) return
      if (canBackfillName(name)) setName(t.name)
      if (canBackfillDesc(description)) setDescription(t.description)
    } else if (type === 'llm_numeric') {
      const t = NUMERIC_TEMPLATES[numericTemplate]
      if (!t || !t.name || !t.description) return
      if (canBackfillName(name)) setName(t.name)
      if (canBackfillDesc(description)) setDescription(withThresholdDesc(t.description, t.threshold))
    }
  }

  const buildConfig = (): Record<string, unknown> => {
    if (evalType === 'llm_classify') {
      return {
        judge_model: judgeModel,
        template: classifyTemplate,
        prompt: classifyPrompt,
        labels: { Pass: labels.pass, Fail: labels.fail },
      }
    }
    if (evalType === 'llm_numeric') {
      return {
        judge_model: numJudgeModel,
        template: numericTemplate,
        prompt: numericPrompt,
        score_min: 0,
        score_max: 5,
        threshold: numericThreshold,
      }
    }
    if (evalType === 'retrieval') {
      const cfg: Record<string, unknown> = { metric: retrievalMetric }
      if (retrievalMetric === 'recall_at_5') {
        cfg.recall_k = recallK
      } else {
        cfg.top_k = topK
      }
      return cfg
    }
    if (evalType === 'spearman') {
      return {
        similarity_method: spearmanSimMethod,
        threshold: spearmanThreshold,
        output_type: spearmanOutputType,
      }
    }
    return {}
  }

  const handleSubmit = async () => {
    if (!name.trim()) return setError('请输入维度名称')
    setSubmitting(true)
    setError('')
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        eval_type: evalType,
        eval_config: buildConfig(),
      }
      if (isEdit && dimensionId) {
        await mlApi.updateDimension(dimensionId, payload)
      } else {
        await mlApi.createDimension(payload)
      }
      navigate('/ml/eval?tab=dimensions')
    } catch (err) {
      setError(err instanceof Error ? err.message : isEdit ? '保存失败' : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500'

  const providerOptions = providers.map((p) => ({
    value: p.id,
    label: p.model_name && p.name !== p.model_name ? `${p.name}（${p.model_name}）` : p.name,
  }))

  const providerSelect = (value: string, onChange: (v: string) => void) => (
    <Select
      value={value}
      onChange={onChange}
      placeholder="请选择裁判模型"
      options={providerOptions}
      className="w-full"
    />
  )

  if (loadingDetail) {
    return (
      <div className="flex justify-center py-24 text-slate-400">
        <Loader2 size={24} className="animate-spin" />
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-400">
        <button type="button" onClick={() => navigate('/ml/eval?tab=dimensions')} className="hover:text-slate-600">模型评测</button>
        <ChevronRight size={14} />
        <span className="font-medium text-slate-900">{isEdit ? '编辑评测维度' : '创建评测维度'}</span>
      </div>

      <div className="mx-auto max-w-3xl space-y-6">
        {/* 基础信息：默认显示名称 / 描述 / 类型 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">基础信息</h3>
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                维度名称 <span className="text-red-500">*</span>
              </label>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={50} placeholder="请输入维度名称" className={inputCls} />
              <div className="mt-1 text-right text-xs text-slate-400">{name.length}/50</div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">描述</label>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} rows={2} placeholder="评测标准说明（选填）" className={inputCls} />
              <div className="mt-1 text-right text-xs text-slate-400">{description.length}/200</div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                类型 <span className="text-red-500">*</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {EVAL_TYPES.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => {
                      setEvalType(t.value)
                      if (!isEdit) backfillBasicsForType(t.value)
                    }}
                    className={`rounded-lg border px-4 py-2 text-sm transition-colors ${evalType === t.value
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                      : 'border-slate-200 text-slate-600 hover:border-slate-300'
                      }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* 大模型评估-分类型 */}
        {evalType === 'llm_classify' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">大模型评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">裁判模型</label>
                {providerSelect(judgeModel, setJudgeModel)}
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">评分器模板</label>
                <div className="flex gap-2">
                  {Object.entries(CLASSIFY_TEMPLATES).map(([key, t]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => chooseClassifyTemplate(key)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${classifyTemplate === key
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="block text-sm font-medium text-slate-700">Prompt</label>
                  <button
                    type="button"
                    onClick={() => {
                      setClassifyPrompt(CLASSIFY_TEMPLATES[classifyTemplate].prompt)
                      userEditedPrompt.current = false
                    }}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    恢复默认 Prompt
                  </button>
                </div>
                <textarea
                  value={classifyPrompt}
                  onChange={(e) => {
                    setClassifyPrompt(e.target.value)
                    userEditedPrompt.current = true
                  }}
                  rows={12}
                  className={`${inputCls} font-mono text-xs leading-relaxed`}
                />
                <p className="mt-1 text-xs text-slate-400">
                  支持变量：<code className="rounded bg-indigo-50 px-1 text-indigo-600">{'${query}'}</code>
                  <code className="ml-1 rounded bg-indigo-50 px-1 text-indigo-600">{'${positive}'}</code>
                  <code className="ml-1 rounded bg-indigo-50 px-1 text-indigo-600">{'${negative}'}</code>
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">标签选项</label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="mb-1 block text-sm font-medium text-slate-700">Pass</span>
                    <p className="mb-2 text-xs leading-relaxed text-slate-400">评测数据通过评估，计算评估维度得分时，该分类下所有标签情况均会被视作Pass。</p>
                    <input value={labels.pass} onChange={(e) => setLabels((p) => ({ ...p, pass: e.target.value }))} className={inputCls} />
                  </div>
                  <div>
                    <span className="mb-1 block text-sm font-medium text-slate-700">Fail</span>
                    <p className="mb-2 text-xs leading-relaxed text-slate-400">评测数据不通过评估，计算评估维度得分时，该分类下所有标签情况均会被视作Fail。</p>
                    <input value={labels.fail} onChange={(e) => setLabels((p) => ({ ...p, fail: e.target.value }))} className={inputCls} />
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 大模型评估-数值型 */}
        {evalType === 'llm_numeric' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">大模型评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">裁判模型</label>
                {providerSelect(numJudgeModel, setNumJudgeModel)}
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">评分器模板</label>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(NUMERIC_TEMPLATES).map(([key, t]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => chooseNumericTemplate(key)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${numericTemplate === key
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="block text-sm font-medium text-slate-700">Prompt</label>
                  <button
                    type="button"
                    onClick={() => {
                      setNumericPrompt(NUMERIC_TEMPLATES[numericTemplate].prompt)
                      userEditedPrompt.current = false
                    }}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    恢复默认 Prompt
                  </button>
                </div>
                <textarea
                  value={numericPrompt}
                  onChange={(e) => {
                    setNumericPrompt(e.target.value)
                    userEditedPrompt.current = true
                  }}
                  rows={12}
                  className={`${inputCls} font-mono text-xs leading-relaxed`}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">评分范围</label>
                <p className="text-sm text-slate-600">0 - 5</p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  通过阈值：<span className="font-mono text-indigo-600">{numericThreshold}</span>
                  <span className="ml-2 text-xs font-normal text-slate-400">（大于等于该阈值为 Pass）</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={5}
                  step={0.5}
                  value={numericThreshold}
                  onChange={(e) => {
                    const th = Number(e.target.value)
                    setNumericThreshold(th)
                    setDescription((prev) => withThresholdDesc(prev, th))
                  }}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>0</span>
                  <span>5</span>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 检索评估 */}
        {evalType === 'retrieval' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">检索评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">检索类型</label>
                <div className="flex flex-wrap gap-2">
                  {RETRIEVAL_METRICS.map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      onClick={() => {
                        setRetrievalMetric(m.key)
                        const k = m.key === 'recall_at_5' ? recallK : topK
                        setName(retrievalName(m.key, k))
                        // 召回率的描述随 K 值联动回填
                        setDescription(m.key === 'recall_at_5' ? recallDesc(k) : m.desc)
                      }}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${retrievalMetric === m.key
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {m.name}
                    </button>
                  ))}
                </div>
              </div>
              {retrievalMetric === 'recall_at_5' ? (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">Recall</label>
                  <input
                    type="number"
                    min={1}
                    value={recallK}
                    onChange={(e) => {
                      // 下限 1，无上限
                      const k = Math.max(1, Number(e.target.value) || 1)
                      setRecallK(k)
                      setName(retrievalName(retrievalMetric, k))
                      // 描述中的 K 同步更新，如 正确答案是否排在前1位
                      setDescription((prev) => (!prev.trim() || isRecallDesc(prev) ? recallDesc(k) : prev))
                    }}
                    className={`${inputCls} w-40`}
                  />
                </div>
              ) : (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">Top-K设置</label>
                  <input
                    type="number"
                    min={1}
                    value={topK}
                    onChange={(e) => {
                      const k = Math.max(1, Number(e.target.value) || 1)
                      setTopK(k)
                      setName(retrievalName(retrievalMetric, k))
                    }}
                    className={`${inputCls} w-40`}
                  />
                </div>
              )}
            </div>
          </section>
        )}

        {/* 统计评估-Spearman相关系数 */}
        {evalType === 'spearman' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">统计评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">相似度计算方法</label>
                <div className="flex flex-wrap gap-2">
                  {SPEARMAN_SIM_METHODS.map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      onClick={() => setSpearmanSimMethod(m.value)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${spearmanSimMethod === m.value
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">
                  用于将模型输出与参考答案向量化后计算相似度，得到模型打分序列。
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  通过阈值：<span className="font-mono text-indigo-600">{spearmanThreshold.toFixed(2)}</span>
                  <span className="ml-2 text-xs font-normal text-slate-400">（Spearman 相关系数的通过阈值，范围 -1 ~ 1）</span>
                </label>
                <input
                  type="range"
                  min={-1}
                  max={1}
                  step={0.01}
                  value={spearmanThreshold}
                  onChange={(e) => setSpearmanThreshold(Number(e.target.value))}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>-1.00</span>
                  <span>0.00</span>
                  <span>1.00</span>
                </div>
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">输出类型</label>
                <div className="flex gap-2">
                  {[
                    { value: 'numeric', label: '数值型（-1 到 1）' },
                    { value: 'classify', label: '分类型（Pass/Fail）' },
                  ].map((o) => (
                    <button
                      key={o.value}
                      type="button"
                      onClick={() => setSpearmanOutputType(o.value)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${spearmanOutputType === o.value
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* 底部操作 */}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => navigate('/ml/eval?tab=dimensions')} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
            {submitting && <Loader2 size={14} className="animate-spin" />}
            保存
          </button>
        </div>
      </div>
    </div>
  )
}
