import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  FileText,
  Loader2,
  Upload,
  X,
} from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ApiError } from '../api/client'
import {
  knowledgeApi,
  type DocumentPreview,
  type ImportStrategy,
  type PreviewChunk,
} from '../api/knowledge'
import Select from '../components/Select'
import { formatSize, statusClass } from '../lib/format'
import type { Document } from '../types'

const ACCEPTED = ['pdf', 'txt', 'doc', 'docx', 'md']
const MAX_FILES = 300
const MAX_SIZE = 100 * 1024 * 1024
const PROCESSING_STATUS = ['待处理', '解析中', '切片中', '向量化中']

const STEP_TITLES = ['上传', '创建设置', '分段预览', '数据处理']

const SEPARATOR_OPTIONS = [
  { value: '\n', label: '换行' },
  { value: '\n\n', label: '段落（空行）' },
  { value: '。', label: '句号' },
  { value: '，', label: '逗号' },
  { value: ' ', label: '空格' },
]

function extOf(name: string): string {
  return name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
}

interface TreeNode {
  title: string
  level: number
  children: TreeNode[]
}

function buildTree(chunks: PreviewChunk[]): TreeNode[] {
  const roots: TreeNode[] = []
  const stack: TreeNode[] = []
  for (const c of chunks) {
    if (!c.title || c.level == null) continue
    const node: TreeNode = { title: c.title, level: c.level, children: [] }
    while (stack.length && stack[stack.length - 1].level >= node.level) stack.pop()
    if (stack.length === 0) roots.push(node)
    else stack[stack.length - 1].children.push(node)
    stack.push(node)
  }
  return roots
}

function TreeNodeView({ node }: { node: TreeNode }) {
  return (
    <div className="border-l border-slate-200 pl-3">
      <div className="py-1 text-sm text-slate-700">{node.title}</div>
      {node.children.length > 0 && (
        <div className="ml-1">
          {node.children.map((c, i) => (
            <TreeNodeView key={`${c.title}_${i}`} node={c} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function KnowledgeImportPage() {
  const { spaceId = '' } = useParams<{ spaceId: string }>()
  const navigate = useNavigate()

  const [step, setStep] = useState(0)
  const [files, setFiles] = useState<File[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [formError, setFormError] = useState('')

  // 创建设置
  const [parseMode, setParseMode] = useState<'accurate' | 'fast'>('fast')
  const [segmentMode, setSegmentMode] = useState<'auto' | 'custom' | 'hierarchy'>('auto')
  const [separator, setSeparator] = useState('\n')
  const [chunkSize, setChunkSize] = useState(800)
  const [chunkOverlap, setChunkOverlap] = useState(10)
  const [collapseWs, setCollapseWs] = useState(false)
  const [removeUrl, setRemoveUrl] = useState(false)
  const [maxLevel, setMaxLevel] = useState(3)
  const [keepHierarchy, setKeepHierarchy] = useState(true)

  // 分段预览
  const [selected, setSelected] = useState<File | null>(null)
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')

  // 数据处理
  const [importStarted, setImportStarted] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [importError, setImportError] = useState('')
  const [createdDocs, setCreatedDocs] = useState<Document[]>([])

  const inputRef = useRef<HTMLInputElement>(null)

  const buildStrategy = (): ImportStrategy => ({
    segment_mode: segmentMode,
    parse_mode: parseMode,
    max_level: maxLevel,
    keep_hierarchy: keepHierarchy,
    chunk_size: chunkSize,
    chunk_overlap: chunkOverlap,
    separator,
    collapse_whitespace: collapseWs,
    remove_urls_email: removeUrl,
  })

  // 进入分段预览时加载选中文件的预览
  useEffect(() => {
    if (step !== 2 || !selected) return
    let cancelled = false
    setPreviewLoading(true)
    setPreviewError('')
    knowledgeApi
      .previewImport(spaceId, selected, buildStrategy())
      .then((res) => {
        if (!cancelled) setPreview(res)
      })
      .catch((err) => {
        if (!cancelled) setPreviewError(err instanceof Error ? err.message : '预览失败')
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, selected, spaceId, segmentMode, parseMode, separator, chunkSize, chunkOverlap, collapseWs, removeUrl, maxLevel, keepHierarchy])

  // 进入数据处理步骤时触发批量导入（后台异步处理）
  useEffect(() => {
    if (step !== 3 || importStarted) return
    setImportStarted(true)
    void (async () => {
      setProcessing(true)
      setImportError('')
      try {
        const res = await knowledgeApi.batchImport(spaceId, files, buildStrategy())
        setCreatedDocs(res.documents)
      } catch (err) {
        setImportError(err instanceof ApiError ? err.message : '导入失败')
      } finally {
        setProcessing(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, importStarted, spaceId])

  // 轮询当前批次文档处理状态，直至全部完成/失败
  const hasProcessingDocs = createdDocs.some((d) => PROCESSING_STATUS.includes(d.status))
  useEffect(() => {
    if (step !== 3 || createdDocs.length === 0 || !hasProcessingDocs) return
    const ids = createdDocs.map((d) => d.id)
    const timer = setInterval(async () => {
      try {
        const res = await knowledgeApi.listDocuments(spaceId)
        const next = res.documents.filter((d) => ids.includes(d.id))
        // 仅当状态发生变化时更新，避免持续重建轮询定时器
        const changed = next.some((d) => {
          const prev = createdDocs.find((p) => p.id === d.id)
          return !prev || prev.status !== d.status
        })
        if (changed) setCreatedDocs(next)
      } catch {
        /* ignore */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [step, spaceId, createdDocs, hasProcessingDocs])

  const addFiles = (incoming: FileList | File[]) => {
    setFormError('')
    const list = Array.from(incoming)
    if (files.length + list.length > MAX_FILES) {
      setFormError(`最多上传 ${MAX_FILES} 个文件`)
      return
    }
    const badType = list.filter((f) => !ACCEPTED.includes(extOf(f.name)))
    if (badType.length > 0) {
      setFormError('仅支持 PDF / TXT / DOC / DOCX / MD 格式')
      return
    }
    const big = list.find((f) => f.size > MAX_SIZE)
    if (big) {
      setFormError('单个文件不能超过 100MB')
      return
    }
    const seen = new Set(files.map((f) => `${f.name}_${f.size}`))
    const fresh = list.filter((f) => !seen.has(`${f.name}_${f.size}`))
    setFiles([...files, ...fresh])
  }

  const handleFilesChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files)
    e.target.value = ''
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(false)
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files)
  }

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  const goPrev = () => setStep((s) => Math.max(0, s - 1))

  const goNext = () => {
    if (step === 0) {
      if (files.length === 0) {
        setFormError('请先上传至少一个文档')
        return
      }
      setStep(1)
    } else if (step === 1) {
      setStep(2)
      if (files.length && !selected) setSelected(files[0])
    } else if (step === 2) {
      setStep(3)
    }
  }

  const finish = () => navigate(`/knowledge/${spaceId}`)

  const allDone = createdDocs.length > 0 && createdDocs.every((d) => !PROCESSING_STATUS.includes(d.status))
  const tree = preview ? buildTree(preview.chunks) : []

  return (
    <div className="mx-auto flex min-h-[calc(100vh-6rem)] max-w-6xl flex-col">
      {/* 顶部：返回 + 步骤条 */}
      <div className="relative mb-6 flex items-center justify-center gap-4">
        <button
          type="button"
          onClick={() => navigate(`/knowledge/${spaceId}`)}
          className="absolute left-0 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50"
          title="返回知识库"
        >
          <ArrowLeft size={18} />
        </button>

        <div className="flex items-center gap-2">
          {STEP_TITLES.map((title, idx) => {
            const active = idx === step
            const done = idx < step
            return (
              <div key={title} className="flex items-center gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-7 w-7 items-center justify-center rounded-full text-sm font-medium ${done
                        ? 'bg-indigo-600 text-white'
                        : active
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-200 text-slate-500'
                      }`}
                  >
                    {done ? <Check size={14} /> : idx + 1}
                  </span>
                  <span
                    className={`text-sm ${active ? 'font-medium text-slate-900' : 'text-slate-500'}`}
                  >
                    {title}
                  </span>
                </div>
                {idx < STEP_TITLES.length - 1 && (
                  <div className={`h-px w-8 ${idx < step ? 'bg-indigo-600' : 'bg-slate-200'}`} />
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1">
        {step === 0 && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragActive(true)
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-16 text-center transition ${dragActive
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-slate-300 bg-slate-50 hover:border-indigo-400 hover:bg-indigo-50/50'
                }`}
            >
              <span className="pointer-events-none mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
                <Upload size={26} />
              </span>
              <p className="pointer-events-none text-base font-medium text-slate-700">
                点击上传或拖拽文档到这里
              </p>
              <p className="pointer-events-none mt-2 text-sm text-slate-400">
                支持 PDF、TXT、DOC、DOCX、MD，最多可上传 {MAX_FILES} 个文件，每个文件不超过 100MB，PDF 最多 500 页
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept=".pdf,.txt,.doc,.docx,.md"
                onChange={handleFilesChange}
                className="hidden"
              />
            </div>

            {files.length > 0 && (
              <ul className="mt-5 max-h-72 space-y-2 overflow-y-auto">
                {files.map((f, idx) => (
                  <li
                    key={`${f.name}_${f.size}_${idx}`}
                    className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-2.5"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <FileText size={16} className="shrink-0 text-slate-400" />
                      <span className="truncate text-sm text-slate-700">{f.name}</span>
                      <span className="shrink-0 text-xs text-slate-400">{formatSize(f.size)}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(idx)}
                      className="ml-2 shrink-0 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                      title="移除"
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {formError && <p className="mt-4 text-sm text-red-600">{formError}</p>}
          </section>
        )}

        {step === 1 && (
          <section className="space-y-6">
            {/* 文档解析策略 */}
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="mb-1 text-base font-semibold text-slate-900">文档解析策略</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                <label
                  className={`cursor-pointer rounded-lg border p-4 transition ${parseMode === 'accurate'
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-slate-200 hover:border-slate-300'
                    }`}
                >
                  <input
                    type="radio"
                    name="parseMode"
                    className="hidden"
                    checked={parseMode === 'accurate'}
                    onChange={() => setParseMode('accurate')}
                  />
                  <div className="font-medium text-slate-900">精准解析</div>
                  <div className="mt-1 text-sm text-slate-500">
                    将从文档中提取图片、表格等元素，需要耗费更长的时间
                  </div>
                </label>
                <label
                  className={`cursor-pointer rounded-lg border p-4 transition ${parseMode === 'fast'
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-slate-200 hover:border-slate-300'
                    }`}
                >
                  <input
                    type="radio"
                    name="parseMode"
                    className="hidden"
                    checked={parseMode === 'fast'}
                    onChange={() => setParseMode('fast')}
                  />
                  <div className="font-medium text-slate-900">快速解析</div>
                  <div className="mt-1 text-sm text-slate-500">
                    不会对文档提取图像、表格等元素，适用于纯文本
                  </div>
                </label>
              </div>
            </div>

            {/* 分段策略 */}
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="mb-3 text-base font-semibold text-slate-900">分段策略</h3>
              <div className="space-y-3">
                <label
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${segmentMode === 'auto'
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-slate-200 hover:border-slate-300'
                    }`}
                >
                  <input
                    type="radio"
                    name="segmentMode"
                    className="mt-1"
                    checked={segmentMode === 'auto'}
                    onChange={() => setSegmentMode('auto')}
                  />
                  <div>
                    <div className="font-medium text-slate-900">自动分段与清洗</div>
                    <div className="mt-1 text-sm text-slate-500">自动分段与预处理规则</div>
                  </div>
                </label>

                <label
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${segmentMode === 'custom'
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-slate-200 hover:border-slate-300'
                    }`}
                >
                  <input
                    type="radio"
                    name="segmentMode"
                    className="mt-1"
                    checked={segmentMode === 'custom'}
                    onChange={() => setSegmentMode('custom')}
                  />
                  <div>
                    <div className="font-medium text-slate-900">自定义</div>
                    <div className="mt-1 text-sm text-slate-500">
                      自定义分段规则、分段长度及预处理规则
                    </div>
                  </div>
                </label>

                {segmentMode === 'custom' && (
                  <div className="ml-8 space-y-4 rounded-lg border border-slate-100 bg-slate-50 p-4">
                    <div className="grid gap-4 sm:grid-cols-3">
                      <div>
                        <label className="mb-1 block text-sm font-medium text-slate-700">
                          分段标识符<span className="text-red-500">*</span>
                        </label>
                        <Select
                          value={separator}
                          onChange={setSeparator}
                          options={SEPARATOR_OPTIONS}
                          className="w-full"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-sm font-medium text-slate-700">
                          分段最大长度
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={chunkSize}
                          onChange={(e) => setChunkSize(Number(e.target.value) || 800)}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-sm font-medium text-slate-700">
                          分段重叠度%<span className="text-red-500">*</span>
                        </label>
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={chunkOverlap}
                          onChange={(e) => setChunkOverlap(Number(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                        />
                      </div>
                    </div>

                    <div>
                      <div className="mb-2 text-sm font-medium text-slate-700">文本预处理规则</div>
                      <label className="flex items-center gap-2 text-sm text-slate-600">
                        <input
                          type="checkbox"
                          checked={collapseWs}
                          onChange={(e) => setCollapseWs(e.target.checked)}
                        />
                        替换掉连续的空格、换行符和制表符
                      </label>
                      <label className="mt-2 flex items-center gap-2 text-sm text-slate-600">
                        <input
                          type="checkbox"
                          checked={removeUrl}
                          onChange={(e) => setRemoveUrl(e.target.checked)}
                        />
                        删除所有URL和电子邮箱地址
                      </label>
                    </div>
                  </div>
                )}

                <label
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition ${segmentMode === 'hierarchy'
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-slate-200 hover:border-slate-300'
                    }`}
                >
                  <input
                    type="radio"
                    name="segmentMode"
                    className="mt-1"
                    checked={segmentMode === 'hierarchy'}
                    onChange={() => setSegmentMode('hierarchy')}
                  />
                  <div>
                    <div className="font-medium text-slate-900">按层级分段</div>
                    <div className="mt-1 text-sm text-slate-500">
                      按照文档层级结构分段，将文档转化为有层级信息的树结构
                    </div>
                  </div>
                </label>

                {segmentMode === 'hierarchy' && (
                  <div className="ml-8 space-y-4 rounded-lg border border-slate-100 bg-slate-50 p-4">
                    <div className="max-w-xs">
                      <label className="mb-1 block text-sm font-medium text-slate-700">
                        分段层级<span className="text-red-500">*</span>
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={6}
                        value={maxLevel}
                        onChange={(e) => setMaxLevel(Number(e.target.value) || 1)}
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input
                        type="checkbox"
                        checked={keepHierarchy}
                        onChange={(e) => setKeepHierarchy(e.target.checked)}
                      />
                      检索切片保留层级信息
                    </label>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="grid gap-4 lg:grid-cols-[280px_1fr_1fr]">
            {/* 左侧：文档列表 + 层级树 */}
            <aside className="flex max-h-[calc(100vh-12rem)] flex-col gap-4 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4">
              <div>
                <h3 className="mb-2 text-sm font-semibold text-slate-700">
                  {segmentMode === 'hierarchy'
                    ? '按层级分段'
                    : segmentMode === 'custom'
                      ? '自定义分段'
                      : '自动分段与清洗'}
                </h3>
                <ul className="space-y-1">
                  {files.map((f) => (
                    <li key={`${f.name}_${f.size}`}>
                      <button
                        type="button"
                        onClick={() => setSelected(f)}
                        className={`flex w-full items-center justify-between gap-2 rounded-lg p-2 text-left text-sm transition ${selected?.name === f.name && selected?.size === f.size
                            ? 'bg-indigo-50 ring-1 ring-indigo-200'
                            : 'hover:bg-slate-50'
                          }`}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <FileText size={14} className="shrink-0 text-slate-400" />
                          <span className="truncate text-slate-700">{f.name}</span>
                        </span>
                        <span className="shrink-0 text-xs text-slate-400">{formatSize(f.size)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>

              {segmentMode === 'hierarchy' && (
                <div>
                  <div className="mb-2 text-sm font-semibold text-slate-700">分段层级</div>
                  {tree.length === 0 ? (
                    <p className="text-sm text-slate-400">暂无层级信息</p>
                  ) : (
                    <div className="space-y-1">
                      {tree.map((node, i) => (
                        <TreeNodeView key={`${node.title}_${i}`} node={node} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </aside>

            {/* 中间：原始文档预览 */}
            <section className="flex max-h-[calc(100vh-12rem)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="border-b border-slate-100 p-4">
                <h3 className="text-sm font-semibold text-slate-700">原始文档预览</h3>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                {previewLoading ? (
                  <div className="flex items-center justify-center py-16 text-slate-400">
                    <Loader2 size={20} className="animate-spin" />
                  </div>
                ) : previewError ? (
                  <p className="py-16 text-center text-sm text-red-500">{previewError}</p>
                ) : !preview ? (
                  <p className="py-16 text-center text-sm text-slate-400">请选择左侧文档查看原文</p>
                ) : (
                  <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-700">
                    {preview.raw_text}
                  </pre>
                )}
              </div>
            </section>

            {/* 右侧：分段预览 */}
            <section className="flex max-h-[calc(100vh-12rem)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="border-b border-slate-100 p-4">
                <h3 className="text-sm font-semibold text-slate-700">
                  分段预览{preview ? ` · ${preview.chunk_count} 段` : ''}
                </h3>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                {previewLoading ? (
                  <div className="flex items-center justify-center py-16 text-slate-400">
                    <Loader2 size={20} className="animate-spin" />
                  </div>
                ) : previewError ? (
                  <p className="py-16 text-center text-sm text-red-500">{previewError}</p>
                ) : !preview || preview.chunks.length === 0 ? (
                  <p className="py-16 text-center text-sm text-slate-400">暂无分段内容</p>
                ) : (
                  <div className="space-y-3">
                    {preview.chunks.map((c, idx) => (
                      <div
                        key={idx}
                        className="rounded-lg border border-slate-200 p-3 transition-colors hover:border-purple-200 hover:bg-purple-50"
                      >
                        <div className="mb-1.5 text-xs text-slate-400">
                          片段 #{idx + 1}
                          {c.title ? ` · ${c.title}` : ''}
                        </div>
                        <div className="markdown-body text-sm text-slate-700">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{c.content}</ReactMarkdown>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          </section>
        )}

        {step === 3 && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <div className="mb-5 flex items-center gap-3">
              {allDone ? (
                <CheckCircle2 size={22} className="text-green-500" />
              ) : (
                <Loader2 size={22} className="animate-spin text-indigo-500" />
              )}
              <h3 className="text-base font-semibold text-slate-900">
                {importError ? '数据处理失败' : allDone ? '服务器处理完成' : '文档处理中…'}
              </h3>
            </div>

            {importError && <p className="mb-4 text-sm text-red-600">{importError}</p>}

            <ul className="space-y-2">
              {createdDocs.map((d) => (
                <li
                  key={d.id}
                  className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3"
                >
                  <div className="flex min-w-0 items-center gap-2.5">
                    <FileText size={16} className="shrink-0 text-slate-400" />
                    <span className="truncate text-sm text-slate-700">{d.filename}</span>
                    <span className="shrink-0 text-xs text-slate-400">{formatSize(d.file_size)}</span>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs ${statusClass(d.status)}`}
                  >
                    {d.status === '待处理' && processing ? '处理中' : d.status}
                  </span>
                </li>
              ))}
              {createdDocs.length === 0 && !processing && !importError && (
                <p className="py-8 text-center text-sm text-slate-400">暂无文档</p>
              )}
            </ul>

            {allDone && (
              <p className="mt-4 text-sm text-slate-500">
                点击确认不影响数据处理，处理完毕后可进行引用。
              </p>
            )}
          </section>
        )}
      </div>

      {/* 底部操作按钮 */}
      <div className="mt-6 flex justify-end gap-2 border-t border-slate-200 pt-4">
        {step > 0 && (
          <button
            type="button"
            onClick={goPrev}
            disabled={processing && step === 3}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            <ArrowLeft size={16} />
            上一步
          </button>
        )}
        {step < 3 ? (
          <button
            type="button"
            onClick={goNext}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            下一步
            <ArrowRight size={16} />
          </button>
        ) : (
          <button
            type="button"
            onClick={finish}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <Check size={16} />
            确认
          </button>
        )}
      </div>
    </div>
  )
}