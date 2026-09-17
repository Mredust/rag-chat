import {
  CheckCircle2,
  GitBranch,
  Layers,
  Loader2,
  MessageSquare,
  Pencil,
  Plus,
  Save,
  Server,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { configApi } from '../api/config'
import { mlApi } from '../api/ml'
import { providerApi } from '../api/provider'
import Modal from '../components/Modal'
import Select from '../components/Select'
import type { Provider, SystemConfig } from '../types'
import { sourceHint } from './ml/constants'

const LABELS: Record<string, string> = {
  embedding_api_base: 'Embedding API 地址',
  embedding_api_key: 'Embedding API Key',
  embedding_model: 'Embedding 模型',
  embedding_dim: '向量维度',
  retrieval_mode: '检索模式',
  top_k: 'Top-K 结果数',
  similarity_threshold: '相似度阈值',
  chunk_size: '切片大小',
  chunk_overlap: '切片重叠',
  rerank_enabled: '启用重排序',
  rerank_model: '重排序模型',
  rerank_top_m: '重排序候选数 (Top-M)',
  rrf_k: 'RRF 融合常数',
  prompt_system: '通用系统提示词',
  prompt_rag: 'RAG 提示词模板',
}

type Category =
  | { id: string; name: string; description: string; icon: typeof Server; kind: 'provider' }
  | {
    id: string
    name: string
    description: string
    icon: typeof Server
    kind: 'config'
    keys: string[]
  }

const CATEGORIES: Category[] = [
  {
    id: 'provider',
    name: '供应商配置',
    description: '管理大模型供应商并切换启用',
    icon: Server,
    kind: 'provider',
  },
  {
    id: 'embedding',
    name: '向量模型',
    description: '向量化（Embedding）供应商配置',
    icon: Layers,
    kind: 'config',
    keys: ['embedding_model'],
  },
  {
    id: 'prompt',
    name: '提示词设置',
    description: '系统提示词与 RAG 提示词模板',
    icon: MessageSquare,
    kind: 'config',
    keys: ['prompt_system', 'prompt_rag'],
  },
  {
    id: 'rag',
    name: 'RAG 管理',
    description: '检索与切片相关参数',
    icon: GitBranch,
    kind: 'config',
    keys: ['retrieval_mode', 'top_k', 'similarity_threshold', 'chunk_size', 'chunk_overlap'],
  },
  {
    id: 'rerank',
    name: '重排序',
    description: '交叉编码器重排序（Cross-Encoder）配置',
    icon: SlidersHorizontal,
    kind: 'config',
    keys: ['rerank_enabled', 'rerank_model', 'rerank_top_m', 'rrf_k'],
  },
]

export default function SettingsPage() {
  const [configs, setConfigs] = useState<SystemConfig[]>([])
  const [values, setValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [activeCategory, setActiveCategory] = useState(CATEGORIES[0].id)
  const [modelOptions, setModelOptions] = useState<{ value: string; label: string; hint?: string }[]>([])

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const fallback = { value: 'bge-large-zh-v1.5', label: 'bge-large-zh-v1.5', hint: '系统内置模型' }
    mlApi
      .listModels()
      .then((res) => {
        const opts = res.models.map((m) => ({ value: m.name, label: m.name, hint: sourceHint(m) }))
        setModelOptions(opts.some((o) => o.value === fallback.value) ? opts : [fallback, ...opts])
      })
      .catch(() => setModelOptions([fallback]))
  }, [])

  const load = async () => {
    setLoading(true)
    try {
      const res = await configApi.list()
      setConfigs(res.configs)
      const init: Record<string, string> = {}
      for (const c of res.configs) {
        init[c.key] = c.is_secret ? '' : c.value
      }
      setValues(init)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }

  const category = CATEGORIES.find((c) => c.id === activeCategory) ?? CATEGORIES[0]
  const isProvider = category.kind === 'provider'
  const categoryConfigs =
    category.kind === 'config' ? configs.filter((c) => category.keys.includes(c.key)) : []

  const saveCategory = async () => {
    setSaving(true)
    setMessage('')
    try {
      for (const c of categoryConfigs) {
        const v = values[c.key] ?? ''
        // 敏感项留空表示不修改
        if (c.is_secret && v.trim() === '') continue
        await configApi.update(c.key, v, c.is_secret)
      }
      setMessage(`已保存「${category.name}」配置`)
      await load()
    } catch {
      setMessage('保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">系统设置</h2>
        {!isProvider && message && <span className="text-sm text-slate-500">{message}</span>}
      </div>

      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        {/* 左侧：分类 */}
        <aside className="h-fit space-y-1 rounded-xl border border-slate-200 bg-white p-2">
          {CATEGORIES.map((cat) => {
            const Icon = cat.icon
            const active = cat.id === activeCategory
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => {
                  setActiveCategory(cat.id)
                  setMessage('')
                }}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${active
                  ? 'bg-indigo-50 text-indigo-700'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                  }`}
              >
                <Icon size={18} className={active ? 'text-indigo-600' : 'text-slate-400'} />
                {cat.name}
              </button>
            )
          })}
        </aside>

        {/* 右侧：设置内容 */}
        {isProvider ? (
          <ProviderPanel />
        ) : (
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-semibold text-slate-900">{category.name}</h3>
                <p className="mt-1 text-sm text-slate-500">{category.description}</p>
              </div>
              <button
                type="button"
                onClick={saveCategory}
                disabled={saving}
                className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60"
              >
                {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                保存
              </button>
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-12 text-slate-400">
                <Loader2 size={20} className="animate-spin" />
              </div>
            ) : categoryConfigs.length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-400">该分类下暂无配置项</p>
            ) : (
              <div className="space-y-3">
                {categoryConfigs.map((c) => (
                  <ConfigField
                    key={c.key}
                    config={c}
                    value={values[c.key] ?? ''}
                    onChange={(v) => setValues((prev) => ({ ...prev, [c.key]: v }))}
                    modelOptions={modelOptions}
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}

function ConfigField({
  config,
  value,
  onChange,
  modelOptions = [],
}: {
  config: SystemConfig
  value: string
  onChange: (v: string) => void
  modelOptions?: { value: string; label: string; hint?: string }[]
}) {
  const label = LABELS[config.key] ?? config.key
  const isSecret = config.is_secret
  const embeddingOptions =
    value && !modelOptions.some((o) => o.value === value)
      ? [{ value, label: value }, ...modelOptions]
      : modelOptions

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-200 p-4">
      <label className="text-sm font-medium text-slate-700">
        {label}
        {isSecret && (
          <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-500">敏感</span>
        )}
      </label>

      {config.key === 'rerank_enabled' ? (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onChange(value === 'true' ? 'false' : 'true')}
            aria-pressed={value === 'true'}
            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${value === 'true' ? 'bg-indigo-600' : 'bg-slate-300'
              }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${value === 'true' ? 'translate-x-6' : 'translate-x-1'
                }`}
            />
          </button>
          <span className="text-sm text-slate-600">
            {value === 'true' ? '已启用（交叉编码器精排）' : '已关闭（回退词法代理重排）'}
          </span>
        </div>
      ) : config.key === 'embedding_model' ? (
        <Select
          value={value}
          onChange={onChange}
          className="w-full"
          options={embeddingOptions}
        />
      ) : config.key === 'retrieval_mode' ? (
        <Select
          value={value}
          onChange={onChange}
          className="w-full"
          options={[
            { value: 'hybrid', label: '混合检索（向量 + 全文）' },
            { value: 'vector', label: '向量检索' },
            { value: 'fulltext', label: '全文检索' },
          ]}
        />
      ) : config.key === 'prompt_rag' || config.key === 'prompt_system' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={12}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm leading-relaxed outline-none focus:border-indigo-500"
        />
      ) : (
        <input
          type={isSecret ? 'password' : 'text'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            isSecret
              ? (config.value ? '******（留空不修改）' : '未设置')
              : config.key === 'rerank_model'
                ? '例如：rerankers/bge-reranker-base（建议绝对路径）'
                : config.key === 'rerank_top_m'
                  ? '例如：20'
                  : config.key === 'rrf_k'
                    ? '例如：60'
                    : ''
          }
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
        />
      )}
    </div>
  )
}

// ---- 供应商面板 ----

const TYPE_LABELS: Record<string, string> = {
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  custom: '自定义',
}

const PRESETS: Record<string, { api_base: string; model_name: string }> = {
  deepseek: { api_base: 'https://api.deepseek.com', model_name: 'deepseek-v4-pro' },
  openai: { api_base: 'https://api.openai.com/v1', model_name: 'gpt-4o-mini' },
  custom: { api_base: '', model_name: '' },
}

// DeepSeek 可选模型（添加供应商时下拉选择）
const DEEPSEEK_MODELS = [
  { value: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
  { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro' },
]

interface ProviderForm {
  name: string
  api_type: string
  api_base: string
  model_names: string[]
  api_key: string
}

function ProviderPanel() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [loading, setLoading] = useState(true)
  const [modalMode, setModalMode] = useState<'create' | 'edit' | null>(null)
  const [editing, setEditing] = useState<Provider | null>(null)
  const [form, setForm] = useState<ProviderForm>({
    name: '',
    api_type: 'deepseek',
    api_base: PRESETS.deepseek.api_base,
    model_names: [PRESETS.deepseek.model_name],
    api_key: '',
  })
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Provider | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    load()
  }, [])

  const load = async () => {
    setLoading(true)
    try {
      const res = await providerApi.list()
      setProviders(res.providers)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }

  const refresh = async () => {
    try {
      const res = await providerApi.list()
      setProviders(res.providers)
    } catch {
      /* ignore */
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm({
      name: '',
      api_type: 'deepseek',
      api_base: PRESETS.deepseek.api_base,
      model_names: [PRESETS.deepseek.model_name],
      api_key: '',
    })
    setFormError('')
    setModalMode('create')
  }

  const openEdit = (p: Provider) => {
    setEditing(p)
    const names = p.model_names && p.model_names.length > 0 ? p.model_names : [p.model_name]
    setForm({
      name: p.name,
      api_type: p.api_type,
      api_base: p.api_base,
      model_names: names,
      api_key: p.masked_key,
    })
    setFormError('')
    setModalMode('edit')
  }

  const changeType = (api_type: string) => {
    const preset = PRESETS[api_type] ?? PRESETS.custom
    setForm((prev) => ({ ...prev, api_type, api_base: preset.api_base, model_names: [preset.model_name] }))
  }

  const updateModelName = (idx: number, val: string) => {
    setForm((prev) => {
      const next = [...prev.model_names]
      next[idx] = val
      return { ...prev, model_names: next }
    })
  }

  const addModelName = () => {
    setForm((prev) => ({ ...prev, model_names: [...prev.model_names, ''] }))
  }

  const removeModelName = (idx: number) => {
    setForm((prev) => {
      const next = prev.model_names.filter((_, i) => i !== idx)
      return { ...prev, model_names: next.length > 0 ? next : [''] }
    })
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!form.name.trim()) {
      setFormError('请输入供应商名称')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      let apiKey = form.api_key.trim()
      if (modalMode === 'edit' && editing && apiKey === editing.masked_key) {
        // 未改动脱敏值，视为不修改 Key
        apiKey = ''
      }
      const models = form.model_names.map((m) => m.trim()).filter(Boolean)
      const payload = {
        name: form.name.trim(),
        api_type: form.api_type,
        api_base: form.api_base.trim(),
        model_name: models[0] || '',
        model_names: models,
        api_key: apiKey,
      }
      if (modalMode === 'create') {
        await providerApi.create(payload)
      } else if (editing) {
        await providerApi.update(editing.id, payload)
      }
      setModalMode(null)
      await refresh()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleActivate = async (p: Provider) => {
    if (p.is_active) return
    setBusyId(p.id)
    try {
      await providerApi.activate(p.id)
      setProviders((prev) => prev.map((item) => ({ ...item, is_active: item.id === p.id })))
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '操作失败')
    } finally {
      setBusyId(null)
    }
  }

  const handleDeactivate = async (p: Provider) => {
    if (!p.is_active) return
    setBusyId(p.id)
    try {
      await providerApi.deactivate(p.id)
      setProviders((prev) => prev.map((item) => (item.id === p.id ? { ...item, is_active: false } : item)))
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '操作失败')
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (p: Provider) => {
    setDeleteTarget(p)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await providerApi.remove(deleteTarget.id)
      setDeleteTarget(null)
      await refresh()
    } catch (err) {
      setDeleteTarget(null)
      window.alert(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">供应商配置</h3>
          <p className="mt-1 text-sm text-slate-500">管理大模型供应商并切换启用</p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
        >
          <Plus size={16} />
          添加供应商
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : providers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-400">
          <Server size={40} className="mb-3" />
          <p className="text-sm">暂无供应商，点击右上角「添加供应商」创建</p>
        </div>
      ) : (
        <ul className="space-y-3">
          {providers.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900">{p.name}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {TYPE_LABELS[p.api_type] ?? p.api_type}
                  </span>
                  {p.is_active && (
                    <span className="flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
                      <CheckCircle2 size={12} />
                      启用中
                    </span>
                  )}
                </div>
                <div className="mt-1 truncate text-sm text-slate-500">
                  模型 {p.model_name || '—'} · {p.api_base || '未设置地址'}
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-1.5">
                {p.is_active ? (
                  <button
                    type="button"
                    onClick={() => handleDeactivate(p)}
                    disabled={busyId === p.id}
                    className="rounded-lg border border-amber-200 px-3 py-1.5 text-sm text-amber-700 hover:bg-amber-50 disabled:opacity-60"
                  >
                    停用
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleActivate(p)}
                    disabled={busyId === p.id}
                    className="rounded-lg border border-indigo-200 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50 disabled:opacity-60"
                  >
                    启用
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => openEdit(p)}
                  className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  title="编辑"
                >
                  <Pencil size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(p)}
                  disabled={busyId === p.id}
                  className="rounded-md p-2 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  title="删除"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Modal
        open={modalMode !== null}
        title={modalMode === 'create' ? '添加供应商' : '编辑供应商'}
        onClose={() => setModalMode(null)}
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">名称</label>
            <input
              value={form.name}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
              maxLength={64}
              placeholder="例如：DeepSeek"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">格式</label>
            <Select
              value={form.api_type}
              onChange={changeType}
              className="w-full"
              options={[
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'openai', label: 'OpenAI' },
                { value: 'custom', label: '自定义' },
              ]}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">URL</label>
            <input
              value={form.api_base}
              onChange={(e) => setForm((prev) => ({ ...prev, api_base: e.target.value }))}
              maxLength={500}
              placeholder="OpenAI 兼容 base_url"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">API Key</label>
            <input
              type="text"
              value={form.api_key}
              onChange={(e) => setForm((prev) => ({ ...prev, api_key: e.target.value }))}
              maxLength={500}
              placeholder={modalMode === 'edit' ? '留空不修改' : '留空表示无需鉴权'}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">模型名称</label>
            <div className="space-y-2">
              {form.model_names.map((m, idx) => (
                <div key={idx} className="flex gap-2">
                  <div className="flex-1">
                    {form.api_type === 'deepseek' ? (
                      <Select
                        value={m}
                        onChange={(v) => updateModelName(idx, v)}
                        className="w-full"
                        options={DEEPSEEK_MODELS}
                      />
                    ) : (
                      <input
                        value={m}
                        onChange={(e) => updateModelName(idx, e.target.value)}
                        maxLength={128}
                        placeholder={idx === 0 ? '例如：gpt-4o-mini（首选模型）' : '备用模型名称（前一个失败后自动切换）'}
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                      />
                    )}
                  </div>
                  {idx === 0 ? (
                    <button
                      type="button"
                      onClick={addModelName}
                      className="flex shrink-0 items-center gap-1 rounded-lg border border-indigo-200 px-3 py-2 text-sm text-indigo-700 hover:bg-indigo-50"
                    >
                      <Plus size={14} />
                      添加
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => removeModelName(idx)}
                      className="flex shrink-0 items-center rounded-lg border border-slate-200 px-2.5 py-2 text-slate-500 hover:bg-slate-50"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            {form.model_names.length > 1 && (
              <p className="mt-1 text-xs text-slate-400">按顺序兜底访问：第一个模型不可用时自动切换下一个</p>
            )}
          </div>

          {formError && <p className="text-sm text-red-600">{formError}</p>}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setModalMode(null)}
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

      <Modal open={deleteTarget !== null} title="删除供应商" onClose={() => setDeleteTarget(null)}>
        <p className="text-sm text-slate-600">
          确定删除供应商「<span className="font-medium text-slate-900">{deleteTarget?.name}</span>」吗？
          此操作不可撤销。
        </p>
        <div className="mt-5 flex justify-end gap-2">
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
            删除
          </button>
        </div>
      </Modal>
    </section>
  )
}